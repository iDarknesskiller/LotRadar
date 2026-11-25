"""Delete Listing vehicle cards and their saved reference photo. Synthetic VINs and photos in temp dirs only.

The pending card's photo is a reference (source, file, SHA-256) saved in the removal identity when the
Owner confirms out of stock. It is served only by /api/removal-photo, only while that VIN is pending
Facebook deletion, and only when the cached file still has the saved SHA-256. Nothing here reaches a
dealer site, Facebook or the Owner's data.
"""
import hashlib, io, json, os, socket, sys, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as S
from core import MarketplaceStore, SCHEMA
from PIL import Image

TOY, MIT = 'toyota_used', 'mitsubishi_used'
VINS = ['1HGCM82633A004352', '2HGCM82633A004353', '3HGCM82633A004354']
FB = ['https://www.facebook.com/marketplace/item/%013d/' % (1111111111111 * (i + 1)) for i in range(len(VINS))]
ROOT = Path(__file__).resolve().parents[1]


def images(src, i, n=3):
    host = 'hamptontoyota' if src == TOY else 'hamptonmitsubishi'
    return [f'https://pictures.dealer.com/h/{host}/v{i}/photo{k}.jpg' for k in range(n)]


def jpeg(color, size=(640, 480)):
    out = io.BytesIO(); Image.new('RGB', size, color).save(out, 'JPEG', quality=90); return out.getvalue()


def offline(url):
    raise OSError('offline test: no network')


