"""Consent-based local Chrome browser collector. No site access workaround.

An unpacked Chrome extension opens a VDP as an ordinary visible browser page,
collects its rendered DOM and returns only the requested dealer information.
Each snapshot is partial, never an authoritative vehicle-stock feed.
"""
from __future__ import annotations
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

from core import SOURCES
USED_SOURCES=('toyota_used','mitsubishi_used')
LIVE_INVENTORY_INDEX={'toyota_used':'https://www.hamptontoyota.com/used-inventory/index.htm',
                      'mitsubishi_used':'https://www.hamptonmitsubishi.com/used-inventory/index.htm'}
MAX_LIVE_SCAN=850
MAX_INDEX_PAGES=35
WORKER_LIMITS=(2,4,6,8,10,12,16,20)
READER_REVISION='R59'

from dealer_site_scraper import allowed_vehicle_url, parse_vehicle_page, parse_basic_vehicle_url, ScanControl


class BasicRun(ScanControl):
    """LR-009: the single owner of a historical (Basic) discovery run.

    It holds the dealer-scan slot from admission until its worker has made its
    last write and closed its browser. Stop asks it to end; it does not release it.
    """
    def __init__(self, run_id, sources, mode):
        super().__init__()
        self.id = run_id
        self.sources = list(sources)
        self.mode = mode
        self.thread = None

    @property
    def state(self):
        return 'stopping' if self.stopping else 'paused' if self.paused else 'running'


from dealer_features import extract_dealer_equipment, has_explicit_carfax_one_owner


