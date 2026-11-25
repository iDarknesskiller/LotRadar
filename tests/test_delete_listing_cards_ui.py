"""Delete Listing vehicle cards in the real app page (headless Chromium, synthetic data and photos only).

Skipped when Playwright/Chromium is not installed. Assertions are on server responses and on loaded
image elements, not on timing. Set LOTRADAR_UI_EVIDENCE_DIR to save the screenshots used as evidence.
Nothing reaches a dealer site, Facebook or the Owner's data: window.open is replaced before any click.
"""
import hashlib, io, json, os, socket, sys, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server as S
from core import MarketplaceStore
from test_delete_listing_refresh import RefreshBase, VINS, LID, FB, TOY, dealer_url
from PIL import Image

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _p:
        _p.chromium.launch().close()
    HAVE_BROWSER = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_BROWSER = False

EVIDENCE = os.environ.get('LOTRADAR_UI_EVIDENCE_DIR', '')


def photo_urls(i):
    return [f'https://pictures.dealer.com/h/hamptontoyota/v{i}/photo{k}.jpg' for k in range(3)]


def jpeg(color):
    out = io.BytesIO(); Image.new('RGB', (640, 480), color).save(out, 'JPEG', quality=90); return out.getvalue()


def offline(url):
    raise OSError('offline test: no network')


def seed(cache, vin, urls, colors):
    d = cache._directory(vin, TOY); d.mkdir(parents=True, exist_ok=True)
    entries, blobs = {}, {}
    for k, (url, color) in enumerate(zip(urls, colors)):
        blob = jpeg(color); name = f'{k + 1:02d}_{hashlib.sha256(url.encode()).hexdigest()[:24]}.jpg'
        (d / name).write_bytes(blob); blobs[k] = blob
        entries[url] = {'file': name, 'size': len(blob), 'status': 'saved', 'error': '', 'width': 640, 'height': 480,
                        'visual_hash': f'v{k}{color}', 'screen_version': 61, 'category': 'vehicle',
                        'quality_reason': 'local_visual_screen_passed', 'quality_checked': True}
    cache._save(vin, TOY, {'urls': urls, 'entries': entries})
    return blobs


LOADED = "(sel)=>{const i=document.querySelector(sel);return Boolean(i&&i.complete&&i.naturalWidth>0)}"


