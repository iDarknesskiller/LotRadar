"""SalesmanHub Marketplace Manager: isolated, offline-first store.

No Facebook API, browser automation, contact scraping, XP or shared-core writes.
Imports may be explicit public-site scans or approved exports. SQLite transactions + backups.
"""
from __future__ import annotations
from urllib.parse import urlsplit
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SOURCES = ('toyota_new', 'toyota_used', 'mitsubishi_new', 'mitsubishi_used')
VEHICLE_SPEC_FIELDS = ('exterior_color','interior_color','engine','transmission','drivetrain','fuel_type','body_style',
                       'exterior_color_generic','interior_color_generic')
DEALERS = {'toyota': 'Hampton Toyota', 'mitsubishi': 'Hampton Mitsubishi'}
VIN_RE = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')
FB_URL_RE = re.compile(r'^https://(?:www\.|m\.)?facebook\.com/marketplace/item/[0-9]+/?(?:\?.*)?$', re.I)
MAX_FEED_CHARS = 12_000_000
# Facebook is NOT an inventory authority. Never read, import, compare or store FB VINs.
FACEBOOK_ID_RE = re.compile(r'^[0-9]{8,24}$')
def facebook_listing_id(value):
    try:
        parsed=urlparse(str(value or '').strip())
        if parsed.scheme!='https' or parsed.hostname not in ('www.facebook.com','facebook.com','m.facebook.com') or parsed.port not in (None,443) or parsed.username or parsed.password:
            return ''
        path=parsed.path.rstrip('/')
        if re.fullmatch(r'/marketplace/item/[0-9]{8,24}',path):
            return path.split('/')[-1]
        if path=='/marketplace/edit':
            item=parse_qs(parsed.query).get('listing_id',[''])[0]
            return item if FACEBOOK_ID_RE.fullmatch(item) else ''
    except (ValueError,TypeError):pass
    return ''

def facebook_field_text(value,length):
    if not isinstance(value,str):return ''
    # Reject markup, control characters and very long text; no HTML or PII scraping.
    value=re.sub(r'[\x00-\x08\x0b-\x1f\x7f]','',value).strip()
    return value[:length]

def dealer_vehicle_title(record):
    """Normalize repeating dealer model/trim display, never modify imported source."""
    model=str(record.get('model') or '').strip()
    trim=str(record.get('trim') or '').strip()
    if trim:
        tail=' '+trim
        while model.casefold().endswith((tail+tail).casefold()):
            model=model[:-len(tail)].rstrip()
    if trim and not model.casefold().endswith(trim.casefold()):
        model=(model+' '+trim).strip()
    return ' '.join(str(record[k]).strip() for k in ('year','make') if record.get(k))+' '+model

SCHEMA = 3
MAX_FRESHNESS_HOURS = 72
COVERAGE_MIN_BASELINE = 10
COVERAGE_FLOOR = 0.50


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def compact_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(compact_json(value).encode('utf8')).hexdigest()


def valid_url(raw, *, image=False):
    if not isinstance(raw, str) or len(raw) > 2048:
        return ''
    raw = raw.strip()
    try:
        p = urlparse(raw)
        if p.scheme != 'https' or not p.hostname or p.username or p.password:
            return ''
        if p.port not in (None, 443):
            return ''
        # Never treat Javascript, data URIs or localhost resources as dealership links.
        if p.hostname.lower() in ('localhost', '127.0.0.1', '0.0.0.0'):
            return ''
        return raw
    except (ValueError, TypeError):
        return ''


def parse_price(value):
    if value is None or str(value).strip() == '':
        return None
    if isinstance(value, bool):
        raise ValueError('invalid_price')
    raw = str(value).strip().replace('$', '').replace(',', '')
    try:
        amount = Decimal(raw)
        if not amount.is_finite() or amount <= 0 or amount > 5_000_000:
            raise ValueError('invalid_price')
        return int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation as ex:
        raise ValueError('invalid_price') from ex


def is_true(value):
    return value is True or str(value).lower().strip() in ('true', '1', 'yes', 'y', 'approved')


def field(row, *keys):
    keys_by_lower = {str(k).strip().lower().replace(' ', '_'): k for k in row}
    for name in keys:
        key = keys_by_lower.get(name)
        if key is not None and row[key] is not None:
            return row[key]
    return None


def normalize(source, row):
    if not isinstance(row, dict):
        raise ValueError('row_not_object')
    vin = str(field(row, 'vin', 'vehicle_vin') or '').strip().upper()
    if not VIN_RE.fullmatch(vin):
        raise ValueError('missing_or_invalid_vin')
    year_raw = field(row, 'year', 'model_year')
    try:
        year = int(str(year_raw).strip())
        if year < 1980 or year > datetime.now().year + 3:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('invalid_year') from None
    make = str(field(row, 'make', 'manufacturer') or '').strip()
    model = str(field(row, 'model', 'vehicle_model') or '').strip()
    if not (1 <= len(make) <= 60 and 1 <= len(model) <= 80):
        raise ValueError('missing_make_or_model')
    condition = 'new' if source.endswith('_new') else 'used'
    supplied_condition = field(row, 'condition', 'new_used')
    if supplied_condition is not None and str(supplied_condition).strip():
        value = str(supplied_condition).strip().lower()
        if value not in {'n', 'new', 'u', 'used', 'preowned', 'pre-owned'}:
            raise ValueError('unrecognized_condition')
        if (value in {'n', 'new'}) != (condition == 'new'):
            raise ValueError('condition_source_mismatch')
    mileage_val = field(row, 'mileage', 'odometer', 'miles')
    mileage = None
    if mileage_val is not None and str(mileage_val).strip() != '':
        try:
            mileage = int(str(mileage_val).replace(',', '').strip())
            if not 0 <= mileage <= 2_000_000:
                raise ValueError()
        except ValueError:
            raise ValueError('invalid_mileage') from None
    images_raw = field(row, 'images', 'image_urls', 'photos', 'image') or []
    if isinstance(images_raw, str):
        # CSV exports commonly use | or ; for multiple approved image URLs.
        images = [x.strip() for x in re.split(r'[|;\n]', images_raw) if x.strip()]
    elif isinstance(images_raw, list):
        images = images_raw
    else:
        raise ValueError('invalid_images')
    if len(images) > 250:
        raise ValueError('too_many_images')
    if any(not valid_url(x, image=True) for x in images):
        raise ValueError('invalid_image_url')
    raw_features = row.get('features') or []
    if isinstance(raw_features,str):
        # Preserve legacy CSV imports that already have a features column.
        raw_features = re.split(r'[|;\n]',raw_features)
    if not isinstance(raw_features,list):
        raise ValueError('invalid_features')
    features=[]
    for value in raw_features[:240]:
        if not isinstance(value,str):continue
        item=' '.join(value.split()).strip()[:110]
        if 3<=len(item)<=110 and not any(x in item.lower() for x in ('http://','https://','@','ignore previous')) and item not in features:
            features.append(item)
    raw_specs=row.get('specifications')
    specs={key:' '.join(value.split()) for key,value in (raw_specs.items() if isinstance(raw_specs,dict) else ())
           if key in VEHICLE_SPEC_FIELDS and isinstance(value,str) and 0<len(value.strip())<=100}
    image_approved = source in ('toyota_used','mitsubishi_used') or is_true(field(row, 'images_approved', 'image_approved', 'photo_permission'))
    state = str(field(row, 'availability', 'status', 'inventory_status') or 'available').strip().lower()
    if state not in ('available', 'in_stock', 'active', 'pending', 'unavailable', 'sold'):
        raise ValueError('unknown_availability')
    # "sold" here is only a statement in an approved feed; it never updates FB.
    availability = 'available' if state in ('available', 'in_stock', 'active') else state
    return {
        'vin': vin, 'source': source, 'condition': condition, 'year': year,
        'make': make[:60], 'model': model[:80],
        'trim': str(field(row, 'trim', 'series') or '').strip()[:80],
        'stock': str(field(row, 'stock', 'stock_number', 'stock_no') or '').strip()[:60],
        'mileage': mileage, 'price_cents': parse_price(field(row, 'price', 'sale_price', 'internet_price')),
        'url': valid_url(str(field(row, 'url', 'vehicle_url', 'vdp_url') or '')),
        'images': images, 'images_approved': image_approved,
        'dealer_lead_photo': row.get('dealer_lead_photo') if row.get('dealer_lead_photo') in images else '',
        'photo_gallery_expected': row.get('photo_gallery_expected')
            if type(row.get('photo_gallery_expected')) is int and 1 <= row['photo_gallery_expected'] <= 999 else None,
        'availability': availability,
        'cash_only': row.get('cash_only') is True,
        # One-owner is a *dealer badge claim*, never an inferred clean report.
        'carfax_one_owner': is_true(field(row, 'carfax_one_owner', 'carfax_1_owner')),
        'features': features,
        'specifications': specs,
        'disclaimer': str(field(row, 'disclaimer', 'price_disclaimer') or '').strip()[:800],
        'demo_only': False,
    }