class ChromeBridge:
    def __init__(self, data_dir, store, events, scan_info, scan_lock, on_import=None):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        from refresh_policy import RefreshPolicy
        self.refresh_policy=RefreshPolicy(self.root)
        self.store = store
        self.on_import = on_import
        self.events = events
        self.scan_info = scan_info
        self.scan_lock = scan_lock
        self.lock = threading.RLock()
        self.queue = []
        self.active = None
        self.completed_samples = deque(maxlen=12)
        self.sample_run_id = None
        self.inflight = {}  # job ID -> assigned dealer task, disjoint from pending queue
        self.basic_run = None  # LR-009: active historical discovery owner, if any
        self.paused = False
        self.max_workers = 10
        self._reset_worker_budget()
        self.failures = defaultdict(int)
        self.count = defaultdict(int)
        self.last_seen = 0.
        self.dealer_engine = 'chrome'
        self.headless_seen = 0.
        self.key_path = self.root / 'chrome_bridge_key.txt'
        try:
            self.key = self.key_path.read_text('ascii').strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,80}', self.key):
                raise ValueError('invalid key')
        except (OSError, ValueError):
            self.key = secrets.token_urlsafe(36)
            # Preserve key between restarts. Do not copy it into scan logs.
            fd = os.open(str(self.key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='ascii') as f:
                f.write(self.key)
        self.run_id = None
        self.dispatch_hold = False  # LR-009: admitted run waits for its coordinator
        self.started = 0.
        self.totals = defaultdict(int)
        # Separate verification ledger. Explicit detail repair refreshes dealer
        # records; stock availability and Facebook publication remain independent.
        self.mode = 'scan'
        self.discovery_limits={}
        self.discovered_urls={}
        self.inventory_pages={}
        self.inventory_counts={}
        self.quick_scan=False
        self.quick_existing_paths=set()
        self.verify_repair=False
        self.verify_path = self.root / 'last_live_verify_report.json'
        self.verify = {'running': False, 'total': 0, 'checked': 0, 'matched': 0,
                       'review': 0, 'unreachable': 0, 'inconclusive': 0,
                       'findings': [], 'started_at': None, 'finished_at': None,
                       'availability_verified': False}
        try:
            previous = json.loads(self.verify_path.read_text('utf-8'))
            if isinstance(previous, dict):
                previous['running'] = False
                if previous.get('finished_at') is None and previous.get('started_at'):
                    previous['interrupted'] = True
                self.verify.update(previous)
        except (OSError, ValueError, TypeError):
            pass

        self._restore_scan()

    def _checkpoint_scan(self):
        with self.lock:
            attrs=['mode','run_id','totals','count','failures','discovery_limits','discovered_urls','inventory_pages','inventory_counts','quick_scan','quick_existing_paths','verify_repair','verify','saved_discovery_links']
            data={k:getattr(self,k,{}) for k in attrs}
            data['jobs']=list(self.inflight.values())+self.queue
            data['provisional']=bool(self.dispatch_hold)  # LR-009: coordinator not started yet
            data['scan_info']=dict(self.scan_info)
            raw=json.dumps(data,default=lambda x:list(x) if isinstance(x,set) else str(x))
            if raw==getattr(self,'_last_checkpoint',None):return
            path=self.root/'pending_dealer_scan.json';temp=path.with_suffix('.tmp')
            temp.write_text(raw,encoding='utf-8');os.replace(temp,path);self._last_checkpoint=raw

    def _restore_scan(self):
        path=self.root/'pending_dealer_scan.json'
        try:
            data=json.loads(path.read_text('utf-8'))
            jobs=data.get('jobs',[])
            if not jobs:return
            if data.get('provisional'):
                self._discard_provisional(data)
                return
            seen=set();self.queue=[]
            for job in jobs:
                if not isinstance(job,dict) or job.get('id') in seen:continue
                if job.get('source') not in SOURCES:continue
                seen.add(job['id']);job.pop('_lease_at',None);job.pop('_worker_epoch',None);self.queue.append(job)
            if not self.queue:return
            for key in ['mode','run_id','discovery_limits','inventory_counts','quick_scan','verify_repair','saved_discovery_links']:
                if key in data:setattr(self,key,data[key])
            for key in ['totals','count','failures']:setattr(self,key,defaultdict(int,data.get(key,{})))
            for key in ['discovered_urls','inventory_pages']:setattr(self,key,{k:set(v) for k,v in data.get(key,{}).items()})
            self.quick_existing_paths=set(data.get('quick_existing_paths',[]))
            self.verify.update(data.get('verify',{}));self.scan_info.update(data.get('scan_info',{}))
            self.paused=True;self.started=time.monotonic()
            if self.mode=='verify':self.verify['running']=True
            else:self.scan_info['running']=True
        except (OSError,ValueError,TypeError,KeyError):return

    def authorized(self, key):
        return bool(key and secrets.compare_digest(str(key), self.key))

    def connected(self):
        return time.monotonic() - self.last_seen < 85

    def dealer_connected(self):
        return (time.monotonic() - self.headless_seen < 85 if self.dealer_engine == 'headless'
                else self.connected())

    # ---- LR-009: one owner for the dealer-scan slot -------------------------
    def _dealer_slot_busy(self):
        """Caller holds self.lock. True while any incompatible dealer run owns the slot.

        A queued, paused, resuming or stopping run still owns its work.
        """
        return bool(self.basic_run is not None or self.scan_info.get('running') or self.inflight
                    or self.queue or self.verify.get('running'))

    def reserve_basic(self, sources, mode='basic'):
        """Atomically admit one historical discovery run, or refuse it."""
        from core import utc
        with self.lock:
            if self.verify.get('running'):
                raise ValueError('live_verification_running; wait for Chrome Reader to finish')
            if self._dealer_slot_busy():
                raise ValueError('another_scan_already_running')
            run = BasicRun(secrets.token_hex(8), sources, mode)
            self.basic_run = run
            with self.scan_lock:
                self.scan_info.update(running=True, current='', completed=[], errors=[], results={},
                    progress={}, events=[], samples={}, sources=list(sources), started_at=utc(),
                    eta_seconds=None, section_durations={}, mode=mode, stopped=False, stopping=False,
                    failed=False, run_id=run.id, committed=[], stopped_sources=[])
            return run

    def basic_owner(self, run):
        """True while ``run`` still owns the slot (checked before every catalog commit)."""
        with self.lock:
            return self.basic_run is run

    def release_basic(self, run, elapsed_seconds=None, failed=None):
        """Release the slot. Only the owning worker, or a failed launch, may do this.

        The final event and diagnostics are written before release, under the
        same lock that admission uses, so a new run can never be overwritten.
        """
        with self.lock:
            if self.basic_run is not run:
                return False
            stopped = run.stopping
            with self.scan_lock:
                self.scan_info.update(running=False, current='', eta_seconds=None, stopping=False,
                                      stopped=stopped, failed=bool(failed))
                if elapsed_seconds is not None:
                    self.scan_info['elapsed_seconds'] = elapsed_seconds
                if failed:
                    self.scan_info['errors'].append({'source': '', 'reason': str(failed)[:300]})
                if stopped:
                    self.scan_info['errors'].append({'source': '', 'reason': 'USER_STOPPED_SCAN; previously saved catalog preserved'})
                committed = len(self.scan_info.get('committed', []))
                errors = len(self.scan_info.get('errors', []))
            if stopped:
                self.events('', 'FINISH', f'Historical discovery stopped by user: {committed} section(s) saved; nothing else written')
            elif failed:
                self.events('', 'FINISH', 'Historical discovery failed: '+str(failed)[:160])
            else:
                self.events('', 'FINISH', f'Scan ended: {committed} sections saved, {errors} failed')
            self._write_diagnostics()
            self.basic_run = None
            return True

    def hold_dispatch(self):
        """Hold dispatch for the run about to be admitted until its coordinator starts.

        Caller holds full_lock. While held, ``next()`` hands out no job, so a
        ready Reader cannot import anything for an operation that may still
        fail to start. Refuses (like ``start``) when another run owns the slot.
        """
        with self.lock:
            if self._dealer_slot_busy():
                raise ValueError('another_scan_already_running')
            self.dispatch_hold = True

    def release_dispatch(self):
        """End the hold. The checkpoint stops marking the work provisional."""
        with self.lock:
            self.dispatch_hold = False
            self._try_checkpoint()

    def _try_checkpoint(self):
        """Best-effort checkpoint for admission/rollback paths (LR-009).

        Memory is already correct when this runs. If the saved queue cannot
        be written, the previous file stays; any of this run's jobs in it were
        written while dispatch was held, so they are marked provisional and a
        restart discards them instead of resuming them.
        """
        try:
            self._checkpoint_scan()
            return True
        except OSError as exc:
            self.events('', 'CHECKPOINT_WRITE_FAILED',
                        'Saved scan queue could not be updated ('+type(exc).__name__+'); '
                        'work that never started is still discarded after a restart')
            return False

    def _discard_provisional(self, data):
        """Restore path: the app stopped before this operation's coordinator started.

        Its queued work was never released for dispatch, so it is not resumed.
        The operation is shown as failed (scan) or interrupted (verification).
        """
        from core import utc
        reason = ('COORDINATOR_NEVER_STARTED: LotRadar restarted before this operation started; '
                  'its queued work was discarded and nothing was dispatched')
        self.run_id = data.get('run_id')
        self.mode = data.get('mode', 'scan')
        if self.mode == 'verify':
            self.verify.update(data.get('verify', {}))
            self.verify.update(running=False, interrupted=True, partial_coverage=True, finished_at=utc(), notice=reason)
            self._save_verify()
        else:
            info = dict(data.get('scan_info', {}))
            info.update(running=False, current='', eta_seconds=None, failed=True, launch_failed=self.run_id)
            info['errors'] = list(info.get('errors', [])) + [{'source': '', 'reason': reason}]
            self.scan_info.update(info)
        self._try_checkpoint()

    def abort_reader_run(self, run_id, reason):
        """Roll back an admitted Reader run whose coordinator never started.

        Only the active run identified by ``run_id`` is touched; a finished or
        newer run is left alone. Nothing is imported or marked sold. Memory is
        rolled back first; the checkpoint is then rewritten (best effort, see
        ``_try_checkpoint``), so a restart cannot resume the failed operation.
        """
        from core import utc
        with self.lock:
            if self.basic_run is not None or run_id is None or self.run_id != run_id:
                return False
            reason = str(reason)[:300]
            if self.mode == 'verify':
                if not self.verify.get('running'):
                    return False
                self.queue.clear();self.inflight.clear();self.paused=False;self._reset_worker_budget()
                self.verify.update(running=False, finished_at=utc(), interrupted=True, partial_coverage=True,
                                   notice='Did not start: '+reason+'; nothing was checked.')
                self._save_verify()
                self.events('', 'FINISH', 'Check did not start: '+reason[:160])
            else:
                if not self.scan_info.get('running'):
                    return False
                self.queue.clear();self.inflight.clear();self.paused=False;self._reset_worker_budget()
                with self.scan_lock:
                    self.scan_info.update(running=False, current='', eta_seconds=None, failed=True, launch_failed=run_id)
                    self.scan_info.setdefault('errors', []).append({'source': '', 'reason': reason})
                self.events('', 'FINISH', 'Scan did not start: '+reason[:160])
                self._write_diagnostics()
            self.dispatch_hold = False
            self._try_checkpoint()
            return True

    def _write_diagnostics(self):
        try:
            with self.scan_lock:
                snapshot = json.loads(json.dumps(self.scan_info))
            dest = self.root/'last_website_scan_diagnostics.json'
            stage = dest.with_suffix('.new')
            stage.write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
            stage.replace(dest)
        except OSError:
            pass

    def _control_basic(self, run, action):
        """Caller holds self.lock. Route Pause/Resume/Stop to the historical worker."""
        if action == 'stop':
            if not run.stopping:  # A repeated Stop is harmless.
                run.stop()
                with self.scan_lock:
                    self.scan_info.update(stopping=True)
                self.events('', 'BASIC_STOPPING', 'Stopping: the current dealer request may finish; nothing new starts and no unsaved section is written')
        elif action == 'pause':
            if not run.stopping and not run.paused:
                run.pause()
                self.events('', 'BASIC_PAUSE', 'Paused historical discovery at the next safe point')
        elif action == 'resume':
            if run.paused:
                run.resume()
                self.events('', 'BASIC_RESUME', 'Resumed historical discovery')
        return self.control_status()

    def scan_state(self):
        """Truthful public state: running, paused, stopping, verifying, stopped, failed, finished, idle."""
        with self.lock:
            run = self.basic_run
            if run is not None:
                return run.state
            if self.mode == 'verify' and self.verify.get('running'):
                return 'paused' if self.paused else 'verifying'
            if self.scan_info.get('running'):
                return 'paused' if self.paused else 'running'
            if self.scan_info.get('stopped'):
                return 'stopped'
            if self.scan_info.get('failed') and (self.scan_info.get('mode') == 'basic'
                                                 or self.scan_info.get('launch_failed') == self.run_id):
                return 'failed'
            return 'finished' if self.scan_info.get('completed') else 'idle'

    def start(self, catalog, sources, limit, skip_existing=False, discover_live=False):
        if not 1 <= limit <= MAX_LIVE_SCAN: raise ValueError('invalid_chrome_scan_limit')
        if not sources or any(src not in USED_SOURCES for src in sources):
            raise ValueError('invalid_chrome_sources')
        with self.lock:
            if self._dealer_slot_busy():
                raise ValueError('another_scan_already_running')
            self.quick_scan=bool(skip_existing and discover_live)
            self.quick_existing_paths=set()
            if self.quick_scan:
                sources=sorted(sources,key=lambda src:src!='toyota_used')
                for vehicle in self.store.state()['vehicles']:
                    for src,record in vehicle['sources'].items():
                        url=record.get('url') or ''
                        if src in USED_SOURCES and allowed_vehicle_url(url,src):
                            self.quick_existing_paths.add(urlsplit(url).path)
            # Full inventory scan starts with live rendered inventory pages.
            # Never substitute a historical sitemap or old local DB snapshot.
            self.discovery_limits={src:limit for src in sources} if discover_live else {}
            self.discovered_urls={src:set() for src in sources}
            self.inventory_pages={src:set() for src in sources}
            self.inventory_counts={src:0 for src in sources}
            if discover_live:
                self.saved_discovery_links={src:[] for src in sources}
                for vehicle in self.store.state()['vehicles']:
                    for src,record in vehicle['sources'].items():
                        url=record.get('url') or ''
                        if src in self.saved_discovery_links and allowed_vehicle_url(url,src):
                            if not self.quick_scan:self.saved_discovery_links[src].append(url)
                jobs=[{'id':secrets.token_hex(10),'source':src,'url':LIVE_INVENTORY_INDEX[src],
                       'kind':'inventory_index'} for src in sources]
                self.mode='scan';self.queue=jobs;self.inflight.clear();self.paused=False;self._reset_worker_budget()
                self.failures=defaultdict(int);self.count=defaultdict(int);self.totals=defaultdict(int)
                self.run_id=secrets.token_hex(8);self.started=time.monotonic()
                from core import utc
                with self.scan_lock:
                    self.scan_info.update({'running':True,'current':sources[0],'completed':[],
                        'errors':[],'results':{},'events':[],'progress':{},'samples':{},
                        'sources':list(sources),'started_at':utc(),'eta_seconds':None,
                        'section_durations':{},'mode':'chrome_inventory_quick' if self.quick_scan else 'chrome_inventory_full','stopped':False})
                    for src in sources:
                        self.scan_info['progress'][src]={'phase':'discovering_live_inventory','discovered':0,
                            'visited':0,'parsed':0,'failed':0,'elapsed_seconds':0,'eta_seconds':None,
                            'website_total':None,'inventory_pages':0}
                self.events('', 'CHROME_DISCOVERY', f'Live inventory discovery started: {len(sources)} used dealer sections; max {limit} live links each')
                return {'queued':len(jobs),'phase':'discovering_live_inventory','by_source':{src:0 for src in sources},
                        'chrome_connected':self.connected(),'discover_live':True}
            # Optional incremental pass: skip already imported URLs for the
            # same dealership source. A different dealer may list the same VIN
            # with different pricing, so matching is source+URL, not VIN alone.
            existing = set()
            if skip_existing:
                for vehicle in self.store.state().get('vehicles', []):
                    for source_name, record in vehicle.get('sources', {}).items():
                        if record.get('url'):
                            existing.add((source_name, record['url']))
            skipped_existing = 0
            skipped_duplicates = 0
            seen_urls = set()
            jobs = []
            for src in sources:
                rows = catalog.get('sources', {}).get(src, {}).get('records', [])
                # Prefer links actually exposed by inventory cards, then the
                # newest model years. Historical sitemap entries stay unverified.
                rows = sorted(rows,key=lambda x:(x.get('discovery_method')=='inventory_page',
                    int(x.get('year') or 0)),reverse=True)
                source_added = 0
                for row in rows:
                    if source_added >= limit:
                        break
                    url = row.get('url', '')
                    if not (allowed_vehicle_url(url, src) and parse_basic_vehicle_url(url, src)):
                        continue
                    if (src, url) in seen_urls:
                        skipped_duplicates += 1
                        continue
                    seen_urls.add((src, url))
                    if (src, url) in existing:
                        skipped_existing += 1
                        continue
                    jobs.append({'id':secrets.token_hex(10), 'source':src, 'url':url})
                    source_added += 1
            if not jobs:
                if skipped_existing:
                    raise ValueError('all_discovered_vehicle_urls_already_imported; uncheck Skip previously imported URLs to refresh')
                raise ValueError('basic_catalog_empty; run year_make_model_scan_first')
            self.mode = 'scan'
            self.queue = jobs
            self.inflight.clear();self.paused=False;self._reset_worker_budget()
            self.failures = defaultdict(int)
            self.count = defaultdict(int)
            self.totals = defaultdict(int)
            self.run_id = secrets.token_hex(8)
            self.started = time.monotonic()
            per_source = {src:sum(1 for job in jobs if job['source']==src) for src in sources}
            with self.scan_lock:
                self.scan_info.update({'running':True,'current':jobs[0]['source'],'completed':[],
                    'errors':[],'results':{},'events':[],'progress':{},'samples':{},'sources':list(sources),
                    'started_at':None,'eta_seconds':None,'section_durations':{},'mode':'chrome','stopped':False})
                from core import utc
                self.scan_info['started_at'] = utc()
                for src in sources:
                    self.scan_info['progress'][src]={'phase':'queued_chrome','discovered':per_source[src],
                        'visited':0,'parsed':0,'failed':0,'elapsed_seconds':0,'eta_seconds':None}
            self.events('', 'CHROME_START', f'Chrome extension scan queued: {len(jobs)} pages; {skipped_existing} already imported URLs skipped; awaiting browser collector')
            return {'queued':len(jobs),'by_source':per_source,'skipped_existing':skipped_existing,
                    'skipped_duplicate_urls':skipped_duplicates,'chrome_connected':self.connected()}

    def start_single(self, vin, source=None, automatic=False):
        """Refresh exactly one stored used-vehicle VDP through Chrome."""
        from core import VIN_RE, utc
        if not VIN_RE.fullmatch(vin) or (source is not None and source not in USED_SOURCES):
            raise ValueError('invalid_used_vehicle_refresh')
        with self.lock:
            if self.verify.get('running'):
                raise ValueError('verification_running; pause/finish verification before vehicle refresh')
            if self.basic_run is not None:
                # LR-009: priority work joins only a compatible Chrome scan, never Basic.
                raise ValueError('historical_discovery_running; refresh this vehicle after it finishes or stops')
            vehicle=next((v for v in self.store.state()['vehicles'] if v['vin']==vin and any(src in USED_SOURCES for src in v['sources'])),None)
            if not vehicle:raise ValueError('unknown_used_vehicle')
            # A shared used VIN needs both dealership pages checked, not just the
            # first link. Keep identity validation per source and partial updates.
            chosen=[source] if source else [src for src in USED_SOURCES if src in vehicle['sources']]
            jobs=[]
            for src in chosen:
                rec=vehicle['sources'].get(src)
                if rec and allowed_vehicle_url(rec.get('url',''),src):
                    jobs.append({'id':secrets.token_hex(10),'source':src,
                                 'url':rec['url'],'expected_vin':vin,'priority':True,'automatic_repair':automatic})
            if not jobs:raise ValueError('saved_used_dealer_link_missing_or_invalid')
            if self.scan_info.get('running') or self.queue or self.inflight:
                for job in jobs:
                    existing=next((j for j in list(self.inflight.values())+self.queue if j['source']==job['source'] and j['url']==job['url']),None)
                    if existing:
                        if not existing.get('priority') or not automatic:existing['automatic_repair']=automatic
                        existing['priority']=True
                        existing['expected_vin']=vin
                        continue
                    self.queue.insert(0,job)
                    self.totals[job['source']]+=1
                    with self.scan_lock:
                        src=job['source']
                        if src not in self.scan_info['sources']:self.scan_info['sources'].append(src)
                        if src in self.scan_info['completed']:self.scan_info['completed'].remove(src)
                        progress=self.scan_info['progress'].setdefault(src,{'phase':'queued_chrome','discovered':0,'visited':0,'parsed':0,'failed':0,'elapsed_seconds':0,'eta_seconds':None})
                        progress['discovered']+=1
                self.events('', 'PRIORITY_REFRESH',f'Priority refresh queued for {vin}; bulk scan retained')
                return {'queued':len(jobs),'priority':True,'chrome_connected':self.connected()}
            self.discovery_limits={};self.discovered_urls={};self.inventory_pages={};self.inventory_counts={}
            self.mode='scan';self.queue=jobs;self.inflight.clear();self.paused=False;self._reset_worker_budget()
            self.failures=defaultdict(int);self.count=defaultdict(int);self.totals=defaultdict(int)
            self.run_id=secrets.token_hex(8);self.started=time.monotonic()
            progress={src:{'phase':'queued_chrome','discovered':1,'visited':0,
                           'parsed':0,'failed':0,'elapsed_seconds':0,'eta_seconds':None}
                      for src in (job['source'] for job in jobs)}
            with self.scan_lock:
                self.scan_info.update(running=True,current=jobs[0]['source'],completed=[],errors=[],results={},events=[],
                                      progress=progress,samples={},sources=list(progress),started_at=utc(),
                                      eta_seconds=None,section_durations={},mode='chrome_single',stopped=False)
            self.quick_scan=False
            self.events('', 'CHROME_REFRESH',f'Refreshing saved VIN {vin} from {len(jobs)} dealer link(s)')
            return {'queued':len(jobs),'by_source':{src:1 for src in progress},
                    'skipped_existing':0,'chrome_connected':self.connected()}

    def start_missing_photos(self, vins):
        """Photo-only jobs for a server-selected snapshot of under-ten vehicles."""
        from core import utc
        with self.lock:
            if self._dealer_slot_busy():
                raise ValueError('another_scan_already_running')
            jobs=[]
            for vehicle in self.store.state()['vehicles']:
                if vehicle['vin'] not in vins:continue
                for source in USED_SOURCES:
                    rec=vehicle['sources'].get(source) or {}
                    if allowed_vehicle_url(rec.get('url',''),source):
                        jobs.append({'id':secrets.token_hex(10),'source':source,'url':rec['url'],
                                     'expected_vin':vehicle['vin'],'photos_only':True,'manual':True,'kind':'vehicle'})
            if not jobs:return {'queued':0,'vehicles':0}
            self.quick_scan=False
            self.discovery_limits={};self.discovered_urls={};self.inventory_pages={};self.inventory_counts={}
            self.mode='scan';self.queue=jobs;self.inflight.clear();self.paused=False;self._reset_worker_budget()
            self.failures=defaultdict(int);self.count=defaultdict(int);self.totals=defaultdict(int)
            self.run_id=secrets.token_hex(8);self.started=time.monotonic()
            sources=list(dict.fromkeys(j['source'] for j in jobs))
            progress={src:{'phase':'fetching_missing_photos','discovered':sum(j['source']==src for j in jobs),
                'visited':0,'parsed':0,'failed':0,'elapsed_seconds':0,'eta_seconds':None} for src in sources}
            with self.scan_lock:
                self.scan_info.update(running=True,current=sources[0],completed=[],errors=[],results={},events=[],
                    progress=progress,samples={},sources=sources,started_at=utc(),eta_seconds=None,
                    section_durations={},mode='chrome_missing_photos',stopped=False)
            self.events('','PHOTO_FETCH_START',f'{len(vins)} vehicles below 10 usable downloaded photos; {len(jobs)} dealer galleries queued')
            return {'queued':len(jobs),'vehicles':len(set(j['expected_vin'] for j in jobs))}

    def _reset_worker_budget(self):
        self.worker_epoch=getattr(self,'worker_epoch',0)+1
        self.effective_workers=2
        self.worker_pressure=0
        self.worker_healthy=0
        self.worker_ramp_at=time.monotonic()
        self.worker_throttled=False
        self.system_load={'available':False}
        self.performance_reason='Waiting for PC load measurements'
        self.load_bad=0
        self.load_good=0
        self.rate_baseline=None
        self.rate_check_at=0

    def _resource_ceiling(self):
        return 20 if self.system_load.get('available') and self.load_good>=3 else 10

    def observe_system_load(self, reading):
        with self.lock:
            self.system_load=dict(reading)
            if not reading.get('available'):
                self.performance_reason='PC load unavailable; automatic ceiling 10'
                self.load_good=0
                return
            bad=(reading['cpu_percent']>=90 or reading['memory_percent']>=90 or reading['available_gb']<1.5)
            healthy=(reading['cpu_percent']<75 and reading['memory_percent']<85 and reading['available_gb']>=2)
            self.load_bad=self.load_bad+1 if bad else 0
            self.load_good=self.load_good+1 if healthy else 0
            now=time.monotonic()
            if self.load_bad>=2 and self.effective_workers>2 and now>=self.worker_ramp_at:
                self.effective_workers-=2
                self.worker_epoch+=1;self.worker_throttled=True
                self.worker_healthy=0;self.worker_ramp_at=now+12;self.completed_samples.clear()
                self.performance_reason='Reduced workers: high CPU or memory pressure'
                self.events('','RESOURCE_THROTTLE',self.performance_reason)
            elif healthy:self.performance_reason='PC has headroom; browser timing controls ramp-up'
            else:
                self.worker_healthy=0
                if not bad:self.worker_ramp_at=max(self.worker_ramp_at,now+5)
                self.performance_reason='Holding worker count while PC is busy'
            samples=self.completed_samples
            if len(samples)>=8 and samples[-1]-samples[0]>=8 and now>=self.rate_check_at:
                rate=(len(samples)-1)/(samples[-1]-samples[0])
                if self.rate_baseline and self.effective_workers>self.rate_baseline[0] and rate<self.rate_baseline[1]*.9:
                    self.effective_workers=max(2,self.rate_baseline[0])
                    self.worker_epoch+=1;self.worker_throttled=True;self.worker_ramp_at=now+45
                    self.performance_reason='Reduced workers: more workers did not improve recent throughput'
                    self.events('','THROUGHPUT_HOLD',self.performance_reason)
                    self.completed_samples.clear()
                else:self.rate_baseline=(self.effective_workers,rate)
                self.rate_check_at=now+15

    def _observe_worker_load(self, job, payload):
        if self.paused or job.get('_worker_epoch')!=self.worker_epoch:
            return
        lag=payload.get('reader_lag_ms')
        if type(lag) is not int or not 0<=lag<=60000:
            return
        outcome=payload.get('outcome')
        now=time.monotonic()
        if lag>=250 or outcome in ('reader_tab_open_failed','reader_browser_error','page_timeout'):
            self.worker_pressure+=1
            self.worker_healthy=0
            if self.worker_pressure>=2 and self.effective_workers>2:
                self.effective_workers-=2
                self.worker_epoch+=1
                self.worker_throttled=True
                self.worker_pressure=0
                self.worker_ramp_at=now+12
                self.completed_samples.clear()
                self.events('', 'CHROME_THROTTLE',f'Browser slowdown: using up to {self.effective_workers} dealer tabs')
        elif lag<=100 and outcome in ('ok','inventory_index') and (not self.system_load.get('available') or self.load_good>=3):
            self.worker_pressure=0
            self.worker_healthy+=1
            if (self.worker_healthy>=4 and now>=self.worker_ramp_at
                and self.effective_workers<min(self.max_workers,4 if self.mode=='verify' else self._resource_ceiling()) and self.queue):
                samples=self.completed_samples
                if len(samples)>=3 and samples[-1]-samples[0]>=3:
                    self.rate_baseline=(self.effective_workers,(len(samples)-1)/(samples[-1]-samples[0]))
                self.effective_workers+=2
                self.worker_epoch+=1
                self.worker_throttled=self.worker_throttled and self.effective_workers<self.max_workers
                self.worker_healthy=0
                self.worker_ramp_at=now+5
                self.completed_samples.clear()
                self.events('', 'CHROME_RAMP',f'Browser responsive: using up to {self.effective_workers} dealer tabs')
        else:
            self.worker_pressure=0
            self.worker_healthy=0

    def control(self, action, workers=None):
        """Token-authorized user controls; never retroactively imports canceled work."""
        from core import utc
        with self.lock:
            run = self.basic_run
            if run is not None and action in ('pause', 'resume', 'stop'):
                return self._control_basic(run, action)
            if action == 'workers':
                if type(workers) is not int or workers not in WORKER_LIMITS:
                    raise ValueError('Choose 2, 4, 6, 8, 10, 12, 16, or 20 dealer workers.')
                if workers!=self.max_workers:
                    self.max_workers=workers
                    self.effective_workers=min(workers,self.effective_workers)
                    self.worker_epoch+=1
                    self.worker_throttled=False
                    self.worker_pressure=self.worker_healthy=0
                    self.worker_ramp_at=time.monotonic()
                    self.completed_samples.clear()
            elif action == 'pause':
                if not (self.scan_info.get('running') or self.verify.get('running')):
                    raise ValueError('no_active_scan_to_pause')
                self.paused=True
                self.events('', 'CHROME_PAUSE', 'Paused: active vehicle pages may finish; no new tabs will open')
            elif action == 'resume':
                if not (self.scan_info.get('running') or self.verify.get('running')):
                    raise ValueError('no_paused_scan_to_resume')
                self.paused=False
                self.completed_samples.clear()
                self.events('', 'CHROME_RESUME', 'Resumed browser scan')
            elif action == 'stop':
                if not (self.scan_info.get('running') or self.verify.get('running') or self.queue or self.inflight):
                    return self.control_status()
                self.queue.clear();self.inflight.clear();self.paused=False;self._reset_worker_budget()
                if self.mode=='verify':
                    self.verify['running']=False
                    self.verify['finished_at']=utc()
                    self.verify['interrupted']=True
                    self.verify['partial_coverage']=True
                    self.verify['notice']='Stopped by user; incomplete checks are not evidence of sold inventory.'
                    self._save_verify()
                else:
                    with self.scan_lock:
                        self.scan_info['stopped']=True
                        self.scan_info['running']=False
                        self.scan_info['current']=''
                        self.scan_info['eta_seconds']=None
                        self.scan_info['errors'].append({'source':'','reason':'USER_STOPPED_SCAN; partial inventory preserved'})
                    self.events('', 'CHROME_STOP', 'Stopped by user; results already imported remain; no further imports')
            else:
                raise ValueError('unknown_scan_control_action')
            return self.control_status()

    def _paused_view(self):
        run = self.basic_run
        return run.paused if run is not None else self.paused

    def control_status(self):
        with self.lock:
            run = self.basic_run
            return {'ok': True, 'running':bool(run is not None or self.scan_info.get('running') or self.verify.get('running')),
                    'paused':self._paused_view(),'stopping':bool(run is not None and run.stopping),
                    'state':self.scan_state(),'historical':run is not None,
                    'workers':self.max_workers,'effective_workers':self.effective_workers,
                    'throttled':self.worker_throttled,'inflight':len(self.inflight),
                    'queued':len(self.queue),'mode':self.mode,'connected':self.dealer_connected()}

    def scan_timing(self):
        """Estimate only outstanding dealer detail jobs from observed throughput."""
        with self.lock:
            run = self.basic_run
            if run is not None:
                return {'state':run.state if run.state != 'running' else 'discovering','seconds':None}
            if not (self.verify.get('running') if self.mode=='verify' else self.scan_info.get('running')):
                return {'state':'idle','seconds':None}
            if self.paused:
                return {'state':'paused','seconds':None}
            if not self.dealer_connected():
                return {'state':'disconnected','seconds':None}
            pending=self.queue+list(self.inflight.values())
            if any(job.get('kind')=='inventory_index' for job in pending):
                return {'state':'discovering','seconds':None}
            samples=self.completed_samples
            if (not pending or self.sample_run_id!=self.run_id or len(samples)<3
                or time.monotonic()-samples[-1]>45 or samples[-1]-samples[0]<3):
                return {'state':'measuring','seconds':None}
            seconds=round(len(pending)*(samples[-1]-samples[0])/(len(samples)-1))
            return {'state':'estimated','seconds':max(1,seconds)}

    def console_snapshot(self):
        """Read-only, bounded active/queued job summary; no secrets or cookies."""
        from urllib.parse import urlsplit,unquote
        with self.lock:
            def summarize(job):
                src=job.get('source','')
                vin=job.get('vin','')
                kind=job.get('kind','vehicle')
                tail=unquote(urlsplit(job.get('url') or '').path.rsplit('/',1)[-1])[:64]
                return {'source':src,'vin':vin,'kind':kind,'vehicle':tail}
            return {'system_load':getattr(self,'system_load',{}),'performance_reason':getattr(self,'performance_reason',''),
                'worker_limit':self.max_workers,'effective_workers':self.effective_workers,
                'throttled':self.worker_throttled,'paused':self._paused_view(),
                'connected':self.dealer_connected(),'mode':self.mode,'state':self.scan_state(),
                'running':bool(self.basic_run is not None or self.scan_info.get('running') or self.verify.get('running')),
                'active':[summarize(j) for j in list(self.inflight.values())[:10]],
                'waiting':[summarize(j) for j in self.queue[:12]],
                'active_count':len(self.inflight),'waiting_count':len(self.queue)}

    def recover_jobs(self):
        """Recover abandoned Chrome jobs even when the reader stops polling."""
        from core import utc
        with self.lock:
            if self.basic_run is not None:
                return  # LR-009: Basic has no Reader jobs; nothing to recover or finalize.
            now=time.monotonic()
            for job_id,job in list(self.inflight.items()):
                if now-job.get('_lease_at',now)<=120:
                    continue
                if not job.get('_retried') and self.dealer_connected():
                    self.inflight.pop(job_id)
                    retry={k:v for k,v in job.items() if k!='_lease_at'}
                    retry.update(id=secrets.token_hex(10),_retried=True)
                    self.queue.insert(0,retry)
                    self.events(job['source'],'CHROME_RETRY','Reader did not return a result. Retrying once.')
                else:
                    self.events(job['source'],'CHROME_FAILED','Chrome Reader did not return a result. Saved inventory preserved.')
                    self.submit({'id':job_id,'url':job['url'],'outcome':'page_timeout'})
            if self.queue and not self.inflight and not self.paused and not self.dealer_connected():
                started=self.started
                if now-started>120:
                    self.events('','CHROME_FAILED','Chrome Reader disconnected before returning results. Reconnect and try again.')
                    self.control('stop')
            if self._remaining():
                return
            if self.mode=='verify' and self.verify.get('running'):
                self.verify.update(running=False,interrupted=True,partial_coverage=True,finished_at=utc())
                self._save_verify()
            elif self.scan_info.get('running') and str(self.scan_info.get('mode','')).startswith('chrome'):
                with self.scan_lock:
                    self.scan_info['errors'].append({'source':'','reason':'Chrome Reader ended without reporting all results. Refresh again.'})
                self.events('','CHROME_FAILED','Chrome Reader ended without reporting all results. Refresh again.')
                self._finalize()

    def next(self, consumer='chrome'):
        with self.lock:
            if consumer != self.dealer_engine:
                return {'job':None,'running':False,'dealer_engine':self.dealer_engine}
            if consumer == 'chrome':
                self.last_seen=time.monotonic()
            else:
                self.headless_seen=time.monotonic()
            if self.basic_run is not None:
                # LR-009: historical discovery owns the slot. An idle Reader poll
                # is not evidence that it finished; never finalize it here.
                return {'job':None,'waiting':True,**self.control_status()}
            if self.dispatch_hold:
                # LR-009: the coordinator of this run has not started yet.
                return {'job':None,'running':True,'waiting':True,**self.control_status()}
            running = self.verify.get('running') if self.mode == 'verify' else self.scan_info.get('running')
            if not running:
                return {'job':None,'running':False,'connected':True, **self.control_status()}
            self.recover_jobs()
            if not (self.verify.get('running') if self.mode == 'verify' else self.scan_info.get('running')):
                return {'job':None, **self.control_status()}
            if self.mode=='scan':
                kept=[]
                for candidate in self.queue:
                    reason='' if candidate.get('kind')=='inventory_index' or candidate.get('link_only') else self.refresh_policy.skip(candidate)
                    if reason:
                        self.events(candidate['source'],'REFRESH_SKIP',candidate.get('expected_vin',candidate['url'])+': '+reason)
                        with self.scan_lock:
                            p=self.scan_info.get('progress',{}).get(candidate['source'],{})
                            p['skipped_existing']=p.get('skipped_existing',0)+1
                            p['visited']=p.get('visited',0)+1
                    else:kept.append(candidate)
                self.queue=kept
                if not self.queue and not self.inflight:
                    for src in self.scan_info.get('sources',[]):
                        if src not in self.scan_info.get('completed',[]):self._finish_source(src)
                    self._finalize()
                    return {'job':None,'running':False,**self.control_status()}
            now=time.monotonic()
            priority_positions=[i for i,j in enumerate(self.queue) if j.get('priority')]
            if not priority_positions and (any(j.get('priority') for j in self.inflight.values()) or getattr(self,'priority_photos_pending',lambda:False)()):
                return {'job':None,'running':True,'waiting':True,'yielding_to_priority':True,**self.control_status()}
            if (self.paused and not priority_positions) or len(self.inflight)>=min(self.effective_workers,4 if self.mode=='verify' else self._resource_ceiling()) or not self.queue:
                return {'job':None,'running':True,'connected':True,'waiting':True,
                        **self.control_status()}
            by_source=defaultdict(int)
            for running_job in self.inflight.values():
                by_source[running_job['source']]+=1
            # Keep queue order within each dealer while giving the less busy
            # dealer the next slot. A dealer can use spare slots on its own.
            positions=priority_positions or list(range(len(self.queue)))
            if not priority_positions and self.mode=='scan' and self.quick_scan:
                toyota=[i for i in positions if self.queue[i]['source']=='toyota_used']
                if toyota:positions=toyota
                elif any(j['source']=='toyota_used' for j in self.inflight.values()):
                    return {'job':None,'running':True,'waiting':True,**self.control_status()}
            position=min(positions,key=lambda i:by_source[self.queue[i]['source']])
            job=self.queue.pop(position)
            job['_lease_at']=now
            job['_worker_epoch']=self.worker_epoch
            job['_run_id']=self.run_id  # LR-009: a transport failure is reported against this run only
            self.inflight[job['id']]=job
            if self.mode=='scan':self.events(job['source'],'CHROME_OPEN',job['url'])
            return {'job':dict(job),'running':True,'connected':True,
                    'remaining':len(self.queue)+len(self.inflight), **self.control_status()}

    def _source_pending(self,source):
        return any(j['source']==source for j in self.queue) or any(j['source']==source for j in self.inflight.values())

    def _remaining(self):
        return len(self.queue)+len(self.inflight)

    def _finish_source(self, source, aborted=False):
        with self.scan_lock:
            if source not in self.scan_info['completed']:
                self.scan_info['completed'].append(source)
                self.scan_info['results'][source] = {
                    'live_discovered':len(self.discovered_urls.get(source,set())),
                    'website_total':self.inventory_counts.get(source) or None,
                    'coverage_incomplete':bool(self.inventory_counts.get(source) and len(self.discovered_urls.get(source,set()))<self.inventory_counts[source]),
                    'accepted': self.count[source], 'parsed':self.count[source],
                    'skipped_existing':self.scan_info['progress'].get(source,{}).get('skipped_existing',0),
                    'coverage':dict(self.scan_info['progress'].get(source,{}).get('coverage',{})),
                    'failed':self.failures[source], 'partial':True,
                    'browser_collected':True, 'availability_verified':False}
        self.events(source, 'CHROME_SECTION_END',
                    f'{self.count[source]} VIN records; {self.failures[source]} failed; '+
                    ('access denied' if aborted else 'finished'))

    def _finalize(self):
        if self.basic_run is not None:
            return  # LR-009: a Chrome path never finalizes a historical run it does not own.
        with self.scan_lock:
            self.scan_info['running'] = False
            self.scan_info['current'] = ''
            self.scan_info['eta_seconds'] = None
            self.scan_info['elapsed_seconds'] = round(time.monotonic()-self.started)
        self.events('', 'FINISH', 'Chrome scan finished; manually verify vehicle availability before posting')
        self._write_diagnostics()

    def _submit_index(self, payload, job):
        """Accept inventory links from the rendered *current* dealer index.

        No VIN or stock inference from the index; VDPs are parsed separately.
        """
        source=job['source']
        url=job['url']
        seen_pages=self.inventory_pages[source]
        seen_pages.add(url)
        reported=payload.get('outcome')
        if reported!='inventory_index':
            self.failures[source]+=1
            with self.scan_lock:
                self.scan_info['errors'].append({'source':source,'reason':'LIVE_INVENTORY_PAGE_UNREADABLE'})
            detail=str(payload.get('detail') or '').replace('\n',' ').replace('\r',' ')[:120]
            self.events(source,'DISCOVERY_FAILED',(str(reported)[:60]+(' · '+detail if detail else ''))[:185])
        else:
            value=payload.get('website_total')
            if isinstance(value,int) and 0<value<3000:
                self.inventory_counts[source]=max(self.inventory_counts[source],value)
            urls=payload.get('urls') or []
            if not isinstance(urls,list):urls=[]
            appended=0
            limit=self.discovery_limits[source]
            for candidate in urls[:3000]:
                if not isinstance(candidate,str) or len(candidate)>1000 or len(self.discovered_urls[source])>=limit:continue
                if (candidate in self.discovered_urls[source] or
                    not allowed_vehicle_url(candidate,source) or
                    not parse_basic_vehicle_url(candidate,source)):
                    continue
                self.discovered_urls[source].add(candidate)
                if self.quick_scan and urlsplit(candidate).path in self.quick_existing_paths:
                    with self.scan_lock:
                        progress=self.scan_info['progress'][source]
                        progress['skipped_existing']=progress.get('skipped_existing',0)+1
                    continue
                # New URLs keep the full collection path at both dealers.
                self.queue.append({'id':secrets.token_hex(10),'source':source,'url':candidate,'kind':'vehicle'})
                appended+=1
            next_page=payload.get('next_url')
            if (isinstance(next_page,str) and next_page not in seen_pages and
                len(seen_pages)<MAX_INDEX_PAGES and self._valid_index_page(next_page,source)):
                self.queue.insert(0,{'id':secrets.token_hex(10),'source':source,
                                     'url':next_page,'kind':'inventory_index'})
            with self.scan_lock:
                status=self.scan_info['progress'][source]
                status.update(phase='reading_vehicles' if self.discovered_urls[source] else 'discovering_live_inventory',
                              discovered=len(self.discovered_urls[source]),
                              website_total=self.inventory_counts[source] or None,
                              inventory_pages=len(seen_pages))
            diagnostic=str(payload.get('detail') or '').replace('\n',' ').replace('\r',' ')[:120]
            self.events(source,'INVENTORY_DISCOVERED',f'Found {len(self.discovered_urls[source])} distinct current-page vehicle links; +{appended} this page; website count {self.inventory_counts[source] or "unknown"}'+(' · '+diagnostic if diagnostic else ''))
        if not any(item['kind']=='inventory_index' and item['source']==source for item in self.queue):
            saved_urls=dict.fromkeys(self.saved_discovery_links.pop(source,[]))
            missing=[link for link in saved_urls if link not in self.discovered_urls[source]]
            probes=missing[:MAX_LIVE_SCAN]
            for link in probes:
                self.queue.append({'id':secrets.token_hex(10),'source':source,'url':link,
                                   'kind':'vehicle','link_only':True})
            if probes:
                with self.scan_lock:
                    progress=self.scan_info['progress'][source]
                    progress['discovered']+=len(probes)
                    progress['saved_link_probes']=len(probes)
                self.events(source,'CHECK_SAVED_LINKS',f'Checking {len(probes)} saved links absent from the current inventory pages')
            if len(probes)<len(missing):
                with self.scan_lock:
                    self.scan_info['errors'].append({'source':source,'reason':'SAVED_LINK_PROBE_LIMIT_REACHED'})
        for src in self.scan_info['sources']:
            if src not in self.scan_info['completed'] and not self._source_pending(src):
                if not self.discovered_urls.get(src):
                    with self.scan_lock:self.scan_info['errors'].append({'source':src,'reason':'NO_LIVE_VEHICLE_LINKS; saved inventory preserved'})
                self._finish_source(src)
        if self._remaining():
            with self.scan_lock:self.scan_info['current']=self.queue[0]['source'] if self.queue else next(iter(self.inflight.values()))['source']
        else:self._finalize()
        return {'ok':True,'discovered':len(self.discovered_urls[source]),'remaining':self._remaining()}

    @staticmethod
    def _valid_index_page(url, source):
        from urllib.parse import urlsplit
        expected=urlsplit(LIVE_INVENTORY_INDEX[source]);actual=urlsplit(url)
        return (actual.scheme=='https' and actual.hostname==expected.hostname and
                actual.path.rstrip('/')==expected.path.rstrip('/') and
                not actual.username and not actual.password and len(url)<1000)

    def submit(self, payload):
        with self.lock:
            job = self.inflight.get(str(payload.get('id','')))
            if not job or payload.get('url') != job['url']:
                raise ValueError('no_matching_active_chrome_job')
            self.inflight.pop(job['id'],None)  # A retry or late canceled result cannot import twice.
            self._observe_worker_load(job,payload)
            if self.mode == 'verify' and job.get('kind') == 'verify':
                return self._submit_verify(payload, job)
            if job.get('kind') == 'inventory_index':
                return self._submit_index(payload, job)
            source = job['source']
            reported = str(payload.get('outcome','error'))[:30]
            result = None
            failure = None
            stage = 'snapshot'
            if job.get('link_only'):
                failure=None if reported=='ok' else reported
            elif reported == 'ok':
                raw = payload.get('html')
                text = payload.get('text','')
                if not isinstance(raw,str) or not 100<=len(raw)<=1_500_000 or not isinstance(text,str) or len(text)>100_000:
                    failure = 'invalid_dom_snapshot'
                else:
                    try:
                        result = parse_vehicle_page(raw,job['url'],source,rendered_text=text)
                        stage = 'identity'
                        url_id = parse_basic_vehicle_url(job['url'],source)
                        if not url_id or (result['year'] != url_id['year'] or
                            result['make'].casefold() != url_id['make'].casefold() or
                            result['model'].casefold() != url_id['model'].casefold()):
                            raise ValueError('vehicle_identity_does_not_match_requested_url: expected '+
                                             f"{url_id['year']} {url_id['make']} {url_id['model']}"+
                                             ' read '+f"{result['year']} {result['make']} {result['model']}")
                        if job.get('expected_vin') and result['vin'] != job['expected_vin']:
                            raise ValueError('refresh_vin_mismatch; existing record preserved')
                        stage = 'equipment'
                        result['features'] = extract_dealer_equipment(text, limit=220)
                        result['carfax_one_owner'] = has_explicit_carfax_one_owner(text)
                        # Browsing a detail page does NOT verify current lot stock.
                        result['availability'] = 'pending'
                        result['images_approved'] = source in USED_SOURCES
                        gallery_expected=payload.get('gallery_expected')
                        if type(gallery_expected) is int and 1 <= gallery_expected <= 999:
                            result['photo_gallery_expected']=gallery_expected
                        if job.get('photos_only'):
                            with self.store.lock:
                                previous=dict(self.store._lookup(result['vin'],source,require_confirmed=False))
                            fresh_images=result.get('images') or []
                            fresh_lead=result.get('dealer_lead_photo')
                            expected=result.get('photo_gallery_expected')
                            previous['price']=previous.get('price_cents')/100 if previous.get('price_cents') is not None else None
                            previous['images']=fresh_images
                            previous['dealer_lead_photo']=fresh_lead or previous.get('dealer_lead_photo','')
                            if expected:previous['photo_gallery_expected']=expected
                            result=previous
                            if expected and len(fresh_images)<expected:
                                self.events(source,'PHOTO_GALLERY_INCOMPLETE',f"{result['vin']}: collected {len(fresh_images)}/{expected} photo links; gallery still incomplete")
                        stage = 'database import'
                        import_response = self.store.import_feed(source,'json',
                            json.dumps({'source':source,'vehicles':[result]}),complete=False,preserve_gallery=True,scan_id=self.run_id)
                        if not import_response.get('accepted'):
                            raise ValueError('feed_import_rejected')
                        self.count[source] += 1
                        if job.get('photos_only'):self.refresh_policy.record_photos(source,job['url'])
                        else:self.refresh_policy.record(source,job['url'],True)
                    except (ValueError, TypeError) as ex:
                        result = None
                        failure = f'{stage} rejected: {str(ex)[:120]}'
                    except Exception as ex:
                        # Keep the scan moving and log the failing stage without
                        # copying page HTML or arbitrary exception data.
                        result = None
                        failure = f'{stage} failed: {type(ex).__name__}'
                    if result is not None:
                        if self.on_import:
                            try:
                                with self.store.lock:
                                    result['images']=self.store._lookup(result['vin'],source,require_confirmed=False)['images']
                                if result['images']:
                                    if job.get('photos_only'):
                                        self.on_import(result['vin'],source,result['images'],force=True)
                                    else:self.on_import(result['vin'],source,result['images'])
                                    self.events(source,'PHOTO_CACHE_QUEUED',
                                        f"{len(result['images'])} images queued for local preview cache")
                            except Exception as exc:
                                self.events(source,'PHOTO_CACHE_ERROR',type(exc).__name__)
                        gallery_info=str(payload.get('detail') or '').replace('\n',' ').replace('\r',' ')[:120]
                        self.events(source,'CHROME_PARSED',f'Saved VIN {result["vin"]}; STOCK {result.get("stock") or "missing"}; '+
                            f'{len(result.get("images") or [])} photo links'+(' · '+gallery_info if gallery_info else ''))
            else:
                reason=re.sub(r'[^a-z0-9_]', '', reported.lower()) or 'unknown'
                failure=reason if reason in ('access_denied','page_unavailable','page_timeout') else 'browser read failed: '+reason
            if reported!='ok' or result is not None or job.get('link_only'):
                outcome=('unavailable' if reported=='dealer_link_unavailable' else
                         'reachable' if result is not None or (job.get('link_only') and reported=='ok') else 'check_failed')
                self.store.record_link_check(source,job['url'],outcome)
                if outcome=='unavailable':
                    self.events(source,'DEALER_LINK_UNAVAILABLE','Dealer page is missing; review under Out of stock.')
            if failure:
                self.refresh_policy.record(source,job['url'],False)
                self.failures[source] += 1
                self.events(source,'CHROME_FAILED',failure)
            with self.scan_lock:
                p=self.scan_info['progress'][source]
                p['phase']='reading_chrome'
                p['visited'] += 1
                if result is not None:
                    if self.sample_run_id!=self.run_id:
                        self.completed_samples.clear()
                        self.sample_run_id=self.run_id
                    if not self.paused:
                        self.completed_samples.append(time.monotonic())
                    coverage=p.setdefault('coverage',{})
                    checks={'price':bool(result.get('price')), 'mileage':result.get('mileage') not in (None,''),
                            'stock':bool(result.get('stock')), 'equipment':bool(result.get('features')),
                            'specifications':bool(result.get('specifications')), 'photo_links':bool(result.get('images'))}
                    expected=result.get('photo_gallery_expected')
                    checks['gallery_complete']=bool(expected and len(result.get('images') or [])>=expected)
                    checks['gallery_incomplete']=bool(expected and len(result.get('images') or [])<expected)
                    for field,found in checks.items():
                        coverage[field]=coverage.get(field,0)+int(found)
                p['parsed'] = self.count[source]
                p['failed'] = self.failures[source]
                p['elapsed_seconds'] = round(time.monotonic()-self.started)
                total=sum(x['discovered'] for x in self.scan_info['progress'].values())
                visited=sum(x['visited'] for x in self.scan_info['progress'].values())
                rate=(time.monotonic()-self.started)/max(1,visited)
                self.scan_info['eta_seconds'] = round(rate*(total-visited)) if visited else None
                p['eta_seconds'] = round(rate*max(0,p['discovered']-p['visited']))
            # Stop on two consecutive access denials without extracting a VIN.
            if failure in ('access_denied','page_unavailable'):
                self.totals[source]+=1
            else:
                self.totals[source]=0
            # Preflight: stop an entirely unreadable section after three
            # consecutive failures, even if there was no explicit 403 text.
            if not self._source_pending(source) and self.count[source]==0 and (self.failures[source]>=4 or self.totals[source]>=3):
                self.queue=[x for x in self.queue if x['source']!=source]
                with self.scan_lock:
                    self.scan_info['errors'].append({'source':source, 'reason':'CHROME_NO_READABLE_VDPS: normal Chrome could not extract a VIN in the sampled pages'})
                self._finish_source(source,aborted=True)
            if not self._source_pending(source) and source not in self.scan_info['completed']:
                if self.count[source]==0 and not any(e.get('source')==source for e in self.scan_info['errors']):
                    with self.scan_lock:
                        self.scan_info['errors'].append({'source':source,'reason':'ZERO_VALID_CHROME_VINS: no usable VDP records'})
                self._finish_source(source)
            # Empty sources not represented in queue also finish.
            for src in self.scan_info['sources']:
                if src not in self.scan_info['completed'] and not self._source_pending(src):
                    self._finish_source(src)
            if self._remaining():
                with self.scan_lock:
                    self.scan_info['current']=self.queue[0]['source'] if self.queue else next(iter(self.inflight.values()))['source']
            else:
                self._finalize()
            return {'ok':True,'parsed':bool(result),'reason':failure,'remaining':self._remaining()}

    def _save_verify(self):
        # Atomic, bounded report for reloads and failed/interrupted browser runs.
        temporary = self.verify_path.with_suffix('.json.new')
        try:
            temporary.write_text(json.dumps(self.verify, ensure_ascii=False, indent=2), 'utf-8')
            os.replace(temporary, self.verify_path)
        except OSError:
            pass

    def start_verify(self, limit=1200, repair_missing=False, *, tracked_vins=None,reuse_recent=False,probe_counterparts=None):
        """Queue *saved* dealer links, not historical sitemap candidates."""
        if not isinstance(limit, int) or not 1 <= limit <= 1200:
            raise ValueError('invalid_verify_limit')
        with self.lock:
            if self._dealer_slot_busy():
                raise ValueError('scan_or_verification_already_running')
            if probe_counterparts is None:probe_counterparts=repair_missing
            jobs, bad = [], []
            skipped_due_to_limit = 0
            skipped_recent=0
            for vehicle in self.store.state().get('vehicles', []):
                vin = str(vehicle.get('vin') or '').upper()
                if tracked_vins is not None and vin not in tracked_vins:continue
                records=dict(vehicle.get('sources', {}))
                inferred=set()
                if probe_counterparts and tracked_vins is None:
                    # Probe a missing dealer counterpart, but import only after
                    # that page returns the exact saved VIN and URL identity.
                    for target in USED_SOURCES:
                        if target in records:continue
                        origin=next((r for source,r in records.items() if source in USED_SOURCES),None)
                        if not origin:continue
                        parts=urlsplit(origin.get('url') or '')
                        candidate='https://'+urlsplit(LIVE_INVENTORY_INDEX[target]).netloc+parts.path
                        if allowed_vehicle_url(candidate,target):
                            records[target]={**origin,'url':candidate}
                            inferred.add(target)
                for src, rec in records.items():
                    if src not in USED_SOURCES:continue
                    url = rec.get('url') or ''
                    if src not in SOURCES or not allowed_vehicle_url(url, src):
                        bad.append({'vin': vin, 'source': src, 'url': str(url)[:240],
                                    'status': 'REVIEW', 'issues': ['INVALID_DEALER_LINK']})
                        continue
                    if reuse_recent and self.refresh_policy.skip({'source':src,'url':url}):
                        skipped_recent+=1
                        continue
                    if len(jobs) >= limit:
                        skipped_due_to_limit += 1
                        continue
                    jobs.append({'kind': 'verify', 'id': secrets.token_hex(10),
                                 'source': src, 'url': url, 'vin': vin,
                                 'link_only': tracked_vins is not None,
                                 'inferred_counterpart':src in inferred,
                                 'expected': {'year': rec.get('year'),
                                              'make': rec.get('make'), 'model': rec.get('model'),
                                              'stock': rec.get('stock'),
                                              'price_cents': rec.get('price_cents'),
                                              'mileage': rec.get('mileage'),
                                              'condition': vehicle.get('condition'),
                                              'photos': len(rec.get('images') or [])}})
            if skipped_recent:self.events('','VERIFY_SKIP',f'{skipped_recent} recent/cooldown dealer pages skipped; {len(jobs)} pages queued')
            if not jobs and not bad and not skipped_recent:
                raise ValueError('no_saved_vehicle_links_to_verify')
            self.quick_scan=False
            self.mode = 'verify'
            self.run_id=secrets.token_hex(8)
            self.started=time.monotonic()
            self.verify_repair=bool(repair_missing)
            self.queue = jobs
            self.inflight.clear();self.paused=False;self._reset_worker_budget()
            from core import utc
            self.verify = {'running': bool(jobs), 'total': len(jobs)+len(bad),
                           'checked': len(bad), 'matched': 0, 'review': len(bad),
                           'unreachable': 0, 'inconclusive': 0, 'findings': bad,
                           'started_at': utc(), 'finished_at': None,
                           'availability_verified': False,
                           'scope': 'tracked_listing_dealer_links' if tracked_vins is not None else 'saved_dealer_links_only',
                           'skipped_due_to_limit': skipped_due_to_limit,'skipped_recent':skipped_recent,
                           'partial_coverage': bool(skipped_due_to_limit),
                           'notice': 'Live fields compared via paired Chrome; visible page does not establish current stock. Run is PARTIAL when skipped_due_to_limit > 0.'}
            if not jobs:
                self.verify['finished_at'] = utc()
            self._save_verify()
            return self.verify_status()

    def verify_status(self):
        with self.lock:
            return json.loads(json.dumps(self.verify))

    def _submit_verify(self, payload, job):
        """Compare snapshots; explicit repair refreshes exact-identity dealer records."""
        from core import utc
        expected = job['expected']
        vin, src = job['vin'], job['source']
        reported = str(payload.get('outcome') or 'browser_error')[:30]
        issues = []
        details = {}
        status = 'MATCH'
        if reported == 'ok' and job.get('link_only'):
            details['scope']='link_reachability'
        elif reported == 'ok':
            raw, text = payload.get('html'), payload.get('text', '')
            if not isinstance(raw, str) or not 100 <= len(raw) <= 1_500_000 or not isinstance(text, str) or len(text) > 100_000:
                status, issues = 'INCONCLUSIVE', ['INVALID_PAGE_SNAPSHOT']
            else:
                try:
                    live = parse_vehicle_page(raw, job['url'], src, rendered_text=text)
                    def compare(field, old, new, severity=True):
                        if old is None or old == '':
                            issues.append('SAVED_'+field.upper()+'_MISSING')
                        elif new is None or new == '':
                            issues.append('LIVE_'+field.upper()+'_MISSING')
                        elif str(old).casefold().strip() != str(new).casefold().strip():
                            issues.append(field.upper()+'_MISMATCH')
                            details[field] = {'saved': old, 'live': new}
                    compare('vin', vin, live.get('vin'))
                    for field in ('year', 'make', 'model', 'stock'):
                        compare(field, expected.get(field), live.get(field))
                    local_price = expected.get('price_cents')
                    live_price = live.get('price')
                    # parse_vehicle_page returns USD dollars; no sale price is
                    # inferred from TSRP/MSRP alone.
                    if local_price in (None, 0):
                        issues.append('SAVED_PRICE_UNCONFIRMED')
                    elif live_price is None:
                        issues.append('LIVE_PRICE_UNCONFIRMED')
                    else:
                        try:
                            live_cents = round(float(live_price)*100)
                        except (TypeError, ValueError):
                            live_cents = None
                        if live_cents is None:
                            issues.append('LIVE_PRICE_UNCONFIRMED')
                        elif int(local_price) != live_cents:
                            issues.append('PRICE_MISMATCH')
                            details['price_cents'] = {'saved': local_price, 'live': live_cents}
                    if expected.get('condition') == 'used' or expected.get('mileage') is not None:
                        compare('mileage', expected.get('mileage'), live.get('mileage'))
                    live_photos = len(live.get('images') or [])
                    saved_photos = int(expected.get('photos') or 0)
                    details['photos'] = {'saved_links': saved_photos, 'live_links': live_photos}
                    if not saved_photos: issues.append('SAVED_PHOTOS_MISSING')
                    if not live_photos: issues.append('LIVE_PHOTOS_MISSING')
                    # Counts fluctuate with lazy gallery loading. A count drop
                    # is a warning, never proof that specific images vanished.
                    if live_photos and saved_photos and live_photos < saved_photos:
                        issues.append('FEWER_LIVE_PHOTO_LINKS')
                    if issues: status = 'REVIEW'
                    if live.get('vin')==vin and self.verify_repair:
                        # Refresh only an exact VIN and URL identity match. Preserve
                        # previously known fields when a partial page omits them.
                        try:
                            identity=parse_basic_vehicle_url(job['url'],src)
                            if not identity or any(str(live.get(k,'')).casefold()!=str(identity[k]).casefold()
                                                   for k in ('year','make','model')):
                                raise ValueError('vehicle_identity_does_not_match_requested_url')
                            with self.store.lock:
                                try:prior=self.store._lookup(vin,src,require_confirmed=False)
                                except ValueError:
                                    if not job.get('inferred_counterpart'):raise
                                    prior={}
                            live['features']=extract_dealer_equipment(text,limit=220)
                            live['carfax_one_owner']=has_explicit_carfax_one_owner(text)
                            missing=[k for k in ('stock','price','mileage','features','specifications','images')
                                     if live.get(k) in (None,'',[],{})]
                            details['missing_live_fields']=missing
                            for field in missing:
                                issue='LIVE_'+field.upper()+'_MISSING'
                                if issue not in issues:issues.append(issue)
                            for field in ('stock','mileage','features','specifications','disclaimer','dealer_lead_photo'):
                                if live.get(field) in (None,'',[],{}) and prior.get(field) not in (None,'',[],{}):
                                    live[field]=prior[field]
                            if live.get('price') in (None,'') and prior.get('price_cents') is not None:
                                live['price']=prior['price_cents']/100
                            live['availability']='pending'
                            live['images_approved']=True
                            expected_gallery=payload.get('gallery_expected')
                            if type(expected_gallery) is int and 1<=expected_gallery<=999:
                                live['photo_gallery_expected']=expected_gallery
                                if len(live.get('images') or [])<expected_gallery:
                                    issues.append('LIVE_GALLERY_INCOMPLETE')
                            imported=self.store.import_feed(src,'json',json.dumps({'source':src,'vehicles':[live]}),
                                complete=False,preserve_gallery=True,scan_id=self.run_id)
                            if not imported.get('accepted'):raise ValueError('verification_import_rejected')
                            self.refresh_policy.record(src,job['url'],True)
                            details['refreshed']=True
                            with self.store.lock:
                                images=self.store._lookup(vin,src,require_confirmed=False).get('images') or []
                            if images and self.on_import:self.on_import(vin,src,images,force=True)
                            self.events(src,'VERIFY_REFRESHED',f'{vin}: dealer details updated; {len(images)} photos checked/queued')
                            if issues:status='REVIEW'
                        except Exception as exc:
                            status='REVIEW'
                            issues.append('DETAIL_REFRESH_FAILED')
                            details['repair_error']=type(exc).__name__+': '+str(exc)[:100]
                except (ValueError, TypeError, KeyError) as exc:
                    status, issues = 'INCONCLUSIVE', ['LIVE_PARSE_FAILED']
                    details['reason'] = str(exc)[:130]
        elif reported in ('access_denied', 'page_unavailable', 'dealer_link_unavailable'):
            status, issues = 'UNREACHABLE', [reported.upper()]
        else:
            status, issues = 'INCONCLUSIVE', [reported.upper() if reported == 'page_timeout' else 'BROWSER_READ_FAILED']
        finding = {'vin': vin, 'source': src, 'url': job['url'],
                   'status': status, 'issues': issues, 'details': details,
                   'checked_at': utc(), 'availability_verified': False}
        outcome='unavailable' if reported=='dealer_link_unavailable' else 'reachable' if reported=='ok' else 'check_failed'
        self.store.record_link_check(src,job['url'],outcome)
        self.verify['findings'].append(finding)
        self.verify['checked'] += 1
        if self.sample_run_id!=self.run_id:
            self.completed_samples.clear();self.sample_run_id=self.run_id
        self.completed_samples.append(time.monotonic())
        self.events(src,'VERIFY_RESULT',f'{vin}: {status}; '+(', '.join(issues) or 'saved/live fields match'))
        key = {'MATCH': 'matched', 'REVIEW': 'review',
               'UNREACHABLE': 'unreachable', 'INCONCLUSIVE': 'inconclusive'}[status]
        self.verify[key] += 1
        if not self._remaining():
            self.verify['running'] = False
            self.verify['finished_at'] = utc()
        self._save_verify()
        return {'ok': True, 'parsed': status == 'MATCH', 'reason': status,
                'remaining': self._remaining(), 'verification': True}

    def ping(self):
        """Authenticated extension heartbeat, separate from dashboard reads."""
        with self.lock:
            self.last_seen = time.monotonic()
            return {**self.status(),'reader_revision':READER_REVISION}

    def status(self):
        with self.lock:
            return {'dealer_engine':self.dealer_engine,'dealer_connected':self.dealer_connected(),
                    'connected':self.connected(),'queued':len(self.queue),'inflight':len(self.inflight),
                    'paused':self._paused_view(),'workers':self.max_workers,'effective_workers':self.effective_workers,
                    'throttled':self.worker_throttled,
                    'running':bool(self.basic_run is not None or self.scan_info.get('running') or self.verify.get('running')),
                    'stopping':bool(self.basic_run is not None and self.basic_run.stopping),
                    'state':self.scan_state(),'historical':self.basic_run is not None,
                    'key_present':bool(self.key)}

# Snapshot queue mutations under the same reentrant lock. Completed jobs are absent.
def _durable_scan_method(method):
    def wrapped(self,*args,**kwargs):
        with self.lock:
            try:return method(self,*args,**kwargs)
            finally:self._checkpoint_scan()
    return wrapped
for _method in ('start','start_single','start_missing_photos','start_verify','control','next','submit','recover_jobs'):
    setattr(ChromeBridge,_method,_durable_scan_method(getattr(ChromeBridge,_method)))
