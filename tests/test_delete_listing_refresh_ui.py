"""Exercise both listing-check controls in the real app page (headless Chromium, synthetic data only).

Skipped when Playwright/Chromium is not installed. Uses the same local reader fixtures as
test_delete_listing_refresh.py; nothing reaches a dealer site, Facebook or the Owner's data.
"""
import os, sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delete_listing_refresh import RefreshBase, VINS, LID, TOY

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as _p:
        _p.chromium.launch().close()
    HAVE_BROWSER = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_BROWSER = False

EVIDENCE = os.environ.get('LOTRADAR_UI_EVIDENCE_DIR', '')


@unittest.skipUnless(HAVE_BROWSER, 'Playwright Chromium not available')
class RefreshUi(RefreshBase):
    def shot(self, page, name):
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(EVIDENCE) / f'{name}.png'), full_page=True)

    def test_refresh_and_check_listing_links_share_one_batch_in_the_page(self):
        self.track(0); self.track(1)
        self.findings = {(VINS[0], TOY): ('INCONCLUSIVE', ['PAGE_TIMEOUT']), (VINS[1], TOY): ('MATCH', [])}
        gate = threading.Event()
        def reader():
            gate.wait(30)
            self.reader({LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown')})
        threading.Thread(target=reader, daemon=True).start()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
            page.goto(f'http://127.0.0.1:{self.port}/')
            page.click('button[data-tab="deletelisting"]')
            page.wait_for_selector('#btn-delete-refresh')
            self.assertIn('Nothing is removed or changed', page.inner_text('.delete-listing-refresh'))
            self.shot(page, '01-delete-listing-before-refresh')
            # Control 1: Refresh in Delete Listing
            page.click('#btn-delete-refresh')
            page.wait_for_function("document.querySelector('#btn-delete-refresh')?.disabled===true", timeout=10000)
            # Control 2: Check Listing Links (More scans) while the batch runs -> joins the same batch
            page.evaluate("document.getElementById('more-scans').open=true")
            page.wait_for_function("document.getElementById('btn-facebook-scan').disabled===true", timeout=10000)
            page.evaluate("checkAllFacebook()")   # the Check Listing Links handler, as if clicked in another window
            page.wait_for_function("document.getElementById('toast')?.textContent.includes('Already checking listing links')"
                                   " || document.body.innerText.includes('Already checking listing links')", timeout=10000)
            self.assertEqual(len(self.verify_calls), 1)
            self.shot(page, '02-joined-while-running')
            gate.set()
            page.wait_for_selector('.refresh-review-card', timeout=40000)
            # The shared workflow opens the existing scan console; the Owner hides it as usual.
            page.evaluate("document.getElementById('more-scans').open=false")
            if page.is_visible('#scan-console-overlay'):
                page.click('#scan-console-overlay button.close[data-dismiss="scan-console"]')
            page.wait_for_selector('#scan-console-overlay', state='hidden', timeout=5000)
            page.locator('.refresh-review-card').scroll_into_view_if_needed()
            card = page.inner_text('.refresh-review-card')
            self.assertIn(VINS[0], card)
            self.assertIn('Check failed', card); self.assertIn('Dealer page timed out', card)
            self.assertIn('Post loaded on Facebook', card)
            self.assertIn('LotRadar will not delete the Facebook post', card)
            self.assertNotIn(VINS[1], page.inner_text('.refresh-review-card'))
            self.assertIn('1 need review', page.inner_text('.delete-listing-refresh'))
            self.shot(page, '03-review-after-refresh')
            # Owner confirmation is unchanged: a confirm dialog, then a pending reminder
            page.click(f'.refresh-review-card [data-refresh-confirm="{VINS[0]}"]')
            page.wait_for_selector(f'[data-delete-confirm="{VINS[0]}"]', timeout=10000)
            self.assertTrue(dialogs and 'no longer available at the dealership' in dialogs[-1])
            self.assertEqual(page.locator('.refresh-review-card').count(), 0)
            self.assertEqual(self.store.state()['summary']['pending_fb_deletions'], 1)
            self.assertIn('0 need review', page.inner_text('.delete-listing-refresh'))
            self.shot(page, '04-after-owner-confirmation')
            browser.close()


    def test_relinked_vehicle_card_disappears_and_cannot_be_confirmed(self):
        from test_delete_listing_refresh import FB, LID
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        self.run_batch({LID[0]: ('captured', 'unknown')})
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.goto(f'http://127.0.0.1:{self.port}/')
            page.click('button[data-tab="deletelisting"]')
            page.wait_for_selector('.refresh-review-card', timeout=15000)
            self.store.db.execute("UPDATE drafts SET published_url=? WHERE vin=?", (FB[4], VINS[0]))
            page.evaluate("reload()")
            page.wait_for_selector('.refresh-review-card', state='detached', timeout=15000)
            self.assertIn('0 need review', page.inner_text('.delete-listing-refresh'))
            self.assertIn('link changed', page.inner_text('.delete-listing-refresh'))
            browser.close()
        self.assertEqual(self.store.state()['summary']['pending_fb_deletions'], 0)


if __name__ == '__main__':
    unittest.main()
