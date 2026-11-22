"""Dealer-only headless transport for the existing validated queue and DOM reader."""
from __future__ import annotations
import asyncio
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

HOSTS = {'www.hamptontoyota.com', 'www.hamptonmitsubishi.com'}


def reader_script():
    source = (Path(__file__).parent / 'chrome-extension' / 'background.js').read_text('utf-8')
    # Reuse the exact shipped equipment, gallery, discovery and missing-page readers.
    start = source.index('function expandVehicleEquipment()')
    end = source.index('async function navigate(url)')
    return '''async (job) => {
const chrome={scripting:{executeScript:async ({func,args=[]})=>[{result:await func(...args)}]}};
''' + source[start:end] + '''
return job.kind==='inventory_index' ? await discoverInventory(0) : await capture(0,job.url,job.link_only===true);
}'''


def allowed_job(job):
    from dealer_site_scraper import allowed_vehicle_url
    from chrome_bridge import ChromeBridge
    url = job.get('url', '')
    source = job.get('source')
    if source not in ('toyota_used', 'mitsubishi_used'):
        return False
    try:
        parsed = urlsplit(url)
        if parsed.port not in (None, 443) or parsed.fragment:
            return False
    except (ValueError, TypeError):
        return False
    return (ChromeBridge._valid_index_page(url, source) if job.get('kind') == 'inventory_index'
            else allowed_vehicle_url(url, source))


class ReaderFault(Exception):
    """A Reader transport failure tagged with the run whose work raised it (LR-009)."""
    def __init__(self, run_id, cause):
        super().__init__(type(cause).__name__)
        self.run_id = run_id
        self.cause = cause


