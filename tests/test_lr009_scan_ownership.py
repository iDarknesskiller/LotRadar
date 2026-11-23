"""LR-009-01: one dealer scan owns its work; Stop really ends the historical worker.

Real local HTTP routes, real Basic worker, real Chrome bridge and a temporary
SQLite store/catalog. Dealer reads and browser startup are fakes; the network is
loopback-only. Synthetic inventory only; never the live LocalAppData profile.
Maps to AC-01..AC-05 in ARCHITECT_HANDOFF.md (see CLAUDE_TEST_PLAN.md).
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chrome_bridge as CB  # noqa: E402
import dealer_site_scraper as DS  # noqa: E402

SOURCES = ['toyota_used', 'mitsubishi_used']
START = '/api/start-site-scan'
STATUS = '/api/site-scan-status'
CONTROL = '/api/chrome-scan-control'
BASIC = {'explicit_user_request': True, 'mode': 'basic', 'sources': SOURCES}
QUICK = dict(BASIC, mode='chrome', skip_existing=True, discover_live=True)
RESCAN = dict(BASIC, mode='chrome', skip_existing=False, discover_live=True)
VERIFY = {'explicit_user_request': True}
VIN = '1HGCM82633A004352'
HOST = {'toyota_used': 'https://www.hamptontoyota.com', 'mitsubishi_used': 'https://www.hamptonmitsubishi.com'}
TOKEN = 'lr009-fixture'


def url(source, n, make=None):
    make = make or ('Toyota' if source == 'toyota_used' else 'Mitsubishi')
    model = 'Camry' if make == 'Toyota' else 'Outlander'
    return f'{HOST[source]}/used/2022-{make}-{model}-{n:020x}.htm'


def catalog_output(source, tag, urls):
    rows = [{'url': u, 'source': source, 'year': 2022, 'make': 'Toyota', 'model': 'Camry',
             'discovery_method': 'inventory_page', 'tag': tag} for u in urls]
    return {'source': source, 'scanned_at': '2026-11-21T00:00:00+00:00', 'records': rows,
            'count': len(rows), 'index_candidates': len(rows), 'warnings': [],
            'verified': False, 'partial': True, 'tag': tag}


def wait_for(event, what='fixture boundary', timeout=10):
    if not event.wait(timeout):
        raise AssertionError('Timed out waiting for ' + what)


_guard = {'installed': False, 'active': 0}


def offline_only(event, args):
    # Audit hooks cannot be removed, so the guard applies only while an LR-009
    # test is running; other suites in the same process are unaffected.
    if not _guard['active']:
        return
    if event == 'socket.connect':
        address = args[1]
        if isinstance(address, tuple) and address and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise RuntimeError('External network is disabled in LR-009 tests')
    if event == 'subprocess.Popen':
        raise RuntimeError('External processes are disabled in LR-009 tests')


def install_offline_guard(test):
    if not _guard['installed']:
        sys.addaudithook(offline_only)
        _guard['installed'] = True
    _guard['active'] += 1

    def deactivate():
        _guard['active'] -= 1
    test.addCleanup(deactivate)


class FakeDiscovery:
    """Stand-in for the dealer website transport; the server worker is real.

    blocking[source]=True holds that dealer's read in flight (a bounded request
    that drains, ignoring Stop) until release(source).
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []
        self.blocking = {}
        self.events = {}
        self.outputs = {}
        self.threads = []
        self.controls = []

    def _pair(self, source):
        with self.lock:
            return self.events.setdefault(source, (threading.Event(), threading.Event()))

    def entered(self, source):
        return self._pair(source)[0]

    def release(self, source):
        self._pair(source)[1].set()

    def release_all(self):
        for src in SOURCES:
            self.release(src)

    def read(self, source, *, max_vehicles=250, progress=None, control=None, **_):
        with self.lock:
            self.calls.append(source)
            self.threads.append(threading.current_thread())
            self.controls.append(control)
        entered, release = self._pair(source)
        entered.set()
        if self.blocking.get(source):
            wait_for(release, 'test release of ' + source)
        if progress:
            progress('catalog_discovered', discovered=1, parsed=1, visited=0, failed=0)
        return self.outputs.get(source) or catalog_output(source, 'new', [url(source, 0xA1)])

    def join(self, timeout=10):
        for thread in list(self.threads):
            thread.join(timeout)
            if thread.is_alive():
                raise AssertionError('historical worker did not finish')