@unittest.skipUnless(HAVE_BROWSER, 'Playwright Chromium not available')
class CardsUi(RefreshBase):
    def shot(self, page, name):
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(EVIDENCE) / f'{name}.png'), full_page=True)

    def open_delete_listing(self, browser, port):
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        page.on('dialog', lambda d: d.accept())
        page.goto(f'http://127.0.0.1:{port}/')
        page.evaluate("()=>{window.__opened=[];window.open=(u)=>{window.__opened.push(u);return null};}")
        page.click('button[data-tab="deletelisting"]')
        page.wait_for_selector('#btn-delete-refresh')
        return page

    def test_three_card_types_with_saved_photo_through_confirmation_and_offline_restart(self):
        H = self.H; H.photo_cache.downloader = offline
        for i in (0, 1):
            self.store.db.execute("UPDATE sources SET record_json=json_set(record_json,'$.images',json(?)) WHERE vin=? AND source=?",
                                  (json.dumps(photo_urls(i)), VINS[i], TOY))
        cover0 = seed(H.photo_cache, VINS[0], photo_urls(0), ['#9a2a2a', '#2a9a2a', '#2a2a9a'])[0]
        cover1 = seed(H.photo_cache, VINS[1], photo_urls(1), ['#2f6f8f', '#8f8f2f', '#6f2f8f'])[0]
        self.track(0); self.track(1)
        # VIN 2: an older pending reminder saved before this change (no photo reference) -> placeholder
        old = {'vin': VINS[2], 'year': 2022, 'make': 'Toyota', 'model': 'Model2', 'trim': None, 'stock': 'T2',
               'stocks': {TOY: 'T2'}, 'sources': [TOY], 'price_cents': 2000000, 'title': '2022 Toyota Model2'}
        self.store.db.execute("INSERT INTO inventory_removals(vin,status,removed_at,identity_json,listing_url,listing_id) VALUES(?,?,?,?,?,?)",
                              (VINS[2], 'PENDING_FB_DELETE', S.utc(), json.dumps(old), FB[2], LID[2]))
        # VIN 1: Needs stock verification (dealer link unavailable); VIN 0: Refresh review (dealer page timed out)
        self.store.record_link_check(TOY, dealer_url(TOY, 1), 'unavailable')
        self.findings = {(VINS[0], TOY): ('INCONCLUSIVE', ['PAGE_TIMEOUT'])}
        _, batch = self.run_batch({LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown')})
        self.assertEqual([i['vin'] for i in batch['review']], [VINS[0]])

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = self.open_delete_listing(browser, self.port)
            review, tracked, older = (f'.refresh-review-card[data-delete-vin="{VINS[0]}"]', f'.tracked-review-card[data-delete-vin="{VINS[1]}"]',
                                      f'.pending-removal-card[data-delete-vin="{VINS[2]}"]')
            for sel in (review, tracked):
                page.wait_for_selector(sel, timeout=20000)
                page.wait_for_function(LOADED, arg=f'{sel} .vehicle-photo img', timeout=20000)
                self.assertTrue(page.get_attribute(f'{sel} .vehicle-photo img', 'src').startswith('/api/photo?vin='))
            # Older reminder: no image element at all, the placeholder text instead
            page.wait_for_selector(older)
            self.assertEqual(page.locator(f'{older} .vehicle-photo img').count(), 0)
            self.assertIn('No saved photo', page.inner_text(f'{older} .vehicle-photo'))
            grid = page.inner_text('#vehicle-grid')
            self.assertNotIn('Download photos', grid); self.assertNotIn('Refresh this vehicle', grid)
            self.assertNotIn('Confirm out of stock', grid)
            for sel in (review, tracked):
                buttons = [b.strip() for b in page.locator(f'{sel} .vehicle-card-actions button').all_inner_texts()]
                self.assertEqual(buttons, ['Open listing ↗', 'Delete listing'])
            self.assertEqual([b.strip() for b in page.locator(f'{older} .vehicle-card-actions button').all_inner_texts()],
                             ['Open listing ↗', "I've deleted it on Facebook"])
            for text in ('STOCK T1', '1,000 mi', '$20,000', VINS[1], 'Loaded'):
                self.assertIn(text, page.inner_text(tracked))
            # Open listing opens the tracked Facebook post (window.open is a stub here)
            page.click(f'{tracked} [data-tracked-listing-open]')
            self.assertEqual(page.evaluate('window.__opened'), [FB[1].rstrip('/')])
            self.shot(page, 'cards-01-before-confirm')

            # Delete listing (= Confirm out of stock) on the stock-verification card
            with page.expect_response(lambda r: r.url.endswith('/api/action')) as reply:
                page.click(f'{tracked} [data-tracked-confirm]')
            self.assertEqual(reply.value.status, 200)
            pending = f'.pending-removal-card[data-delete-vin="{VINS[1]}"]'
            page.wait_for_selector(pending, timeout=10000)
            page.wait_for_function(LOADED, arg=f'{pending} .vehicle-photo img', timeout=10000)
            self.assertTrue(page.get_attribute(f'{pending} .vehicle-photo img', 'src').startswith('/api/removal-photo?vin='))
            row = next(r for r in self.store.state()['removals'] if r['vin'] == VINS[1])
            self.assertEqual(row['identity']['photo']['sha256'], hashlib.sha256(cover1).hexdigest())   # the same image
            self.assertIn('Photo saved when confirmed out of stock', page.inner_text(pending))
            # Delete listing on the Refresh review card too
            with page.expect_response(lambda r: r.url.endswith('/api/action')) as reply:
                page.click(f'{review} [data-refresh-confirm]')
            self.assertEqual(reply.value.status, 200)
            pending0 = f'.pending-removal-card[data-delete-vin="{VINS[0]}"]'
            page.wait_for_function(LOADED, arg=f'{pending0} .vehicle-photo img', timeout=10000)
            self.assertIn('STOCK T0', page.inner_text(pending0))   # same stock as its active card (VIN 0 is at both dealers)
            self.shot(page, 'cards-02-after-confirm')
            browser.close()

        # Restart offline: new store, handler and photo cache from the same data folder; no network.
        H.photo_cache.close(); self.store.close()
        store = MarketplaceStore(Path(self.tmp.name) / 'data'); self.addCleanup(store.close)
        sk = socket.socket(); sk.bind(('127.0.0.1', 0)); port = sk.getsockname()[1]; sk.close()
        H2 = S.create_handler(store, port, 'tok'); H2.photo_cache.downloader = offline
        srv = ThreadingHTTPServer(('127.0.0.1', port), H2); srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), H2.photo_cache.close()))

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = self.open_delete_listing(browser, port)
            for vin in (VINS[0], VINS[1]):
                sel = f'.pending-removal-card[data-delete-vin="{vin}"] .vehicle-photo img'
                page.wait_for_selector(sel, state='attached', timeout=10000)
                page.wait_for_function(LOADED, arg=sel, timeout=10000)
            served = page.evaluate("async(u)=>{const r=await fetch(u);const b=new Uint8Array(await r.arrayBuffer());"
                                   "const h=await crypto.subtle.digest('SHA-256',b);return [...new Uint8Array(h)].map(x=>x.toString(16).padStart(2,'0')).join('')}",
                                   page.get_attribute(f'.pending-removal-card[data-delete-vin="{VINS[0]}"] .vehicle-photo img', 'src'))
            self.assertEqual(served, hashlib.sha256(cover0).hexdigest())
            self.assertEqual(page.locator(f'.pending-removal-card[data-delete-vin="{VINS[2]}"] .vehicle-photo img').count(), 0)
            self.shot(page, 'cards-03-after-offline-restart')

            # Open listing on a pending card, then "I've deleted it on Facebook" clears the card
            page.click(f'.pending-removal-card[data-delete-vin="{VINS[1]}"] [data-delete-open]')
            self.assertEqual(page.evaluate('window.__opened'), [FB[1].rstrip('/')])
            src = page.get_attribute(f'.pending-removal-card[data-delete-vin="{VINS[1]}"] .vehicle-photo img', 'src')
            with page.expect_response(lambda r: r.url.endswith('/api/action')) as reply:
                page.click(f'.pending-removal-card[data-delete-vin="{VINS[1]}"] [data-delete-confirm]')
            self.assertEqual(reply.value.status, 200)
            page.wait_for_selector(f'.pending-removal-card[data-delete-vin="{VINS[1]}"]', state='detached', timeout=10000)
            self.assertEqual(page.evaluate("async(u)=>(await fetch(u)).status", src), 404)   # stale reference refused
            self.shot(page, 'cards-04-after-facebook-confirmation')
            browser.close()


if __name__ == '__main__':
    unittest.main()