class HeadlessDealer:
    def __init__(self, bridge):
        self.bridge = bridge
        self.stop_event = threading.Event()
        self.error = None
        self.teardown_error = None
        self.serving_run = None   # run whose pending work the pump is serving
        self.restarted_for = None  # run that already used its one pump restart
        self.user_agent = None
        self.denial_run = None
        self.denials = {}
        self.thread = None
        self.start_lock = threading.Lock()
        self.script = reader_script()
        from system_load import SystemLoad
        self.load_monitor=SystemLoad()
        self.last_load_at=0

    def ensure_ready(self):
        with self.start_lock:
            self._ensure_ready()

    def _ensure_ready(self):
        if self.bridge.dealer_engine != 'headless':
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ValueError('Playwright is missing. Run Launch Marketplace Scanner.cmd.') from exc
        if not self.thread or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name='LotRadar-Headless', daemon=True)
            self.thread.start()
        self.bridge.headless_seen = time.monotonic()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def _run(self):
        while True:
            try:
                asyncio.run(self._pump())
                return
            except Exception as exc:
                if not self._fault(exc):
                    return
                # A retired run's failure must not strand the current run's
                # queue without a transport: serve it from a fresh pump.

    def _fault(self, exc):
        """LR-009: report and stop only the run whose Reader work failed.

        A failure tagged with (or, untagged, raised while serving) a run other
        than the active one restarts the pump once for the active run. A second
        failure means the transport itself is broken: the active run is stopped.
        Returns True when the pump should restart.
        """
        cause = exc.cause if isinstance(exc, ReaderFault) else exc
        failed_run = exc.run_id if isinstance(exc, ReaderFault) else self.serving_run
        self.error = type(cause).__name__
        bridge = self.bridge
        with bridge.lock:
            # Historical discovery has its own browser and its own owner; an
            # idle Reader failure is not part of its run history.
            if getattr(bridge, 'basic_run', None) is not None:
                return False
            active = bridge.verify.get('running') if bridge.mode == 'verify' else bridge.scan_info.get('running')
            if not active:
                return False
            if failed_run != bridge.run_id and self.restarted_for != bridge.run_id:
                self.restarted_for = bridge.run_id
                return not self.stop_event.is_set()
            bridge.events('', 'HEADLESS_ERROR', 'Headless browser stopped: '+self.error)
            bridge.control('stop')
            with bridge.scan_lock:
                bridge.scan_info.setdefault('errors', []).append({'source':'', 'reason':'Headless browser failed: '+self.error})
            return False

    async def _retire(self, browser):
        """Close a browser no run is using; its teardown failure belongs to no run."""
        try:
            await browser.close()
        except Exception as exc:
            self.teardown_error = type(exc).__name__

    async def _read(self, browser, job):
        if not allowed_job(job):
            return {'outcome': 'reader_url_rejected'}
        context = await browser.new_context(viewport={'width': 1365, 'height': 900}, accept_downloads=False, user_agent=self.user_agent)
        try:
            page = await context.new_page()
            async def route(request_route):
                req = request_route.request
                u = urlsplit(req.url)
                if req.is_navigation_request() and req.frame == page.main_frame:
                    if u.scheme != 'https' or u.hostname not in HOSTS or u.username or u.password:
                        return await request_route.abort()
                # Preserve images and scripts: gallery navigation needs both.
                if req.resource_type in ('media', 'font'):
                    return await request_route.abort()
                await request_route.continue_()
            await context.route('**/*', route)
            response = await page.goto(job['url'], wait_until='domcontentloaded', timeout=30000)
            if response and response.status in (401, 403, 429):
                return {'outcome':'access_denied'}
            if response and response.status >= 500:
                return {'outcome':'page_unavailable'}
            # No inference of sold from HTTP failures; DOM evidence goes through the shared reader.
            result = await page.evaluate(self.script, job)
            # Measure actual page event-loop delay; do not invent a healthy sample.
            try:
                lag = await asyncio.wait_for(page.evaluate("""async () => {
                    let worst=0;
                    for(let i=0;i<3;i++){
                        const start=performance.now();
                        await new Promise(resolve=>setTimeout(resolve,50));
                        worst=Math.max(worst,performance.now()-start-50);
                    }
                    return Math.min(60000,Math.max(0,Math.round(worst)));
                }"""), timeout=2)
                if isinstance(result, dict):
                    result['reader_lag_ms'] = lag
            except Exception:
                if isinstance(result, dict):
                    result['reader_lag_ms'] = 2000
            return result
        finally:
            await context.close()

    async def _job(self, browser, job):
        try:
            result = await asyncio.wait_for(self._read(browser, job), timeout=105)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = {'outcome':'page_timeout' if 'Timeout' in type(exc).__name__ else 'page_unavailable',
                      'detail':'Headless reader: '+type(exc).__name__}
            if result['outcome'] == 'page_timeout':
                result['reader_lag_ms'] = 2000
        try:
            with self.bridge.lock:
                if job['id'] not in self.bridge.inflight:
                    return
                if self.denial_run != self.bridge.run_id:
                    self.denial_run = self.bridge.run_id
                    self.denials = {}
                self.bridge.submit({**result, 'id':job['id'], 'url':job['url']})
                source = job['source']
                self.denials[source] = self.denials.get(source, 0) + 1 if result.get('outcome') == 'access_denied' else 0
                if self.denials[source] >= 3:
                    reason = 'BLOCKED: three consecutive access denials from '+source+'. Scan stopped; saved inventory preserved.'
                    self.bridge.control('stop')
                    self.bridge.events(source, 'HEADLESS_BLOCKED', reason)
                    with self.bridge.scan_lock:
                        self.bridge.scan_info['blocked'] = True
                        self.bridge.scan_info.setdefault('errors', []).append({'source':source, 'reason':reason})
        except ValueError as exc:
            if str(exc) != 'no_matching_active_chrome_job':
                raise

    async def _launch(self, chromium):
        browser = await chromium.launch(channel='chrome', headless=True, timeout=20000)
        try:
            probe = await browser.new_page()
            try:
                original = await probe.evaluate('navigator.userAgent')
                self.user_agent = original.replace('HeadlessChrome/', 'Chrome/')
            finally:
                await probe.close()
            return browser
        except BaseException:
            await browser.close()
            raise

    async def _pump(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = None
            tasks = {}  # task -> (lease id, run id); stop discards stale work before another run
            self.serving_run = None
            try:
                while not self.stop_event.is_set():
                    self.bridge.headless_seen = time.monotonic()
                    if time.monotonic()-self.last_load_at>=2:
                        self.bridge.observe_system_load(self.load_monitor.sample())
                        self.last_load_at=time.monotonic()
                    with self.bridge.lock:
                        live_ids = set(self.bridge.inflight)
                        pending = bool(self.bridge.queue) and not self.bridge.paused
                        cap = self.bridge.effective_workers
                        current_run = self.bridge.run_id
                    if pending:
                        self.serving_run = current_run
                    elif not tasks:
                        self.serving_run = None
                    for task, (job_id, job_run) in list(tasks.items()):
                        if job_id not in live_ids and not task.done():
                            task.cancel()
                        if task.done():
                            del tasks[task]
                            if not task.cancelled():
                                try:
                                    task.result()
                                except Exception as exc:
                                    raise ReaderFault(job_run, exc) from exc
                    if pending and len(tasks) < cap:
                        if browser is None:
                            try:
                                browser = await self._launch(p.chromium)
                            except Exception as exc:
                                raise ReaderFault(current_run, exc) from exc
                            self.error = None
                        state = self.bridge.next(consumer='headless')
                        if state.get('job'):
                            job = state['job']
                            task = asyncio.create_task(self._job(browser, job))
                            tasks[task] = (job['id'], job.get('_run_id'))
                    if not pending and not tasks and browser is not None:
                        retired, browser = browser, None
                        await self._retire(retired)
                    await asyncio.sleep(.15)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if browser:
                    await self._retire(browser)