class Fixture(unittest.TestCase):
    engine = 'headless'

    def seed(self, root):
        """Subclasses may write files into the temporary data dir before startup."""

    def setUp(self):
        install_offline_guard(self)
        import server
        self.server = server
        stack = ExitStack()
        self.addCleanup(stack.close)
        local = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='lr009-test-')))
        stack.enter_context(patch.dict(os.environ, {'LOCALAPPDATA': str(local), 'APPDATA': str(local),
                                                    'LOTRADAR_DEALER_ENGINE': self.engine}))
        self.store = server.MarketplaceStore(local / 'data')
        stack.callback(self.store.close)
        self.seed(self.store.root)
        self.disc = FakeDiscovery()
        stack.enter_context(patch.object(server, 'scan_basic_source', self.disc.read))
        stack.enter_context(patch('vin_decode.VinDecoder', autospec=True))
        from headless_dealer import HeadlessDealer
        stack.enter_context(patch.object(HeadlessDealer, 'ensure_ready', autospec=True))
        http = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
        http.daemon_threads = True
        stack.callback(http.server_close)
        self.port = http.server_port
        handler = server.create_handler(self.store, self.port, TOKEN)
        handler.log_message = lambda *a: None
        http.RequestHandlerClass = handler
        self.handler = handler
        self.bridge = handler.headless_dealer.bridge
        stack.callback(handler.photo_cache.close)
        pump = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        pump.start()
        stack.callback(pump.join, 5)
        stack.callback(http.shutdown)
        stack.callback(self.disc.join)
        stack.callback(self.disc.release_all)
        self.root = self.store.root
        # Reader is "connected" for routes that require it (no real browser).
        self.bridge.headless_seen = time.monotonic() + 10 ** 6
        self.bridge.last_seen = time.monotonic() + 10 ** 6

    # -- helpers -----------------------------------------------------------
    def call(self, path, body=None, token=TOKEN):
        conn = HTTPConnection('127.0.0.1', self.port, timeout=20)
        headers = {'Content-Type': 'application/json', 'X-SalesmanHub-Token': token}
        if path.startswith('/api/chrome-bridge/'):
            headers.update({'X-SHM-Bridge-Key': self.bridge.key, 'X-SHM-Reader-Rev': self.server.READER_REVISION})
        try:
            conn.request('GET' if body is None else 'POST', path,
                         body=None if body is None else json.dumps(body), headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def status(self):
        code, body = self.call(STATUS)
        self.assertEqual(code, 200)
        return body

    def wait_state(self, *states, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.status()
            if body.get('state') in states:
                return body
            time.sleep(0.02)
        self.fail(f'state never became {states}; last={body.get("state")}')

    def seed_vehicle(self):
        row = {'vin': VIN, 'condition': 'used', 'year': 2022, 'make': 'Toyota', 'model': 'Camry',
               'stock': 'T123A', 'mileage': 1000, 'price': 20000, 'url': url('toyota_used', 0x77)}
        self.store.import_feed('toyota_used', 'json', json.dumps([row]))

    def disk_catalog(self):
        path = self.root / 'basic_catalog_unverified.json'
        return json.loads(path.read_text('utf-8')) if path.exists() else None

    def api_catalog(self):
        code, body = self.call('/api/basic-catalog')
        self.assertEqual(code, 200)
        return body

    def events(self, stage):
        return [e for e in self.status().get('events', []) if e.get('stage') == stage]

    def finish_basic(self):
        self.disc.release_all()
        self.wait_state('finished', 'stopped', 'failed', 'idle')
        self.disc.join()


PRIOR = {
    'schema': 1,
    'sources': {
        'toyota_used': catalog_output('toyota_used', 'prior', [url('toyota_used', 0x01), url('toyota_used', 0xA1)]),
        'mitsubishi_used': catalog_output('mitsubishi_used', 'prior', [url('mitsubishi_used', 0x02)]),
    },
}
PRIOR['sources']['toyota_used']['records'][1]['enrichment'] = {'vin': VIN, 'stock': 'T123A', 'captured': 'user'}


class SeededCatalog(Fixture):
    def seed(self, root):
        (root / 'basic_catalog_unverified.json').write_text(json.dumps(PRIOR), 'utf-8')


# ---------------------------------------------------------------- AC-01 -----
class AC01Admission(Fixture):
    def _race(self, first, second, gate_points):
        """Both requests pass every pre-admission check, then race for the slot."""
        barrier = threading.Barrier(2, timeout=10)
        seen = set()
        seen_lock = threading.Lock()
        originals = {}

        def gated(name):
            original = originals[name]

            def wrapper(*args, **kwargs):
                me = threading.get_ident()
                with seen_lock:
                    hit = me not in seen
                    seen.add(me)
                if hit:
                    barrier.wait()
                return original(*args, **kwargs)
            return wrapper

        with ExitStack() as stack:
            for obj, name in gate_points:
                originals[name] = getattr(obj, name)
                stack.enter_context(patch.object(obj, name, gated(name)))
            with ThreadPoolExecutor(2) as pool:
                a = pool.submit(self.call, *first)
                b = pool.submit(self.call, *second)
                return a.result(20), b.result(20)

    def _reset(self):
        if self.bridge.basic_run is not None:
            self.finish_basic()
        self.call(CONTROL, {'action': 'stop'})
        self.wait_state('stopped', 'finished', 'idle', 'failed')
        self.disc.events.clear()

    def _assert_one_winner(self, results, labels):
        wins = [label for label, (code, body) in zip(labels, results) if code == 200]
        self.assertEqual(len(wins), 1, f'exactly one start must win: {list(zip(labels, results))}')
        for (code, body) in results:
            if code != 200:
                self.assertEqual(code, 400)
                self.assertRegex(body.get('error', ''), 'already_running|another_scan')
        return wins[0]

    def test_basic_races_quick_rescan_and_twin_basic(self):
        self.disc.blocking = {'toyota_used': True}
        gate = [(self.bridge, 'verify_status')]
        for label, other in (('quick', QUICK), ('rescan', RESCAN), ('basic2', BASIC)):
            for order in range(3):
                pair = ((START, BASIC), (START, other)) if order % 2 == 0 else ((START, other), (START, BASIC))
                labels = ('basic', label) if order % 2 == 0 else (label, 'basic')
                with self.subTest(other=label, order=order):
                    results = self._race(*pair, gate_points=gate)
                    winner = self._assert_one_winner(results, labels)
                    body = self.status()
                    self.assertTrue(body['running'])
                    if winner.startswith('basic'):
                        self.assertEqual(body['mode'], 'basic')
                        self.assertIsNotNone(self.bridge.basic_run)
                        self.assertEqual(self.bridge.queue, [])
                    else:
                        self.assertTrue(body['mode'].startswith('chrome'))
                        self.assertIsNone(self.bridge.basic_run)
                    self._reset()

    def test_basic_races_live_verification(self):
        self.seed_vehicle()
        self.disc.blocking = {'toyota_used': True}
        from headless_dealer import HeadlessDealer
        gate = [(self.bridge, 'verify_status'), (HeadlessDealer, 'ensure_ready')]
        for order in range(4):
            pair = ((START, BASIC), ('/api/start-live-verify', VERIFY))
            labels = ('basic', 'verify')
            if order % 2:
                pair, labels = pair[::-1], labels[::-1]
            with self.subTest(order=order):
                results = self._race(*pair, gate_points=gate)
                wins = [label for label, (code, _) in zip(labels, results) if code == 200]
                self.assertEqual(len(wins), 1, results)
                if wins[0] == 'basic':
                    self.assertFalse(self.bridge.verify.get('running'))
                    self.finish_basic()
                else:
                    self.assertIsNone(self.bridge.basic_run)
                    self.assertTrue(self.bridge.verify.get('running'))
                    self.call(CONTROL, {'action': 'stop'})
                    self.assertFalse(self.bridge.verify.get('running'))
                self.disc.events.clear()

    def test_quick_holding_the_slot_serializes_a_basic_start(self):
        """Barrier inside admission: Quick holds the bridge lock mid-start."""
        inside, go = threading.Event(), threading.Event()
        real_state = self.store.state

        def held_state():
            if threading.current_thread().name != 'MainThread' and not inside.is_set():
                inside.set()
                wait_for(go, 'release of Quick admission')
            return real_state()

        with patch.object(self.store, 'state', held_state), ThreadPoolExecutor(2) as pool:
            quick = pool.submit(self.call, START, QUICK)
            wait_for(inside, 'Quick inside admission')
            basic = pool.submit(self.call, START, BASIC)
            time.sleep(0.3)
            self.assertFalse(basic.done(), 'Basic must wait for the slot, not race past it')
            go.set()
            self.assertEqual(quick.result(10)[0], 200)
            code, body = basic.result(10)
        self.assertEqual((code, body.get('error')), (400, 'another_scan_already_running'))
        self.assertIsNone(self.bridge.basic_run)
        self.assertEqual(self.disc.calls, [])

    def test_sequential_rejection_while_basic_owns_the_slot(self):
        self.seed_vehicle()
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        for path, body in ((START, QUICK), (START, RESCAN), (START, BASIC), ('/api/start-live-verify', VERIFY),
                           ('/api/full-scan-start', {'explicit_user_request': True}),
                           ('/api/fetch-missing-photos', {'explicit_request': True}),
                           ('/api/recheck-outstock', {'explicit_request': True})):
            with self.subTest(path=path, mode=body.get('mode')):
                code, reply = self.call(path, body)
                self.assertEqual(code, 400, reply)
        self.assertEqual(self.bridge.queue, [])
        self.assertFalse(self.handler.full_job['running'])
        self.assertEqual(self.status()['mode'], 'basic')
        self.finish_basic()
        self.assertEqual(self.call(START, QUICK)[0], 200, 'admission after the owner exits')

    def test_failed_thread_start_releases_the_slot(self):
        class Broken:
            def __init__(self, **_):
                pass

            def start(self):
                raise RuntimeError("can't start new thread")

        with patch.object(self.server, 'launch_scan_thread', Broken):
            code, body = self.call(START, BASIC)
        self.assertEqual((code, body.get('error')), (400, 'scan_worker_start_failed; no scan is running'))
        status = self.status()
        self.assertFalse(status['running'])
        self.assertEqual(status['state'], 'failed')
        self.assertIsNone(self.bridge.basic_run)
        self.assertEqual(self.disc.calls, [])
        self.assertEqual(self.call(START, QUICK)[0], 200)

    def test_full_scan_stage_transition_blocks_new_starts(self):
        """Between Full Scan stages the bridge is idle but the coordinator owns the run."""
        self.handler.full_job['running'] = True
        try:
            for body in (BASIC, QUICK):
                code, reply = self.call(START, body)
                self.assertEqual(code, 400)
                self.assertTrue(reply['error'].startswith('full_scan_running'))
            self.seed_vehicle()
            code, reply = self.call('/api/start-live-verify', VERIFY)
            self.assertEqual(code, 400)
            self.assertTrue(reply['error'].startswith('full_scan_running'))
        finally:
            self.handler.full_job['running'] = False
        self.assertIsNone(self.bridge.basic_run)
        self.assertEqual(self.disc.calls, [])


# ---------------------------------------------------------------- AC-02 -----
class AC02ReaderIsolationChrome(SeededCatalog):
    engine = 'chrome'

    def test_idle_chrome_poll_recovery_and_refresh_leave_basic_intact(self):
        self.seed_vehicle()
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        diagnostics = self.root / 'last_website_scan_diagnostics.json'
        self.assertFalse(diagnostics.exists())
        for _ in range(3):
            code, reply = self.call('/api/chrome-bridge/next')
            self.assertEqual(code, 200)
            self.assertIsNone(reply['job'])
            self.assertTrue(reply['running'])
        for path in ('/api/dealer-connection-console', '/api/live-verify-status'):
            self.assertEqual(self.call(path)[0], 200)
        self.bridge.recover_jobs()
        code, reply = self.call('/api/chrome-refresh-vehicle', {'explicit_user_request': True, 'vin': VIN})
        self.assertEqual(code, 400)
        self.assertTrue(reply['error'].startswith('historical_discovery_running'))
        with self.assertRaises(ValueError):
            self.bridge.start_single(VIN, 'toyota_used', automatic=True)
        status = self.status()
        self.assertEqual((status['running'], status['state'], status['completed']), (True, 'running', []))
        self.assertEqual(self.bridge.queue, [])
        self.assertEqual(self.bridge.inflight, {})
        self.assertFalse(diagnostics.exists(), 'no final diagnostics while Basic owns the slot')
        self.assertEqual(self.disk_catalog(), PRIOR)
        self.finish_basic()
        self.assertEqual(self.status()['state'], 'finished')
        self.assertEqual(json.loads(diagnostics.read_text('utf-8'))['run_id'], status['run_id'])

    def test_previous_verify_mode_does_not_finalize_basic(self):
        self.bridge.mode = 'verify'
        self.bridge.verify['running'] = False
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        self.assertIsNone(self.call('/api/chrome-bridge/next')[1]['job'])
        self.assertEqual(self.status()['state'], 'running')
        self.finish_basic()

    def test_priority_refresh_still_joins_a_compatible_chrome_scan(self):
        self.seed_vehicle()
        self.assertEqual(self.call(START, QUICK)[0], 200)
        reply = self.bridge.start_single(VIN)
        self.assertTrue(reply.get('priority'))
        self.assertTrue(self.bridge.queue[0].get('priority'))
        self.assertEqual(self.bridge.queue[0]['expected_vin'], VIN)
        self.call(CONTROL, {'action': 'stop'})


class AC02ReaderIsolationHeadless(SeededCatalog):
    engine = 'headless'

    def test_headless_poll_and_control_leave_basic_intact(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        self.assertIsNone(self.bridge.next(consumer='headless')['job'])
        self.assertIsNone(self.call('/api/chrome-bridge/next')[1]['job'])  # wrong engine poll
        self.call(CONTROL, {'action': 'workers', 'workers': 4})
        status = self.status()
        self.assertEqual((status['running'], status['state'], status['completed']), (True, 'running', []))
        self.assertEqual(self.disk_catalog(), PRIOR)
        self.finish_basic()


class AC02RestorePausedQueue(Fixture):
    def seed(self, root):
        job = {'id': 'a' * 20, 'source': 'toyota_used', 'url': url('toyota_used', 0x55), 'kind': 'vehicle'}
        data = {'jobs': [job], 'mode': 'scan', 'run_id': 'older-run', 'quick_scan': False,
                'totals': {}, 'count': {}, 'failures': {}, 'discovered_urls': {}, 'inventory_pages': {},
                'scan_info': {'running': True, 'mode': 'chrome', 'current': 'toyota_used', 'sources': ['toyota_used'],
                              'completed': [], 'errors': [], 'results': {}, 'events': [], 'samples': {},
                              'progress': {'toyota_used': {'phase': 'queued_chrome', 'discovered': 1, 'visited': 0,
                                                           'parsed': 0, 'failed': 0}}}}
        (root / 'pending_dealer_scan.json').write_text(json.dumps(data), 'utf-8')

    def test_restored_paused_queue_owns_the_slot(self):
        self.assertTrue(self.bridge.paused)
        self.assertEqual(len(self.bridge.queue), 1)
        self.assertEqual(self.status()['state'], 'paused')
        code, reply = self.call(START, BASIC)
        self.assertEqual((code, reply.get('error')), (400, 'another_scan_already_running'))
        self.assertEqual(self.disc.calls, [])
        self.assertTrue(self.call(CONTROL, {'action': 'resume'})[1]['control']['running'])
        job = self.bridge.next(consumer='headless')['job']
        self.assertEqual(job['url'], url('toyota_used', 0x55))
        self.call(CONTROL, {'action': 'stop'})
        self.assertEqual(self.status()['state'], 'stopped')
        self.assertEqual(self.call(START, BASIC)[0], 200)
        self.finish_basic()


# ---------------------------------------------------------------- AC-03 -----
class GatedRun(getattr(CB, 'BasicRun', object)):  # importable on pre-fix main for baseline evidence
    """Holds the worker at the N-th dealer-boundary checkpoint (between dealers)."""
    gate_at = 2
    hit = None
    go = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.boundaries = 0

    def checkpoint(self):
        self.boundaries += 1
        if self.boundaries == self.gate_at:
            GatedRun.hit.set()
            wait_for(GatedRun.go, 'between-dealer gate')
        return super().checkpoint()


class AC03Controls(SeededCatalog):
    def test_stop_on_first_dealer_drains_then_releases(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        code, reply = self.call(CONTROL, {'action': 'stop'})
        self.assertEqual(code, 200)
        control = reply['control']
        self.assertEqual((control['running'], control['stopping'], control['state']), (True, True, 'stopping'))
        status = self.status()
        self.assertEqual((status['running'], status['state'], status['stopping']), (True, 'stopping', True))
        dashboard = self.call('/api/chrome-bridge/dashboard')[1]
        self.assertEqual((dashboard['running'], dashboard['stopping']), (True, True))
        for body in (QUICK, RESCAN, BASIC):
            self.assertEqual(self.call(START, body)[0], 400, 'no new scan while the old worker drains')
        self.disc.release('toyota_used')
        status = self.wait_state('stopped')
        self.disc.join()
        self.assertEqual(self.disc.calls, ['toyota_used'], 'no new dealer request after Stop')
        self.assertFalse(status['running'])
        self.assertEqual(status['stopped_sources'], ['toyota_used'])
        self.assertEqual(status['committed'], [])
        self.assertEqual(self.disk_catalog(), PRIOR)
        self.assertEqual(self.api_catalog(), PRIOR)
        self.assertEqual(len(self.events('FINISH')), 1)
        self.assertEqual(self.call(START, QUICK)[0], 200)
        later = self.status()
        self.assertEqual((later['running'], later['mode']), (True, 'chrome_inventory_quick'))
        self.assertEqual(len(self.bridge.queue), 2)
        self.assertEqual(self.disk_catalog(), PRIOR, 'old worker wrote nothing after the new run began')

    def test_stop_between_dealers(self):
        GatedRun.hit, GatedRun.go = threading.Event(), threading.Event()
        with patch.object(CB, 'BasicRun', GatedRun):
            self.assertEqual(self.call(START, BASIC)[0], 200)
            wait_for(GatedRun.hit, 'worker between dealers')
            self.assertEqual(self.call(CONTROL, {'action': 'stop'})[1]['control']['state'], 'stopping')
            GatedRun.go.set()
            status = self.wait_state('stopped')
        self.disc.join()
        self.assertEqual(self.disc.calls, ['toyota_used'])
        self.assertEqual(status['committed'], ['toyota_used'])
        disk = self.disk_catalog()
        self.assertEqual(disk, self.api_catalog())
        self.assertEqual(disk['sources']['mitsubishi_used'], PRIOR['sources']['mitsubishi_used'])
        self.assertEqual(disk['sources']['toyota_used']['tag'], 'new')

    def test_stop_on_second_dealer_keeps_its_prior_catalog(self):
        self.disc.blocking = {'mitsubishi_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('mitsubishi_used'))
        self.call(CONTROL, {'action': 'stop'})
        self.disc.release('mitsubishi_used')
        status = self.wait_state('stopped')
        self.disc.join()
        self.assertEqual(status['committed'], ['toyota_used'])
        self.assertEqual(status['stopped_sources'], ['mitsubishi_used'])
        disk = self.disk_catalog()
        self.assertEqual(disk, self.api_catalog())
        self.assertEqual(disk['sources']['mitsubishi_used'], PRIOR['sources']['mitsubishi_used'])
        self.assertEqual(disk['sources']['toyota_used']['tag'], 'new')

    def test_pause_resume_and_stop_while_paused(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        reply = self.call(CONTROL, {'action': 'pause'})[1]['control']
        self.assertEqual((reply['paused'], reply['state']), (True, 'paused'))
        self.disc.release('toyota_used')
        time.sleep(0.4)
        self.assertEqual(self.disc.calls, ['toyota_used'], 'paused worker starts no new dealer')
        self.assertEqual(self.status()['state'], 'paused')
        self.assertEqual(self.status()['timing']['state'], 'paused')
        self.call(CONTROL, {'action': 'resume'})
        self.wait_state('finished')
        self.disc.join()
        self.assertEqual(self.disc.calls, SOURCES)
        self.assertEqual(self.status()['committed'], SOURCES)

    def test_stop_while_paused_wakes_the_worker(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        self.call(CONTROL, {'action': 'pause'})
        self.disc.release('toyota_used')
        time.sleep(0.3)
        self.assertEqual(self.status()['state'], 'paused')
        started = time.monotonic()
        self.call(CONTROL, {'action': 'stop'})
        status = self.wait_state('stopped')
        self.assertLess(time.monotonic() - started, 3)
        self.disc.join()
        self.assertEqual(self.disc.calls, ['toyota_used'])
        self.assertEqual(status['committed'], ['toyota_used'])

    def test_stop_twice_is_harmless(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        first = self.call(CONTROL, {'action': 'stop'})
        second = self.call(CONTROL, {'action': 'stop'})
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(second[1]['control']['state'], 'stopping')
        self.assertEqual(self.call(CONTROL, {'action': 'pause'})[1]['control']['state'], 'stopping')
        self.disc.release('toyota_used')
        self.wait_state('stopped')
        self.disc.join()
        third = self.call(CONTROL, {'action': 'stop'})
        self.assertEqual(third[0], 200)
        self.assertFalse(third[1]['control']['running'])
        self.assertEqual(len(self.events('BASIC_STOPPING')), 1)
        self.assertEqual(len(self.events('FINISH')), 1)

    def test_invalid_token_cannot_stop(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        self.assertEqual(self.call(CONTROL, {'action': 'stop'}, token='wrong')[0], 403)
        self.assertEqual(self.call(START, QUICK, token='wrong')[0], 403)
        self.assertEqual(self.call(STATUS, token='wrong')[0], 403)
        self.assertEqual(self.status()['state'], 'running')
        self.finish_basic()
        self.assertEqual(self.status()['state'], 'finished')


# ---------------------------------------------------------------- AC-04 -----
class AC04CatalogCommit(SeededCatalog):
    def test_stop_immediately_before_commit_keeps_prior_catalog(self):
        self.disc.blocking = {'toyota_used': True}
        self.disc.outputs['toyota_used'] = catalog_output('toyota_used', 'new', [url('toyota_used', 0xA1)])
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        self.call(CONTROL, {'action': 'stop'})  # read finishes after Stop: commit loses
        self.disc.release('toyota_used')
        self.wait_state('stopped')
        self.disc.join()
        self.assertEqual(self.disk_catalog(), PRIOR)
        self.assertEqual(self.api_catalog(), PRIOR)

    def test_stop_during_commit_lets_commit_finish_first(self):
        real_replace = pathlib.Path.replace
        in_replace, go = threading.Event(), threading.Event()

        def gated_replace(self_path, target):
            if self_path.name == 'basic_catalog_unverified.new' and not in_replace.is_set():
                in_replace.set()
                wait_for(go, 'commit release')
            return real_replace(self_path, target)

        with patch.object(pathlib.Path, 'replace', gated_replace):
            self.assertEqual(self.call(START, BASIC)[0], 200)
            wait_for(in_replace, 'toyota commit in progress')
            stopper = threading.Thread(target=self.call, args=(CONTROL, {'action': 'stop'}))
            stopper.start()
            deadline = time.monotonic() + 5
            while not (self.bridge.basic_run and self.bridge.basic_run.stopping):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            go.set()
            stopper.join(10)
            status = self.wait_state('stopped')
        self.disc.join()
        self.assertEqual(self.disc.calls, ['toyota_used'])
        self.assertEqual(status['committed'], ['toyota_used'])
        disk = self.disk_catalog()
        self.assertEqual(disk, self.api_catalog())
        toyota = disk['sources']['toyota_used']
        self.assertEqual(toyota['tag'], 'new')
        enriched = [r for r in toyota['records'] if r['url'] == url('toyota_used', 0xA1)]
        self.assertEqual(enriched[0]['enrichment'], PRIOR['sources']['toyota_used']['records'][1]['enrichment'])
        self.assertEqual(disk['sources']['mitsubishi_used'], PRIOR['sources']['mitsubishi_used'])
        self.assertEqual(len(self.events('FINISH')), 1)

    def test_replace_failure_keeps_file_and_memory_consistent(self):
        real_replace = pathlib.Path.replace
        failed = []

        def failing_replace(self_path, target):
            if self_path.name == 'basic_catalog_unverified.new' and not failed:
                failed.append(True)
                raise PermissionError('fixture: catalog is locked')
            return real_replace(self_path, target)

        with patch.object(pathlib.Path, 'replace', failing_replace):
            self.assertEqual(self.call(START, BASIC)[0], 200)
            status = self.wait_state('finished')
        self.disc.join()
        self.assertEqual(status['committed'], ['mitsubishi_used'])
        self.assertTrue(any(e['source'] == 'toyota_used' and 'catalog_write_failed' in e['reason']
                            for e in status['errors']))
        self.assertNotIn('toyota_used', status['results'])
        disk = self.disk_catalog()
        self.assertEqual(disk, self.api_catalog())
        self.assertEqual(disk['sources']['toyota_used'], PRIOR['sources']['toyota_used'])
        self.assertEqual(disk['sources']['mitsubishi_used']['tag'], 'new')
        self.assertFalse((self.root / 'basic_catalog_unverified.new').exists())

    def test_no_writes_from_old_run_after_next_run_begins(self):
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        old_run = self.bridge.basic_run
        self.call(CONTROL, {'action': 'stop'})
        self.disc.release('toyota_used')
        self.wait_state('stopped')
        self.disc.join()
        self.assertFalse(old_run.thread.is_alive())
        diagnostics = self.root / 'last_website_scan_diagnostics.json'
        before = (self.disk_catalog(), diagnostics.read_bytes())
        self.disc.events.clear()  # hold the NEW run in its first dealer read
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'), 'new run in flight')
        # A stale owner can neither commit nor release the new run.
        self.assertFalse(self.bridge.basic_owner(old_run))
        self.assertFalse(self.bridge.release_basic(old_run))
        self.assertEqual(self.status()['state'], 'running')
        self.assertEqual((self.disk_catalog(), diagnostics.read_bytes()), before)
        self.finish_basic()


# ---------------------------------------------------------------- AC-05 -----
class AC05Regression(Fixture):
    def test_chrome_quick_scan_finishes_normally(self):
        self.assertEqual(self.call(START, QUICK)[0], 200)
        for _ in range(2):
            job = self.bridge.next(consumer='headless')['job']
            self.assertEqual(job['kind'], 'inventory_index')
            self.bridge.submit({'id': job['id'], 'url': job['url'], 'outcome': 'inventory_index', 'urls': []})
        status = self.status()
        self.assertEqual((status['running'], status['state']), (False, 'finished'))
        self.assertEqual(sorted(status['completed']), sorted(SOURCES))
        self.assertTrue((self.root / 'last_website_scan_diagnostics.json').exists())

    def test_chrome_stop_is_immediate_and_frees_the_slot(self):
        self.assertEqual(self.call(START, RESCAN)[0], 200)
        job = self.bridge.next(consumer='headless')['job']
        reply = self.call(CONTROL, {'action': 'stop'})[1]['control']
        self.assertEqual((reply['running'], reply['state']), (False, 'stopped'))
        with self.assertRaises(ValueError):  # late result from the stopped run is rejected
            self.bridge.submit({'id': job['id'], 'url': job['url'], 'outcome': 'inventory_index', 'urls': []})
        self.assertEqual(self.call(START, BASIC)[0], 200)
        self.finish_basic()

    def test_full_scan_stop_then_basic(self):
        code, _ = self.call('/api/full-scan-start', {'explicit_user_request': True})
        self.assertEqual(code, 200)
        self.assertEqual(self.call(START, BASIC)[0], 400)
        self.call(CONTROL, {'action': 'stop'})
        deadline = time.monotonic() + 10
        while self.handler.full_job['running']:
            self.assertLess(time.monotonic(), deadline, 'Full Scan coordinator did not stop')
            time.sleep(0.1)
        self.assertEqual(self.handler.full_job['phase'], 'stopped')
        self.assertEqual(self.call(START, BASIC)[0], 200)
        self.finish_basic()

    def test_missing_photo_and_verify_start_when_idle(self):
        self.seed_vehicle()
        code, reply = self.call('/api/start-live-verify', VERIFY)
        self.assertEqual(code, 200)
        self.assertTrue(reply['verification']['running'])
        self.assertEqual(self.call(START, BASIC)[0], 400)
        self.call(CONTROL, {'action': 'stop'})
        self.assertFalse(self.bridge.verify['running'])
        code, reply = self.call('/api/fetch-missing-photos', {'explicit_request': True})
        self.assertEqual(code, 200)
        self.call(CONTROL, {'action': 'stop'})

    def test_stopped_historical_scan_marks_nothing_sold(self):
        self.seed_vehicle()
        before = json.dumps(self.store.state()['vehicles'], sort_keys=True)
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        self.call(CONTROL, {'action': 'stop'})
        self.disc.release('toyota_used')
        self.wait_state('stopped')
        self.disc.join()
        self.assertEqual(json.dumps(self.store.state()['vehicles'], sort_keys=True), before)
        self.assertEqual(len(self.store.removals()), 0)


# ------------------------------------- LR-009-03 Codex findings (F1-F3) -----
class FakeBrowser:
    """Reader transport stand-in. ``close_gate`` holds close() in flight, then raises."""
    def __init__(self, close_gate=None):
        self.close_gate = close_gate
        self.closing = threading.Event()

    async def close(self):
        self.closing.set()
        if self.close_gate is None:
            return
        import asyncio
        while not self.close_gate.is_set():
            await asyncio.sleep(0.01)
        self.closed = time.monotonic()
        raise RuntimeError('synthetic old browser close failure')


class PumpHarness:
    """Run the production HeadlessDealer._run/_pump loop with a fake transport."""
    def __init__(self, test, browsers):
        import asyncio
        from contextlib import asynccontextmanager
        self.test = test
        self.h = test.handler.headless_dealer
        self.browsers = list(browsers)
        self.leases = []
        self.leased = threading.Event()

        @asynccontextmanager
        async def transport():
            yield types.SimpleNamespace(chromium=None)

        async def launch(_chromium):
            return self.browsers.pop(0)

        async def read(_browser, job):
            self.leases.append(job)
            self.leased.set()
            await asyncio.Future()  # an in-flight dealer page; only cancellation ends it

        api = types.ModuleType('playwright.async_api')
        api.async_playwright = transport
        pkg = types.ModuleType('playwright')
        pkg.async_api = api
        self.stack = ExitStack()
        self.stack.enter_context(patch.dict(sys.modules, {'playwright': pkg, 'playwright.async_api': api}))
        self.stack.enter_context(patch.object(self.h, '_launch', launch))
        self.stack.enter_context(patch.object(self.h, '_read', read))
        self.stack.enter_context(patch.object(self.h.load_monitor, 'sample', lambda: {}))
        self.h.stop_event.clear()
        self.thread = threading.Thread(target=self.h._run, name='LR009-Test-Pump', daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.h.stop_event.set()
        self.thread.join(10)
        self.stack.close()
        if self.thread.is_alive():
            raise AssertionError('Reader pump did not exit')
        return False


class F1RetiredReaderTransport(Fixture):
    """Codex LR-009-03 finding 1: a retired browser's close failure stops the new run."""

    def _lease_old_quick_and_retire_it(self, pump, close_gate):
        self.assertEqual(self.call(START, QUICK)[0], 200)
        wait_for(pump.leased, 'old Quick lease')
        self.call(CONTROL, {'action': 'stop'})
        wait_for(pump.browsers_used[0].closing, 'old browser close in flight')

    def test_old_browser_close_failure_leaves_new_rescan_running_and_served(self):
        gate = threading.Event()
        old, new = FakeBrowser(gate), FakeBrowser()
        with PumpHarness(self, [old, new]) as pump:
            pump.browsers_used = [old, new]
            self._lease_old_quick_and_retire_it(pump, gate)
            self.assertEqual(self.call(START, RESCAN)[0], 200)
            new_run = self.bridge.run_id
            pump.leased.clear()
            gate.set()  # the retired browser's close now fails
            wait_for(pump.leased, 'the Rescan job is served after the old close failed')
            self.assertEqual(pump.leases[-1]['_run_id'], new_run)
            status = self.status()
            self.assertEqual((status['running'], status['state'], status['mode']),
                             (True, 'running', 'chrome_inventory_full'))
            self.assertEqual(self.events('HEADLESS_ERROR'), [])
            self.assertEqual(self.h_teardown(), 'RuntimeError')
            self.call(CONTROL, {'action': 'stop'})

    def test_old_browser_close_failure_stays_out_of_new_basic(self):
        gate = threading.Event()
        old = FakeBrowser(gate)
        with PumpHarness(self, [old]) as pump:
            pump.browsers_used = [old]
            self._lease_old_quick_and_retire_it(pump, gate)
            self.disc.blocking = {'toyota_used': True}
            self.assertEqual(self.call(START, BASIC)[0], 200)
            wait_for(self.disc.entered('toyota_used'))
            gate.set()
            # The close failure has been handled once it is recorded, or once
            # the pump (pre-fix behaviour) has died from it.
            deadline = time.monotonic() + 5
            while (self.h_teardown() is None and pump.thread.is_alive()
                   and time.monotonic() < deadline):
                time.sleep(0.02)
            time.sleep(0.2)
            self.assertEqual(self.status()['state'], 'running')
            self.call(CONTROL, {'action': 'stop'})
            self.finish_basic()
        diag = json.loads((self.root / 'last_website_scan_diagnostics.json').read_text('utf-8'))
        self.assertEqual([e for e in diag['events'] if e['stage'] == 'HEADLESS_ERROR'], [])
        self.assertEqual([e for e in diag['errors'] if 'Headless' in e['reason']], [])
        self.assertEqual(self.h_teardown(), 'RuntimeError')

    def test_current_run_transport_failure_still_stops_that_run(self):
        """The legitimate case: the active run's own transport fails to launch."""
        async def broken_launch(_chromium):
            raise RuntimeError('synthetic launch failure')
        with PumpHarness(self, []) as pump:
            with patch.object(pump.h, '_launch', broken_launch):
                self.assertEqual(self.call(START, QUICK)[0], 200)
                run = self.bridge.run_id
                pump.thread.join(5)  # a current-run fault ends the pump
                self.assertFalse(pump.thread.is_alive())
        status = self.status()
        self.assertEqual((status['running'], status['state'], self.bridge.run_id), (False, 'stopped', run))
        self.assertEqual(len(self.events('HEADLESS_ERROR')), 1)
        self.assertTrue(any('Headless browser failed: RuntimeError' in e['reason'] for e in status['errors']))

    def test_retired_run_fault_restarts_the_pump_for_the_current_run(self):
        from headless_dealer import ReaderFault
        h = self.handler.headless_dealer
        self.assertEqual(self.call(START, QUICK)[0], 200)
        calls = []

        async def pump():
            calls.append(self.bridge.run_id)
            if len(calls) == 1:
                raise ReaderFault('retired-run', RuntimeError('late teardown'))
        with patch.object(h, '_pump', pump):
            h._run()
        self.assertEqual(len(calls), 2, 'pump restarted once for the active run')
        self.assertEqual(self.status()['state'], 'running')
        self.assertEqual(self.events('HEADLESS_ERROR'), [])
        self.call(CONTROL, {'action': 'stop'})

    def _late_untagged_failure(self, failures):
        """Codex's delayed pump failure: the old pump raises after Stop + Rescan."""
        h = self.handler.headless_dealer
        entered, go = threading.Event(), threading.Event()
        calls = []

        async def pump():
            calls.append(self.bridge.run_id)
            if len(calls) == 1:
                entered.set()
                wait_for(go, 'release of the old pump')
            if len(calls) <= failures:
                raise RuntimeError('synthetic transport shutdown')
        with patch.object(h, '_pump', pump):
            self.assertEqual(self.call(START, QUICK)[0], 200)
            worker = threading.Thread(target=h._run, daemon=True)
            worker.start()
            wait_for(entered)
            try:
                self.call(CONTROL, {'action': 'stop'})
                self.assertEqual(self.call(START, RESCAN)[0], 200)
                rescan = self.bridge.run_id
            finally:
                go.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
        return calls, rescan

    def test_one_late_untagged_failure_restarts_the_pump_for_the_new_rescan(self):
        calls, rescan = self._late_untagged_failure(failures=1)
        self.assertEqual(calls[1:], [rescan], 'one restart, serving the Rescan')
        status = self.status()
        self.assertEqual((status['running'], status['state'], self.bridge.run_id), (True, 'running', rescan))
        self.assertEqual(self.events('HEADLESS_ERROR'), [])
        self.call(CONTROL, {'action': 'stop'})

    def test_a_transport_that_keeps_failing_is_reported_unavailable_once(self):
        calls, rescan = self._late_untagged_failure(failures=10)
        budget = self.handler.headless_dealer.RESTART_BUDGET
        self.assertEqual(len(calls), 1 + budget, 'bounded restarts, then the Reader is unavailable')
        status = self.status()
        self.assertEqual((status['running'], status['state'], self.bridge.run_id), (False, 'stopped', rescan))
        self.assertEqual(len(self.events('HEADLESS_UNAVAILABLE')), 1)
        self.assertEqual(self.events('HEADLESS_ERROR'), [], 'not reported as a failure of the Rescan itself')
        self.assertTrue(any(e['reason'].startswith('READER_UNAVAILABLE') for e in status['errors']))

    def test_repeated_retired_faults_do_not_stop_a_paused_successor(self):
        """LR-009-05: two faults tagged with a retired run id are not the paused run's."""
        from headless_dealer import ReaderFault
        h = self.handler.headless_dealer
        self.assertEqual(self.call(START, QUICK)[0], 200)
        self.call(CONTROL, {'action': 'pause'})
        calls = []

        async def pump():
            calls.append(1)
            if len(calls) <= 2:
                raise ReaderFault('retired-run', RuntimeError('late teardown'))
        with patch.object(h, '_pump', pump):
            h._run()
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.status()['state'], 'paused')
        self.assertEqual(self.events('HEADLESS_ERROR') + self.events('HEADLESS_UNAVAILABLE'), [])
        self.call(CONTROL, {'action': 'stop'})

    def h_teardown(self):
        return getattr(self.handler.headless_dealer, 'teardown_error', None)


class F2ForeignEventsStayOutOfBasic(SeededCatalog):
    """Codex LR-009-03 finding 2: unrelated Reader/refresh errors in Basic's history."""

    def test_reader_pump_failure_while_basic_owns_the_slot(self):
        h = self.handler.headless_dealer
        entered, release = threading.Event(), threading.Event()

        async def failing_pump():
            entered.set()
            wait_for(release, 'test release of the old pump')
            raise RuntimeError('synthetic transport shutdown')
        with patch.object(h, '_pump', failing_pump):
            self.assertEqual(self.call(START, QUICK)[0], 200)
            worker = threading.Thread(target=h._run, daemon=True)
            worker.start()
            wait_for(entered)
            try:
                self.call(CONTROL, {'action': 'stop'})
                self.disc.blocking = {'toyota_used': True}
                self.assertEqual(self.call(START, BASIC)[0], 200)
                wait_for(self.disc.entered('toyota_used'))
            finally:
                release.set()
                worker.join(5)
        self.assertEqual(self.status()['state'], 'running')
        self.call(CONTROL, {'action': 'stop'})
        self.finish_basic()
        diag = json.loads((self.root / 'last_website_scan_diagnostics.json').read_text('utf-8'))
        self.assertEqual([e['stage'] for e in diag['events'] if e['stage'] == 'HEADLESS_ERROR'], [])

    def test_trade_ready_refresh_refusal_is_not_logged_in_basic(self):
        import inspect
        self.seed_vehicle()
        self.disc.blocking = {'toyota_used': True}
        self.assertEqual(self.call(START, BASIC)[0], 200)
        wait_for(self.disc.entered('toyota_used'))
        trade_ready = inspect.getclosurevars(self.handler.do_POST).nonlocals.get('trade_ready')
        self.assertIsNotNone(trade_ready, 'trade-ready hook not reachable from the handler')
        trade_ready.refresh_gallery(VIN, 'toyota_used')
        self.assertEqual(self.events('TRADE_READY_REFRESH_ERROR'), [])
        self.assertEqual(self.bridge.queue, [])
        self.assertEqual(self.status()['state'], 'running')
        self.finish_basic()


class F3CoordinatorLaunchFailure(Fixture):
    """Codex LR-009-03 finding 3: a failed coordinator launch keeps the slot occupied."""

    def _failing(self, thread_name):
        real = threading.Thread.start

        def start(thread):
            if thread.name == thread_name:
                raise RuntimeError("can't start new thread")
            return real(thread)
        return patch.object(threading.Thread, 'start', start)

    def _assert_slot_free(self):
        self.assertFalse(self.handler.full_job['running'])
        self.assertEqual(self.handler.full_job['phase'], 'failed')
        self.assertEqual(self.bridge.queue, [])
        self.assertEqual(self.bridge.inflight, {})
        self.assertEqual(self.call(START, QUICK)[0], 200, 'a new scan is admitted after the rollback')
        self.call(CONTROL, {'action': 'stop'})

    def test_full_scan_coordinator_launch_failure_rolls_back(self):
        with self._failing('Marketplace-Full-Scan'):
            code, reply = self.call('/api/full-scan-start', VERIFY)
        self.assertEqual((code, reply.get('error')), (400, 'scan_coordinator_start_failed; no scan is running'))
        status = self.status()
        self.assertEqual((status['running'], status['state']), (False, 'failed'))
        self.assertTrue(any(e['reason'].startswith('full_scan_coordinator_start_failed') for e in status['errors']))
        self.assertTrue(self.handler.full_job['error'].startswith('full_scan_coordinator_start_failed'))
        self._assert_slot_free()

    def test_check_listings_coordinator_launch_failure_rolls_back_verification(self):
        self.seed_vehicle()
        self.store.create_draft(VIN, 'toyota_used')
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url=? WHERE vin=?",
                              ('https://www.facebook.com/marketplace/item/1111111111111/', VIN))
        self.store.db.commit()
        with self._failing('LotRadar-Check-Listing-Links'):
            code, reply = self.call('/api/facebook-auto-check-all', {'explicit_request': True})
        self.assertEqual((code, reply.get('error')), (400, 'scan_coordinator_start_failed; no scan is running'))
        self.assertFalse(self.bridge.verify['running'])
        self.assertTrue(self.bridge.verify.get('interrupted'))
        self._assert_slot_free()

    def _seed_coordinated_targets(self):
        """One saved vehicle that every coordinated route has work for."""
        self.seed_vehicle()
        self.store.create_draft(VIN, 'toyota_used')
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url=? WHERE vin=?",
                              ('https://www.facebook.com/marketplace/item/1111111111111/', VIN))
        self.store.db.commit()
        self.store.record_link_check('toyota_used', url('toyota_used', 0x77), 'unavailable')

    def test_rollback_is_durable_on_every_coordinated_route(self):
        """LR-009-05: a restarted bridge must not restore the failed operation's jobs."""
        self._seed_coordinated_targets()
        routes = [('/api/full-scan-start', VERIFY, 'Marketplace-Full-Scan'),
                  ('/api/recheck-outstock', {'explicit_request': True}, 'LotRadar-Recheck-Outstock'),
                  ('/api/facebook-auto-check-all', {'explicit_request': True}, 'LotRadar-Check-Listing-Links')]
        for route, body, thread_name in routes:
            with self.subTest(route=route):
                with self._failing(thread_name):
                    code, reply = self.call(route, body)
                self.assertEqual((code, reply.get('error')), (400, 'scan_coordinator_start_failed; no scan is running'))
                self.assertFalse(self.bridge.queue or self.bridge.inflight)
                checkpoint = json.loads((self.root / 'pending_dealer_scan.json').read_text('utf-8'))
                self.assertEqual(checkpoint['jobs'], [])
                reopened = CB.ChromeBridge(self.root, self.store, lambda *a: None, {}, threading.RLock())
                self.assertEqual(reopened.queue, [], 'failed coordinator work restored after restart')
                self.assertFalse(reopened.scan_info.get('running') or reopened.verify.get('running'))
                self._assert_slot_free()

    def test_no_job_is_dispatched_before_the_coordinator_starts(self):
        """LR-009-05: a ready Reader cannot import while the coordinator launch is pending."""
        self.seed_vehicle()
        before = json.dumps(self.store.state()['vehicles'], sort_keys=True)
        arrived, release = threading.Event(), threading.Event()
        polls = []

        def launch(**_):
            arrived.set()
            wait_for(release, 'test release of the coordinator launch')
            raise RuntimeError("can't start new thread")
        with patch.object(self.server, 'launch_scan_thread', launch), ThreadPoolExecutor(1) as pool:
            pending = pool.submit(self.call, '/api/full-scan-start', VERIFY)
            try:
                wait_for(arrived)
                for _ in range(4):  # the Reader is connected and polling
                    polls.append(self.bridge.next(consumer='headless')['job'])
            finally:
                release.set()
            self.assertEqual(pending.result(10)[0], 400)
        self.assertEqual(polls, [None] * 4, 'no lease while the coordinator is not running')
        self.assertEqual(json.dumps(self.store.state()['vehicles'], sort_keys=True), before)
        self._assert_slot_free()

    def test_jobs_dispatch_once_the_coordinator_has_started(self):
        code, reply = self.call('/api/full-scan-start', VERIFY)
        self.assertEqual(code, 200)
        job = self.bridge.next(consumer='headless')['job']
        self.assertEqual(job['kind'], 'inventory_index')
        self.assertFalse(self.bridge.dispatch_hold)
        self.call(CONTROL, {'action': 'stop'})
        deadline = time.monotonic() + 10
        while self.handler.full_job['running']:
            self.assertLess(time.monotonic(), deadline, 'Full Scan coordinator did not stop')
            time.sleep(0.1)

    def test_successful_launch_is_unchanged(self):
        code, reply = self.call('/api/full-scan-start', VERIFY)
        self.assertEqual(code, 200)
        self.assertTrue(reply['full']['running'])
        self.call(CONTROL, {'action': 'stop'})
        deadline = time.monotonic() + 10
        while self.handler.full_job['running']:
            self.assertLess(time.monotonic(), deadline, 'Full Scan coordinator did not stop')
            time.sleep(0.1)


# ------------------------------------------------- scraper checkpoints ------
class FakeRobots:
    def permitted(self, _url):
        return True

    def sitemaps_for(self, _home):
        return []


class ScraperCheckpoints(unittest.TestCase):
    def setUp(self):
        install_offline_guard(self)

    def _fake_playwright(self, on_wait):
        state = types.SimpleNamespace(gotos=0, scrolls=0, waits=0, closed=0, launched=0)

        class Page:
            def goto(self, *_a, **_k):
                state.gotos += 1

            def wait_for_timeout(self, _ms):
                state.waits += 1
                on_wait(state)

            def content(self):
                links = ''.join(f'<a href="/used/2022-Toyota-Camry-{n:020x}.htm">x</a>'
                                for n in range(state.scrolls * 2 + 2))
                return '<html><body>' + links + '</body></html>'

            def evaluate(self, _js):
                state.scrolls += 1

        class Browser:
            def new_context(self, **_):
                return types.SimpleNamespace(new_page=Page)

            def close(self):
                state.closed += 1

        class Chromium:
            def launch(self, **_):
                state.launched += 1
                return Browser()

        class Manager:
            def __enter__(self):
                return types.SimpleNamespace(chromium=Chromium())

            def __exit__(self, *_):
                return False

        module = types.ModuleType('playwright.sync_api')
        module.sync_playwright = Manager
        return state, {'playwright': types.ModuleType('playwright'), 'playwright.sync_api': module}

    def test_stop_during_browser_scroll_closes_this_runs_browser(self):
        control = DS.ScanControl()
        state, modules = self._fake_playwright(lambda s: control.stop() if s.waits == 2 else None)
        with patch.dict(sys.modules, modules), patch.object(DS, 'RobotsGate', FakeRobots):
            with self.assertRaises(DS.ScanCancelled):
                DS.scan_basic_source('toyota_used', max_vehicles=800, control=control)
        self.assertEqual((state.launched, state.closed, state.gotos), (1, 1, 1))
        self.assertLessEqual(state.scrolls, 1, 'no scroll pass after Stop')

    def test_stop_before_start_makes_no_request(self):
        control = DS.ScanControl()
        control.stop()
        state, modules = self._fake_playwright(lambda s: None)
        with patch.dict(sys.modules, modules), patch.object(DS, 'RobotsGate', FakeRobots):
            with self.assertRaises(DS.ScanCancelled):
                DS.scan_basic_source('toyota_used', control=control)
        self.assertEqual(state.launched, 0)

    def test_sitemap_stops_between_requests_and_wait_is_interruptible(self):
        control = DS.ScanControl()
        requests = []
        xml = (b'<?xml version="1.0"?><sitemapindex>'
               b'<sitemap><loc>https://www.hamptontoyota.com/inventory-1.xml</loc></sitemap>'
               b'<sitemap><loc>https://www.hamptontoyota.com/inventory-2.xml</loc></sitemap></sitemapindex>')

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _n):
                return xml

        def fake_urlopen(req, timeout=None):
            requests.append(req.full_url)
            threading.Timer(0.2, control.stop).start()
            return Response()

        started = time.monotonic()
        with patch.object(DS, 'urlopen', fake_urlopen):
            with self.assertRaises(DS.ScanCancelled):
                DS.sitemap_vehicle_links(FakeRobots(), 'toyota_used', delay=30, control=control)
        self.assertEqual(len(requests), 1, 'no sitemap request after Stop')
        self.assertLess(time.monotonic() - started, 5, 'the 30s politeness wait is interruptible')

    def test_pause_blocks_and_stop_wakes(self):
        control = DS.ScanControl()
        control.pause()
        self.assertTrue(control.paused)
        result = []
        worker = threading.Thread(target=lambda: result.append(self._try(control)))
        worker.start()
        time.sleep(0.2)
        self.assertTrue(worker.is_alive(), 'paused checkpoint waits')
        control.stop()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, ['cancelled'])
        self.assertFalse(control.paused)

    @staticmethod
    def _try(control):
        try:
            control.checkpoint()
            return 'continued'
        except DS.ScanCancelled:
            return 'cancelled'


if __name__ == '__main__':
    unittest.main()
