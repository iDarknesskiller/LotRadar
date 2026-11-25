"""Exercise both listing-check controls in the real app page (headless Chromium, synthetic data only).

Skipped when Playwright/Chromium is not installed. Uses the same local reader fixtures as
test_delete_listing_refresh.py; nothing reaches a dealer site, Facebook or the Owner's data.
"""
import json, os, sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delete_listing_refresh import RefreshBase, VINS, LID, TOY


def check_all_reply(origin):
    """Match ONLY the /api/facebook-auto-check-all reply to a POST sent with this origin.

    Refresh and Check Listing Links share that endpoint; matching the URL alone can pick up the other
    control's reply (Codex, 2026-11-25: Refresh's own late reply was taken for the join reply).
    """
    def match(response):
        request = response.request
        if request.method != 'POST' or not response.url.endswith('/api/facebook-auto-check-all'):
            return False
        try:
            return json.loads(request.post_data or '{}').get('origin') == origin
        except ValueError:
            return False
    return match


def gated_reader(test, outcomes):
    """Run the fixture Reader in a thread that waits for gate.set(). Always stopped before the store closes.

    The cleanup is registered after RefreshBase.setUp's, so it runs first (cleanups are LIFO): on an early
    failure it cancels the Reader, releases the gate and joins the thread before the database is closed.
    """
    gate, stop = threading.Event(), threading.Event()
    def run():
        gate.wait(30)
        if not stop.is_set():
            test.reader(outcomes)
    thread = threading.Thread(target=run, name='fixture-reader', daemon=True)
    thread.start()
    def release():
        stop.set(); gate.set(); thread.join(30)
        test.reader_teardown = {'alive': thread.is_alive(), 'store_open': _store_open(test.store)}
    test.addCleanup(release)
    return gate, thread


def _store_open(store):
    try:
        store.db.execute('SELECT 1').fetchone(); return True
    except Exception:
        return False

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
        gate, _ = gated_reader(self, {LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown')})
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
            # Control 1: Refresh in Delete Listing STARTS the batch. Wait for ITS reply (matched by origin);
            # a disabled button is not proof, the page disables both controls before the reply arrives.
            with page.expect_response(check_all_reply('delete_listing_refresh')) as first:
                page.click('#btn-delete-refresh')
            self.assertEqual(first.value.status, 200)
            started = first.value.json()
            self.assertTrue(started['ok']); self.assertFalse(started['joined'])
            self.assertTrue(started['batch_id']); self.assertEqual(started['started_by'], 'delete_listing_refresh')
            # Control 2: Check Listing Links (More scans) while the Reader is still gated JOINS that batch.
            page.evaluate("document.getElementById('more-scans').open=true")
            # Check Listing Links is disabled while the batch runs. A locator, not a string expression:
            # the page's CSP (script-src 'self') blocks the eval() a string wait uses on later polls.
            page.locator('#btn-facebook-scan:disabled').wait_for(state='attached', timeout=10000)
            # The Check Listing Links handler, as if clicked in another window; its own reply, by origin.
            with page.expect_response(check_all_reply('check_listing_links')) as second:
                page.evaluate("()=>{void checkAllFacebook();}")
            self.assertEqual(second.value.status, 200)
            joined = second.value.json()
            self.assertTrue(joined['ok']); self.assertTrue(joined['joined'])
            self.assertEqual(joined['started_by'], 'delete_listing_refresh')
            self.assertEqual(joined['batch_id'], started['batch_id'])
            self.assertEqual(len(self.verify_calls), 1)          # one dealer verification for both controls
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


class ReaderTeardown(RefreshBase):
    """Codex, 2026-11-25: a failure before gate.set() left the Reader thread using a closed database."""

    def test_reader_thread_exits_before_the_store_closes_after_an_early_failure(self):
        outer = self
        class EarlyFailure(RefreshBase):
            def runTest(inner):
                inner.track(0)
                _, outer.inner_thread = gated_reader(inner, {LID[0]: ('captured', 'unknown')})
                outer.inner = inner
                inner.fail('simulated failure before the Reader gate opens')
        result = unittest.TestResult()
        EarlyFailure().run(result)
        self.assertEqual(len(result.failures), 1, result.errors)
        self.assertIn('simulated failure', result.failures[0][1])
        self.assertEqual(result.errors, [])
        self.assertEqual(self.inner.reader_teardown, {'alive': False, 'store_open': True})   # joined first
        self.assertFalse(self.inner_thread.is_alive())
        self.assertFalse(_store_open(self.inner.store))                                     # then closed


class BrowserTestsRespectThePagePolicy(unittest.TestCase):
    """Codex, 2026-11-25 (d2c7231): a wait_for_function given a bare expression string re-polls it with eval()
    inside the page, which LotRadar's Content Security Policy (script-src 'self') blocks: an intermittent
    EvalError whenever the condition was not already true on the first check. Browser tests must wait
    with a locator, or pass a FUNCTION (compiled once by the driver, no page eval on later polls)."""

    def test_no_browser_test_waits_on_a_bare_expression_string(self):
        import re
        offenders = []
        for path in sorted(Path(__file__).resolve().parent.glob('test_*.py')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                m = re.search(r"wait_for_function\(\s*(['\"])(.*)", line)
                if m and not re.match(r"\s*(\(|async\b|function\b)", m.group(2)):
                    offenders.append(f'{path.name}:{number}: {line.strip()}')
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