def decode_feed(text, fmt, source):
    if not isinstance(text, str) or not (0 < len(text) <= MAX_FEED_CHARS):
        raise ValueError('empty_or_excessive_feed')
    if fmt == 'json':
        root = json.loads(text)
        if isinstance(root, list):
            rows = root
        elif isinstance(root, dict):
            if root.get('source') and root['source'] != source:
                raise ValueError('source_mismatch')
            rows = root.get('vehicles')
        else:
            raise ValueError('json_root_not_array_or_object')
        if not isinstance(rows, list):
            raise ValueError('vehicles_must_be_array')
    elif fmt == 'csv':
        rows = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    else:
        raise ValueError('format_must_be_csv_or_json')
    if len(rows) > 25000:
        raise ValueError('feed_row_limit_exceeded')
    return rows


def source_fingerprint(rec):
    # Publication-relevant values only. Do not include last_seen/sync bookkeeping.
    # Disclosure, chosen dealer and vehicle detail link are mandatory review inputs.
    keys = ('vin', 'source', 'condition', 'year', 'make', 'model', 'trim',
            'stock', 'price_cents', 'mileage', 'url', 'images',
            'images_approved', 'availability', 'disclaimer', 'demo_only')
    payload = {k: rec.get(k) for k in keys}
    # Historical drafts without equipment evidence keep their old hash.
    if rec.get('cash_only'): payload['cash_only'] = True
    if rec.get('features'):
        payload['features'] = rec['features']
    if rec.get('carfax_one_owner') is True:
        payload['carfax_one_owner'] = True
    return fingerprint(payload)


