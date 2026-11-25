"""Full close-and-reopen of a REAL LotRadar process, offline, with synthetic data (Architect's open test).

Two separate `python server.py` processes run one after the other on the same temporary data folder:
  1. start LotRadar, press Delete listing on a synthetic tracked vehicle (it moves to Pending),
  2. kill the process completely (TerminateProcess on Windows: no clean shutdown),
  3. start LotRadar again, offline, and check the Pending card has the same VIN, stock and photo bytes,
     in the API and (when Chromium is installed) in the real page; then "I've deleted it on Facebook".

Safety: --data-dir is a temp folder and LOCALAPPDATA/USERPROFILE point inside it, so nothing can reach the
Owner's %LOCALAPPDATA%\\MarketplaceScanner. HTTP(S)_PROXY point at a closed local port (only 127.0.0.1 is
exempt), so any dealer/CDN request fails: the app is offline. Nothing is posted to Facebook; window.open is
replaced in the page before any click. Set LOTRADAR_UI_EVIDENCE_DIR to save a screenshot.
"""
import hashlib, io, json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.error, urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import MarketplaceStore

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _p:
        _p.chromium.launch().close()
    HAVE_BROWSER = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_BROWSER = False

EVIDENCE = os.environ.get('LOTRADAR_UI_EVIDENCE_DIR', '')
TOY = 'toyota_used'
VIN = '1HGCM82633A004352'
FB = 'https://www.facebook.com/marketplace/item/1111111111111/'
URLS = [f'https://pictures.dealer.com/h/hamptontoyota/v0/photo{k}.jpg' for k in range(3)]
LOADED = "(sel)=>{const i=document.querySelector(sel);return Boolean(i&&i.complete&&i.naturalWidth>0)}"


def jpeg(color):
    out = io.BytesIO(); Image.new('RGB', (640, 480), color).save(out, 'JPEG', quality=90); return out.getvalue()


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