class CardsBase(unittest.TestCase):
    """Real HTTP server on a temp store. VIN 0 is at both dealers; VINs 1 and 2 are Toyota only."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'data'
        self.store = MarketplaceStore(self.data)
        rows = lambda src, n: [{'vin': v, 'condition': 'used', 'year': 2022, 'make': 'Toyota', 'model': f'Model{i}',
                                'stock': f'{src[0].upper()}{i}', 'mileage': 1000 + i, 'price': 20000 + i,
                                'url': f'https://www.{"hamptontoyota" if src == TOY else "hamptonmitsubishi"}.com/used/{i}.htm',
                                'images': images(src, i)} for i, v in enumerate(VINS[:n])]
        self.store.import_feed(TOY, 'json', json.dumps(rows(TOY, 3)))
        self.store.import_feed(MIT, 'json', json.dumps(rows(MIT, 1)))
        self.start()

    def start(self):
        sk = socket.socket(); sk.bind(('127.0.0.1', 0)); self.port = sk.getsockname()[1]; sk.close()
        H = S.create_handler(self.store, self.port, 'tok')
        H.photo_cache.downloader = offline          # never reach a CDN
        srv = ThreadingHTTPServer(('127.0.0.1', self.port), H); srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.H, self.cache, self.srv = H, H.photo_cache, srv
        self._stopped = False
        self.addCleanup(self.stop)

    def stop(self):
        if self._stopped: return
        self._stopped = True
        self.srv.shutdown(); self.srv.server_close(); self.cache.close()
        try: self.store.close()
        except Exception: pass

    def restart_offline(self):
        """Close the server and store, reopen both from the same data folder. The downloader stays offline."""
        self.stop()
        self.store = MarketplaceStore(self.data)
        self.start()

    # ---- fixtures
    def track(self, i, src=TOY):
        self.store.create_draft(VINS[i], src)
        self.store.db.execute("UPDATE drafts SET status='USER_CONFIRMED_PUBLISHED',published_url=? WHERE vin=?", (FB[i], VINS[i]))

    def seed(self, i, src, colors):
        """Write cached photos the way PhotoCache stores them. colors[k] None = not downloaded."""
        vin, urls = VINS[i], images(src, i)
        d = self.cache._directory(vin, src); d.mkdir(parents=True, exist_ok=True)
        entries, blobs = {}, {}
        for k, (url, color) in enumerate(zip(urls, colors)):
            if color is None: continue
            blob = jpeg(color)
            name = f'{k + 1:02d}_{hashlib.sha256(url.encode()).hexdigest()[:24]}.jpg'
            (d / name).write_bytes(blob)
            entries[url] = {'file': name, 'size': len(blob), 'status': 'saved', 'error': '', 'width': 640, 'height': 480,
                            'visual_hash': f'v{k}{color}', 'screen_version': 61, 'category': 'vehicle',
                            'quality_reason': 'local_visual_screen_passed', 'quality_checked': True}
            blobs[k] = blob
        self.cache._save(vin, src, {'urls': urls, 'entries': entries})
        return blobs

    def cached_file(self, i, src, k):
        return self.cache._directory(VINS[i], src) / f'{k + 1:02d}_{hashlib.sha256(images(src, i)[k].encode()).hexdigest()[:24]}.jpg'

    def tree(self):
        """Every file under the photo cache with its SHA-256: originals must never change or disappear."""
        root = self.data / 'vehicle_photos'
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

    # ---- HTTP
    def post(self, body):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/action', json.dumps(body).encode(),
                                     {'Content-Type': 'application/json', 'X-SalesmanHub-Token': 'tok'})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as e: return e.code, json.load(e)

    def raw(self, path, headers=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r: return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e: return e.code, e.read(), dict(e.headers)

    def state(self):
        return json.loads(self.raw('/api/state')[1])

    def remove(self, i, **extra):
        code, body = self.post({'action': 'remove_out_of_stock', 'vin': VINS[i], 'explicit_out_of_stock_confirmation': True, **extra})
        self.assertEqual(code, 200, body)
        return body['state']

    def removal(self, i, st=None):
        return next(r for r in (st or self.state())['removals'] if r['vin'] == VINS[i])

    def removal_photo(self, i, src=None, ref=None, headers=None):
        photo = self.removal(i)['identity'].get('photo') or {}
        src = photo.get('source', '') if src is None else src
        ref = photo.get('sha256', '') if ref is None else ref
        q = urllib.parse.urlencode({'vin': VINS[i], 'source': src, 'ref': ref})
        return self.raw('/api/removal-photo?' + q, headers)


import urllib.parse  # noqa: E402  (used by removal_photo)


class SavedReference(CardsBase):
    """AC-01: the card cover is saved at Confirm out of stock and stays the same photo."""

    def test_confirm_saves_the_card_cover_and_pending_serves_the_same_bytes(self):
        self.track(1); blobs = self.seed(1, TOY, ['red', 'green', 'blue'])
        code, before, _ = self.raw(f'/api/photo?vin={VINS[1]}&source={TOY}&index=0')
        self.assertEqual((code, before), (200, blobs[0]))
        st = self.remove(1)
        photo = self.removal(1, st)['identity']['photo']
        self.assertEqual(photo, {'source': TOY, 'index': 0, 'file': self.cached_file(1, TOY, 0).name,
                                 'sha256': hashlib.sha256(blobs[0]).hexdigest()})
        code, body, headers = self.removal_photo(1)
        self.assertEqual((code, body), (200, blobs[0]))
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_identity_keeps_title_stock_price_and_mileage_for_the_card(self):
        self.track(1); self.seed(1, TOY, ['red', None, None])
        identity = self.removal(1, self.remove(1))['identity']
        self.assertEqual((identity['stock'], identity['price_cents'], identity['mileage']), ('T1', 2000100, 1001))
        self.assertTrue(identity['title'])

    def test_manual_cover_is_the_saved_photo(self):
        self.track(1); blobs = self.seed(1, TOY, ['red', 'green', 'blue'])
        self.cache.set_cover(VINS[1], TOY, images(TOY, 1)[2], images(TOY, 1))
        self.assertEqual(self.removal(1, self.remove(1))['identity']['photo']['index'], 2)
        self.assertEqual(self.removal_photo(1)[1], blobs[2])

    def test_dealer_lead_photo_is_used_when_no_manual_cover(self):
        self.store.db.execute("UPDATE sources SET record_json=json_set(record_json,'$.dealer_lead_photo',?) WHERE vin=? AND source=?",
                              (images(TOY, 1)[1], VINS[1], TOY))
        car = next(v for v in self.state()['vehicles'] if v['vin'] == VINS[1])
        self.assertEqual(car['sources'][TOY]['dealer_lead_photo'], images(TOY, 1)[1])   # fixture took effect
        self.track(1); blobs = self.seed(1, TOY, ['red', 'green', 'blue'])
        self.remove(1)
        self.assertEqual(self.removal_photo(1)[1], blobs[1])

    def test_uncached_photos_are_skipped_and_a_graphic_is_never_saved(self):
        self.track(1); blobs = self.seed(1, TOY, [None, 'green', 'blue'])
        m = self.cache._manifest(VINS[1], TOY)
        m['entries'][images(TOY, 1)[1]].update(category='graphic', quality_reason='flat_color_brand_graphic')
        self.cache._save(VINS[1], TOY, m)
        self.assertEqual(self.removal(1, self.remove(1))['identity']['photo']['index'], 2)
        self.assertEqual(self.removal_photo(1)[1], blobs[2])

    def test_two_dealer_sources_toyota_first_then_mitsubishi(self):
        self.track(0)
        mit = self.seed(0, MIT, ['purple', None, None])
        self.seed(0, TOY, [None, None, None])                     # Toyota has nothing cached
        self.remove(0)
        self.assertEqual(self.removal(0)['identity']['photo']['source'], MIT)
        self.assertEqual(self.removal_photo(0)[1], mit[0])
        self.assertEqual(self.removal_photo(0, src=TOY)[0], 404)   # the other dealer is not this reference

    def test_two_dealer_sources_prefer_toyota_like_the_inventory_card(self):
        self.track(0)
        toy = self.seed(0, TOY, ['orange', None, None]); self.seed(0, MIT, ['purple', None, None])
        self.remove(0)
        self.assertEqual(self.removal(0)['identity']['photo']['source'], TOY)
        self.assertEqual(self.removal_photo(0)[1], toy[0])

    def test_changed_cover_after_removal_keeps_the_saved_photo(self):
        self.track(1); blobs = self.seed(1, TOY, ['red', 'green', 'blue'])
        self.remove(1)
        self.cache.set_cover(VINS[1], TOY, images(TOY, 1)[2], images(TOY, 1))
        self.assertEqual(self.removal(1)['identity']['photo']['index'], 0)
        self.assertEqual(self.removal_photo(1)[1], blobs[0])

    def test_no_cached_photo_saves_no_reference_and_the_removal_still_works(self):
        self.track(1)
        st = self.remove(1)
        row = self.removal(1, st)
        self.assertEqual(row['status'], 'PENDING_FB_DELETE')
        self.assertNotIn('photo', row['identity'])
        self.assertEqual(self.removal_photo(1, src=TOY, ref='0' * 64)[0], 404)

    def test_older_pending_record_without_a_reference_still_renders_its_identity(self):
        self.track(1)
        old = {'vin': VINS[1], 'year': 2022, 'make': 'Toyota', 'model': 'Model1', 'trim': None, 'stock': 'T1',
               'stocks': {TOY: 'T1'}, 'sources': [TOY], 'price_cents': 2000100, 'title': '2022 Toyota Model1'}
        self.store.db.execute("INSERT INTO inventory_removals(vin,status,removed_at,identity_json,listing_url,listing_id) VALUES(?,?,?,?,?,?)",
                              (VINS[1], 'PENDING_FB_DELETE', S.utc(), json.dumps(old), FB[1], FB[1].rstrip('/').split('/')[-1]))
        row = self.removal(1)
        self.assertEqual(row['identity'], old)
        self.assertEqual(self.removal_photo(1, src=TOY, ref='0' * 64)[0], 404)

    def test_pending_photo_survives_an_offline_restart(self):
        self.track(1); blobs = self.seed(1, TOY, ['red', 'green', 'blue'])
        self.remove(1)
        before = self.removal(1)
        self.restart_offline()
        after = self.removal(1)
        self.assertEqual((after['identity'], after['status']), (before['identity'], 'PENDING_FB_DELETE'))
        self.assertEqual(self.removal_photo(1)[:2], (200, blobs[0]))


class MissingOrChanged(CardsBase):
    """AC-01/AC-03: a missing, corrupt or replaced file is never served; the card shows a placeholder."""

    def setUp(self):
        super().setUp()
        self.track(1); self.blobs = self.seed(1, TOY, ['red', 'green', 'blue'])
        self.remove(1)
        self.path = self.cached_file(1, TOY, 0)

    def test_missing_file(self):
        self.path.unlink()
        self.assertEqual(self.removal_photo(1)[0], 404)

    def test_corrupt_file(self):
        self.path.write_bytes(b'not an image at all')
        self.assertEqual(self.removal_photo(1)[0], 404)

    def test_replaced_by_a_different_valid_photo(self):
        self.path.write_bytes(jpeg('yellow'))   # e.g. a later full-size re-download wrote the same name
        self.assertEqual(self.removal_photo(1)[0], 404)

    def test_oversized_file(self):
        with open(self.path, 'ab') as h: h.write(b'\0' * (8 * 1024 * 1024 + 1))
        self.assertEqual(self.removal_photo(1)[0], 404)

    def test_disk_read_failure(self):
        self.path.unlink(); self.path.mkdir()    # reading a directory raises OSError
        self.assertEqual(self.removal_photo(1)[0], 404)


class Scope(CardsBase):
    """AC-03: only the current pending VIN's own saved photo, same-origin, never a path the client chooses."""

    def setUp(self):
        super().setUp()
        self.track(1); self.track(2)
        self.blobs = self.seed(1, TOY, ['red', 'green', 'blue']); self.other = self.seed(2, TOY, ['white', None, None])
        self.remove(1)
        self.ref = self.removal(1)['identity']['photo']

    def get(self, vin, src, ref, headers=None):
        return self.raw('/api/removal-photo?' + urllib.parse.urlencode({'vin': vin, 'source': src, 'ref': ref}), headers)[0]

    def test_baseline_is_served(self):
        self.assertEqual(self.get(VINS[1], TOY, self.ref['sha256']), 200)
        self.assertEqual(self.get(VINS[1].lower(), TOY, self.ref['sha256']), 200)

    def test_foreign_vin_is_refused_even_with_a_valid_reference(self):
        self.assertEqual(self.get(VINS[2], TOY, self.ref['sha256']), 404)                         # active, not pending
        self.assertEqual(self.get(VINS[2], TOY, hashlib.sha256(self.other[0]).hexdigest()), 404)
        self.assertEqual(self.get(VINS[0], TOY, self.ref['sha256']), 404)                         # never removed

    def test_foreign_or_invalid_source_and_reference(self):
        for src in (MIT, 'new_toyota', '../toyota_used', '', 'toyota_used/../../x'):
            self.assertEqual(self.get(VINS[1], src, self.ref['sha256']), 404, src)
        for ref in ('', '0' * 64, self.ref['sha256'][:16], self.ref['sha256'].upper() + 'x', '../' + self.ref['sha256']):
            self.assertEqual(self.get(VINS[1], TOY, ref), 404, ref)
        for vin in ('', 'bad', '../' + VINS[1], VINS[1] + '/..'):
            self.assertEqual(self.get(vin, TOY, self.ref['sha256']), 404, vin)

    def test_tampered_stored_reference_cannot_traverse(self):
        secret = self.data / 'secret.jpg'; secret.write_bytes(jpeg('black'))
        for name in ('../../secret.jpg', '..\\..\\secret.jpg', str(secret), '01_' + 'a' * 24 + '.jpg/../../../secret.jpg'):
            identity = dict(self.removal(1)['identity'])
            identity['photo'] = {**self.ref, 'file': name, 'sha256': hashlib.sha256(secret.read_bytes()).hexdigest()}
            self.store.db.execute('UPDATE inventory_removals SET identity_json=? WHERE vin=?', (json.dumps(identity), VINS[1]))
            self.assertEqual(self.get(VINS[1], TOY, identity['photo']['sha256']), 404, name)

    def test_tampered_reference_to_another_vehicles_file_is_refused(self):
        other = self.cached_file(2, TOY, 0)
        identity = dict(self.removal(1)['identity'])
        identity['photo'] = {**self.ref, 'file': '../../' + VINS[2] + '/' + TOY + '/' + other.name, 'sha256': hashlib.sha256(self.other[0]).hexdigest()}
        self.store.db.execute('UPDATE inventory_removals SET identity_json=? WHERE vin=?', (json.dumps(identity), VINS[1]))
        self.assertEqual(self.get(VINS[1], TOY, identity['photo']['sha256']), 404)

    def test_cross_origin_requests_are_refused(self):
        ok = self.ref['sha256']
        self.assertEqual(self.get(VINS[1], TOY, ok, {'Sec-Fetch-Site': 'cross-site'}), 403)
        self.assertEqual(self.get(VINS[1], TOY, ok, {'Sec-Fetch-Site': 'same-site'}), 403)
        self.assertEqual(self.get(VINS[1], TOY, ok, {'Sec-Fetch-Site': 'same-origin'}), 200)
        self.assertEqual(self.get(VINS[1], TOY, ok, {'Sec-Fetch-Site': 'none'}), 200)
        self.assertEqual(self.get(VINS[1], TOY, ok, {'Host': 'evil.example'}), 403)
        self.assertEqual(self.get(VINS[1], TOY, ok, {'Host': f'localhost:{self.port}'}), 403)

    def test_stale_reference_after_facebook_confirmation(self):
        code, _ = self.post({'action': 'confirm_facebook_deleted', 'vin': VINS[1], 'explicit_manual_facebook_deletion': True,
                             'expected_listing_url': FB[1]})
        self.assertEqual(code, 200)
        self.assertEqual(self.get(VINS[1], TOY, self.ref['sha256']), 404)
        self.assertTrue(self.cached_file(1, TOY, 0).is_file())       # no file deletion: retention policy owns that

    def test_stale_reference_after_restore_and_a_fresh_one_after_removing_again(self):
        self.assertEqual(self.post({'action': 'restore_removed', 'vin': VINS[1], 'explicit_confirmation': True})[0], 200)
        self.assertEqual(self.get(VINS[1], TOY, self.ref['sha256']), 404)
        self.cache.set_cover(VINS[1], TOY, images(TOY, 1)[1], images(TOY, 1))
        self.remove(1)
        fresh = self.removal(1)['identity']['photo']
        self.assertEqual(fresh['index'], 1)
        self.assertEqual(self.get(VINS[1], TOY, self.ref['sha256']), 404)    # the old reference is stale
        self.assertEqual(self.get(VINS[1], TOY, fresh['sha256']), 200)

    def test_general_photo_route_is_not_broadened_to_removed_vehicles(self):
        self.assertEqual(self.raw(f'/api/photo?vin={VINS[1]}&source={TOY}&index=0')[0], 404)
        self.assertEqual(self.raw(f'/api/photo?vin={VINS[2]}&source={TOY}&index=0')[0], 200)

    def test_only_get_is_served(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/removal-photo?vin={VINS[1]}&source={TOY}&ref={self.ref["sha256"]}',
                                     b'{}', {'Content-Type': 'application/json', 'X-SalesmanHub-Token': 'tok'})
        with self.assertRaises(urllib.error.HTTPError) as ctx: urllib.request.urlopen(req)
        self.assertNotEqual(ctx.exception.code, 200)