def record_is_fresh(timestamp, *, now=None, max_hours=MAX_FRESHNESS_HOURS):
    try:
        seen = datetime.fromisoformat(timestamp)
        if seen.tzinfo is None:
            return False
        now = now or datetime.now(timezone.utc)
        age = (now - seen.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= max_hours * 3600
    except (TypeError, ValueError, OverflowError):
        return False


def build_listing_copy(record, source):
    """User-approved Hampton Facebook format, strictly from recorded equipment."""
    from dealer_features import render_post, verified_title
    title = verified_title(record)
    description = render_post(record, source, DEALERS[source.split('_')[0]])
    return title, description

class MarketplaceStore:
    """One writer per instance, single SQLite transaction per mutation."""
    facebook_form_from_saved_draft = True

    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'marketplace.sqlite3'
        self.backup_dir = self.root / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._backed_up_scan = None
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=10000')
        # Preserve pre-R19 manually edited and approved drafts before enabling auto-refresh.
        had_copy_locks = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='draft_copy_locks'").fetchone() is not None
        if not had_copy_locks and self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone():
            self.backup()
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sources(
                source TEXT NOT NULL, vin TEXT NOT NULL, record_json TEXT NOT NULL,
                seen_at TEXT NOT NULL, missing_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(source,vin));
            CREATE INDEX IF NOT EXISTS ix_sources_vin ON sources(vin);
            CREATE TABLE IF NOT EXISTS vehicle_first_seen(
                vin TEXT PRIMARY KEY, first_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS listing_link_checks(
                source TEXT NOT NULL, link TEXT NOT NULL,
                outcome TEXT NOT NULL, checked_at TEXT NOT NULL,
                PRIMARY KEY(source,link));
            CREATE TABLE IF NOT EXISTS feeds(
                source TEXT PRIMARY KEY, last_import TEXT, rows_seen INTEGER DEFAULT 0,
                last_accepted INTEGER DEFAULT 0, last_complete INTEGER DEFAULT 0,
                last_error TEXT, last_run TEXT);
            CREATE TABLE IF NOT EXISTS quarantined(
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, source TEXT NOT NULL,
                row_index INTEGER NOT NULL, reason TEXT NOT NULL, row_json TEXT NOT NULL,
                at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts(
                vin TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT NOT NULL, price_cents INTEGER NOT NULL,
                status TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
                conflict_ack INTEGER NOT NULL DEFAULT 0, published_url TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS draft_copy_locks(
                vin TEXT PRIMARY KEY, saved_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facebook_listing_captures(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT NOT NULL, vin TEXT NOT NULL,
                captured_at TEXT NOT NULL, snapshot_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_fb_captures_listing
                ON facebook_listing_captures(listing_id,id);
            CREATE TABLE IF NOT EXISTS listing_trash(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vin TEXT NOT NULL, draft_json TEXT NOT NULL,
                copy_saved_at TEXT, deleted_at TEXT NOT NULL,
                expires_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_listing_trash_expiry
                ON listing_trash(expires_at);
            CREATE TABLE IF NOT EXISTS inventory_removals(
                vin TEXT PRIMARY KEY, status TEXT NOT NULL,
                removed_at TEXT NOT NULL, identity_json TEXT NOT NULL,
                listing_url TEXT NOT NULL DEFAULT '', listing_id TEXT NOT NULL DEFAULT '',
                fb_confirmed_at TEXT, restored_at TEXT);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY, event TEXT NOT NULL, vin TEXT,
                details_json TEXT NOT NULL, at TEXT NOT NULL);
        ''')
        self.db.execute('''INSERT OR IGNORE INTO vehicle_first_seen(vin,first_seen)
                           SELECT vin,MIN(seen_at) FROM sources GROUP BY vin''')
        if not had_copy_locks:
            # Existing drafts may have been manually edited in R18. Protect them
            # rather than silently replacing work on the first R19 inventory scan.
            self.db.execute('INSERT OR IGNORE INTO draft_copy_locks(vin,saved_at) SELECT vin,updated_at FROM drafts')
        current = self.db.execute('PRAGMA user_version').fetchone()[0]
        if current > SCHEMA:
            raise RuntimeError('Database created by a newer Marketplace Manager')
        if current < 3:
            columns = {r['name'] for r in self.db.execute('PRAGMA table_info(drafts)')}
            if 'review_state' not in columns:
                self.db.execute("ALTER TABLE drafts ADD COLUMN review_state TEXT NOT NULL DEFAULT ''")
        self.db.execute(f'PRAGMA user_version={SCHEMA}')

    def close(self):
        with self.lock:
            self.db.close()

    def backup(self):
        with self.lock:
            name = f'backup-{time.time_ns()}-{uuid.uuid4().hex[:8]}.sqlite3'
            dest = self.backup_dir / name
            temp = self.backup_dir / (name + '.tmp')
            conn = sqlite3.connect(temp)
            try:
                self.db.backup(conn)
            finally:
                conn.close()
            os.replace(temp, dest)
            backups = sorted(self.backup_dir.glob('backup-*.sqlite3'), key=lambda p: p.stat().st_mtime_ns)
            for old in backups[:-8]:
                old.unlink(missing_ok=True)
            return dest.name

    def _event(self, action, vin=None, **details):
        self.db.execute('INSERT INTO audit(event,vin,details_json,at) VALUES(?,?,?,?)',
                        (action, vin, compact_json(details), utc()))

    def fill_missing_dealer_fields(self, vin, source, live, features=None):
        """Fill absent trusted dealer fields from an exact-VIN browser snapshot.

        This never overwrites a nonempty stored field or promotes availability.
        """
        if source not in ('toyota_used','mitsubishi_used') or not VIN_RE.fullmatch(vin):
            raise ValueError('invalid_used_dealer_record')
        if str(live.get('vin') or '').upper()!=vin:
            raise ValueError('live_vin_mismatch')
        with self.lock:
            row=self.db.execute('SELECT record_json FROM sources WHERE source=? AND vin=?',(source,vin)).fetchone()
            if not row:raise ValueError('unknown_used_dealer_record')
            rec=json.loads(row['record_json'])
            # Require identity agreement. A VIN match alone must not let a
            # wrongly interpreted page replace dealership attributes.
            if (str(live.get('year'))!=str(rec.get('year')) or
                str(live.get('make') or '').casefold()!=str(rec.get('make') or '').casefold() or
                str(live.get('model') or '').casefold()!=str(rec.get('model') or '').casefold()):
                raise ValueError('live_vehicle_identity_conflict')
            change={}
            for key,live_key in (('stock','stock'),('mileage','mileage'),('price_cents','price'),('trim','trim')):
                if rec.get(key) not in ('',None,0) or live.get(live_key) in (None,'',0):continue
                value=live[live_key]
                if key=='price_cents':
                    try:value=round(float(value)*100)
                    except (TypeError,ValueError):continue
                if key=='mileage':
                    try:value=int(value)
                    except (TypeError,ValueError):continue
                if key=='stock' and (not isinstance(value,str) or len(value)>42 or not re.search(r'\d',value)):continue
                if key=='trim' and (not isinstance(value,str) or len(value)>110):continue
                rec[key]=value;change[key]=value
            if not rec.get('images') and isinstance(live.get('images'),list):
                from urllib.parse import urlsplit
                pictures=[]
                for url in live['images'][:250]:
                    if isinstance(url,str) and len(url)<1000 and urlsplit(url).scheme=='https':pictures.append(url)
                if pictures:rec['images']=pictures;change['images']=len(pictures)
            if not rec.get('features') and isinstance(features,list):
                verified=[]
                for value in features[:220]:
                    if isinstance(value,str) and 3<=len(value)<=110 and value not in verified:
                        verified.append(value)
                if verified:rec['features']=verified;change['features']=len(verified)
            if change:
                self.backup()
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    self.db.execute('UPDATE sources SET record_json=? WHERE source=? AND vin=?',
                                    (compact_json(rec),source,vin))
                    self._event('missing_dealer_fields_filled',vin,source=source,fields=list(change))
                    self.db.execute('COMMIT')
                except Exception:
                    self.db.execute('ROLLBACK');raise
            return {'updated':change,'availability_verified':False}

    def import_feed(self, source, fmt, text, complete=True, *, preserve_gallery=False, scan_id=None):
        if source not in SOURCES:
            raise ValueError('unsupported_source')
        rows = decode_feed(text, fmt, source)
        is_demo = bool(fmt == 'json' and isinstance(json.loads(text), dict) and json.loads(text).get('demo_only') is True)
        if not rows:
            raise ValueError('empty_snapshot_rejected')
        accepted, quarantined, duplicates = {}, [], 0
        poisoned_vins = set()
        for idx, raw in enumerate(rows, 1):
            try:
                rec = normalize(source, raw)
                rec['demo_only'] = is_demo
                vin = rec['vin']
                if vin in accepted:
                    if accepted[vin] == rec:
                        duplicates += 1
                        continue
                    poisoned_vins.add(vin)
                    quarantined.append((idx, 'conflicting_duplicate_same_source', raw))
                    continue
                accepted[vin] = rec
            except ValueError as e:
                quarantined.append((idx, str(e), raw))
        for vin in poisoned_vins:
            del accepted[vin]
        if not accepted:
            raise ValueError('no_valid_rows; previous_snapshot_preserved')
        # A seemingly complete export that unexpectedly collapses in size is
        # rejected wholesale. A partial/truncated export must never rewrite a
        # verified full snapshot's missing flags or approvals.
        if complete and not quarantined:
            with self.lock:
                baseline = self.db.execute("SELECT COUNT(*) FROM sources WHERE source=? AND missing_count=0", (source,)).fetchone()[0]
            if baseline >= COVERAGE_MIN_BASELINE and len(accepted) < baseline * COVERAGE_FLOOR:
                raise ValueError(f'suspicious_feed_coverage_drop: prior={baseline}, received={len(accepted)}; snapshot_preserved')
        # Imperfect exports can add/update known vehicles but cannot mark missing.
        authoritative_complete = bool(complete and not quarantined and not poisoned_vins)
        runid = uuid.uuid4().hex
        now = utc()
        with self.lock:
            if scan_id is None or scan_id != self._backed_up_scan:
                self.backup()
                self._backed_up_scan=scan_id
            self.db.execute('BEGIN IMMEDIATE')
            try:
                for rec in accepted.values():
                    self.db.execute('INSERT OR IGNORE INTO vehicle_first_seen(vin,first_seen) VALUES(?,?)',
                                    (rec['vin'],now))
                    if preserve_gallery:
                        row=self.db.execute('SELECT record_json FROM sources WHERE source=? AND vin=?',
                                            (source,rec['vin'])).fetchone()
                        prior=json.loads(row['record_json']) if row else {}
                        if prior.get('url') == rec.get('url'):
                            old_images=prior.get('images') or []
                            def asset(url):
                                parts=urlsplit(url);return (parts.netloc.lower(),parts.path)
                            old_assets={asset(url) for url in old_images}
                            new_assets={asset(url) for url in rec['images']}
                            subset=bool(new_assets) and new_assets < old_assets
                            lead=rec['dealer_lead_photo'] or (prior.get('dealer_lead_photo','') if subset else '')
                            if subset:rec['images']=old_images
                            if lead and valid_url(lead,image=True):
                                rec['images']=[lead]+[image for image in rec['images'] if image!=lead]
                                rec['images']=rec['images'][:250]
                                rec['dealer_lead_photo']=lead
                            rec['photo_gallery_expected']=rec.get('photo_gallery_expected') or (prior.get('photo_gallery_expected') if subset else None)
                    self.db.execute('''INSERT INTO sources(source,vin,record_json,seen_at,missing_count)
                        VALUES(?,?,?,?,0) ON CONFLICT(source,vin) DO UPDATE SET
                        record_json=excluded.record_json,seen_at=excluded.seen_at,missing_count=0''',
                        (source, rec['vin'], compact_json(rec), now))
                if authoritative_complete:
                    placeholders = ','.join('?' for _ in accepted)
                    self.db.execute(f'''UPDATE sources SET missing_count=missing_count+1
                        WHERE source=? AND vin NOT IN ({placeholders})''', [source, *accepted])
                # Any approved, unposted draft becomes review-required when its
                # inventory evidence changes or is no longer in a full feed.
                # This never changes an already published Facebook listing.
                candidate_vins = set(accepted)
                if authoritative_complete:
                    candidate_vins.update(r['vin'] for r in self.db.execute(
                        'SELECT vin FROM sources WHERE source=? AND missing_count>0',(source,)))
                snapshots=self._group() if authoritative_complete else self._group(candidate_vins)
                for affected in candidate_vins:
                    # R19: refresh a preview when a new Chrome import changes
                    # the underlying dealer facts, unless Save was clicked.
                    draft_row = self.db.execute('SELECT source,snapshot_hash,status FROM drafts WHERE vin=?',(affected,)).fetchone()
                    if (draft_row and draft_row['status']=='READY_TO_REVIEW' and
                        not self.db.execute('SELECT 1 FROM draft_copy_locks WHERE vin=?',(affected,)).fetchone()):
                        live = snapshots.get(affected,{}).get(draft_row['source'])
                        if (live and live.get('sync_state')=='present' and live.get('price_cents') and
                            source_fingerprint(live)!=draft_row['snapshot_hash']):
                            fresh_title,fresh_description=build_listing_copy(live,draft_row['source'])
                            self.db.execute('''UPDATE drafts SET title=?,description=?,price_cents=?,
                               snapshot_hash=?,conflict_ack=0,updated_at=? WHERE vin=?''',
                               (fresh_title,fresh_description,live['price_cents'],source_fingerprint(live),now,affected))
                            self._event('unsaved_preview_refreshed_from_dealer_facts',affected,source=draft_row['source'])
                for affected in candidate_vins:
                    d = self.db.execute('SELECT source,snapshot_hash,conflict_ack,status FROM drafts WHERE vin=?',(affected,)).fetchone()
                    if not d or d['status'] not in ('READY_FOR_MANUAL_PUBLISH','USER_CONFIRMED_PUBLISHED'):
                        continue
                    selected = snapshots.get(affected,{}).get(d['source'])
                    problems = self._holds(snapshots[affected]) if snapshots.get(affected) else []
                    missing = (not selected or selected['sync_state'] != 'present'
                               or selected['availability'] != 'available')
                    stale = (missing
                             or source_fingerprint(selected) != d['snapshot_hash']
                             or 'condition_conflict' in problems
                             or 'vehicle_description_conflict' in problems
                             or ('price_conflict' in problems and not d['conflict_ack']))
                    if stale and d['status'] == 'READY_FOR_MANUAL_PUBLISH':
                        self.db.execute('UPDATE drafts SET status=?,conflict_ack=0,updated_at=? WHERE vin=?',
                                        ('READY_TO_REVIEW',now,affected))
                        self._event('approval_revoked_due_to_inventory_change',affected,trigger_source=source)
                    elif stale and d['status'] == 'USER_CONFIRMED_PUBLISHED':
                        review_state = 'NEEDS_REMOVAL_REVIEW' if missing else 'NEEDS_UPDATE'
                        old = self.db.execute('SELECT review_state FROM drafts WHERE vin=?',(affected,)).fetchone()
                        if old and old['review_state'] != review_state:
                            self.db.execute('UPDATE drafts SET review_state=?,updated_at=? WHERE vin=?',
                                            (review_state,now,affected))
                            self._event('published_listing_requires_user_review',affected,
                                        trigger_source=source,attention=review_state)
                for idx, reason, row in quarantined:
                    self.db.execute('''INSERT INTO quarantined(run_id,source,row_index,reason,row_json,at)
                        VALUES(?,?,?,?,?,?)''', (runid, source, idx, reason,
                        compact_json(row)[:8000], now))
                self.db.execute('''INSERT INTO feeds(source,last_import,rows_seen,last_accepted,last_complete,last_error,last_run)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET
                    last_import=excluded.last_import,rows_seen=excluded.rows_seen,
                    last_accepted=excluded.last_accepted,last_complete=excluded.last_complete,
                    last_error=excluded.last_error,last_run=excluded.last_run''',
                    (source, now, len(rows), len(accepted), int(authoritative_complete),
                     'Rows quarantined; removal checks skipped' if quarantined else '', runid))
                self._event('inventory_import', source=source, run_id=runid,
                            accepted=len(accepted), quarantined=len(quarantined),
                            duplicates=duplicates, complete=authoritative_complete)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
        return {'source': source, 'accepted': len(accepted), 'quarantined': len(quarantined),
                'duplicates_skipped': duplicates, 'complete': authoritative_complete,
                'run_id': runid, 'warning': 'Incomplete/invalid export: no missing-vehicle changes' if not authoritative_complete else ''}

    def authorize_used_dealer_photos(self):
        """Apply owner's standing dealership-photo authorization to USED sources only.

        Atomic, backed-up, idempotent. Never touches new-car records or
        publication status. Source fingerprint changes still flag stale drafts.
        """
        with self.lock:
            updates=[]
            for row in self.db.execute('SELECT source,vin,record_json FROM sources WHERE source IN (?,?)',('toyota_used','mitsubishi_used')):
                rec=json.loads(row['record_json'])
                if not rec.get('images_approved'):
                    rec['images_approved']=True
                    updates.append((compact_json(rec),row['source'],row['vin']))
            if not updates:return 0
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.executemany('UPDATE sources SET record_json=? WHERE source=? AND vin=?',updates)
                self._event('used_dealership_photo_authorization',None,records=len(updates))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return len(updates)

    def _group(self, vins=None):
        groups = defaultdict(dict)
        sql='SELECT source,vin,record_json,seen_at,missing_count FROM sources'
        params=()
        if vins is not None:
            if not vins:return groups
            params=tuple(vins)
            sql+=' WHERE vin IN ('+','.join('?' for _ in params)+')'
        for row in self.db.execute(sql,params):
            rec = json.loads(row['record_json'])
            rec['last_seen'] = row['seen_at']
            rec['missing_count'] = row['missing_count']
            rec['sync_state'] = ('present' if not row['missing_count'] else
                                 'missing_recheck' if row['missing_count'] == 1 else 'unavailable_verify')
            rec['fresh'] = record_is_fresh(row['seen_at'])
            groups[row['vin']][row['source']] = rec
        return groups

    @staticmethod
    def _holds(records):
        recs = list(records.values())
        reasons = []
        if len({r['condition'] for r in recs}) > 1:
            reasons.append('condition_conflict')
        if len({(r['year'], r['make'].lower(), r['model'].lower()) for r in recs}) > 1:
            reasons.append('vehicle_description_conflict')
        if len({r['price_cents'] for r in recs if r['price_cents'] is not None}) > 1:
            reasons.append('price_conflict')
        if any(not r['price_cents'] for r in recs):
            reasons.append('unconfirmed_price')
        if any(not r['images'] or not r['images_approved'] for r in recs):
            reasons.append('photo_approval_required')
        if any(r['sync_state'] != 'present' for r in recs):
            reasons.append('missing_from_feed_recheck')
        if any(not r['fresh'] for r in recs):
            reasons.append('inventory_stale')
        if any(r['availability'] != 'available' for r in recs):
            reasons.append('availability_needs_confirmation')
        if any(r.get('demo_only') for r in recs):
            reasons.append('demo_sample_not_publishable')
        return reasons

    def state(self):
        with self.lock:
            self._purge_expired_listing_trash()
            groups = self._group()
            draft_rows = {r['vin']: dict(r) for r in self.db.execute('SELECT * FROM drafts')}
            copy_locked = {r['vin'] for r in self.db.execute('SELECT vin FROM draft_copy_locks')}
            first_seen={r['vin']:r['first_seen'] for r in self.db.execute(
                'SELECT vin,first_seen FROM vehicle_first_seen')}
            removals = self.removals()
            removed_vins = {r['vin'] for r in removals}
            items = []
            for vin, recs in sorted(groups.items()):
                if vin in removed_vins:continue
                rec = next(iter(recs.values()))
                draft = draft_rows.get(vin)
                if draft:
                    draft['conflict_ack'] = bool(draft['conflict_ack'])
                    draft['copy_saved'] = vin in copy_locked
                    selected = recs.get(draft['source'])
                    draft['changed_since_draft'] = (not selected or
                        source_fingerprint(selected) != draft['snapshot_hash'])
                    if draft['status'] == 'USER_CONFIRMED_PUBLISHED':
                        if (not selected or selected['sync_state'] != 'present' or
                                selected['availability'] in ('sold','unavailable')):
                            draft['review_state'] = 'NEEDS_REMOVAL_REVIEW'
                        elif selected['availability'] != 'available':
                            # An existing FB link can be recorded without claiming
                            # the dealer still has the vehicle in stock.
                            draft['review_state'] = 'NEEDS_AVAILABILITY_REVIEW'
                        elif not selected['fresh'] or draft['changed_since_draft']:
                            draft['review_state'] = 'NEEDS_UPDATE'
                holds = self._holds(recs)
                # A source-specific price choice must be manual; do not pick the cheapest price.
                items.append({'vin': vin, 'first_seen': first_seen.get(vin), 'year': rec['year'], 'make': rec['make'],
                              'model': rec['model'], 'condition': rec['condition'] if 'condition_conflict' not in holds else 'review',
                              'sources': recs, 'holds': holds,
                              'draft': draft, 'listed': bool(draft and draft['status'] == 'USER_CONFIRMED_PUBLISHED')})
            feeds = {row['source']: dict(row) for row in self.db.execute('SELECT * FROM feeds')}
            qcount = self.db.execute('SELECT COUNT(*) FROM quarantined').fetchone()[0]
            alerts = sum(1 for item in items if item['holds'] or (item['draft'] is not None and
                         (item['draft']['changed_since_draft'] or item['draft'].get('review_state'))))
            return {'schema': SCHEMA, 'vehicles': items, 'feeds': feeds, 'removals': removals,
                    'summary': {'vehicles': len(items),
                                'pending_fb_deletions': sum(r['status'] == 'PENDING_FB_DELETE' for r in removals),
                                'shared_used': sum(item['condition'] == 'used' and len(item['sources']) > 1 for item in items),
                                'needs_attention': alerts, 'drafts': sum(bool(item['draft']) and item['draft']['status'] not in ('USER_CONFIRMED_PUBLISHED','USER_CONFIRMED_REMOVED') for item in items),
                                'published_confirmed': sum(item['listed'] for item in items),
                                'listing_reviews': sum(bool(item['draft'] and item['draft'].get('review_state')) for item in items),
                                'quarantined': qcount},
                    'recent_events': [{'id': r['id'], 'event': r['event'], 'vin': r['vin'], 'at': r['at'],
                                       'details': json.loads(r['details_json'])} for r in self.db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 30')]}

    def _lookup(self, vin, source, *, require_confirmed=True):
        if not VIN_RE.fullmatch(vin):
            raise ValueError('invalid_vin')
        row = self.db.execute('SELECT record_json,missing_count,seen_at FROM sources WHERE vin=? AND source=?', (vin,source)).fetchone()
        if not row:
            raise ValueError('unknown_vehicle_source')
        record = json.loads(row['record_json'])
        if require_confirmed:
            if row['missing_count'] or record['availability'] != 'available':
                raise ValueError('inventory_not_verified_available')
            if not record_is_fresh(row['seen_at']):
                raise ValueError('inventory_stale; refresh_authorized_feed_and_reconfirm')
        return record

    def create_draft(self, vin, source):
        with self.lock:
            if source not in SOURCES:
                raise ValueError('unknown_source')
            record = self._lookup(vin, source, require_confirmed=False)
            grouped = self._group((vin,))[vin]
            holds = self._holds(grouped)
            if 'condition_conflict' in holds or 'vehicle_description_conflict' in holds:
                raise ValueError('identity_conflict_must_be_resolved_first')
            if self.db.execute('SELECT 1 FROM drafts WHERE vin=?', (vin,)).fetchone():
                raise ValueError('draft_already_exists; use_edit')
            title, description = build_listing_copy(record, source)
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('''INSERT INTO drafts(vin,source,title,description,price_cents,status,snapshot_hash,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)''', (vin,source,title,description,record['price_cents'] or 0,
                    'READY_TO_REVIEW',source_fingerprint(record),utc()))
                self._event('draft_created',vin,source=source)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def confirm_used_availability(self, vin, source, explicit):
        """Human stock confirmation, never inferred from Chrome or sitemap.

        Page refresh later returns availability to pending, requiring a new check.
        """
        if explicit is not True:
            raise ValueError('explicit_current_stock_confirmation_required')
        if source not in ('toyota_used','mitsubishi_used') or not VIN_RE.fullmatch(vin):
            raise ValueError('invalid_used_vehicle_source')
        with self.lock:
            row=self.db.execute('SELECT record_json,missing_count,seen_at FROM sources WHERE vin=? AND source=?',(vin,source)).fetchone()
            if not row:raise ValueError('unknown_vehicle_source')
            if row['missing_count'] or not record_is_fresh(row['seen_at']):
                raise ValueError('vehicle_record_stale_or_missing; refresh_this_vehicle_first')
            rec=json.loads(row['record_json'])
            if rec.get('availability') in ('sold','unavailable'):
                raise ValueError('dealer_record_sold_or_unavailable; refresh_and_verify_first')
            prior_hash=source_fingerprint(rec)
            rec['availability']='available'
            rec['availability_verified_by_user_at']=utc()
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('UPDATE sources SET record_json=? WHERE vin=? AND source=?',
                    (compact_json(rec),vin,source))
                # Stock confirmation is evidence, NOT content approval. Keep
                # drafts editable and reconcile only the changed availability.
                self.db.execute('''UPDATE drafts SET
                                  snapshot_hash=CASE WHEN snapshot_hash=? THEN ? ELSE snapshot_hash END,
                                  status='READY_TO_REVIEW',conflict_ack=0,updated_at=? WHERE vin=? AND source=?
                                  AND status IN ('READY_TO_REVIEW','READY_FOR_MANUAL_PUBLISH')''',
                                (prior_hash,source_fingerprint(rec),utc(),vin,source))
                self._event('user_confirmed_current_lot_availability',vin,source=source)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def edit_draft(self, vin, title, description, price_cents=None):
        with self.lock:
            d = self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not d:
                raise ValueError('draft_missing')
            if d['status'] == 'USER_CONFIRMED_PUBLISHED':
                raise ValueError('published_record_locked; make_a_new_listing_after_manual_review')
            title = str(title).strip(); description = str(description).strip()
            if not (5 <= len(title) <= 130 and 40 <= len(description) <= 5000):
                raise ValueError('invalid_title_or_description_length')
            # Price is sourced from the selected dealer, never arbitrary user input.
            src = self._lookup(vin,d['source'], require_confirmed=False)
            if price_cents is not None and int(price_cents) != src['price_cents']:
                raise ValueError('price_must_match_verified_source')
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('UPDATE drafts SET title=?,description=?,status=?,conflict_ack=0,updated_at=? WHERE vin=?',
                                (title,description,'READY_TO_REVIEW',utc(),vin))
                self.db.execute('INSERT INTO draft_copy_locks(vin,saved_at) VALUES(?,?) ON CONFLICT(vin) DO UPDATE SET saved_at=excluded.saved_at',(vin,utc()))
                self._event('draft_description_saved_and_locked',vin)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def reconcile_draft(self, vin, *, explicit_review, explicit_stock_confirmation=False,
                        conflict_ack=False):
        '''Explicitly rebind dealer facts while preserving the user's saved copy.

        Never silently approve, publish, or regenerate descriptions. A newer scan
        may change photo URLs, odometer, price, features or pending availability.
        The user has to review the *current* source and confirm stock when needed.
        '''
        if explicit_review is not True:
            raise ValueError('explicit_dealer_facts_review_required')
        with self.lock:
            draft=self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not draft or draft['status'] != 'READY_TO_REVIEW':
                raise ValueError('draft_not_editable_for_reconciliation')
            source=draft['source']
            if source not in ('toyota_used','mitsubishi_used'):
                raise ValueError('used_vehicle_source_required')
            row=self.db.execute('SELECT record_json,seen_at,missing_count FROM sources WHERE vin=? AND source=?',
                                (vin,source)).fetchone()
            if not row or row['missing_count'] or not record_is_fresh(row['seen_at']):
                raise ValueError('dealer_record_stale_or_missing; refresh_vehicle_first')
            current=json.loads(row['record_json'])
            if current.get('demo_only') or current.get('availability') in ('sold','unavailable'):
                raise ValueError('vehicle_unavailable_or_demonstration; cannot_approve')
            if not current.get('price_cents') or not current.get('images') or not current.get('images_approved'):
                raise ValueError('verified_dealer_price_and_photos_required')
            groups=self._group().get(vin,{})
            holds=self._holds(groups)
            if any(x in holds for x in ('condition_conflict','vehicle_description_conflict')):
                raise ValueError('vehicle_identity_conflict; review_dealer_records')
            if 'price_conflict' in holds and conflict_ack is not True:
                raise ValueError('price_conflict_requires_explicit_acknowledgement')
            # Current dealer-page presence is not stock verification. A Chrome
            # refresh may set availability to pending; do not infer available.
            if current.get('availability') != 'available':
                if explicit_stock_confirmation is not True:
                    raise ValueError('explicit_current_stock_confirmation_required')
                current['availability']='available'
                current['availability_verified_by_user_at']=utc()
            new_hash=source_fingerprint(current)
            if new_hash == draft['snapshot_hash'] and current['price_cents']==draft['price_cents']:
                return self.state()
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if explicit_stock_confirmation is True and current.get('availability_verified_by_user_at'):
                    self.db.execute('UPDATE sources SET record_json=? WHERE vin=? AND source=?',
                                    (compact_json(current),vin,source))
                self.db.execute('''UPDATE drafts SET snapshot_hash=?,price_cents=?,
                     status='READY_TO_REVIEW',conflict_ack=0,updated_at=? WHERE vin=?''',
                     (new_hash,current['price_cents'],utc(),vin))
                # Intentional: title, description, and draft_copy_locks NEVER change.
                self._event('user_reviewed_and_synced_dealer_facts_preserved_copy',vin,
                    source=source,price_changed=current['price_cents']!=draft['price_cents'],
                    stock_confirmed=explicit_stock_confirmation is True)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def facebook_form_fields(self, vin, decoded=None):
        with self.lock:
            draft=self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not draft or draft['status'] not in ('READY_TO_REVIEW','READY_FOR_MANUAL_PUBLISH'):
                raise ValueError('Create a listing draft in LotRadar first.')
            record=self._lookup(vin,draft['source'],require_confirmed=False)
            sources=self._group((vin,))[vin]
            if (sources[draft['source']]['sync_state']!='present'
                or record['availability'] in ('sold','unavailable')):
                raise ValueError('This vehicle is missing or marked unavailable. Refresh the vehicle first.')
            if any(reason in self._holds(sources) for reason in ('condition_conflict','vehicle_description_conflict')):
                raise ValueError('Dealer records disagree about the vehicle identity.')
            from vin_decode import valid_spec, mapped_specs
            specs=dict(record.get('specifications') or {})
            fallback=mapped_specs(decoded)
            spec_sources={}
            for field in ('body_style','fuel_type'):
                value=valid_spec(field,specs.get(field))
                spec_sources[field]='dealer' if value else ('vin' if fallback.get(field) else None)
                specs[field]=value or fallback.get(field)
            cents=record['price_cents']
            return {'year':record['year'],'make':record['make'],
                    'model':record['model'],'mileage':record.get('mileage'),
                    'price':cents//100 if cents and cents>0 and cents%100==0 else None,
                    'description':draft['description'],'body_style':specs.get('body_style'),
                    'vehicle_type':'Car/Truck','fuel_type':specs.get('fuel_type'),'spec_sources':spec_sources,
                    'transmission':specs.get('transmission'),
                    'exterior_color':specs.get('exterior_color'),'interior_color':specs.get('interior_color'),
                    'exterior_color_generic':specs.get('exterior_color_generic'),'interior_color_generic':specs.get('interior_color_generic')}

    def approve_draft(self, vin, explicit, conflict_ack):
        if explicit is not True:
            raise ValueError('explicit_approval_required')
        with self.lock:
            d = self.db.execute('SELECT * FROM drafts WHERE vin=?', (vin,)).fetchone()
            if not d or d['status'] != 'READY_TO_REVIEW':
                raise ValueError('draft_not_ready_to_approve')
            record = self._lookup(vin, d['source'], require_confirmed=False)
            active = self.db.execute('SELECT missing_count,seen_at FROM sources WHERE vin=? AND source=?',(vin,d['source'])).fetchone()
            if not active or active['missing_count'] or not record_is_fresh(active['seen_at']) or record.get('availability') != 'available':
                raise ValueError('dealer_record_missing_stale_or_sold; refresh_and_review_before_approval')
            if record.get('demo_only'):
                raise ValueError('demo_only_cannot_be_approved')
            if source_fingerprint(record) != d['snapshot_hash'] or record['price_cents'] != d['price_cents']:
                raise ValueError('dealer_information_changed; rebuild_draft')
            reasons = self._holds(self._group()[vin])
            if any(reason in reasons for reason in ('condition_conflict','vehicle_description_conflict')):
                raise ValueError('vehicle_identity_conflict')
            if 'price_conflict' in reasons and conflict_ack is not True:
                raise ValueError('price_conflict_requires_explicit_acknowledgement')
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('''UPDATE drafts SET status=?,conflict_ack=?,updated_at=? WHERE vin=?''',
                                ('READY_FOR_MANUAL_PUBLISH',int(conflict_ack is True),utc(),vin))
                self._event('content_approved_not_published',vin,source=d['source'], price_cents=d['price_cents'])
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def confirm_published(self, vin, url, explicit):
        if explicit is not True:
            raise ValueError('explicit_manual_publication_confirmation_required')
        url = str(url or '').strip()
        if not FB_URL_RE.fullmatch(url):
            raise ValueError('valid_facebook_marketplace_item_url_required')
        with self.lock:
            d = self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not d or d['status'] not in ('READY_TO_REVIEW','READY_FOR_MANUAL_PUBLISH'):
                raise ValueError('editable_listing_draft_required')
            if self.db.execute('SELECT 1 FROM drafts WHERE published_url=? AND vin<>?', (url,vin)).fetchone():
                raise ValueError('marketplace_url_already_assigned_to_another_vin')
            for trash in self.db.execute('SELECT draft_json FROM listing_trash'):
                if facebook_listing_id(json.loads(trash['draft_json']).get('published_url'))==facebook_listing_id(url):
                    raise ValueError('facebook_listing_in_trash; restore_or_wait_30_days')
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('''UPDATE drafts SET status=?,published_url=?,updated_at=? WHERE vin=?''',
                                ('USER_CONFIRMED_PUBLISHED',url,utc(),vin))
                self._event('user_confirmed_facebook_publication',vin,url=url)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def relink_facebook(self, vin, url, expected_url, explicit):
        """Update only a user-confirmed local Facebook link, never inventory or a FB post.

        The expected old URL prevents stale browser forms from overwriting a
        newer edit. A different listing ID does not inherit the old capture.
        """
        if explicit is not True:raise ValueError('explicit_facebook_relink_required')
        vin=str(vin or '').strip().upper()
        url=str(url or '').strip()
        if not FB_URL_RE.fullmatch(url):raise ValueError('valid_facebook_marketplace_item_url_required')
        listing_id=facebook_listing_id(url)
        if not listing_id:raise ValueError('valid_facebook_listing_id_required')
        normalized='https://www.facebook.com/marketplace/item/'+listing_id
        with self.lock:
            self._purge_expired_listing_trash()
            row=self.db.execute('SELECT status,published_url FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not row or row['status']!='USER_CONFIRMED_PUBLISHED':raise ValueError('active_tracked_listing_required')
            if row['published_url']!=str(expected_url or ''):raise ValueError('facebook_link_changed_elsewhere; reload_vehicle')
            if row['published_url']==normalized:return self.state()
            for active in self.db.execute('SELECT vin,published_url FROM drafts WHERE published_url<>""'):
                if active['vin']!=vin and facebook_listing_id(active['published_url'])==listing_id:
                    raise ValueError('facebook_listing_id_already_linked_to_another_vehicle')
            for trash in self.db.execute('SELECT draft_json FROM listing_trash'):
                if facebook_listing_id(json.loads(trash['draft_json']).get('published_url'))==listing_id:
                    raise ValueError('facebook_listing_in_trash; restore_or_wait_30_days')
            old_id=facebook_listing_id(row['published_url'])
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('UPDATE drafts SET published_url=?,updated_at=? WHERE vin=?',(normalized,utc(),vin))
                self._event('local_facebook_listing_url_updated',vin,old_listing_id=old_id,new_listing_id=listing_id,facebook_post_unchanged=True)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
            return self.state()

    def rebuild_draft(self, vin):
        with self.lock:
            d = self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not d or d['status'] == 'USER_CONFIRMED_PUBLISHED':
                raise ValueError('no_editable_draft')
            r = self._lookup(vin, d['source'], require_confirmed=False)
            title, description = build_listing_copy(r, d['source'])
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('''UPDATE drafts SET title=?,description=?,price_cents=?,snapshot_hash=?,status=?,conflict_ack=0,updated_at=? WHERE vin=?''',
                                (title,description,r['price_cents'] or 0,source_fingerprint(r),'READY_TO_REVIEW',utc(),vin))
                self.db.execute('DELETE FROM draft_copy_locks WHERE vin=?',(vin,))
                self._event('draft_regenerated_from_current_dealer_source',vin,source=d['source'])
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def track_existing(self, vin, source, url, explicit):
        """Manually record an existing listing; never contact Facebook."""
        if explicit is not True:
            raise ValueError('user_must_confirm_existing_listing')
        url = str(url or '').strip()
        if not FB_URL_RE.fullmatch(url):
            raise ValueError('valid_facebook_marketplace_item_url_required')
        with self.lock:
            if source not in ('toyota_used', 'mitsubishi_used'):
                raise ValueError('used_inventory_only')
            # A real Facebook listing already created by the user may be
            # recorded even when the current dealer stock status is pending.
            # That is a historical tracking action, NOT fresh stock approval.
            rec = self._lookup(vin, source, require_confirmed=False)
            if rec.get('condition') != 'used' or rec.get('demo_only'):
                raise ValueError('used_real_vehicle_required_for_tracking')
            holds = self._holds(self._group()[vin])
            if any(reason in holds for reason in ('condition_conflict','vehicle_description_conflict')):
                raise ValueError('vehicle_identity_conflict')
            if self.db.execute('SELECT 1 FROM drafts WHERE vin=?', (vin,)).fetchone():
                raise ValueError('draft_exists; no_overwrite')
            if self.db.execute('SELECT 1 FROM drafts WHERE published_url=?', (url,)).fetchone():
                raise ValueError('marketplace_url_already_tracked')
            for trashed in self.db.execute('SELECT draft_json FROM listing_trash'):
                if facebook_listing_id(json.loads(trashed['draft_json']).get('published_url'))==facebook_listing_id(url):
                    raise ValueError('facebook_listing_in_trash; restore_or_wait_30_days')
            title = dealer_vehicle_title(rec)[:130]
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('''INSERT INTO drafts(vin,source,title,description,price_cents,status,
                                snapshot_hash,published_url,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?)''',
                                (vin,source,title,'Existing personal Marketplace listing tracked by user',
                                 rec['price_cents'] or 0,'USER_CONFIRMED_PUBLISHED',
                                 source_fingerprint(rec),url,utc()))
                self._event('existing_facebook_listing_manually_linked',vin,url=url,source=source)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def capture_facebook_listing(self, payload):
        """User-clicked browser capture, bound ONLY by a previously tracked listing ID.

        The supplied page is not allowed to identify a VIN, dealership source or user.
        Only the already-linked draft supplies the internal identity.
        """
        if not isinstance(payload,dict):raise ValueError('facebook_capture_must_be_object')
        if payload.get('explicit_capture') is not True:raise ValueError('explicit_facebook_capture_required')
        url=str(payload.get('url') or '')
        listing_id=facebook_listing_id(url)
        if not listing_id:raise ValueError('facebook_listing_url_not_supported')
        clean_url='https://www.facebook.com/marketplace/item/'+listing_id
        snapshot={'listing_id':listing_id,'url':clean_url,
                  'page_type':'edit' if '/marketplace/edit' in urlparse(url).path else 'item',
                  'title':facebook_field_text(payload.get('title'),180),
                  'description':facebook_field_text(payload.get('description'),5000),
                  'status':str(payload.get('status') or 'unknown') if payload.get('status') in ('active','sold','unavailable') else 'unknown',
                  'price':None,'mileage':None}
        for key,limit in [('price',5000000),('mileage',2000000)]:
            value=payload.get(key)
            if value is None or value=='':continue
            if isinstance(value,bool):raise ValueError('facebook_'+key+'_invalid')
            try:
                number=int(value)
                if number<0 or number>limit:raise ValueError()
                snapshot[key]=number
            except (ValueError,TypeError):raise ValueError('facebook_'+key+'_invalid') from None
        if not any(snapshot[k] not in ('',None,'unknown') for k in ('title','description','price','mileage','status')):
            raise ValueError('facebook_fields_not_visible;open_edit_page_and_retry')
        with self.lock:
            matches=[]
            for row in self.db.execute("SELECT vin,published_url,status FROM drafts WHERE published_url<>''"):
                if facebook_listing_id(row['published_url'])==listing_id:
                    matches.append(row)
            if not matches:raise ValueError('facebook_listing_not_linked;track_existing_first')
            if len(matches)!=1:raise ValueError('facebook_listing_id_link_conflict')
            match=matches[0]
            if match['status']!='USER_CONFIRMED_PUBLISHED':
                raise ValueError('facebook_listing_not_user_confirmed_published')
            vin=match['vin']
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                at=utc()
                self.db.execute('INSERT INTO facebook_listing_captures(listing_id,vin,captured_at,snapshot_json) VALUES(?,?,?,?)',
                                (listing_id,vin,at,compact_json(snapshot)))
                self.db.execute("DELETE FROM facebook_listing_captures WHERE listing_id=? AND id NOT IN (SELECT id FROM facebook_listing_captures WHERE listing_id=? ORDER BY id DESC LIMIT 30)",
                    (listing_id,listing_id))
                self._event('facebook_listing_read_only_capture',vin,listing_id=listing_id,page_type=snapshot['page_type'])
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return {'ok':True,'listing_id':listing_id,'vehicle_linked':True,
                    'capture_fields':[k for k in ('title','price','mileage','description','status')
                                      if snapshot[k] not in ('',None,'unknown')],
                    'captured_at':at}

    def facebook_comparison(self,vin):
        with self.lock:
            row=self.db.execute('SELECT * FROM drafts WHERE vin=?',(str(vin or '').upper(),)).fetchone()
            if not row or not row['published_url']:
                raise ValueError('no_tracked_facebook_listing_for_vehicle')
            listing_id=facebook_listing_id(row['published_url'])
            if not listing_id:raise ValueError('tracked_facebook_listing_url_invalid')
            captured=self.db.execute("SELECT * FROM facebook_listing_captures WHERE listing_id=? AND vin=? ORDER BY id DESC LIMIT 1",(listing_id,vin)).fetchone()
            try:rec=self._lookup(vin,row['source'],require_confirmed=False)
            except ValueError:rec=None
            def dealer_title():
                return dealer_vehicle_title(rec).strip() if rec is not None else ''
            local_desc=(row['description'] if row['description']!='Existing personal Marketplace listing tracked by user' else '')
            dealer={'title':dealer_title(), 'price':rec['price_cents']//100 if rec and rec.get('price_cents') is not None else None,
                    'mileage':rec.get('mileage') if rec else None,'description':local_desc}
            fb=json.loads(captured['snapshot_json']) if captured else None
            rows=[]
            for key,label in [('title','Model / title'),('price','Price'),('mileage','Mileage'),('description','Description')]:
                a=dealer[key];b=fb[key] if fb else None
                if a in ('',None) or b in ('',None):state='unknown'
                elif key in ('price','mileage'):state='match' if a==b else 'different'
                else:state='match' if ' '.join(str(a).casefold().split())==' '.join(str(b).casefold().split()) else 'different'
                rows.append({'key':key,'label':label,'dealer':a,'facebook':b,'state':state})
            return {'ok':True,'vin':vin,'listing_id':listing_id,'linked_url':row['published_url'],
                    'captured_at':captured['captured_at'] if captured else None,
                    'facebook_status':fb['status'] if fb else 'unknown',
                    'page_type':fb['page_type'] if fb else None,
                    'rows':rows,
                    'capture_count':self.db.execute('SELECT COUNT(*) FROM facebook_listing_captures WHERE listing_id=? AND vin=?',(listing_id,vin)).fetchone()[0]}

    def confirm_listing_updated(self, vin, explicit, conflict_ack=False):
        """User attests a live Facebook listing was manually updated. Never edits Facebook."""
        if explicit is not True:
            raise ValueError('explicit_manual_update_confirmation_required')
        with self.lock:
            d = self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not d or d['status'] != 'USER_CONFIRMED_PUBLISHED':
                raise ValueError('no_user_confirmed_live_listing')
            # FB update confirmation is an audit of the USER'S manual Facebook action.
            # Unlike new-listing approval, it must not claim the dealer has verified stock.
            rec = self._lookup(vin,d['source'],require_confirmed=False)
            reasons = self._holds(self._group()[vin])
            if any(x in reasons for x in ('condition_conflict','vehicle_description_conflict')):
                raise ValueError('vehicle_identity_conflict')
            if 'price_conflict' in reasons and conflict_ack is not True:
                raise ValueError('price_conflict_requires_explicit_acknowledgement')
            source_row=self.db.execute('SELECT missing_count,seen_at FROM sources WHERE vin=? AND source=?',(vin,d['source'])).fetchone()
            missing=not source_row or bool(source_row['missing_count'])
            sold=rec.get('availability') in ('sold','unavailable')
            stale=not source_row or not record_is_fresh(source_row['seen_at'])
            review_state=('NEEDS_REMOVAL_REVIEW' if missing or sold else
                          'NEEDS_AVAILABILITY_REVIEW' if rec.get('availability')!='available' else
                          'NEEDS_UPDATE' if stale else '')
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute("UPDATE drafts SET snapshot_hash=?,price_cents=?,review_state=?, conflict_ack=?,updated_at=? WHERE vin=?",
                    (source_fingerprint(rec),rec['price_cents'],review_state,int(conflict_ack is True),utc(),vin))
                self._event('user_confirmed_listing_updated_outside_app',vin,source=d['source'],dealer_stock_unverified=bool(review_state))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def confirm_listing_removed(self, vin, explicit):
        """Historical record retained after user manually removes a listing on Facebook."""
        if explicit is not True:
            raise ValueError('explicit_manual_removal_confirmation_required')
        with self.lock:
            d = self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not d or d['status'] != 'USER_CONFIRMED_PUBLISHED':
                raise ValueError('no_user_confirmed_live_listing')
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute("UPDATE drafts SET status='USER_CONFIRMED_REMOVED', review_state='',updated_at=? WHERE vin=?",(utc(),vin))
                self._event('user_confirmed_listing_removed_outside_app',vin,url=d['published_url'])
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def _purge_expired_listing_trash(self):
        """Purge only expired local tracking artifacts, never dealership records or Facebook posts.

        Caller holds self.lock; database backup precedes the first destructive deletion.
        """
        now = utc()
        expired = self.db.execute('SELECT id,vin,draft_json FROM listing_trash WHERE expires_at<=?',(now,)).fetchall()
        if not expired:return 0
        self.backup()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for entry in expired:
                draft=json.loads(entry['draft_json'])
                lid=facebook_listing_id(draft.get('published_url'))
                if lid:
                    # Never remove snapshots now linked to some other active listing.
                    active=self.db.execute('SELECT 1 FROM drafts WHERE published_url LIKE ?',('%/item/'+lid+'%',)).fetchone()
                    if not active:self.db.execute('DELETE FROM facebook_listing_captures WHERE vin=? AND listing_id=?',(entry['vin'],lid))
                self.db.execute('DELETE FROM listing_trash WHERE id=?',(entry['id'],))
                self._event('local_listing_trash_expired',entry['vin'])
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK');raise
        return len(expired)

    def listing_trash(self):
        """List recoverable records. Trash contains *local* listing links, not Facebook posts."""
        with self.lock:
            self._purge_expired_listing_trash()
            return {'ok':True,'items':[{'vin':r['vin'], 'title':json.loads(r['draft_json']).get('title',''),
                 'url':json.loads(r['draft_json']).get('published_url',''),
                 'deleted_at':r['deleted_at'],'expires_at':r['expires_at'],'id':r['id']}
                for r in self.db.execute('SELECT * FROM listing_trash ORDER BY deleted_at DESC')]}

    def record_link_check(self, source, link, outcome):
        if source=='facebook':
            link=facebook_listing_id(link)
        elif source not in ('toyota_used','mitsubishi_used'):
            return
        if not link or outcome not in ('reachable','unavailable','check_failed'):
            return
        with self.lock:
            self.db.execute('''INSERT INTO listing_link_checks(source,link,outcome,checked_at)
                VALUES(?,?,?,?) ON CONFLICT(source,link) DO UPDATE SET
                outcome=excluded.outcome,checked_at=excluded.checked_at
                WHERE listing_link_checks.outcome!='unavailable' OR excluded.outcome!='check_failed' ''',
                (source,link,outcome,utc()))

    def cleanup_status(self, vin=None):
        with self.lock:
            groups=self._group({vin}) if vin else self._group()
            checks={(r['source'],r['link']):dict(r) for r in self.db.execute(
                'SELECT source,link,outcome,checked_at FROM listing_link_checks')}
            tracked={r['vin']:r['published_url'] for r in self.db.execute(
                "SELECT vin,published_url FROM drafts WHERE status='USER_CONFIRMED_PUBLISHED'")}
            issues={}
            removed={r['vin'] for r in self.removals()}
            for key,records in groups.items():
                if key in removed:continue
                dealer=[(source,rec,checks.get((source,rec.get('url')))) for source,rec in records.items()
                        if source in ('toyota_used','mitsubishi_used')]
                if not dealer:continue
                dealer_issues=[]
                for source,rec,check in dealer:
                    if check and check['outcome']!='reachable':
                        dealer_issues.append({'source':source,**check})
                    elif not rec.get('url') or rec.get('missing_count') or rec.get('availability') in ('sold','unavailable'):
                        dealer_issues.append({'source':source,'outcome':'inventory_review'})
                fb_id=facebook_listing_id(tracked.get(key,''))
                fb=checks.get(('facebook',fb_id))
                fb_issue=fb if fb and fb['outcome']!='reachable' else None
                if not dealer_issues and not fb_issue:continue
                both=bool(fb_issue and fb_issue['outcome']=='unavailable' and
                          all(check and check['outcome']=='unavailable' for _,_,check in dealer))
                out_of_stock=all((check and check['outcome']=='unavailable')
                                 or rec.get('availability') in ('sold','unavailable')
                                 for _,rec,check in dealer)
                issues[key]={'dealer':dealer_issues,'facebook':fb_issue,'probable_out_of_stock':out_of_stock,
                             'can_trash':both,'listing_id':fb_id}
            return issues

    def removals(self):
        """Vehicles removed from active inventory (excludes restored). Caller may hold self.lock."""
        out=[]
        for r in self.db.execute("SELECT * FROM inventory_removals WHERE status!='RESTORED' ORDER BY removed_at,vin"):
            row=dict(r);row['identity']=json.loads(row.pop('identity_json'))
            # Only a canonical marketplace item URL derived from a validated ID is ever offered for opening.
            row['open_url']=('https://www.facebook.com/marketplace/item/'+row['listing_id']+'/') if row['listing_id'] else ''
            out.append(row)
        return out

    def remove_out_of_stock(self, vin, explicit):
        """Owner-confirmed removal from active inventory. Source records and drafts are never deleted.

        A tracked Facebook listing creates exactly one durable pending-deletion reminder.
        """
        if explicit is not True:raise ValueError('explicit_out_of_stock_confirmation_required')
        vin=str(vin or '').strip().upper()
        if not VIN_RE.fullmatch(vin):raise ValueError('invalid_vin')
        with self.lock:
            existing=self.db.execute('SELECT status FROM inventory_removals WHERE vin=?',(vin,)).fetchone()
            if existing and existing['status']!='RESTORED':return self.state()  # duplicate click
            groups=self._group({vin})
            if vin not in groups:raise ValueError('unknown_vehicle')
            rec=next((r for s,r in sorted(groups[vin].items()) if s in ('toyota_used','mitsubishi_used')),next(iter(groups[vin].values())))
            stocks={s:r.get('stock') for s,r in groups[vin].items() if r.get('stock')}
            identity={'vin':vin,'year':rec.get('year'),'make':rec.get('make'),'model':rec.get('model'),
                      'trim':rec.get('trim'),'stock':rec.get('stock') or next(iter(stocks.values()),''),
                      'stocks':stocks,'sources':sorted(groups[vin]),'price_cents':rec.get('price_cents'),
                      'title':dealer_vehicle_title(rec)}
            draft=self.db.execute('SELECT status,published_url FROM drafts WHERE vin=?',(vin,)).fetchone()
            tracked=bool(draft and draft['status']=='USER_CONFIRMED_PUBLISHED')
            url=draft['published_url'] if tracked else ''
            lid=facebook_listing_id(url) if tracked else ''
            status='PENDING_FB_DELETE' if tracked else 'REMOVED'
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT OR REPLACE INTO inventory_removals(vin,status,removed_at,identity_json,listing_url,listing_id,fb_confirmed_at,restored_at) VALUES(?,?,?,?,?,?,NULL,NULL)',
                    (vin,status,utc(),compact_json(identity),url,lid))
                self._event('owner_confirmed_out_of_stock_removed',vin,pending_facebook_deletion=tracked,listing_id=lid,facebook_post_unchanged=True)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
            return self.state()

    def confirm_facebook_deleted(self, vin, explicit, expected_listing_url):
        """Owner attests the Marketplace post was deleted manually; only then clear the reminder and archive tracking."""
        if explicit is not True:raise ValueError('explicit_manual_facebook_deletion_confirmation_required')
        if not isinstance(expected_listing_url,str):raise ValueError('expected_listing_url_required')
        vin=str(vin or '').strip().upper()
        with self.lock:
            row=self.db.execute('SELECT * FROM inventory_removals WHERE vin=?',(vin,)).fetchone()
            if not row or row['status'] not in ('PENDING_FB_DELETE','FB_DELETE_CONFIRMED'):
                raise ValueError('no_pending_facebook_deletion')
            if row['status']=='FB_DELETE_CONFIRMED':return self.state()  # duplicate click
            if (facebook_listing_id(expected_listing_url) or expected_listing_url)!=(row['listing_id'] or row['listing_url']):
                raise ValueError('facebook_listing_changed_since_review')
            self._purge_expired_listing_trash()
            draft=self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            same=bool(draft and draft['status']=='USER_CONFIRMED_PUBLISHED' and
                      (facebook_listing_id(draft['published_url'])==row['listing_id'] if row['listing_id'] else draft['published_url']==row['listing_url']))
            copied=self.db.execute('SELECT saved_at FROM draft_copy_locks WHERE vin=?',(vin,)).fetchone()
            now=datetime.now(timezone.utc)
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                if same:
                    self.db.execute('INSERT INTO listing_trash(vin,draft_json,copy_saved_at,deleted_at,expires_at) VALUES(?,?,?,?,?)',
                        (vin,compact_json(dict(draft)),copied['saved_at'] if copied else None,
                         now.isoformat(timespec='seconds'),(now+timedelta(days=30)).isoformat(timespec='seconds')))
                    self.db.execute('DELETE FROM drafts WHERE vin=?',(vin,))
                    self.db.execute('DELETE FROM draft_copy_locks WHERE vin=?',(vin,))
                self.db.execute("UPDATE inventory_removals SET status='FB_DELETE_CONFIRMED',fb_confirmed_at=? WHERE vin=? AND status='PENDING_FB_DELETE'",(utc(),vin))
                self._event('user_attested_facebook_post_deleted_manually',vin,listing_id=row['listing_id'],
                    local_tracking_archived=same,facebook_deletion_performed_by_app=False)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
            return self.state()

    def restore_removed(self, vin, explicit):
        """Recovery for a mistaken removal. Source records and Facebook tracking were never altered."""
        if explicit is not True:raise ValueError('explicit_restore_confirmation_required')
        vin=str(vin or '').strip().upper()
        with self.lock:
            row=self.db.execute('SELECT status FROM inventory_removals WHERE vin=?',(vin,)).fetchone()
            if not row:raise ValueError('vehicle_not_removed')
            if row['status']=='RESTORED':return self.state()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute("UPDATE inventory_removals SET status='RESTORED',restored_at=? WHERE vin=?",(utc(),vin))
                self._event('removed_vehicle_restored_to_active_inventory',vin,previous_status=row['status'])
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
            return self.state()

    def trash_listing(self,vin,explicit,*,cleanup_listing_id=None):
        """Archive and unlink a tracked Facebook listing for 30 days; never touch Facebook."""
        if explicit is not True:raise ValueError('explicit_local_trash_confirmation_required')
        vin=str(vin or '').strip().upper()
        with self.lock:
            self._purge_expired_listing_trash()
            draft=self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not draft or draft['status']!='USER_CONFIRMED_PUBLISHED' or not facebook_listing_id(draft['published_url']):
                raise ValueError('no_active_tracked_listing_to_trash')
            if cleanup_listing_id is not None:
                current=self.cleanup_status(vin).get(vin,{})
                if not current.get('can_trash') or current.get('listing_id')!=cleanup_listing_id:
                    raise ValueError('Link status or Facebook listing changed. Check both links again.')
            copy=self.db.execute('SELECT saved_at FROM draft_copy_locks WHERE vin=?',(vin,)).fetchone()
            now=datetime.now(timezone.utc)
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT INTO listing_trash(vin,draft_json,copy_saved_at,deleted_at,expires_at) VALUES(?,?,?,?,?)',
                    (vin,compact_json(dict(draft)),copy['saved_at'] if copy else None,
                     now.isoformat(timespec='seconds'),(now+timedelta(days=30)).isoformat(timespec='seconds')))
                self.db.execute('DELETE FROM drafts WHERE vin=?',(vin,))
                self.db.execute('DELETE FROM draft_copy_locks WHERE vin=?',(vin,))
                self._event('local_facebook_listing_moved_to_30_day_trash',vin,
                    listing_id=facebook_listing_id(draft['published_url']),facebook_post_unchanged=True)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
            return self.state()

    def complete_facebook_cleanup(self, vin, explicit_manual_removal, explicit_local_trash, expected_listing_url):
        """User attests deletion on Facebook, then archives LOCAL tracking for 30 days.

        Does not call Facebook or modify dealership inventory. Refuses stale listing
        ID confirmations so an already relinked URL cannot be archived by mistake.
        """
        if explicit_manual_removal is not True or explicit_local_trash is not True:
            raise ValueError('manual_facebook_removal_and_local_trash_confirmation_required')
        vin = str(vin or '').strip().upper()
        expected_id = facebook_listing_id(expected_listing_url)
        if not expected_id:
            raise ValueError('valid_expected_facebook_listing_id_required')
        with self.lock:
            self._purge_expired_listing_trash()
            draft = self.db.execute('SELECT * FROM drafts WHERE vin=?',(vin,)).fetchone()
            if not draft or draft['status']!='USER_CONFIRMED_PUBLISHED':
                raise ValueError('active_tracked_listing_required')
            actual_id = facebook_listing_id(draft['published_url'])
            if actual_id != expected_id:
                raise ValueError('facebook_listing_changed_since_review')
            copied = self.db.execute('SELECT saved_at FROM draft_copy_locks WHERE vin=?',(vin,)).fetchone()
            now = datetime.now(timezone.utc)
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT INTO listing_trash(vin,draft_json,copy_saved_at,deleted_at,expires_at) VALUES(?,?,?,?,?)',
                    (vin,compact_json(dict(draft)),copied['saved_at'] if copied else None,
                    now.isoformat(timespec='seconds'),(now+timedelta(days=30)).isoformat(timespec='seconds')))
                self.db.execute('DELETE FROM drafts WHERE vin=?',(vin,))
                self.db.execute('DELETE FROM draft_copy_locks WHERE vin=?',(vin,))
                self._event('user_attested_facebook_post_removed_local_copy_trashed',vin,
                    listing_id=actual_id,facebook_post_removed_user_attested=True,facebook_deletion_performed_by_app=False)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
            return self.state()

    def restore_listing(self,vin,explicit,trash_id=None):
        if explicit is not True:raise ValueError('explicit_local_restore_required')
        vin=str(vin or '').strip().upper()
        with self.lock:
            self._purge_expired_listing_trash()
            entries=self.db.execute('SELECT * FROM listing_trash WHERE vin=? ORDER BY id DESC',(vin,)).fetchall()
            entry=next((row for row in entries if row['id']==int(trash_id)),None) if trash_id is not None and str(trash_id).isdigit() else (entries[0] if len(entries)==1 else None)
            if not entry:raise ValueError('listing_not_in_trash_or_ambiguous_restore_id')
            if self.db.execute('SELECT 1 FROM drafts WHERE vin=?',(vin,)).fetchone():
                raise ValueError('active_draft_exists; restore_blocked')
            row=json.loads(entry['draft_json']);url=row['published_url'];lid=facebook_listing_id(url)
            for existing in self.db.execute('SELECT vin,published_url FROM drafts WHERE published_url<>""'):
                if existing['vin']!=vin and facebook_listing_id(existing['published_url'])==lid:
                    raise ValueError('facebook_listing_id_already_linked_to_another_vehicle')
            self.backup()
            self.db.execute('BEGIN IMMEDIATE')
            try:
                cols=','.join(row.keys());marks=','.join('?' for _ in row)
                self.db.execute(f'INSERT INTO drafts({cols}) VALUES({marks})',tuple(row.values()))
                if entry['copy_saved_at']:
                    self.db.execute('INSERT INTO draft_copy_locks(vin,saved_at) VALUES(?,?)',(vin,entry['copy_saved_at']))
                self.db.execute('DELETE FROM listing_trash WHERE id=?',(entry['id'],))
                self._event('local_facebook_listing_restored_from_trash',vin,listing_id=lid)
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK');raise
            return self.state()

    def export_audit(self):
        with self.lock:
            return {'generated_at':utc(), 'state': self.state(),
                    'quarantine': [dict(row) for row in self.db.execute('SELECT * FROM quarantined ORDER BY id DESC LIMIT 500')]}

    def verify_integrity(self):
        with self.lock:
            return self.db.execute('PRAGMA integrity_check').fetchone()[0]