class RealProcessRestart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.data = self.home / 'data'
        store = MarketplaceStore(self.data)
        store.import_feed(TOY, 'json', json.dumps([{'vin': VIN, 'condition': 'used', 'year': 2022, 'make': 'Toyota',
            'model': 'Camry', 'stock': 'T100', 'mileage': 12345, 'price': 24434, 'url': 'https://www.hamptontoyota.com/used/0.htm',
            'images': URLS}]))
        store.create_draft(VIN, TOY)
        store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url=? WHERE vin=?", (FB, VIN))
        store.close()
        # Cached photos exactly as PhotoCache stores them: vehicle_photos/<VIN>/<source>/<NN>_<hash>.jpg + manifest.json
        folder = self.data / 'vehicle_photos' / VIN / TOY; folder.mkdir(parents=True)
        entries = {}
        for k, (url, color) in enumerate(zip(URLS, ['#9a2a2a', '#2a9a2a', '#2a2a9a'])):
            blob = jpeg(color); name = f'{k + 1:02d}_{hashlib.sha256(url.encode()).hexdigest()[:24]}.jpg'
            (folder / name).write_bytes(blob)
            if k == 0: self.cover = blob
            entries[url] = {'file': name, 'size': len(blob), 'status': 'saved', 'error': '', 'width': 640, 'height': 480,
                            'visual_hash': f'v{k}', 'screen_version': 61, 'category': 'vehicle',
                            'quality_reason': 'local_visual_screen_passed', 'quality_checked': True}
        (folder / 'manifest.json').write_text(json.dumps({'urls': URLS, 'entries': entries}), 'utf-8')
        self.proc = None
        self.addCleanup(self.kill)

    # ---- process control
    def start(self):
        self.port = free_port()
        env = dict(os.environ)
        sandbox = str(self.home)
        env.update(LOCALAPPDATA=sandbox, APPDATA=sandbox, USERPROFILE=sandbox, HOME=sandbox,
                   HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
                   http_proxy='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9',
                   NO_PROXY='127.0.0.1', no_proxy='127.0.0.1', PYTHONUNBUFFERED='1')
        env.pop('OPENAI_API_KEY', None)
        self.log = open(self.home / f'server-{self.port}.log', 'wb')
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--data-dir', str(self.data),
                                      '--port', str(self.port), '--no-browser'],
                                     cwd=str(self.home), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.fail('LotRadar exited during startup: ' + (self.home / f'server-{self.port}.log').read_text('utf-8', 'replace')[-2000:])
            try:
                if self.get_json('/api/health').get('ok'): break
            except OSError:
                time.sleep(0.3)
        else:
            self.fail('LotRadar did not start within 60 s')
        self.token = self.get_json('/api/bootstrap')['csrf']

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()            # TerminateProcess on Windows: an abrupt close, no shutdown code runs
            self.proc.wait(30)
        if self.proc:
            self.log.close()
        self.proc = None

    # ---- HTTP (direct to 127.0.0.1, never through the blocking proxy)
    def open(self, req):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20)

    def get_json(self, path):
        with self.open(urllib.request.Request(f'http://127.0.0.1:{self.port}{path}')) as r: return json.load(r)

    def get_bytes(self, path):
        try:
            with self.open(urllib.request.Request(f'http://127.0.0.1:{self.port}{path}')) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, e.read()

    def action(self, body):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/action', json.dumps(body).encode(),
                                     {'Content-Type': 'application/json', 'X-SalesmanHub-Token': self.token})
        with self.open(req) as r: return json.load(r)

    def pending(self):
        return [r for r in self.get_json('/api/state')['removals'] if r['status'] == 'PENDING_FB_DELETE']

    def photo(self, row):
        p = row['identity']['photo']
        return self.get_bytes(f"/api/removal-photo?vin={row['vin']}&source={p['source']}&ref={p['sha256']}")

    def test_pending_card_survives_a_full_offline_restart_of_the_real_process(self):
        self.start()
        first_pid = self.proc.pid
        self.action({'action': 'remove_out_of_stock', 'vin': VIN, 'explicit_out_of_stock_confirmation': True})
        before = self.pending()
        self.assertEqual([r['vin'] for r in before], [VIN])
        self.assertEqual(before[0]['identity']['stock'], 'T100')
        self.assertEqual(self.photo(before[0]), (200, self.cover))

        self.kill()                                   # LotRadar fully closed
        with self.assertRaises(OSError): self.get_json('/api/health')
        self.port_before = self.port

        self.start()                                  # LotRadar opened again, offline
        self.assertNotEqual(self.proc.pid, first_pid)
        after = self.pending()
        self.assertEqual(after, before)               # same VIN, stock, identity and saved photo reference
        self.assertEqual(self.photo(after[0]), (200, self.cover))   # same image bytes
        self.assertFalse(any(VIN == v['vin'] for v in self.get_json('/api/state')['vehicles']))

        if HAVE_BROWSER:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={'width': 1280, 'height': 1000})
                page.on('dialog', lambda d: d.accept())
                page.goto(f'http://127.0.0.1:{self.port}/')
                page.evaluate("()=>{window.__opened=[];window.open=(u)=>{window.__opened.push(u);return null};}")
                page.click('button[data-tab="deletelisting"]')
                card = f'.pending-removal-card[data-delete-vin="{VIN}"]'
                page.wait_for_selector(card, timeout=20000)
                page.wait_for_function(LOADED, arg=f'{card} .vehicle-photo img', timeout=20000)
                text = page.inner_text(card)
                for needle in ('STOCK T100', VIN, '12,345 mi', '$24,434', 'Photo saved when confirmed out of stock'):
                    self.assertIn(needle, text)
                if EVIDENCE:
                    Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(Path(EVIDENCE) / 'cards-05-after-real-process-restart.png'), full_page=True)
                with page.expect_response(lambda r: r.url.endswith('/api/action')) as reply:
                    page.click(f'{card} [data-delete-confirm]')
                self.assertEqual(reply.value.status, 200)
                page.wait_for_selector(card, state='detached', timeout=10000)
                browser.close()
            self.assertEqual(self.pending(), [])
            self.assertEqual(self.photo(after[0])[0], 404)    # reminder cleared: the photo is no longer served
        # The original cached file is untouched (no deletion in this work)
        cached = self.data / 'vehicle_photos' / VIN / TOY / after[0]['identity']['photo']['file']
        self.assertEqual(cached.read_bytes(), self.cover)


if __name__ == '__main__':
    unittest.main()