class DataSafety(CardsBase):
    """AC-02: removal, confirmation and restore never change original photos, saved order or drafts."""

    def test_full_cycle_leaves_photos_order_and_cover_choice_intact(self):
        self.track(1); self.seed(1, TOY, ['red', 'green', 'blue']); self.seed(2, TOY, ['white', 'gray', None])
        self.cache.set_cover(VINS[2], TOY, images(TOY, 2)[1], images(TOY, 2))
        files, prefs = self.tree(), self.cache.preferences()
        manifests = {v: self.cache._manifest(v, TOY) for v in VINS[1:]}
        draft = dict(self.store.db.execute('SELECT * FROM drafts WHERE vin=?', (VINS[1],)).fetchone())
        self.remove(1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM inventory_removals WHERE vin=?', (VINS[1],)).fetchone()[0], 1)
        self.remove(1)                                             # a second click creates no second reminder
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM inventory_removals WHERE vin=?', (VINS[1],)).fetchone()[0], 1)
        self.assertEqual(self.post({'action': 'restore_removed', 'vin': VINS[1], 'explicit_confirmation': True})[0], 200)
        self.assertEqual(dict(self.store.db.execute('SELECT * FROM drafts WHERE vin=?', (VINS[1],)).fetchone()), draft)
        self.remove(1)
        self.assertEqual(self.post({'action': 'confirm_facebook_deleted', 'vin': VINS[1], 'explicit_manual_facebook_deletion': True,
                                    'expected_listing_url': FB[1]})[0], 200)
        self.assertEqual(self.tree(), files)
        self.assertEqual(self.cache.preferences(), prefs)
        self.assertEqual({v: self.cache._manifest(v, TOY) for v in VINS[1:]}, manifests)

    def test_relinked_listing_is_still_refused_and_saves_nothing(self):
        self.track(1); self.seed(1, TOY, ['red', None, None])
        code, body = self.post({'action': 'remove_out_of_stock', 'vin': VINS[1], 'explicit_out_of_stock_confirmation': True,
                                'expected_listing_id': FB[2].rstrip('/').split('/')[-1]})
        self.assertEqual(code, 400); self.assertIn('listing_changed_since_review', body['error'])
        self.assertEqual(self.state()['removals'], [])

    def test_schema_is_unchanged(self):
        self.assertEqual(SCHEMA, 3)
        cols = [r['name'] for r in self.store.db.execute('PRAGMA table_info(inventory_removals)')]
        self.assertEqual(cols, ['vin', 'status', 'removed_at', 'identity_json', 'listing_url', 'listing_id', 'fb_confirmed_at', 'restored_at'])


class StoreReference(unittest.TestCase):
    """core.remove_out_of_stock stores only a well-formed reference; anything else is dropped, never trusted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = MarketplaceStore(Path(self.tmp.name) / 'data'); self.addCleanup(self.store.close)
        self.store.import_feed(TOY, 'json', json.dumps([{'vin': VINS[0], 'condition': 'used', 'year': 2022, 'make': 'Toyota',
            'model': 'Camry', 'stock': 'T0', 'mileage': 5, 'price': 1, 'url': 'https://www.hamptontoyota.com/used/0.htm', 'images': []}]))
        self.good = {'source': TOY, 'index': 0, 'file': '01_' + 'a' * 24 + '.jpg', 'sha256': 'b' * 64}

    def identity(self):
        return json.loads(self.store.db.execute('SELECT identity_json FROM inventory_removals WHERE vin=?', (VINS[0],)).fetchone()[0])

    def test_valid_reference_is_stored(self):
        self.store.remove_out_of_stock(VINS[0], True, photo=self.good)
        self.assertEqual(self.identity()['photo'], self.good)

    def test_invalid_references_are_dropped(self):
        bad = [None, 'x', [], {**self.good, 'source': 'new_toyota'}, {**self.good, 'file': '../01_' + 'a' * 24 + '.jpg'},
               {**self.good, 'file': '01_' + 'a' * 24 + '.exe'}, {**self.good, 'sha256': 'B' * 64}, {**self.good, 'index': -1},
               {**self.good, 'index': True}, {**self.good, 'extra': 1}, {k: v for k, v in self.good.items() if k != 'sha256'}]
        for ref in bad:
            with self.subTest(ref=ref):
                self.store.remove_out_of_stock(VINS[0], True, photo=ref)
                self.assertNotIn('photo', self.identity())
                self.store.restore_removed(VINS[0], True)


class Frontend(unittest.TestCase):
    """The three Delete Listing card types use the inventory card layout with the Owner's button changes."""
    js = (ROOT / 'app.js').read_text(encoding='utf-8')

    def cards_source(self):
        start = self.js.index('function deleteListingCard(')
        return self.js[start:self.js.index('function openFacebookForDeletion(')]

    def test_cards_have_a_photo_and_no_download_button(self):
        src = self.cards_source()
        self.assertIn('vehicle-photo', src)
        self.assertNotIn('Download photos', src); self.assertNotIn('data-photos-vin', src)
        self.assertNotIn('data-refresh-vin', src)

    def test_owner_button_labels(self):
        src = self.cards_source()
        self.assertIn('>Open listing ↗<', src)
        self.assertIn('>Delete listing<', src)
        self.assertIn("I've deleted it on Facebook", src)
        self.assertNotIn('>Confirm out of stock<', src)
        self.assertNotIn('Refresh this vehicle', src)

    def test_pending_photo_uses_the_scoped_route_and_active_cards_use_the_inventory_cover(self):
        src = self.cards_source()
        self.assertIn('/api/removal-photo?vin=', src)
        self.assertIn('photoInfo(car)', src)
        self.assertNotIn('/api/photo?vin=', src)


if __name__ == '__main__':
    unittest.main()
