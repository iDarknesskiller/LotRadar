"""Delete Listing Refresh (architect handoff, baseline main 8c72835). Synthetic data in temp dirs only.

The dealer reader and the Facebook reader are replaced by local fixtures:
- dealer: ChromeBridge.start_verify is replaced so each test decides the per-link finding of THIS run;
- Facebook: the test plays the Chrome Reader against the real FacebookAutoQueue (next/capture/finish).
Nothing reaches a dealer site, Facebook or the Owner's data.
"""
import json, socket, sqlite3, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as S
from core import MarketplaceStore

TOY, MIT = 'toyota_used', 'mitsubishi_used'
VINS = ['1HGCM82633A004352', '2HGCM82633A004353', '3HGCM82633A004354', '4T1BF1FK5CU000001', '5YJSA1E26HF000002']
FB = ['https://www.facebook.com/marketplace/item/%013d/' % (1111111111111 * (i + 1)) for i in range(len(VINS))]
LID = [u.rstrip('/').split('/')[-1] for u in FB]
ROOT = Path(__file__).resolve().parents[1]


def dealer_url(src, i):
    host = 'www.hamptontoyota.com' if src == TOY else 'www.hamptonmitsubishi.com'
    return f'https://{host}/used/{i}.htm'


class RefreshBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = MarketplaceStore(Path(self.tmp.name) / 'data'); self.addCleanup(self.store.close)
        rows = lambda src: [{'vin': v, 'condition': 'used', 'year': 2022, 'make': 'Toyota', 'model': f'Model{i}',
                             'stock': f'{src[0].upper()}{i}', 'mileage': 1000, 'price': 20000,
                             'url': dealer_url(src, i), 'images': []} for i, v in enumerate(VINS)]
        self.store.import_feed(TOY, 'json', json.dumps(rows(TOY)))
        self.store.import_feed(MIT, 'json', json.dumps(rows(MIT)[:1]))   # VIN 0 is at BOTH dealers
        sk = socket.socket(); sk.bind(('127.0.0.1', 0)); self.port = sk.getsockname()[1]; sk.close()
        H = S.create_handler(self.store, self.port, 'tok')
        srv = ThreadingHTTPServer(('127.0.0.1', self.port), H); srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), H.photo_cache.close()))
        self.H, self.cb, self.fa = H, H.chrome_bridge, H.facebook_auto
        self.findings = {}           # (vin, source) -> (status, issues); absent = not checked in this run
        self.verify_calls = []
        self.cb.connected = lambda: True
        H.headless_dealer.ensure_ready = lambda: None
        self.cb.start_verify = self.fake_start_verify
        self.fa.report_reader(enabled=True, permitted=True)

    # ---- fixtures
    def track(self, i, url=None):
        self.store.create_draft(VINS[i], TOY)
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url=? WHERE vin=?",
                              (url if url is not None else FB[i], VINS[i]))

    def fake_start_verify(self, limit, repair_missing=False, *, tracked_vins=None, **_):
        self.verify_calls.append(set(tracked_vins or ()))
        run = 'run%d' % len(self.verify_calls)
        found = []
        for (vin, src), (status, issues) in self.findings.items():
            if vin in (tracked_vins or ()):
                i = VINS.index(vin)
                found.append({'vin': vin, 'source': src, 'url': dealer_url(src, i), 'status': status, 'issues': issues,
                              'details': {}, 'checked_at': S.utc(), 'availability_verified': False})
        with self.cb.lock:
            self.cb.run_id = run
            self.cb.verify = {'running': False, 'run_id': run, 'total': len(found), 'checked': len(found),
                              'findings': found, 'skipped_due_to_limit': 0, 'unreachable': 0, 'inconclusive': 0,
                              'started_at': S.utc(), 'finished_at': S.utc()}
        return self.cb.verify_status()

    def reader(self, outcomes, timeout=20):
        """Play the Chrome Reader for the queued Facebook jobs. outcomes: listing_id -> ('captured', status) | ('failed', detail) | None (leave)."""
        deadline = time.monotonic() + timeout
        done = set()
        while time.monotonic() < deadline and len(done) < len([k for k, v in outcomes.items() if v]):
            job = self.fa.next()['job']
            if not job:
                time.sleep(0.1); continue
            lid = job['listing_id']
            outcome = outcomes.get(lid)
            if outcome is None:
                continue
            kind, value = outcome
            if kind == 'captured':
                try:
                    with self.fa.lock:
                        self.fa.require_active_capture(job['id'], lid)
                        self.store.capture_facebook_listing({'url': job['url'], 'title': '2022 Toyota Model', 'status': value,
                                                             'explicit_capture': True, 'attempt_id': job['id']})
                except ValueError as exc:   # the real Reader reports a rejected save as a failed check
                    self.fa.finish(job['id'], 'failed', str(exc)[:170], [])
                else:
                    self.fa.finish(job['id'], 'captured', 'Facebook listing captured; temporary tab closed.', ['title'])
            else:
                self.fa.finish(job['id'], 'failed', value, [])
            done.add(lid)

    # ---- HTTP
    def post(self, path, body):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', json.dumps(body).encode(),
                                     {'Content-Type': 'application/json', 'X-SalesmanHub-Token': 'tok'})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as e: return e.code, json.load(e)

    def get(self, path):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers={'X-SalesmanHub-Token': 'tok'})
        with urllib.request.urlopen(req) as r: return json.load(r)

    def refresh(self, origin='delete_listing_refresh'):
        return self.post('/api/facebook-auto-check-all', {'explicit_request': True, 'origin': origin})

    def wait_finished(self, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.get('/api/listing-refresh-status')
            if st.get('finished_at'): return st
            time.sleep(0.2)
        self.fail('refresh batch did not finish')

    def run_batch(self, outcomes, origin='delete_listing_refresh'):
        code, started = self.refresh(origin)
        self.assertEqual(code, 200, started)
        self.reader(outcomes)
        return started, self.wait_finished()

    def by_vin(self, st, group):
        return {i['vin']: i for i in st[group]}

    def snapshot(self, *tables):
        return {t: [tuple(r) for r in self.store.db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables}


class AC01Targets(RefreshBase):
    def test_only_linked_tracked_used_vehicles_and_every_skip_is_itemized(self):
        self.track(0)                                           # valid
        self.track(1, 'https://example.com/marketplace/item/1')  # invalid link
        self.track(2, FB[3]); self.track(3)                      # same post linked to two VINs
        # VIN 4 is not linked at all
        started, st = self.run_batch({LID[0]: ('captured', 'unknown')})
        self.assertEqual((started['total'], started['skipped']), (1, 3))
        self.assertEqual(self.verify_calls, [{VINS[0]}])          # dealer links only for checked targets
        reasons = {i['vin']: i['reason'] for i in st['skipped']}
        self.assertEqual(reasons, {VINS[1]: 'invalid_facebook_link', VINS[2]: 'duplicate_listing_link',
                                   VINS[3]: 'duplicate_listing_link'})
        self.assertNotIn(VINS[4], json.dumps(st))
        self.assertEqual(st['targets'], 1)

    def test_batch_above_the_facebook_limit_reports_over_limit_and_unchecked_dealer_pages(self):
        for i in range(4): self.track(i)
        original = S.FACEBOOK_BATCH_LIMIT
        S.FACEBOOK_BATCH_LIMIT = 3
        self.addCleanup(setattr, S, 'FACEBOOK_BATCH_LIMIT', original)
        self.findings = {(VINS[0], TOY): ('MATCH', []), (VINS[1], TOY): ('MATCH', [])}   # VIN 2 dealer page not reached
        started, st = self.run_batch({LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown'),
                                      LID[2]: ('captured', 'unknown')})
        self.assertEqual(started['total'], 3)
        self.assertEqual([(i['vin'], i['reason']) for i in st['skipped']], [(VINS[3], 'over_batch_limit')])
        self.assertIn(VINS[2], self.by_vin(st, 'unchecked'))
        self.assertEqual(self.by_vin(st, 'unchecked')[VINS[2]]['dealers'][0]['outcome'], 'unchecked')

    def test_relinked_listing_result_is_ignored(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        code, _ = self.refresh(); self.assertEqual(code, 200)
        # Owner relinks the post while the batch is running
        self.store.db.execute("UPDATE drafts SET published_url=? WHERE vin=?", (FB[4], VINS[0]))
        self.reader({LID[0]: ('captured', 'unknown')})
        st = self.wait_finished()
        self.assertEqual(st['review'], [])
        self.assertIn(VINS[0], self.by_vin(st, 'stale'))

    def test_nothing_linked_returns_zero_without_touching_the_reader(self):
        code, r = self.refresh()
        self.assertEqual((code, r['total']), (200, 0))
        self.assertEqual(self.verify_calls, [])


class AC02Review(RefreshBase):
    def test_active_post_with_dealer_404_or_timeout_needs_review_with_time_links_and_outcome(self):
        for i in range(3): self.track(i)
        self.findings = {(VINS[0], MIT): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE']),
                         (VINS[1], TOY): ('INCONCLUSIVE', ['PAGE_TIMEOUT']),
                         (VINS[2], TOY): ('MATCH', [])}
        _, st = self.run_batch({LID[i]: ('captured', 'unknown') for i in range(3)})
        review = self.by_vin(st, 'review')
        self.assertEqual(set(review), {VINS[0], VINS[1]})
        timeout = review[VINS[1]]['dealers'][0]
        self.assertEqual((timeout['outcome'], timeout['detail']), ('check_failed', 'Dealer page timed out'))
        self.assertTrue(timeout['checked_at'] and timeout['url'] == dealer_url(TOY, 1))
        self.assertEqual(review[VINS[1]]['facebook']['outcome'], 'active')
        self.assertTrue(review[VINS[1]]['facebook']['checked_at'])
        self.assertEqual(review[VINS[1]]['facebook_url'], 'https://www.facebook.com/marketplace/item/' + LID[1])
        self.assertIn(VINS[2], self.by_vin(st, 'no_action'))

    def test_multiple_dealers_show_every_result_including_the_one_that_still_loads(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('INCONCLUSIVE', ['PAGE_TIMEOUT']), (VINS[0], MIT): ('MATCH', [])}
        _, st = self.run_batch({LID[0]: ('captured', 'unknown')})
        dealers = {d['source']: d['outcome'] for d in self.by_vin(st, 'review')[VINS[0]]['dealers']}
        self.assertEqual(dealers, {TOY: 'check_failed', MIT: 'loads'})

    def test_facebook_sign_in_or_reader_failure_is_reported_inconclusive_not_review(self):
        for i in range(3): self.track(i)
        self.findings = {(VINS[i], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE']) for i in range(3)}
        _, st = self.run_batch({LID[0]: ('failed', 'Facebook login required. Sign in normally in Chrome, then retry.'),
                                LID[1]: ('failed', 'facebook_listing_unavailable'),
                                LID[2]: ('captured', 'sold')})
        self.assertEqual(st['review'], [])
        inconclusive = self.by_vin(st, 'facebook_inconclusive')
        self.assertEqual(set(inconclusive), {VINS[0]})
        self.assertIn('login required', inconclusive[VINS[0]]['facebook']['detail'])
        no_action = self.by_vin(st, 'no_action')
        self.assertEqual(no_action[VINS[1]]['facebook']['outcome'], 'unavailable')
        self.assertEqual(no_action[VINS[2]]['facebook']['outcome'], 'marked_sold')

    def test_fresh_failure_after_a_historical_unavailable_result_is_this_batch_evidence(self):
        self.track(0); self.track(1)
        # Historical rows: both dealer pages were once "unavailable".
        self.store.record_link_check(TOY, dealer_url(TOY, 0), 'unavailable')
        self.store.record_link_check(TOY, dealer_url(TOY, 1), 'unavailable')
        # This batch: VIN 0 times out (stored row keeps the old 'unavailable'); VIN 1 loads now.
        self.findings = {(VINS[0], TOY): ('INCONCLUSIVE', ['PAGE_TIMEOUT']), (VINS[1], TOY): ('MATCH', [])}
        self.store.record_link_check(TOY, dealer_url(TOY, 0), 'check_failed')
        _, st = self.run_batch({LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown')})
        review = self.by_vin(st, 'review')
        self.assertEqual(set(review), {VINS[0]})
        self.assertEqual(review[VINS[0]]['dealers'][0]['outcome'], 'check_failed')   # not the historical 'unavailable'
        self.assertIn(VINS[1], self.by_vin(st, 'no_action'))
        # The historical projection is unchanged and still distinguishable.
        self.assertEqual(self.store.cleanup_status()[VINS[0]]['dealer'][0]['outcome'], 'unavailable')


class AC03Admission(RefreshBase):
    def test_repeated_clicks_on_both_controls_admit_one_batch(self):
        self.track(0); self.track(1)
        c1, first = self.refresh('delete_listing_refresh')
        c2, second = self.refresh('check_listing_links')
        c3, third = self.refresh('delete_listing_refresh')
        self.assertEqual((c1, c2, c3), (200, 200, 200))
        self.assertFalse(first['joined']); self.assertTrue(second['joined']); self.assertTrue(third['joined'])
        self.assertEqual({first['batch_id'], second['batch_id'], third['batch_id']}, {first['batch_id']})
        self.assertEqual(second['started_by'], 'delete_listing_refresh')
        self.assertEqual(len(self.verify_calls), 1)
        self.reader({LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown')})
        st = self.wait_finished()
        self.assertEqual((st['batch_id'], st['targets']), (first['batch_id'], 2))
        self.assertEqual(self.fa.bulk_status()['total'], 2)

    def test_concurrent_clicks_admit_exactly_one_batch(self):
        self.track(0)
        results = []
        threads = [threading.Thread(target=lambda o=o: results.append(self.refresh(o)))
                   for o in ('delete_listing_refresh', 'check_listing_links') * 3]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertTrue(all(code == 200 for code, _ in results), results)
        self.assertEqual(len({r['batch_id'] for _, r in results}), 1)
        self.assertEqual(sum(not r['joined'] for _, r in results), 1)
        self.assertEqual(len(self.verify_calls), 1)
        self.reader({LID[0]: ('captured', 'unknown')}); self.wait_finished()

    def test_competing_quick_scan_is_named_and_nothing_starts(self):
        self.track(0)
        with self.cb.lock:
            self.cb.scan_info['running'] = True; self.cb.quick_scan = True
        code, r = self.refresh()
        self.assertEqual(code, 400)
        self.assertIn('Quick Scan is running', r['error'])
        self.assertEqual(self.verify_calls, [])
        self.assertEqual(self.get('/api/listing-refresh-status')['batch_id'], None)

    def test_reader_disconnected_then_retry_after_reconnect(self):
        self.track(0)
        self.cb.connected = lambda: False
        code, r = self.refresh()
        self.assertEqual(code, 400); self.assertIn('Connect LotRadar Browser Reader', r['error'])
        self.assertEqual(self.verify_calls, [])
        self.cb.connected = lambda: True
        _, st = self.run_batch({LID[0]: ('captured', 'unknown')})
        self.assertEqual(st['targets'], 1)

    def test_cancel_stops_the_batch_and_reports_unchecked_facebook(self):
        self.track(0); self.track(1)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        code, _ = self.refresh(); self.assertEqual(code, 200)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not self.fa.bulk_status()['active']: time.sleep(0.1)
        code, _ = self.post('/api/chrome-scan-control', {'action': 'stop'})
        self.assertEqual(code, 200)
        st = self.wait_finished()
        self.assertFalse(st['running'])
        self.assertEqual(st['review'], [])
        self.assertEqual({i['facebook']['detail'] for i in st['facebook_inconclusive']}, {'Facebook check cancelled'})
        self.assertEqual(set(self.by_vin(st, 'facebook_inconclusive')), {VINS[0], VINS[1]})
        # A later Refresh is a new batch (cancel does not wedge admission)
        _, st2 = self.run_batch({LID[0]: ('captured', 'unknown'), LID[1]: ('captured', 'unknown')})
        self.assertNotEqual(st2['batch_id'], st['batch_id'])
        self.assertIn(VINS[0], self.by_vin(st2, 'review'))

    def test_invalid_origin_and_missing_explicit_flag_are_rejected(self):
        self.track(0)
        self.assertEqual(self.post('/api/facebook-auto-check-all', {'explicit_request': True, 'origin': 'cron'})[0], 400)
        self.assertEqual(self.post('/api/facebook-auto-check-all', {'origin': 'delete_listing_refresh'})[0], 400)
        self.assertEqual(self.verify_calls, [])


class AC04Preservation(RefreshBase):
    TABLES = ('sources', 'drafts', 'inventory_removals')

    def test_refresh_never_changes_inventory_drafts_or_reminders(self):
        for i in range(4): self.track(i)
        self.store.remove_out_of_stock(VINS[3], True)                    # existing pending deletion reminder
        before = self.snapshot(*self.TABLES)
        self.findings = {(VINS[i], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE']) for i in range(3)}
        _, st = self.run_batch({LID[i]: ('captured', 'unknown') for i in range(3)})
        self.assertEqual(set(self.by_vin(st, 'review')), {VINS[0], VINS[1], VINS[2]})
        self.assertEqual(self.snapshot(*self.TABLES), before)
        self.assertNotIn(VINS[3], json.dumps(st['review']))                  # removed VIN is not a target
        self.assertEqual(self.store.state()['summary']['pending_fb_deletions'], 1)

    def test_manual_confirmation_still_required_and_moves_item_to_already_pending(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        _, st = self.run_batch({LID[0]: ('captured', 'unknown')})
        self.assertIn(VINS[0], self.by_vin(st, 'review'))
        self.assertEqual(self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[0]})[0], 400)
        self.assertIn(VINS[0], {v['vin'] for v in self.store.state()['vehicles']})
        code, r = self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[0],
                                            'explicit_out_of_stock_confirmation': True})
        self.assertEqual((code, r['state']['summary']['pending_fb_deletions']), (200, 1))
        # The next Refresh does not re-target it; the frozen previous batch keeps its own evidence.
        code, r = self.refresh(); self.assertEqual((code, r['total']), (200, 0))

    def test_stale_listing_confirmation_is_still_rejected_after_refresh(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        self.run_batch({LID[0]: ('captured', 'unknown')})
        self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[0], 'explicit_out_of_stock_confirmation': True})
        code, _ = self.post('/api/action', {'action': 'confirm_facebook_deleted', 'vin': VINS[0],
                                            'explicit_manual_facebook_deletion': True, 'expected_listing_url': FB[1]})
        self.assertEqual(code, 400)
        self.assertEqual(self.store.state()['summary']['pending_fb_deletions'], 1)

    def test_refresh_code_path_has_no_mutating_store_call(self):
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        block = src[src.index('    LISTING_CHECK_ORIGINS='):src.index('    def listing_refresh_status():')]
        for verb in ('remove_out_of_stock', 'trash_listing', 'confirm_facebook_deleted', 'complete_facebook_cleanup',
                     'record_link_check', 'archive', '.delete(', 'DELETE ', 'unlink(', 'rmtree', 'execute(',
                     'cancel_bulk', 'enqueue('):
            self.assertNotIn(verb, block, verb)


class AC05Frontend(unittest.TestCase):
    js = (ROOT / 'app.js').read_text(encoding='utf-8')
    html = (ROOT / 'index.html').read_text(encoding='utf-8')

    def test_both_controls_use_the_same_workflow(self):
        self.assertIn("$('btn-facebook-scan').addEventListener('click',checkAllFacebook)", self.js)
        self.assertIn("void checkAllFacebook('delete_listing_refresh')", self.js)
        self.assertEqual(self.js.count("api('/api/facebook-auto-check-all'"), 1)
        self.assertIn('if(result.joined)', self.js)
        self.assertIn("refreshButton.disabled=Boolean(f.running)", self.js)

    def test_review_section_reuses_owner_confirmation_and_never_deletes(self):
        card = self.js[self.js.index('function refreshReviewCard'):self.js.index('function refreshBarHtml')]
        self.assertIn('data-refresh-confirm=', card)
        confirm = self.js[self.js.index('function confirmRefreshReview'):self.js.index('function confirmFacebookDeleted')]
        self.assertIn('expected_listing_id:item.listing_id', confirm)      # reviewed identity sent to the server
        self.assertIn('refreshItemCurrent(item)', confirm)
        self.assertIn('window.confirm(', confirm)
        self.assertIn('LotRadar will not delete the Facebook post', card)
        for verb in ('remove_out_of_stock', 'trash', 'confirm_facebook_deleted', "api('"):
            self.assertNotIn(verb, card)
        self.assertIn('reviewVins.has(r.vin)', self.js)              # not shown twice
        self.assertIn('!isPendingCleanupVin(i.vin)&&refreshItemCurrent(i)', self.js)   # pending wins; stale hidden
        self.assertIn('Show what was not fully checked', self.js)

    def test_assets_cache_busted(self):
        self.assertIn('app.js?v=delete-listing-refresh-2', self.html)


class HoldFindings(RefreshBase):
    """Codex HOLD on bc9f5b3 (2026-11-24): stale review after a later relink; coverage gaps."""

    def test_relink_after_refresh_finished_invalidates_the_review_card(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        _, st = self.run_batch({LID[0]: ('captured', 'unknown')})
        self.assertIn(VINS[0], self.by_vin(st, 'review'))
        # Owner relinks the vehicle to a different post AFTER the batch finished.
        self.store.db.execute("UPDATE drafts SET published_url=? WHERE vin=?", (FB[4], VINS[0]))
        st = self.get('/api/listing-refresh-status')
        self.assertEqual(st['review'], [])
        self.assertIn(VINS[0], self.by_vin(st, 'stale'))
        self.assertEqual(st['counts']['review'], 0)

    def test_confirmation_from_a_review_card_must_match_the_reviewed_listing(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        self.run_batch({LID[0]: ('captured', 'unknown')})
        self.store.db.execute("UPDATE drafts SET published_url=? WHERE vin=?", (FB[4], VINS[0]))
        code, r = self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[0],
                                            'explicit_out_of_stock_confirmation': True, 'expected_listing_id': LID[0]})
        self.assertEqual(code, 400)
        self.assertIn('listing_changed_since_review', r['error'])
        self.assertIsNone(self.store.db.execute('SELECT * FROM inventory_removals WHERE vin=?', (VINS[0],)).fetchone())
        code, r = self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[0],
                                            'explicit_out_of_stock_confirmation': True, 'expected_listing_id': LID[4]})
        self.assertEqual((code, r['state']['summary']['pending_fb_deletions']), (200, 1))
        row = self.store.db.execute('SELECT listing_id FROM inventory_removals WHERE vin=?', (VINS[0],)).fetchone()
        self.assertEqual(row['listing_id'], LID[4])

    def test_expected_listing_id_is_validated_and_optional_for_existing_callers(self):
        self.track(0); self.track(1)
        for bad in ('', 'abc', '123', None):
            if bad is None: continue
            code, _ = self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[0],
                                                'explicit_out_of_stock_confirmation': True, 'expected_listing_id': bad})
            self.assertEqual(code, 400, bad)
        # Out of Stock / Needs-verification callers send no expected id: unchanged behaviour.
        code, _ = self.post('/api/action', {'action': 'remove_out_of_stock', 'vin': VINS[1],
                                            'explicit_out_of_stock_confirmation': True})
        self.assertEqual(code, 200)

    def test_listings_over_the_limit_are_checked_first_on_the_next_refresh(self):
        for i in range(4): self.track(i)
        original = S.FACEBOOK_BATCH_LIMIT
        S.FACEBOOK_BATCH_LIMIT = 2
        self.addCleanup(setattr, S, 'FACEBOOK_BATCH_LIMIT', original)
        all_ids = {LID[i]: ('captured', 'unknown') for i in range(4)}
        _, first = self.run_batch(all_ids)
        over_first = {i['vin'] for i in first['skipped'] if i['reason'] == 'over_batch_limit'}
        self.assertEqual(len(over_first), 2)
        for vin, lid in zip(VINS, LID):   # what the real finish endpoint records for each captured check
            if vin not in over_first: self.store.record_link_check('facebook', 'https://www.facebook.com/marketplace/item/' + lid, 'reachable')
        _, second = self.run_batch(all_ids)
        checked_second = {i['vin'] for g in ('review', 'facebook_inconclusive', 'unchecked', 'stale', 'already_pending', 'no_action')
                          for i in second[g]}
        self.assertEqual(checked_second, over_first)

    def test_partially_checked_vehicle_stays_in_the_incomplete_coverage_summary(self):
        self.track(0)   # VIN 0 is at Toyota AND Mitsubishi
        self.findings = {(VINS[0], TOY): ('MATCH', [])}   # Mitsubishi page not reached in this batch
        _, st = self.run_batch({LID[0]: ('captured', 'unknown')})
        self.assertEqual(st['review'], [])
        unchecked = self.by_vin(st, 'unchecked')
        self.assertIn(VINS[0], unchecked)
        self.assertEqual({d['source']: d['outcome'] for d in unchecked[VINS[0]]['dealers']},
                         {TOY: 'loads', MIT: 'unchecked'})
        self.assertEqual(st['counts']['unchecked'], 1)

if __name__ == '__main__':
    unittest.main()
