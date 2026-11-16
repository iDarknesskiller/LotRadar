"""Standalone local-only Marketplace Manager. No Facebook API or automatic posts.

Run from this folder: python server.py --data-dir <user-owned-dir>.
This code never contacts Facebook and never publishes a listing.
"""
from __future__ import annotations
import argparse
import json
import hashlib
import io
from zipfile import ZipFile, ZIP_DEFLATED
import copy
import os
import secrets
import re
import sys
import threading
import time
import traceback
import webbrowser
import subprocess
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from core import MarketplaceStore, utc, VIN_RE, SOURCES, facebook_listing_id
from ai_copy import generate_ai_description
from feed_sync import sync_configured
from listing_transfer import build_transfer_kit
from photo_cache import PhotoCache
from chrome_bridge import ChromeBridge, READER_REVISION
from facebook_auto import FacebookAutoQueue
from dealer_site_scraper import scan_source, scan_basic_source, enrich_basic_from_visible_text, SITES, ScanFailure, prepare as prepare_external_scan

BASE = Path(__file__).resolve().parent
STATIC = {'/photo-selection.css':'photo-selection.css','/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css'}
MIMES = {'.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.css':'text/css; charset=utf-8'}
MAX_BODY = 25_000_000
USED_SOURCES = ('toyota_used','mitsubishi_used')


def launch_form_chrome(handoff):
    candidates=[shutil.which('chrome'),shutil.which('google-chrome')]
    for root in ('LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)'):
        base=os.environ.get(root)
        if base:candidates.append(str(Path(base)/'Google/Chrome/Application/chrome.exe'))
    chrome=next((p for p in candidates if p and Path(p).is_file()),None)
    if not chrome:raise ValueError('Google Chrome was not found. Install Chrome and load LotRadar Reader first.')
    subprocess.Popen([chrome,'http://127.0.0.1:8765/#vehicle-form='+handoff],shell=False)


def outstock_recheck_targets(store):
    """Snapshot the whole Out of Stock view, ignoring UI search/page filters."""
    vins=set(store.cleanup_status())
    pairs=[]
    for vehicle in store.state().get('vehicles',[]):
        if vehicle['vin'] not in vins:continue
        draft=vehicle.get('draft') or {}
        if draft.get('status')=='USER_CONFIRMED_PUBLISHED' and draft.get('published_url'):
            pairs.append((vehicle['vin'],draft['published_url']))
    return vins,pairs


def missing_photo_targets(store, cache):
    targets=set()
    for vehicle in store.state().get('vehicles',[]):
        records=vehicle.get('sources') or {}
        source=next((src for src in USED_SOURCES if src in records),None)
        if source is None:continue
        rec=records[source]
        status=cache.status(vehicle['vin'],source,rec.get('images') or [],analyze=False)
        # Ten is the selection threshold, never the number to download.
        if status.get('usable',0)<10:targets.add(vehicle['vin'])
    return targets


def default_data_dir():
    if os.name == 'nt':
        return Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'MarketplaceScanner' / 'data'
    return Path.home() / '.marketplace_scanner' / 'data'


def create_handler(store, port, token):
    from vin_decode import VinDecoder, valid_spec
    vin_decoder=VinDecoder(store.root)
    from photo_selection import PhotoSelections
    photo_selections=PhotoSelections(store.root)
    from photo_classify import PhotoCategories, classifiable, AutoSorter
    photo_categories=PhotoCategories(store.root)
    def auto_sort_job(vin,source):
        """Sort one vehicle's photos 03+ (cached photos cost nothing). Runs on the AutoSorter thread."""
        try:
            _rev,frames,_used=export_for_preferred_dealer(vin,source,for_preview=True)
        except ValueError as exc:
            return {'classified':0,'total':0,'error':''}     # photos not ready yet: nothing to sort
        candidates=classifiable(frames)
        auto_sorter.progress(vin,source,len(photo_categories.known(candidates)),len(candidates))
        result=photo_categories.classify(candidates,progress=lambda n:auto_sorter.progress(vin,source,n,len(candidates)))
        counts={}
        for category in result['categories'].values():counts[category]=counts.get(category,0)+1
        return {'classified':len(result['categories']),'total':len(candidates),'counts':counts,'error':result['error']}
    auto_sorter=AutoSorter(auto_sort_job,enabled=photo_selections.auto_sort_enabled)
    def classify_status(vin,source):
        return {**auto_sorter.state(vin,source),'enabled':photo_selections.auto_sort_enabled(),
                'available':bool(os.environ.get('OPENAI_API_KEY','').strip())}

    scan_lock = threading.Lock()
    scan_info = {'running':False, 'current':'', 'completed':[], 'errors':[], 'results':{}, 'progress':{},
                 'events':[], 'samples':{}, 'sources':[], 'started_at':None, 'eta_seconds':None, 'section_durations':{}}
    scan_report_path = store.root / 'last_website_scan_diagnostics.json'
    catalog_path = store.root / 'basic_catalog_unverified.json'
    try:
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
        if not isinstance(catalog,dict) or catalog.get('schema')!=1:catalog={'schema':1,'sources':{}}
    except (OSError,ValueError,TypeError):
        catalog={'schema':1,'sources':{}}

    try:
        if scan_report_path.is_file():
            previous = json.loads(scan_report_path.read_text(encoding='utf-8'))
            if isinstance(previous,dict) and not previous.get('running'):
                scan_info.update(previous)
    except (OSError,ValueError,TypeError):
        pass

    def push_event(source, stage, message):
        """A factual, capped progress log; never invented code animation."""
        with scan_lock:
            item={'at':utc(), 'source':source, 'stage':stage, 'message':str(message)[:260]}
            scan_info.setdefault('events',[]).append(item)
            del scan_info['events'][:-200]

    # User has supplied standing permission for dealership photos in this used-car workflow.
    store.authorize_used_dealer_photos()
    from trade_ready import TradeReady,is_trade_in
    photo_cache = PhotoCache(store.root,restore_trade_vins={c['vin'] for c in store.state()['vehicles'] if is_trade_in(c)})
    trade_ready=TradeReady(store,photo_cache,push_event)
    card_repair_lock=threading.Lock()
    card_repair={'running':False,'checked':0,'total':0,'ready':0,'needs_review':0,'skipped':0,'repaired':0,'current':'','error':''}
    card_report_path=Path(store.root)/'business_card_diagnostic.json'
    def repair_business_cards():
        rows=[]
        push_event('', 'BUSINESS_CARD_START', 'Checking cached galleries with more than 10 downloaded photos; no downloads')
        try:
            try:previous={(r['vin'],r['source']):r for r in json.loads(card_report_path.read_text('utf-8')).get('vehicles',[])}
            except (OSError,ValueError,KeyError,TypeError):previous={}
            temp=card_report_path.with_suffix('.tmp');temp.write_text(json.dumps({'summary':dict(card_repair),'vehicles':[]}),encoding='utf-8');os.replace(temp,card_report_path)
            targets=[]
            for vehicle in store.state()['vehicles']:
                for source,record in vehicle.get('sources',{}).items():
                    if source in USED_SOURCES and record.get('images'):
                        targets.append((vehicle['vin'],source,record))
            with card_repair_lock:card_repair['total']=len(targets)
            # Focused repair is cache-only. Never join/promote the bulk photo queue.
            for vin,source,record in targets:
                if photo_cache.stopping.is_set():return
                with card_repair_lock:card_repair['current']=vin
                push_event(source,'BUSINESS_CARD_CHECK',f'{vin}: checking saved photos')
                try:snapshot=photo_cache.status(vin,source,record['images'],analyze=False)
                except Exception as exc:
                    push_event(source,'BUSINESS_CARD_ERROR',f'{vin}: {str(exc)[:160]}')
                    rows.append({'vin':vin,'source':source,'cover_ready':False,'error':str(exc)[:200]})
                    with card_repair_lock:
                        card_repair['checked']+=1;card_repair['needs_review']+=1
                    continue
                if snapshot['downloaded']<=10:
                    push_event(source,'BUSINESS_CARD_SKIP',f"{vin}: {snapshot['downloaded']} downloaded; requires 11 or more")
                    result={'vin':vin,'source':source,'downloaded':snapshot['downloaded'],
                            'cover_ready':False,'skipped':True,'reason':'requires_more_than_10_downloaded_photos'}
                    rows.append(result)
                    with card_repair_lock:
                        card_repair['checked']+=1
                        card_repair['skipped']+=1
                    continue
                def repair_signature():
                    import hashlib
                    paths=[photo_cache._directory(vin,source)/'manifest.json',photo_cache.preferences_path,
                           Path(__file__).parent/'branding'/'business_card.png',Path(__file__).parent/'branding'/'dedication.jpg']
                    versions=[]
                    for path in paths:
                        try:
                            st=path.stat();versions.append((st.st_mtime_ns,st.st_size))
                        except OSError:versions.append(None)
                    return hashlib.sha256(repr(('repair-save-cover-2',record['images'],record.get('dealer_lead_photo'),versions)).encode()).hexdigest()
                cached=previous.get((vin,source),{})
                if cached.get('cover_ready') and cached.get('repair_signature')==repair_signature():
                    push_event(source,'BUSINESS_CARD_SKIP',f'{vin}: cover already ready and unchanged')
                    result={**cached,'skipped':True,'reason':'already_ready_unchanged'}
                    rows.append(result)
                    with card_repair_lock:
                        card_repair['checked']+=1;card_repair['ready']+=1;card_repair['skipped']+=1
                    continue
                try:
                    result=photo_cache.business_card_diagnostic(vin,source,record['images'],record.get('dealer_lead_photo'))
                    if result['cover_ready']:
                        cover=result['first_export_url']
                        current=photo_cache.preferences().get('covers',{}).get(vin+':'+source)
                        if current!=cover:
                            photo_cache.set_cover(vin,source,cover,record['images'])
                            result['cover_saved']=True
                            push_event(source,'BUSINESS_CARD_SAVED',f'{vin}: branded cover saved as photo 1')
                            with card_repair_lock:card_repair['repaired']+=1
                        else:
                            result['cover_saved']=False
                            push_event(source,'BUSINESS_CARD_READY',f'{vin}: branded cover already selected')
                    result['repair_signature']=repair_signature()
                    result['operation']='cached_photos_only'
                    if not result['cover_ready']:
                        result['next_step']='No usable branded cover in downloaded photos; use Refresh vehicle or Fetch missing photos separately.'
                        push_event(source,'BUSINESS_CARD_REVIEW',f'{vin}: no usable branded cover found among cached photos; see diagnostic report')
                except Exception as exc:
                    result={'vin':vin,'source':source,'cover_ready':False,'error':str(exc)[:200]}
                    push_event(source,'BUSINESS_CARD_ERROR',f'{vin}: {str(exc)[:160]}')
                rows.append(result)
                with card_repair_lock:
                    card_repair['checked']+=1
                    card_repair['ready' if result['cover_ready'] else 'needs_review']+=1
                    report={'summary':dict(card_repair),'vehicles':rows}
                temp=card_report_path.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2),encoding='utf-8');os.replace(temp,card_report_path)
        except Exception as exc:
            with card_repair_lock:card_repair['error']=str(exc)[:200]
            push_event('','BUSINESS_CARD_ERROR',str(exc)[:200])
        finally:
            with card_repair_lock:
                card_repair['running']=False
                card_repair['current']=''
                summary=dict(card_repair)
            push_event('','BUSINESS_CARD_FINISHED',f"{summary['checked']}/{summary['total']} checked; {summary['repaired']} covers saved; {summary['ready']} ready; {summary['skipped']} skipped; {summary['needs_review']} need review")
            temp=card_report_path.with_suffix('.tmp');temp.write_text(json.dumps({'summary':summary,'vehicles':rows},indent=2),encoding='utf-8');os.replace(temp,card_report_path)

    # R58: one active vehicle's export-copy bytes, held for two minutes.
    # Both gallery preview and ZIP download read this SAME prepared export;
    # never mutate or write cached original dealership photographs.
    preview_lock=threading.RLock()
    preview_cache={'key':None,'files':None,'timestamp':0.0,'size':0}
    def prepared_photo_export(vin,source,record,*,for_preview=False):
        import hashlib
        urls=record.get('images') or []
        lead_url=record.get('dealer_lead_photo')
        # Invalidate preview when cover/settings or downloaded image manifest changes.
        # No dealer-photo pixels are read merely to compute this fingerprint.
        photo_dir=photo_cache._directory(vin,source)
        manifest_file=photo_dir/'manifest.json'
        settings_file=photo_cache.preferences_path
        def version(path):
            try:
                st=path.stat()
                return (st.st_mtime_ns,st.st_size)
            except OSError:return (0,0)
        version_data=('business-card-repair-1',vin,source,tuple(urls),lead_url,version(manifest_file),version(settings_file))
        fingerprint=hashlib.sha256(repr(version_data).encode('utf-8')).hexdigest()[:24]
        with preview_lock:
            now=time.monotonic()
            if preview_cache['key']==fingerprint and now-preview_cache['timestamp']<120 and preview_cache['files'] is not None:
                files=preview_cache['files']
            else:
                files=photo_cache.prepared_export_frames(vin,source,urls,lead_url=lead_url)
                # The initial R61 screening can update the per-VIN manifest
                # while export bytes are prepared. Use the POST-preparation
                # manifest version, otherwise later frame GETs can 409 even
                # though the user hasn't changed anything.
                fingerprint=hashlib.sha256(repr(('business-card-repair-1',vin,source,tuple(urls),lead_url,
                    version(manifest_file),version(settings_file))).encode('utf-8')).hexdigest()[:24]
                size=sum(len(data) for _,data,_ in files)
                # Never cache an enormous photo set in RAM. Export itself can
                # still proceed; preview returns an honest size limitation.
                if size<=90*1024*1024:
                    preview_cache.update(key=fingerprint,files=files,timestamp=now,size=size)
                else:
                    preview_cache.update(key=None,files=None,timestamp=0.0,size=0)
                    if for_preview:raise ValueError('preview_too_large; use_Download_photos')
            if not files:raise ValueError('no_export_ready_photos; download_and_screen_vehicle_photos_first')
            return fingerprint,files
    # R26.1: photo diagnostics are local, bounded, and contain no secrets.
    photo_errors=[]
    photo_error_lock=threading.Lock()
    def photo_error(where, exc):
        note={'at':utc(),'stage':where,'error_type':type(exc).__name__,
              'error':str(exc)[:180]}
        with photo_error_lock:
            photo_errors.append(note)
            del photo_errors[:-25]
        # Crash investigation without logging API keys, VINs, request bodies or photos.
        try:
            log_file=store.root/'marketplace_photo_errors.log'
            if not log_file.exists() or log_file.stat().st_size<100_000:
                with log_file.open('a',encoding='utf-8') as out:
                    out.write(json.dumps(note,ensure_ascii=False)+'\n')
        except OSError:pass

    def safe_photo_status(vin,source,urls,*,fast=False):
        try:return photo_cache.status(vin,source,urls,analyze=not fast)
        except Exception as exc:
            photo_error('photo_status',exc)
            # Emergency read-only fallback: inventory can still render.
            return {'vin':vin,'source':source,'total':len(urls) if isinstance(urls,list) else 0,
                    'downloaded':0,'pending':False,'usable':0,'excluded':0,
                    'photos':[],'photo_analysis_available':False,
                    'warning':'photo_analysis_unavailable'}

    def imported_photos(vin, source, urls, **kwargs):
        result=photo_cache.enqueue(vin,source,urls,**kwargs)
        vin_decoder.enqueue(vin)
        return result
    chrome_bridge = ChromeBridge(store.root,store,push_event,scan_info,scan_lock,
                                 on_import=imported_photos)
    for vehicle in store.state().get('vehicles',[]):
        for source, record in vehicle.get('sources',{}).items():
            specs=record.get('specifications') or {}
            if source in USED_SOURCES and any(not valid_spec(key,specs.get(key)) for key in ('body_style','fuel_type')):
                vin_decoder.enqueue(vehicle['vin'])
                break
    def refresh_ready_gallery(vin,source):
        try:
            result=chrome_bridge.start_single(vin,source,automatic=True)
            if not result.get('queued'):return
            while not photo_cache.stopping.is_set():
                with chrome_bridge.lock:
                    pending=any(j.get('expected_vin')==vin and j['source']==source for j in chrome_bridge.queue+list(chrome_bridge.inflight.values()))
                if not pending:return
                photo_cache.stopping.wait(.5)
        except Exception as exc:push_event(source,'TRADE_READY_REFRESH_ERROR',f'{vin}: {str(exc)[:150]}')
    trade_ready.refresh_gallery=refresh_ready_gallery
    chrome_bridge.priority_photos_pending=photo_cache.has_priority_work
    photo_cache.foreground_scan_pending=lambda:any(j.get('priority') for j in chrome_bridge.queue[:]+list(chrome_bridge.inflight.copy().values()))
    from headless_dealer import HeadlessDealer
    chrome_bridge.dealer_engine = 'chrome' if os.environ.get('LOTRADAR_DEALER_ENGINE') == 'chrome' else 'headless'
    headless_dealer = HeadlessDealer(chrome_bridge)
    facebook_auto = FacebookAutoQueue()
    facebook_form_drafts = {}
    facebook_form_lock = threading.Lock()
    full_lock=threading.RLock()
    full_job={'running':False,'phase':'idle','started_at':None,'finished_at':None,
              'scan':None,'verify':None,'facebook':None,'error':None,'partial':False}

    def full_job_status():
        with full_lock:return json.loads(json.dumps(full_job))

    def full_scan_worker(tracked_pairs=None):
        """Advance three explicit, bounded browser jobs in sequence.

        This cannot silently mark a vehicle sold or claim all pages were imported.
        """
        try:
            def change(**items):
                with full_lock:full_job.update(items)
            def wait_stage(pred,timeout_seconds):
                stop=time.monotonic()+timeout_seconds
                while time.monotonic()<stop:
                    if pred():return True
                    time.sleep(1.5)
                return False
            if tracked_pairs is None:
                if not wait_stage(lambda:not scan_info.get('running'),2*60*60):
                    change(phase='failed',partial=True,error='dealer_inventory_scan_timed_out')
                    return
                if full_job_status().get('cancel_requested') or scan_info.get('stopped'):
                    change(phase='stopped',partial=True,error='User stopped Full Scan; subsequent stages not started.',finished_at=utc())
                    return
                with scan_lock:
                    result=json.loads(json.dumps(scan_info.get('results',{})))
                    errors=list(scan_info.get('errors',[]))
                coverage_gap=any(bool(r.get('coverage_incomplete')) for r in result.values())
            try:
                with full_lock:
                    if full_job['cancel_requested']:
                        change(phase='stopped',partial=True,finished_at=utc())
                        return
                    if tracked_pairs is None:
                        change(phase='verifying_inventory',scan={'results':result,'errors':errors},partial=bool(errors or coverage_gap))
                        chrome_bridge.start_verify(1200,repair_missing=True,reuse_recent=True,probe_counterparts=False)
                    elif full_job['verify'] and full_job['verify'].get('error'):
                        raise ValueError(full_job['verify']['error'])
                if not wait_stage(lambda:not chrome_bridge.verify_status().get('running'),2*60*60):
                    raise ValueError('dealer_verification_timed_out')
                vr=chrome_bridge.verify_status()
                change(verify={'checked':vr.get('checked'),'total':vr.get('total'),
                     'unreachable':vr.get('unreachable'),'inconclusive':vr.get('inconclusive'),
                     'skipped_due_to_limit':vr.get('skipped_due_to_limit')},
                     partial=bool(full_job_status()['partial'] or vr.get('skipped_due_to_limit') or vr.get('unreachable') or vr.get('inconclusive')))
            except ValueError as exc:
                change(verify={'error':str(exc)[:180]},partial=True)
            verify_failed=bool((full_job_status().get('verify') or {}).get('error'))
            if full_job_status().get('cancel_requested') or (not verify_failed and chrome_bridge.verify_status().get('interrupted')):
                change(phase='stopped',partial=True,error='User stopped Full Scan; Facebook check not started.',finished_at=utc())
                return
            change(phase='checking_facebook')
            try:
                pairs=tracked_pairs
                if pairs is None:
                    pairs=[(vehicle['vin'],draft['published_url']) for vehicle in store.state()['vehicles']
                           if (draft:=vehicle.get('draft') or {}).get('status')=='USER_CONFIRMED_PUBLISHED'
                           and draft.get('published_url')]
                if pairs:
                    ready=facebook_auto.preflight()
                    if not ready['ready']:
                        raise ValueError('facebook_reader_not_ready: '+ready['reason'])
                    with full_lock:
                        if full_job['cancel_requested']:
                            change(phase='stopped',partial=True,finished_at=utc())
                            return
                        fb=facebook_auto.bulk_enqueue(pairs)
                    if fb['active']:
                        if not wait_stage(lambda:not facebook_auto.bulk_status().get('active'),60*60):
                            facebook_auto.cancel_bulk();raise ValueError('facebook_bulk_timeout')
                    fb=facebook_auto.bulk_status()
                else:
                    fb={'total':0,'checked':0,'captured':0,'failed':0,'skipped':0,'active':False}
                change(facebook=fb,partial=bool(full_job_status()['partial'] or fb.get('failed') or fb.get('expired') or fb.get('cancelled') or fb.get('skipped')))
            except ValueError as exc:
                change(facebook={'error':str(exc)[:180]},partial=True,error=str(exc)[:180])
            with full_lock:
                if full_job['cancel_requested']:
                    change(phase='stopped',partial=True,error='Full Scan stopped before completion',finished_at=utc())
                else:
                    change(phase='completed',finished_at=utc())
        except Exception as exc:
            with full_lock:full_job.update(phase='failed',partial=True,error=f'{type(exc).__name__}: {str(exc)[:180]}',finished_at=utc())
        finally:
            with full_lock:full_job['running']=False


    def current_photo_record(vin,source):
        if not VIN_RE.fullmatch(str(vin or '')) or source not in SOURCES:
            raise ValueError('invalid_photo_identity')
        vehicle=next((v for v in store.state()['vehicles'] if v['vin']==vin),None)
        if not vehicle or source not in vehicle['sources']:
            raise ValueError('unknown_vehicle_source')
        return vehicle['sources'][source]

    def export_for_preferred_dealer(vin, requested, *, for_preview=False):
        """Exactly one dealer supplies photos; never merge photo sets or dealer facts.

        Toyota is preferred when linked to this VIN. A Mitsubishi fallback is
        used only when Toyota has no export-ready photographs. Errors other
        than missing/unprepared photos are never silently hidden.
        """
        vehicle=next((v for v in store.state().get('vehicles',[]) if v['vin']==vin),None)
        if not vehicle:raise ValueError('unknown_vehicle')
        sources=vehicle.get('sources') or {}
        if requested not in ('toyota_used','mitsubishi_used') or requested not in sources:
            raise ValueError('unknown_vehicle_source')
        order=['toyota_used','mitsubishi_used'] if 'toyota_used' in sources else ['mitsubishi_used']
        errors=[]
        for src in order:
            if src not in sources:continue
            try:
                _revision,photos=prepared_photo_export(vin,src,sources[src],for_preview=for_preview)
                if photos:return _revision,photos,src
            except ValueError as exc:
                # Preserve independent source identity and do not mask severe errors.
                if not str(exc).startswith(('no_export_ready_photos','no_image_urls')):
                    raise
                errors.append(str(exc))
        raise ValueError('no_export_ready_photos; download_car_photos_from_Toyota_or_Mitsubishi_first')

    def photo_source_with_links(vin,requested):
        """Preferred used dealer source that actually has saved photo links (Toyota first)."""
        if requested not in USED_SOURCES:raise ValueError('invalid_photo_identity')
        current_photo_record(vin,requested)    # validates VIN and used source
        vehicle=next(v for v in store.state()['vehicles'] if v['vin']==vin)
        for src in ('toyota_used','mitsubishi_used'):
            if src in vehicle['sources'] and (vehicle['sources'][src].get('images') or []):return src
        raise ValueError('no_image_urls_for_vehicle')

    def photo_failure_reason(error):
        text=str(error or '').lower()
        if not text:return 'not_downloaded'
        for needle,label in (('403','blocked_by_host'),('404','not_found'),('timeout','timeout'),('timed out','timeout'),('ssl','tls_error'),('too large','too_large'),('size','too_large'),('type','not_an_image'),('image','not_an_image')):
            if needle in text:return label
        return 'download_failed'

    def scoped_photo_progress(vin,source):
        """One canonical, source-scoped funnel: Found >= Unique >= Downloaded >= Usable."""
        if source not in USED_SOURCES:raise ValueError('invalid_photo_identity')
        record=current_photo_record(vin,source)
        raw=[u for u in (record.get('images') or []) if isinstance(u,str)]
        snap=safe_photo_status(vin,source,raw)
        photos=snap.get('photos') or []
        downloaded=int(snap.get('downloaded',0));unique=int(snap.get('total',0))
        usable=min(downloaded,int(snap.get('usable',0)))
        failures={}
        for item in photos:
            if item.get('downloaded'):continue
            if item.get('status')=='failed' or item.get('error'):
                reason=photo_failure_reason(item.get('error'));failures[reason]=failures.get(reason,0)+1
        failed=sum(failures.values())
        sort=classify_status(vin,source)
        pending=bool(snap.get('pending'))
        if not raw:stage='unavailable'
        elif pending:stage='downloading' if downloaded<unique else 'queued'
        elif sort.get('running'):stage='sorting'
        elif unique and downloaded>=unique:stage='ready'
        elif downloaded:stage='partial'
        else:stage='unavailable' if failed else 'queued'
        revision=hashlib.sha256(json.dumps([[p.get('url'),p.get('downloaded'),p.get('excluded'),p.get('status')] for p in photos]+[sort.get('classified',0),bool(sort.get('running'))],sort_keys=True).encode()).hexdigest()[:16]
        return {'ok':True,'vin':vin,'source':source,'stage':stage,'pending':pending,
                'found':len(raw),'unique':unique,'downloaded':downloaded,'usable':usable,'failed':failed,
                'failure_reasons':failures,'dealer_reported':record.get('photo_gallery_expected'),
                'discovery_shortfall':bool(record.get('photo_gallery_expected') and unique<record['photo_gallery_expected']),
                'sorting':{'running':bool(sort.get('running')),'classified':sort.get('classified',0),'total':sort.get('total',0),'error':sort.get('error','')},
                'revision':revision}

    # 1.9.13: sort photos into exterior/interior as soon as a vehicle's photo download finishes.
    # Set here, after export_for_preferred_dealer exists, so a job finishing at startup can't hit a NameError.
    photo_cache.on_finished=lambda vin,source:auto_sorter.request(vin,source)
    def verify_inventory():
        """Read-only validation of captured dealer records. No network availability claim."""
        state=store.state()
        findings=[]
        totals={'vehicles':sum(v.get('condition')=='used' for v in state.get('vehicles',[])), 'source_records':0,
                'missing_stock':0,'missing_mileage_used':0,'missing_price':0,
                'missing_photos':0,'photos_not_downloaded':0,'stale':0,'missing_model':0,'invalid_vins':0,
                'invalid_source_urls':0}
        by_source={src:{'records':0,'passing':0,'issues':0} for src in USED_SOURCES}
        for item in state.get('vehicles',[]):
            if not any(src in USED_SOURCES for src in item.get('sources',{})):continue
            vin=str(item.get('vin') or '')
            valid_vin=bool(VIN_RE.fullmatch(vin))
            for src,rec in item.get('sources',{}).items():
                if src not in USED_SOURCES:continue
                issues=[]
                totals['source_records']+=1
                if src not in by_source:
                    continue
                by_source[src]['records']+=1
                if not valid_vin:
                    issues.append('invalid_vin');totals['invalid_vins']+=1
                if not rec.get('stock'):
                    issues.append('stock');totals['missing_stock']+=1
                if item.get('condition')=='used' and rec.get('mileage') is None:
                    issues.append('mileage');totals['missing_mileage_used']+=1
                if not rec.get('price_cents'):
                    issues.append('price');totals['missing_price']+=1
                if not rec.get('images'):
                    issues.append('photos');totals['missing_photos']+=1
                elif valid_vin:
                    # Downloader verifies image signatures. Count missing local
                    # files separately from missing published photo links.
                    cache = safe_photo_status(vin,src,rec['images'])
                    uncached = cache['total'] - cache['downloaded']
                    if uncached:
                        issues.append('photo_files_not_downloaded')
                        totals['photos_not_downloaded'] += uncached
                if not rec.get('fresh',False):
                    issues.append('stale');totals['stale']+=1
                if not rec.get('model'):
                    issues.append('model');totals['missing_model']+=1
                url=rec.get('url') or ''
                if not (url.startswith('https://') and urlsplit(url).hostname in
                            ('www.hamptontoyota.com','www.hamptonmitsubishi.com')):
                    issues.append('dealer_url');totals['invalid_source_urls']+=1
                if issues:
                    by_source[src]['issues']+=1
                    if len(findings)<150:findings.append({'vin':vin,'source':src,'issues':issues})
                else:
                    by_source[src]['passing']+=1
        issues_count=sum(v['issues'] for v in by_source.values())
        with scan_lock:
            latest_scan={'running':scan_info['running'], 'completed':list(scan_info['completed']),
                         'errors':list(scan_info['errors']), 'results':dict(scan_info['results'])}
        unscanned_sources=[src for src in USED_SOURCES if not by_source[src]['records']]
        # Only inspect saved used records. One unused dealer section is not
        # evidence of invalid data in the other dealer's saved vehicles.
        passed=(totals['source_records']>0 and issues_count==0
                and not latest_scan['running'])
        return {'verified_at':utc(),'kind':'local_data_quality_only','passed':passed,
                'notice':'Checks saved USED records. Historical scan errors are shown for context but do not invalidate saved fields. Live link matching is a separate Chrome step.',
                'totals':totals, 'by_source':by_source,'unscanned_sources':unscanned_sources,'latest_scan':latest_scan,
                'findings':findings[:160]}

    def website_scan_worker(sources, photos_approved, max_vehicles, mode="basic"):
        start=time.monotonic()
        push_event('', 'START', f'User started {len(sources)} dealership sections; mode {mode}; max {max_vehicles} links per section')
        try:
            for source in sources:
                source_start=time.monotonic()
                with scan_lock:
                    scan_info['current'] = source
                push_event(source, 'CONNECT', 'Browser navigating to '+SITES[source])
                try:
                    def report(phase, **numbers):
                        visited=int(numbers.get('visited') or 0)
                        discovered=int(numbers.get('discovered') or 0)
                        eta=None
                        if visited >= 2 and discovered > visited:
                            rate=(time.monotonic()-source_start)/visited
                            eta=round(rate*(discovered-visited))
                        with scan_lock:
                            scan_info['progress'][source] = {'phase':phase, **numbers,
                                'eta_seconds':eta, 'elapsed_seconds':round(time.monotonic()-source_start)}
                            scan_info['eta_seconds']=eta
                        if phase == 'reading_vehicles':
                            url=str(numbers.get('last_url') or '')[:170]
                            status=numbers.get('last_http_status')
                            method=(f'HTTP {status} GET ' if status else 'VDP CHECK ')
                            push_event(source, 'VDP',method+url)
                            if numbers.get('last_vin'):
                                push_event(source,'PARSED', 'VIN '+str(numbers['last_vin'])+
                                    ' | STOCK '+str(numbers.get('last_stock') or 'missing')+
                                    f' | records={numbers.get("parsed",0)}')
                            else:
                                push_event(source, 'FAILED',str(numbers.get('last_failure') or 'no usable VIN')[:170])
                        elif phase in ('loading_inventory','inventory_discovered','finished','early_abort'):
                            msg=(f'{phase}: {visited}/{discovered} detail URLs, '
                                 f'{numbers.get("parsed",0)} parsed, {numbers.get("failed",0)} failed')
                            if numbers.get('last_failure'):msg+='; '+str(numbers['last_failure'])[:110]
                            push_event(source,phase.upper(),msg)
                    if mode == 'basic':
                        # Browser/sitemap link discovery only: no VDP requests, no VIN requirement.
                        output = scan_basic_source(source,max_vehicles=max_vehicles,progress=report)
                        with scan_lock:
                            # Preserve user-captured details when a subsequent scan
                            # discovers the SAME URL. Never transfer details by model
                            # name alone: many vehicles share year/make/model.
                            old_rows={r.get('url'):r for r in catalog.get('sources',{}).get(source,{}).get('records',[])}
                            for row in output.get('records',[]):
                                old=old_rows.get(row.get('url'))
                                if old and isinstance(old.get('enrichment'),dict):
                                    row['enrichment']=old['enrichment']
                            catalog['sources'][source] = output
                            scan_info['results'][source] = {
                                'catalog_candidates':output['count'], 'index_candidates':output['index_candidates'],
                                'verified':False, 'partial':True, 'accepted':0, 'parsed':0,
                                'complete_details':0, 'pending':output['count']}
                            snapshot=json.loads(json.dumps(catalog))
                        tmp=catalog_path.with_suffix('.new')
                        tmp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
                        tmp.replace(catalog_path)
                        push_event(source,'CATALOG',f'{output["count"]} URL-derived Y/M/model candidates; 0 VINs verified; no detail requests')
                    else:
                        output = scan_source(source, photos_approved=photos_approved,
                                             max_vehicles=max_vehicles, progress=report)
                        if not output['vehicles']:
                            raise ValueError('no_valid_vehicle_rows; data_untouched')
                        result=store.import_feed(source,'json',json.dumps(output),complete=False)
                        with scan_lock:
                            scan_info['results'][source] = {'accepted':result['accepted'],
                                'quarantined':result['quarantined'],
                                'failures':len(output['scraper']['failures']), 'partial':True,
                                'discovered':output['scraper']['listing_pages_discovered'],
                                'parsed':output['scraper']['detail_parsed'],
                                'complete_details':output['scraper']['complete_vehicle_records'],
                                'pending':output['scraper']['sitemap_only_pending'],
                                'discovery':output['scraper']['discovery'],
                                'first_errors':output['scraper']['failures'][:5]}
                        push_event(source,'IMPORTED',f'{result["accepted"]} valid records, {result["quarantined"]} quarantined')
                except Exception as exc:
                    with scan_lock:
                        scan_info['errors'].append({'source':source,'reason':str(exc)[:300]})
                        if isinstance(exc,ScanFailure):
                            scan_info.setdefault('samples',{})[source]=exc.samples[:5]
                    push_event(source,'FAILED',str(exc)[:220])
                with scan_lock:
                    scan_info['completed'].append(source)
                    scan_info.setdefault('section_durations',{})[source]=round(time.monotonic()-source_start,1)
        finally:
            with scan_lock:
                scan_info['running'] = False
                scan_info['current'] = ''
                scan_info['eta_seconds'] = None
                scan_info['elapsed_seconds'] = round(time.monotonic()-start)
                snapshot = dict(scan_info)
            push_event('', 'FINISH',f'Scan ended: {len(snapshot["completed"])} sections, {len(snapshot["errors"])} failed')
            with scan_lock:snapshot=dict(scan_info)
            try:
                stage = scan_report_path.with_suffix('.new')
                stage.write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
                stage.replace(scan_report_path)
            except OSError:
                pass

    def decorated_state(snapshot):
        for car in snapshot.get('vehicles',[]):
            car['posting_ready']=trade_ready.status(car)
            car['last_successful_refresh']={src:chrome_bridge.refresh_policy.get(src,rec.get('url','')).get('last_success') for src,rec in car.get('sources',{}).items() if src in USED_SOURCES}
            for source,record in car.get('sources',{}).items():
                if source in ('toyota_used','mitsubishi_used'):
                    photo_state=safe_photo_status(car['vin'],source,record.get('images') or [],fast=True)
                    record['photo_usable_indices']=[p['index'] for p in photo_state['photos']
                        if p['downloaded'] and not p['excluded']]
                    record['photo_review_preview_indices']=[p['index'] for p in photo_state['photos']
                        if p['downloaded'] and p['category']=='review' and
                        p['quality_reason'] in ('possible_dealership_banner','low_detail_review_needed')]
                    record['photo_graphic_indices']=[p['index'] for p in photo_state['photos']
                        if p['downloaded'] and p['category']=='graphic']
                    try:
                        cover_choice=photo_cache.cover_choice(car['vin'],source,record.get('images') or [],photo_state,
                                                           lead_url=record.get('dealer_lead_photo'))
                        record['photo_cover_index']=cover_choice['index']
                        record['photo_cover_manual']=bool(cover_choice.get('manual'))
                    except Exception as exc:
                        photo_error('cover_choice',exc)
                        record['photo_cover_index']=None
                        record['photo_cover_manual']=False
        return snapshot

    class Handler(BaseHTTPRequestHandler):
        server_version = 'MarketplaceScanner/1.0'
        def log_message(self, format, *args):
            # No requests, tokens or user text printed by default.
            if self.path.startswith('/api') and not self.path.startswith('/api/health'):
                return
            super().log_message(format, *args)

        def _headers(self, status, ctype='application/json; charset=utf-8', size=None, extra=None):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            if urlsplit(self.path).path.startswith('/api/chrome-bridge/') and self._ext_origin():
                self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
                self.send_header('Vary','Origin')
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Content-Type, X-SHM-Bridge-Key, X-SHM-Reader-Rev')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' https: data: blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            if size is not None:
                self.send_header('Content-Length', str(size))
            for key,value in (extra or {}).items(): self.send_header(key,value)
            self.end_headers()

        def _json(self, status, data):
            if isinstance(data,dict) and isinstance(data.get("state"),dict):
                data={**data,"state":decorated_state(data["state"])}
            raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self._headers(status, size=len(raw))
            self.wfile.write(raw)

        def _same_host(self):
            # Host pinning stops DNS rebinding into a token-bearing local service.
            return self.headers.get('Host') == f'127.0.0.1:{port}'

        def _same_origin(self):
            expected = f'http://127.0.0.1:{port}'
            origin = self.headers.get('Origin')
            site = self.headers.get('Sec-Fetch-Site')
            return self._same_host() and origin in (None, expected) and site not in ('cross-site', 'same-site')

        def _ext_origin(self):
            return bool(re.fullmatch(r'chrome-extension://[a-p]{32}',self.headers.get('Origin','')))

        def _bridge_authorized(self):
            # MV3 service-worker fetches may omit Origin entirely. The R8
            # implementation required that header, so even the correct secret
            # was rejected with chrome_extension_pairing_required. An explicit
            # non-extension Origin is NEVER allowed. Origin-less requests
            # still require the high-entropy local pairing key and pinned Host.
            origin = self.headers.get('Origin')
            return (self._same_host() and (origin is None or self._ext_origin())
                    and chrome_bridge.authorized(self.headers.get('X-SHM-Bridge-Key')))

        def do_OPTIONS(self):
            if urlsplit(self.path).path.startswith('/api/chrome-bridge/') and self._same_host() and self._ext_origin():
                return self._headers(204,size=0)
            return self._json(403,{'error':'preflight_rejected'})

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/api/chrome-bridge/next','/api/chrome-bridge/ping','/api/chrome-bridge/facebook-auto-next'):
                if not self._bridge_authorized():
                    return self._json(403,{'error':'chrome_extension_pairing_required'})
                if self.headers.get('X-SHM-Reader-Rev') != READER_REVISION:
                    return self._json(426,{'error':'reader_update_required_reload_extension'})
                return self._json(200, facebook_auto.next() if path.endswith('/facebook-auto-next') else chrome_bridge.next() if path.endswith('/next') else chrome_bridge.ping())
            if not self._same_host() or self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
                return self._json(403, {'error':'invalid_local_host_or_site'})
            path = urlsplit(self.path).path
            if path in ('/api/chrome-bridge/key','/api/chrome-bridge/dashboard'):
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                return self._json(200,{'key':chrome_bridge.key} if path.endswith('/key') else chrome_bridge.status())
            if path == '/api/facebook-auto-readiness':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                return self._json(200,facebook_auto.preflight())
            if path == '/api/dealer-connection-console':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                chrome_bridge.recover_jobs()
                with scan_lock:
                    recent=list(scan_info.get('events',[])[-200:])
                    scan_running=bool(scan_info.get('running'))
                    scan_counts={k:{x:rec.get(x,0) for x in ('phase','discovered','visited','parsed','failed','skipped_existing')}
                                  for k,rec in (scan_info.get('progress') or {}).items()}
                verify=chrome_bridge.verify_status()
                fb=facebook_auto.bulk_status()
                with facebook_auto.lock:
                    facebook_pending=[{'vin':j.get('vin',''),'state':j.get('state','')}
                                      for j in facebook_auto.jobs if j.get('state') in ('queued','checking')]
                photo_progress=photo_cache.progress()
                return self._json(200,{'ok':True,'worker':chrome_bridge.console_snapshot(),
                    'photo_downloads':photo_progress,
                    'business_card_repair':dict(card_repair),
                    'trade_ready_running':trade_ready.running,
                    'facebook_jobs':{'pending':len(facebook_pending),'items':facebook_pending[:12],
                                     'timing':facebook_auto.timing()},
                    'dealer_timing':chrome_bridge.scan_timing(),
                    'scan':{'running':scan_running,'progress':scan_counts,'recent':recent,'timing':chrome_bridge.scan_timing()},
                    'verify':{k:verify.get(k) for k in ('running','checked','total','matched','review','unreachable','inconclusive','partial_coverage')},
                    'facebook':{k:fb.get(k) for k in ('active','total','captured','failed','expired','checked')},
                    'full':{k:full_job_status().get(k) for k in ('running','phase','partial','error')}})
            if path == '/api/facebook-auto-bulk-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                return self._json(200,facebook_auto.bulk_status())
            if path == '/api/facebook-auto-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                vin=parse_qs(urlsplit(self.path).query).get('vin',[''])[0].upper()
                return self._json(200,facebook_auto.status(vin))
            if path == '/api/cleanup-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                return self._json(200,{'ok':True,'issues':store.cleanup_status()})
            if path == '/api/listing-trash':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                return self._json(200,store.listing_trash())
            if path == '/api/facebook-comparison':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                try:
                    vin=parse_qs(urlsplit(self.path).query).get('vin',[''])[0].upper()
                    return self._json(200,store.facebook_comparison(vin))
                except ValueError as exc:
                    return self._json(400,{'ok':False,'error':str(exc)})
            if path == '/api/photo-health':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                from photo_cache import pillow_available
                with photo_error_lock:recent=list(photo_errors[-10:])
                return self._json(200,{'ok':True,'pillow_available':pillow_available(),
                                       'recent_errors':recent,'fallback_enabled':True})
            if path == '/api/photo-settings':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                cfg=photo_cache.preferences()
                return self._json(200,{'ok':True,'contact_number':cfg['contact_number'],
                                       'auto_replace':cfg['auto_replace']})
            if path == '/api/photos/progress':
                if self.headers.get('X-SalesmanHub-Token') != token:return self._json(403,{'error':'session_token_required'})
                q=parse_qs(urlsplit(self.path).query)
                try:return self._json(200,scoped_photo_progress(q.get('vin',[''])[0].upper(),q.get('source',[''])[0]))
                except ValueError as exc:return self._json(400,{'error':str(exc)})
            if path == '/api/photo-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                query=parse_qs(urlsplit(self.path).query)
                try:
                    vin=query.get('vin',[''])[0].upper();source=query.get('source',[''])[0]
                    rec=current_photo_record(vin,source)
                    snapshot=safe_photo_status(vin,source,rec['images'])
                    snapshot['cover']=photo_cache.cover_choice(vin,source,rec['images'],snapshot,lead_url=rec.get('dealer_lead_photo'))
                    return self._json(200,snapshot)
                except ValueError as exc:
                    return self._json(400,{'error':str(exc)})
            if path == '/api/photos/classify':
                if self.headers.get('X-SalesmanHub-Token') != token:return self._json(403,{'error':'session_token_required'})
                q=parse_qs(urlsplit(self.path).query)
                try:
                    vin=q.get('vin',[''])[0].upper();source=q.get('source',[''])[0]
                    current_photo_record(vin,source)
                    return self._json(200,classify_status(vin,source))
                except ValueError as exc:return self._json(400,{'error':str(exc)})
            if path == '/api/photos/selection':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                q=parse_qs(urlsplit(self.path).query)
                try:
                    vin=q.get('vin',[''])[0].upper();source=q.get('source',[''])[0]
                    current_photo_record(vin,source)
                    _rev,frames,used_source=export_for_preferred_dealer(vin,source,for_preview=True)
                    candidates=classifiable(frames);known=photo_categories.known(candidates)
                    if len(known)<len(candidates):auto_sorter.request(vin,used_source)   # never sorted (e.g. downloaded before 1.9.13)
                    return self._json(200,{'ok':True,**photo_selections.get(vin,used_source,frames),'auto_groups':known,
                                           'classify_available':bool(os.environ.get('OPENAI_API_KEY','').strip()),
                                           'auto_sort':classify_status(vin,used_source)})
                except ValueError as exc:return self._json(400,{'error':str(exc)})
            if path == '/api/photos/export-preview':
                # Private per-user local data. Explicit same-origin session
                # authorization is required even for the image bytes.
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403,{'error':'session_token_required'})
                q=parse_qs(urlsplit(self.path).query)
                vin=q.get('vin',[''])[0].upper();source=q.get('source',[''])[0]
                try:
                    record=current_photo_record(vin,source)
                    revision,images,used_source=export_for_preferred_dealer(vin,source,for_preview=True)
                    if 'index' not in q:
                        # R62: distinguish missing dealer links from failed downloads
                        # and from excluded/collapsed images, without trusting a
                        # gallery headline or altering any originals.
                        source_record=current_photo_record(vin,used_source)
                        snapshot=safe_photo_status(vin,used_source,source_record.get('images') or [],fast=True)
                        counts={'links':snapshot.get('total',0),'downloaded':snapshot.get('downloaded',0),
                                'failed':sum(item.get('status')=='failed' for item in snapshot.get('photos',[])),
                                'excluded':max(0,snapshot.get('downloaded',0)-max(0,len(images)-1)),
                                'pending':bool(snapshot.get('pending'))}
                        return self._json(200,{'ok':True,'revision':revision,'count':len(images),
                            'photo_source':used_source,'photo_counts':counts,
                            'photos':[{'name':name,'kind':'dedication' if i==1 else 'vehicle',
                                       'cover':i==0,'url':url} for i,(name,_,url) in enumerate(images)]})
                    position=int(q['index'][0])
                    if position<0 or position>=len(images):
                        raise ValueError('invalid_export_preview_index')
                    if q.get('rev',[''])[0]!=revision:
                        return self._json(409,{'error':'export_preview_changed; refresh_preview'})
                    filename,data,_=images[position]
                    mime='image/png' if filename.lower().endswith('.png') else 'image/webp' if filename.lower().endswith('.webp') else 'image/jpeg'
                    self._headers(200,mime,len(data))
                    return self.wfile.write(data)
                except (ValueError,OSError) as exc:
                    return self._json(400,{'error':str(exc)[:180]})
            if path == '/api/photo':
                # Never return cached user photos to a cross-origin embedded image.
                if self.headers.get('Sec-Fetch-Site','same-origin') not in ('same-origin','none'):
                    return self._json(403,{'error':'cross_origin_photo_request_denied'})
                query=parse_qs(urlsplit(self.path).query)
                try:
                    vin=query.get('vin',[''])[0].upper();source=query.get('source',[''])[0]
                    index=int(query.get('index',['-1'])[0]);rec=current_photo_record(vin,source)
                    data,mime=photo_cache.read_photo(vin,source,index,rec['images'])
                    self._headers(200,mime,len(data))
                    return self.wfile.write(data)
                except (ValueError,OSError):
                    return self._json(404,{'error':'photo_not_cached'})
            if path == '/api/health':
                return self._json(200, {'ok': True, 'service':'Marketplace Scanner', 'local_only': True,
                                         'chrome_bridge_available': True, 'api_revision':'CHROME-R13-USED-REFRESH',
                                         'facebook_form_from_saved_draft': getattr(store,'facebook_form_from_saved_draft',False)})
            if path == '/api/bootstrap':
                return self._json(200, {'csrf': token, 'local_only':True,
                                         'facebook_publish_enabled':False, 'live_feed_configured':False})
            if path == '/api/state':
                # R21: transient photo indices are derived from local, visually
                # screened files. Never mutate inventory, VINs or the saved
                # image list during read-only rendering.
                snapshot=decorated_state(store.state())
                return self._json(200,snapshot)
            if path == '/api/full-scan-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403, {'error':'session_token_required'})
                return self._json(200,{'ok':True,'full':full_job_status()})
            if path == '/api/basic-catalog':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403, {'error':'session_token_required'})
                with scan_lock:
                    snapshot=json.loads(json.dumps(catalog))
                return self._json(200, snapshot)
            if path == '/api/live-verify-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403, {'error':'session_token_required'})
                chrome_bridge.recover_jobs()
                return self._json(200, {'ok':True, 'verification':chrome_bridge.verify_status()})
            if path == '/api/site-scan-status':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403, {'error':'session_token_required'})
                chrome_bridge.recover_jobs()
                with scan_lock:
                    snapshot=json.loads(json.dumps(scan_info))
                snapshot['timing']=chrome_bridge.scan_timing()
                return self._json(200,snapshot)
            if path == '/api/export':
                return self._json(200, store.export_audit())
            if path == '/api/transfer-kit':
                if self.headers.get('X-SalesmanHub-Token') != token:
                    return self._json(403, {'error':'session_token_required'})
                query = parse_qs(urlsplit(self.path).query)
                vin = query.get('vin',[''])[0]
                try:
                    item=next((v for v in store.state()['vehicles'] if v['vin']==vin),None)
                    chosen=(item.get('draft') or {}).get('source') if item else None
                    chosen_rec=item['sources'].get(chosen) if chosen else None
                    cached=photo_cache.cached_for_zip(vin,chosen,chosen_rec['images']) if chosen_rec else []
                    safe_urls=photo_cache.usable_urls(vin,chosen,chosen_rec['images']) if chosen_rec else []
                    raw = build_transfer_kit(store,vin,cached_photos=cached,allowed_photo_urls=safe_urls)
                except ValueError as ex:
                    return self._json(400, {'error':str(ex)})
                self._headers(200,'application/zip',len(raw))
                return self.wfile.write(raw)
            if path in STATIC:
                p = BASE / STATIC[path]
                raw = p.read_bytes()
                self._headers(200, MIMES[p.suffix], len(raw))
                return self.wfile.write(raw)
            return self._json(404, {'error':'not_found'})

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == '/api/chrome-bridge/vehicle-form':
                if not self._bridge_authorized():
                    return self._json(403,{'error':'chrome_extension_pairing_required'})
                if self.headers.get('X-SHM-Reader-Rev') != READER_REVISION:
                    return self._json(426,{'error':'reader_update_required_reload_extension'})
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
                    return self._json(415,{'error':'application_json_required'})
                try:
                    size=int(self.headers.get('Content-Length','-1'))
                    if not 1 <= size <= 512:
                        raise ValueError('Invalid vehicle form request.')
                    data=json.loads(self.rfile.read(size))
                    handoff,tab,operation=data['handoff'],data['tab_id'],data['operation']
                    if (not isinstance(handoff,str) or type(tab) is not int or tab < 0
                        or operation not in ('bind','read','claim','ready','login','failed')):
                        raise ValueError('Invalid vehicle form request.')
                    with facebook_form_lock:
                        prepared=facebook_form_drafts.get(handoff)
                        if not prepared or time.monotonic() >= prepared['expires']:
                            facebook_form_drafts.pop(handoff,None)
                            code,response=404,{'error':'Draft expired. Open a new Facebook form from LotRadar.'}
                        elif operation == 'claim':
                            claimed=bool(prepared.get('claimed'))
                            prepared['claimed']=True
                            code,response=200,{'claimed':not claimed}
                        elif operation in ('ready','login','failed') and prepared['tab']==tab:
                            prepared['result']=operation
                            code,response=200,{'ok':True}
                        elif operation == 'bind' and prepared['tab'] in (None,tab):
                            prepared['tab']=tab
                            code,response=200,{'ok':True}
                        elif operation == 'read' and prepared['tab'] == tab:
                            code,response=200,{'fields':prepared['fields']}
                        else:
                            code,response=409,{'error':'Open the Facebook form from the matching vehicle in LotRadar.'}
                    if code == 200 and operation == 'read':
                        try:
                            decoded=prepared.get('decoded') or vin_decoder.fetch_now(prepared['vin'])
                            current=store.facebook_form_fields(prepared['vin'],decoded=prepared.get('decoded'))
                            if current != prepared['fields']:
                                raise ValueError('Draft changed. Open a new Facebook form from LotRadar.')
                            response={'fields':store.facebook_form_fields(prepared['vin'],decoded=decoded)}
                        except ValueError as exc:
                            return self._json(409,{'error':str(exc)})
                    return self._json(code,response)
                except (ValueError,TypeError,KeyError):
                    return self._json(400,{'error':'Invalid vehicle form request.'})
            if path == '/api/chrome-bridge/facebook-capture':
                if not self._bridge_authorized():
                    return self._json(403,{'error':'chrome_extension_pairing_required'})
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':
                    return self._json(415,{'error':'application_json_required'})
                try:
                    size=int(self.headers.get('Content-Length','-1'))
                    if not 1<=size<=28000:raise ValueError('facebook_capture_size_invalid')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):
                        raise ValueError('facebook_capture_must_be_object')
                    if self.headers.get('X-SHM-Reader-Rev') != READER_REVISION:
                        return self._json(426,{'error':'reader_update_required_reload_extension'})
                    if 'attempt_id' in data:
                        with facebook_auto.lock:
                            facebook_auto.require_active_capture(data['attempt_id'],facebook_listing_id(data.get('url')))
                            captured=store.capture_facebook_listing(data)
                    else:
                        captured=store.capture_facebook_listing(data)
                    return self._json(200,captured)
                except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                    return self._json(400,{'ok':False,'error':str(exc)[:180]})
            if path == '/api/chrome-bridge/facebook-auto-readiness':
                if not self._bridge_authorized():
                    return self._json(403,{'error':'chrome_extension_pairing_required'})
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':
                    return self._json(415,{'error':'application_json_required'})
                try:
                    size=int(self.headers.get('Content-Length','-1'))
                    if not 1<=size<=256:raise ValueError('facebook_readiness_size_invalid')
                    data=json.loads(self.rfile.read(size))
                    return self._json(200,facebook_auto.report_reader(enabled=data.get('enabled'),permitted=data.get('permitted')))
                except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                    return self._json(400,{'ok':False,'error':str(exc)[:180]})
            if path == '/api/chrome-bridge/facebook-auto-finish':
                if not self._bridge_authorized():
                    return self._json(403,{'error':'chrome_extension_pairing_required'})
                if self.headers.get('X-SHM-Reader-Rev') != READER_REVISION:
                    return self._json(426,{'error':'reader_update_required_reload_extension'})
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':
                    return self._json(415,{'error':'application_json_required'})
                try:
                    size=int(self.headers.get('Content-Length','-1'))
                    if not 1<=size<=2000:raise ValueError('facebook_auto_result_size_invalid')
                    data=json.loads(self.rfile.read(size))
                    result=facebook_auto.finish(data.get('id'),data.get('result'),
                                                data.get('detail',''),data.get('fields',[]))
                    if result.get('state') in ('captured','failed'):
                        outcome='reachable' if result['state']=='captured' else 'unavailable' if result.get('detail')=='facebook_listing_unavailable' else 'check_failed'
                        store.record_link_check('facebook','https://www.facebook.com/marketplace/item/'+result['listing_id'],outcome)
                    return self._json(200,result)
                except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                    return self._json(400,{'ok':False,'error':str(exc)[:180]})
            if path == '/api/chrome-bridge/result':
                if not self._bridge_authorized():
                    return self._json(403,{'error':'chrome_extension_pairing_required'})
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
                    return self._json(415,{'error':'application_json_required'})
                try:
                    size=int(self.headers.get('Content-Length','-1'))
                    if not 1<=size<=1_800_000:raise ValueError('browser_result_size_invalid')
                    payload=json.loads(self.rfile.read(size))
                    if not isinstance(payload,dict):raise ValueError('browser_result_must_be_object')
                    return self._json(200,chrome_bridge.submit(payload))
                except (ValueError,TypeError,KeyError) as ex:
                    return self._json(400,{'error':str(ex)[:180]})
            if not self._same_origin():
                return self._json(403, {'error':'cross_origin_request_denied'})
            if self.headers.get('X-SalesmanHub-Token') != token:
                return self._json(403, {'error':'missing_local_session_token'})
            if self.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
                return self._json(415, {'error':'application_json_required'})
            try:
                n = int(self.headers.get('Content-Length', '-1'))
            except ValueError:
                n = -1
            if n < 1 or n > MAX_BODY:
                return self._json(413, {'error':'request_size_invalid'})
            try:
                data = json.loads(self.rfile.read(n))
                if not isinstance(data, dict):
                    raise ValueError('expected_json_object')
                path = urlsplit(self.path).path
                if path == '/api/trade-ready':
                    vins=data.get('vins')
                    if vins is not None and (not isinstance(vins,list) or any(not isinstance(v,str) for v in vins)):raise ValueError('invalid_vins')
                    return self._json(200,{'ok':True,**trade_ready.start(vins,prepare=data.get('prepare') is True)})
                if path == '/api/business-card-repair':
                    operation=data.get('operation')
                    if operation=='start':
                        with card_repair_lock:
                            if not card_repair['running']:
                                card_repair.update(running=True,checked=0,total=0,ready=0,needs_review=0,skipped=0,repaired=0,current='',error='')
                                threading.Thread(target=repair_business_cards,name='business-card-repair',daemon=True).start()
                            result=dict(card_repair)
                        return self._json(200,{'ok':True,**result})
                    if operation=='report':
                        try:report=json.loads(card_report_path.read_text('utf-8'))
                        except (ValueError,OSError):report={'summary':dict(card_repair),'vehicles':[]}
                        return self._json(200,{'ok':True,**report})
                    return self._json(200,{'ok':True,**dict(card_repair)})
                if path == '/api/photo-queue-control':
                    if data.get('action')=='clear':return self._json(200,{'ok':True,'photos':photo_cache.clear_queue()})
                    if data.get('action') not in ('pause','resume'):raise ValueError('invalid_photo_queue_action')
                    return self._json(200,{'ok':True,'photos':photo_cache.control(data['action']=='pause')})
                if path == '/api/vehicle-form-control':
                    form_handoff=str(data.get('handoff') or '')
                    with facebook_form_lock:
                        entry=facebook_form_drafts.get(form_handoff)
                        if not entry or entry['expires']<=time.monotonic():raise ValueError('Handoff expired. Retry Prepare Facebook form.')
                        operation=data.get('operation')
                        if operation=='cancel':entry['expires']=0
                        if operation=='launch' and not entry.get('launched'):
                            entry['launched']=True
                            launch_form_chrome(form_handoff)
                        return self._json(200,{'result':entry.get('result','waiting')})
                if path == '/api/prepare-vehicle-form':
                    if data.get('explicit_request') is not True:
                        raise ValueError('Prepare the draft from LotRadar.')
                    vin=str(data.get('vin') or '').upper()
                    fields=store.facebook_form_fields(vin)
                    decoded=vin_decoder.get(vin)
                    fields=store.facebook_form_fields(vin,decoded=decoded)
                    vin_decoder.enqueue(vin)
                    handoff=secrets.token_urlsafe(24)
                    with facebook_form_lock:
                        now=time.monotonic()
                        for key in list(facebook_form_drafts):
                            if facebook_form_drafts[key]['expires'] <= now:
                                del facebook_form_drafts[key]
                        if len(facebook_form_drafts) >= 100:
                            del facebook_form_drafts[next(iter(facebook_form_drafts))]
                        facebook_form_drafts[handoff]={'vin':vin,'fields':fields,'decoded':decoded,'expires':now+900,'tab':None}
                    return self._json(200,{'ok':True,'handoff':handoff})
                if path == '/api/import':
                    if data.get('source') not in USED_SOURCES:raise ValueError('used_inventory_only')
                    value = store.import_feed(data.get('source'),data.get('format'),data.get('text'),
                                              complete=(data.get('complete') is True))
                    return self._json(200, {'ok':True, 'result':value, 'state':store.state()})
                if path in ('/api/preview-external-scan', '/api/import-external-scan'):
                    # The user can transfer the successful other-scraper export
                    # without granting this local app any new website privileges.
                    prepared = prepare_external_scan(data.get('text'), data.get('format'),
                                                     data.get('fallback_source') or 'auto')
                    # Mixed old exports may contain new cars. Show and import
                    # only used records, without treating rejected new rows as stock changes.
                    dropped=sum(len(rows) for src,rows in prepared['groups'].items() if src not in USED_SOURCES)
                    prepared['groups']={src:rows for src,rows in prepared['groups'].items() if src in USED_SOURCES}
                    prepared['preview']['valid']=sum(map(len,prepared['groups'].values()))
                    prepared['preview']['rejected']+=dropped
                    prepared['preview']['by_source']={src:len(rows) for src,rows in prepared['groups'].items()}
                    if dropped:prepared['preview'].setdefault('sample_rejections',[]).append({'reason':'new_inventory_excluded', 'rows':dropped})
                    if path == '/api/preview-external-scan':
                        return self._json(200, {'ok':True,'preview':prepared['preview']})
                    if data.get('explicit_import') is not True:
                        raise ValueError('explicit_import_confirmation_required')
                    if not prepared['groups']:
                        raise ValueError('no_used_vehicle_records_to_import')
                    with scan_lock:
                        if scan_info['running']:
                            raise ValueError('cannot_import_during_website_scan')
                    outcomes = {}
                    for source, rows in prepared['groups'].items():
                        if source not in USED_SOURCES:continue
                        # Always partial: never mark a missing VIN sold or removed.
                        outcomes[source] = store.import_feed(source,'json',json.dumps({'source':source,'vehicles':rows}),complete=False)
                    return self._json(200, {'ok':True,'preview':prepared['preview'],
                        'imports':{k:{'accepted':v['accepted'],'quarantined':v['quarantined']} for k,v in outcomes.items()},
                        'state':store.state()})
                if path == '/api/enrich-basic-candidate':
                    if data.get('explicit_capture') is not True:
                        raise ValueError('explicit_page_capture_required')
                    source=data.get('source');url=data.get('url');page_text=data.get('text')
                    if not isinstance(source,str) or source not in SITES or not isinstance(url,str):
                        raise ValueError('invalid_candidate_selection')
                    with scan_lock:
                        if scan_info['running']:
                            raise ValueError('cannot_capture_during_website_scan')
                        found=next((r for r in catalog.get('sources',{}).get(source,{}).get('records',[])
                                    if r.get('url')==url),None)
                        if found is None:raise ValueError('candidate_url_not_in_basic_catalog')
                        parsed=enrich_basic_from_visible_text(page_text,found)
                        previous=copy.deepcopy(found.get('enrichment'))
                        found['enrichment']=parsed
                        try:
                            snapshot=json.loads(json.dumps(catalog))
                            stage=catalog_path.with_suffix('.new')
                            stage.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
                            stage.replace(catalog_path)
                        except Exception:
                            if previous is None:found.pop('enrichment',None)
                            else:found['enrichment']=previous
                            raise
                    return self._json(200,{'ok':True,'enrichment':parsed,
                        'notice':'Visible fields captured; vehicle still UNVERIFIED for current availability.'})
                if path == '/api/chrome-scan-control':
                    action=str(data.get('action') or '')
                    if action not in ('pause','resume','stop','workers'):
                        raise ValueError('invalid_chrome_scan_control')
                    workers=data.get('workers')
                    if action=='stop':
                        with full_lock:
                            result=chrome_bridge.control(action,workers)
                            if full_job['running']:
                                full_job['cancel_requested']=True
                                full_job['partial']=True
                                if full_job.get('phase')=='checking_facebook':
                                    facebook_auto.cancel_bulk()
                    else:
                        result=chrome_bridge.control(action,workers)
                    return self._json(200,{'ok':True,'control':result})
                if path == '/api/start-site-scan':
                    if data.get('explicit_user_request') is not True:
                        raise ValueError('explicit_scan_request_required')
                    sources = list(data.get('sources') or [])
                    if not sources or len(sources) > 2 or len(set(sources)) != len(sources) or any(x not in USED_SOURCES for x in sources):
                        raise ValueError('invalid_dealership_source_selection')
                    mode=data.get('mode','basic')
                    if mode not in ('basic','chrome','headless'):
                        raise ValueError('invalid_scan_mode')
                    limit=int(data.get('max_vehicles') or 800)
                    if not 1<=limit<=850:
                        raise ValueError('invalid_scan_limit')
                    if chrome_bridge.verify_status().get('running'):
                        raise ValueError('live_verification_running; wait for Chrome Reader to finish')
                    if mode in ('chrome','headless'):
                        headless_dealer.ensure_ready()
                        return self._json(200,{'ok':True,'started':True,
                            'chrome':chrome_bridge.start(catalog,sources,limit,
                                skip_existing=data.get('skip_existing') is True,
                                discover_live=data.get('discover_live') is True)})
                    with scan_lock:
                        if scan_info['running']:
                            raise ValueError('website_scan_already_running')
                        scan_info.update(running=True,current='',completed=[],errors=[],results={},progress={},events=[],samples={},sources=sources,started_at=utc(),eta_seconds=None,section_durations={},mode=mode)
                    thread=threading.Thread(target=website_scan_worker,
                        args=(sources,True,limit,mode),daemon=True)
                    thread.start()
                    return self._json(200, {'ok':True,'started':True})
                if path == '/api/full-scan-start':
                    if data.get('explicit_user_request') is not True:
                        raise ValueError('explicit_full_scan_request_required')
                    headless_dealer.ensure_ready()
                    if not chrome_bridge.dealer_connected():
                        raise ValueError('dealer_reader_not_connected')
                    with full_lock:
                        if full_job['running']:
                            raise ValueError('full_scan_already_running')
                        # Start first to ensure we never report an active Full Scan
                        # when the browser queue itself refused to start.
                        started=chrome_bridge.start(catalog,list(USED_SOURCES),850,
                                                     skip_existing=False,discover_live=True)
                        full_job.update(running=True,phase='scanning_inventory',operation='full_scan',
                            started_at=utc(),finished_at=None,cancel_requested=False,scan=None,verify=None,
                            facebook=None,error=None,partial=False)
                    threading.Thread(target=full_scan_worker,daemon=True,
                                     name='Marketplace-Full-Scan').start()
                    return self._json(200,{'ok':True,'full':full_job_status(),'chrome':started})
                if path == '/api/chrome-refresh-vehicle':
                    if data.get('explicit_user_request') is not True:raise ValueError('explicit_vehicle_refresh_required')
                    vin=str(data.get('vin') or '').upper()
                    headless_dealer.ensure_ready()
                    photo_cache.prioritize(vin)
                    dealer_job=chrome_bridge.start_single(vin)
                    facebook_job={'ok':True,'state':'not_linked','detail':'No linked Facebook listing; dealer refresh only.'}
                    # Keep the dealer and Facebook outcomes independent; never hide a skipped check.
                    vehicle=next((v for v in store.state()['vehicles'] if v['vin']==vin),None)
                    if vehicle and (vehicle.get('draft') or {}).get('status')=='USER_CONFIRMED_PUBLISHED':
                        try:
                            comparison=store.facebook_comparison(vin)
                            ready=facebook_auto.preflight()
                            if not ready['ready']:
                                facebook_job={'ok':True,'state':'skipped','detail':ready['reason']}
                            else:
                                facebook_job=facebook_auto.enqueue(vin,comparison['linked_url'])
                        except ValueError as exc:
                            facebook_job={'ok':True,'state':'skipped','detail':str(exc)}
                    return self._json(200, {'ok':True,'chrome':dealer_job,'facebook':facebook_job})
                if path == '/api/start-live-verify':
                    if data.get('explicit_user_request') is not True:
                        raise ValueError('explicit_live_verify_request_required')
                    headless_dealer.ensure_ready()
                    if not chrome_bridge.dealer_connected():
                        raise ValueError('dealer_reader_not_connected')
                    return self._json(200, {'ok':True,
                        'verification':chrome_bridge.start_verify(int(data.get('limit') or 1200),
                            repair_missing=data.get('repair_missing') is True)})
                if path == '/api/transfer-kit':
                    vin=str(data.get('vin') or '').upper()
                    item=next((v for v in store.state()['vehicles'] if v['vin']==vin),None)
                    chosen=(item.get('draft') or {}).get('source') if item else None
                    chosen_rec=item['sources'].get(chosen) if chosen else None
                    cached=photo_cache.prepared_for_zip(vin,chosen,chosen_rec['images'],
                        lead_url=chosen_rec.get('dealer_lead_photo')) if chosen_rec else []
                    # Only clean original URLs travel as raw links. Processed
                    # banner photos travel as new JPEG bytes, not old URLs.
                    safe_urls=photo_cache.usable_urls(vin,chosen,chosen_rec['images']) if chosen_rec else []
                    raw=build_transfer_kit(store,vin,cached_photos=cached,allowed_photo_urls=safe_urls)
                    self._headers(200,'application/zip',len(raw))
                    return self.wfile.write(raw)
                if path == '/api/photo-settings':
                    saved=photo_cache.set_preferences(data.get('contact_number',''),
                        data.get('auto_replace',False))
                    threading.Thread(target=photo_cache.prepare_all_cached,
                        name='marketplace-prepare-photos',daemon=True).start()
                    return self._json(200,{'ok':True,**saved})
                if path == '/api/photo-cover':
                    vin=str(data.get('vin') or '').upper()
                    source=data.get('source')
                    rec=current_photo_record(vin,source)
                    url=data.get('url')
                    choice=photo_cache.set_cover(vin,source,url,rec.get('images') or [])
                    return self._json(200,{'ok':True,'cover':choice})
                if path == '/api/photos/classify':
                    vin=str(data.get('vin') or '').upper();source=data.get('source')
                    current_photo_record(vin,source)
                    if not os.environ.get('OPENAI_API_KEY','').strip():return self._json(400,{'error':'Needs the OpenAI API key used by AI listing'})
                    # Resume after a pause (quota/key) and sort this vehicle now.
                    auto_sorter.resume();auto_sorter.request(vin,source)
                    return self._json(200,classify_status(vin,source))
                if path == '/api/photos/auto-sort':
                    enabled=photo_selections.set_auto_sort(data.get('enabled'))
                    if enabled:auto_sorter.resume()
                    return self._json(200,{'ok':True,'enabled':enabled})
                if path == '/api/photos/selection':
                    vin=str(data.get('vin') or '').upper();source=data.get('source')
                    current_photo_record(vin,source)
                    _rev,frames,used_source=export_for_preferred_dealer(vin,source,for_preview=True)
                    if used_source!=source:raise ValueError('photo_source_changed_refresh_preview')
                    saved=photo_selections.save(vin,source,data.get('keys'),frames,data.get('limit'),data.get('groups'))
                    return self._json(200,{'ok':True,**saved})
                if path == '/api/photos/open-folder':
                    vin=str(data.get('vin') or '').upper()
                    vehicle=next((v for v in store.state()['vehicles'] if v['vin']==vin),None)
                    if not vehicle:raise ValueError('vehicle_not_found')
                    folder=photo_selections.exported_folder(vin)
                    if folder is not None:
                        if os.name!='nt':raise ValueError('open_folder_requires_windows')
                        os.startfile(str(folder))
                        return self._json(200,{'ok':True})
                    raise ValueError('Download_selected_photos_first')
                if path == '/api/photos/export':
                    if 'selection' in data:
                        vin=str(data.get('vin') or '').upper();source=data.get('source')
                        current_photo_record(vin,source)
                        _rev,frames,used_source=export_for_preferred_dealer(vin,source,for_preview=True)
                        if used_source!=source:raise ValueError('photo_source_changed_refresh_preview')
                        record=current_photo_record(vin,source)
                        raw,folder,filename,report=photo_selections.export(vin,source,record,frames,data['selection'],auto_groups=photo_categories.known(classifiable(frames)))
                        self._headers(200,'application/zip',len(raw),extra={'Content-Disposition':'attachment; filename="'+filename+'"','X-LotRadar-Missing':str(len(report['missing_keys'])),'X-LotRadar-Selected':str(report['selected']),'X-LotRadar-Folder-Warning':report.get('folder_warning',''),**({'X-LotRadar-Folder':str(folder)} if folder is not None else {})})
                        return self.wfile.write(raw)

                    vin=str(data.get('vin') or '').upper();source=data.get('source')
                    if data.get('prepare') is True:photo_cache.prioritize(vin)
                    rec=current_photo_record(vin,source)
                    urls=rec.get('images') or []
                    used_source=source
                    if not urls:
                        used_source='mitsubishi_used' if source=='toyota_used' else 'toyota_used'
                        rec=current_photo_record(vin,used_source)
                        urls=rec.get('images') or []
                    if not urls:raise ValueError('No dealer photos saved. Use Refresh vehicle first.')
                    snapshot=safe_photo_status(vin,used_source,urls,fast=True)
                    expected=rec.get('photo_gallery_expected')
                    if snapshot['downloaded']<snapshot['total']:
                        if data.get('prepare') is True and not snapshot['pending']:
                            snapshot=photo_cache.enqueue(vin,used_source,urls,force=True)
                        if snapshot['pending'] and snapshot['downloaded']<snapshot['total']:
                            return self._json(409,{'error':'photo_download_pending',
                                'downloaded':snapshot['downloaded'],'total':snapshot['total']})
                    # Terminal failures must not block already prepared vehicle photos.
                    missing=max(0,snapshot['total']-snapshot['downloaded'])
                    undiscovered=max(0,int(expected or 0)-snapshot['total'])
                    _revision,cached=prepared_photo_export(vin,used_source,rec)
                    if not cached:raise ValueError('no_export_ready_photos; enter_your_number_for_confident_banner_replacements_or_find_clean_photos')
                    buf=io.BytesIO()
                    with ZipFile(buf,'w',compression=ZIP_DEFLATED) as z:
                        z.writestr('README.txt','LOTRADAR VEHICLE PHOTOS\n\n'
                            f'Downloaded source images: {snapshot["downloaded"]}/{snapshot["total"]}. Failed/missing downloads: {missing}.\n'
                            f'Additional gallery links not captured: {undiscovered}. Export files: {len(cached)} (includes dedication; excludes hidden/duplicate images).\n'
                            'If counts are incomplete, use Fetch missing photos or Refresh vehicle and export again.\n\n'
                            'Files were downloaded from dealer image links for your private review.\n'
                            'When a dealership phone sticker is confidently detected, your original business card is added over that area in the exported copy.\n'
                            'Photo 2 is your supplied dedication artwork; the remaining photos follow.\n'
                            'Original dealership photos and cache files are not modified.\n'
                            f'Photo source: {used_source} (Toyota preferred; Mitsubishi backup only when needed).\n'
                            'Confirm current vehicle availability and listing details separately.\n'
                            'No Facebook listing was created, filled or published.\n')
                        for filename,blob,_ in cached:z.writestr(filename,blob)
                    raw=buf.getvalue()
                    self._headers(200,'application/zip',len(raw))
                    return self.wfile.write(raw)
                if path == '/api/photos/open':
                    # Opening the picker is explicit intent: queue ONE (VIN, source) job, cache reused,
                    # never force (the failed-host cooldown still applies), no duplicate downloads.
                    vin=str(data.get('vin') or '').upper()
                    source=photo_source_with_links(vin,data.get('source'))
                    rec=current_photo_record(vin,source)
                    photo_cache.enqueue(vin,source,rec['images'],force=False,explicit=True)
                    return self._json(200,scoped_photo_progress(vin,source))
                if path == '/api/photos/download':
                    photo_cache.prioritize(str(data.get('vin') or '').upper())
                    vin=str(data.get('vin') or '').upper();source=data.get('source')
                    rec=current_photo_record(vin,source)
                    if not rec.get('images'):
                        other='mitsubishi_used' if source=='toyota_used' else 'toyota_used'
                        try:
                            rec=current_photo_record(vin,other);source=other
                        except ValueError:raise ValueError('no_image_urls_for_vehicle')
                        if not rec.get('images'):raise ValueError('no_image_urls_for_vehicle')
                    return self._json(200,{'ok':True,'photo_source':source,'photos':photo_cache.enqueue(vin,source,rec['images'],
                        force=data.get('force') is True)})
                if path == '/api/ai-draft':
                    if data.get('explicit_user_request') is not True:
                        raise ValueError('explicit_ai_generation_request_required')
                    vin=str(data.get('vin') or '').upper()
                    source=data.get('source')
                    if source not in USED_SOURCES or not VIN_RE.fullmatch(vin):
                        raise ValueError('used_vehicle_vin_and_source_required')
                    vehicle=next((v for v in store.state().get('vehicles',[]) if v['vin']==vin),None)
                    if not vehicle or source not in vehicle['sources'] or not vehicle.get('draft'):
                        raise ValueError('create_local_draft_first')
                    if vehicle['draft']['status'] in ('USER_CONFIRMED_PUBLISHED','USER_CONFIRMED_REMOVED'):
                        raise ValueError('published_draft_is_read_only')
                    if vehicle['draft']['source'] != source:
                        raise ValueError('draft_source_mismatch')
                    return self._json(200,{'ok':True,**generate_ai_description(vehicle['sources'][source],source)})
                if path == '/api/verify-inventory':
                    return self._json(200, {'ok':True,'verification':verify_inventory()})
                if path == '/api/sync':
                    requested=data.get('source')
                    if requested and requested not in USED_SOURCES:
                        raise ValueError('used_inventory_only')
                    sources=[requested] if requested else list(USED_SOURCES)
                    result={}
                    for used_source in sources:
                        result.update(sync_configured(store,only_source=used_source))
                    return self._json(200, {'ok':True,'results':result,'state':store.state()})
                if path == '/api/facebook-auto-cancel-all':
                    if data.get('explicit_request') is not True:raise ValueError('explicit_cancel_required')
                    return self._json(200,facebook_auto.cancel_bulk())
                if path == '/api/facebook-auto-retry':
                    if data.get('explicit_request') is not True:raise ValueError('explicit_check_request_required')
                    vin=str(data.get('vin') or '').upper()
                    comparison=store.facebook_comparison(vin)
                    ready=facebook_auto.preflight()
                    if not ready['ready']:raise ValueError('facebook_reader_not_ready; '+ready['reason'])
                    return self._json(200,facebook_auto.retry_one(vin,comparison['linked_url']))
                if path == '/api/facebook-auto-retry-failed':
                    if data.get('explicit_request') is not True:raise ValueError('explicit_check_request_required')
                    ready=facebook_auto.preflight()
                    if not ready['ready']:raise ValueError('facebook_reader_not_ready; '+ready['reason'])
                    current=facebook_auto.bulk_status()
                    if current['active']:raise ValueError('facebook_batch_still_active')
                    failed_vins={j['vin'] for j in facebook_auto.jobs if j['id'] in facebook_auto.bulk_job_ids
                                 and j['state'] in ('failed','expired','cancelled')}
                    pairs=[]
                    for vehicle in store.state().get('vehicles',[]):
                        draft=vehicle.get('draft') or {}
                        if vehicle['vin'] not in failed_vins or draft.get('status')!='USER_CONFIRMED_PUBLISHED':continue
                        if not any(src in USED_SOURCES for src in (vehicle.get('sources') or {})):continue
                        if draft.get('published_url'):pairs.append((vehicle['vin'],draft['published_url']))
                    return self._json(200,facebook_auto.bulk_enqueue(pairs))
                if path == '/api/fetch-missing-photos':
                    if data.get('explicit_request') is not True:raise ValueError('explicit_photo_fetch_required')
                    with full_lock:
                        if full_job['running'] or chrome_bridge.status()['running']:
                            raise ValueError('Finish or stop the current dealer scan before fetching missing photos.')
                        targets=missing_photo_targets(store,photo_cache)
                        if not targets:return self._json(200,{'ok':True,'vehicles':0,'queued':0})
                        headless_dealer.ensure_ready()
                        if not chrome_bridge.dealer_connected():raise ValueError('dealer_reader_not_connected')
                        result=chrome_bridge.start_missing_photos(targets)
                    return self._json(200,{'ok':True,**result,'eligible':len(targets)})
                if path == '/api/recheck-outstock':
                    if data.get('explicit_request') is not True:
                        raise ValueError('explicit_outstock_recheck_required')
                    with full_lock:
                        if full_job['running'] or chrome_bridge.status()['running'] or facebook_auto.bulk_status()['active']:
                            raise ValueError('A scan is already running. Finish or stop it before rechecking Out of Stock.')
                        vins,pairs=outstock_recheck_targets(store)
                        if not vins:return self._json(200,{'ok':True,'vehicles':0,'dealer_links':0,'facebook_links':0})
                        headless_dealer.ensure_ready()
                        if not chrome_bridge.dealer_connected():raise ValueError('dealer_reader_not_connected')
                        try:
                            verify=chrome_bridge.start_verify(1200,tracked_vins=vins)
                        except ValueError as exc:
                            if str(exc)!='no_saved_vehicle_links_to_verify':raise
                            verify={'error':'No valid saved dealer links to check.'}
                        full_job.update(running=True,phase='verifying_inventory',operation='recheck_outstock',
                            started_at=utc(),finished_at=None,cancel_requested=False,scan=None,verify=verify,
                            facebook=None,error=None,partial=bool(verify.get('error')))
                    threading.Thread(target=full_scan_worker,args=(pairs,),daemon=True,
                        name='LotRadar-Recheck-Outstock').start()
                    return self._json(200,{'ok':True,'vehicles':len(vins),'dealer_links':verify.get('total',0),
                        'facebook_links':len(pairs)})
                if path == '/api/facebook-auto-check-all':
                    if data.get('explicit_request') is not True:raise ValueError('explicit_check_request_required')
                    pairs=[(vehicle['vin'],draft['published_url']) for vehicle in store.state()['vehicles']
                           if (draft:=vehicle.get('draft') or {}).get('status')=='USER_CONFIRMED_PUBLISHED'
                           and draft.get('published_url') and any(src in USED_SOURCES for src in vehicle['sources'])]
                    if not pairs:
                        return self._json(200,{'ok':True,'total':0})
                    if not chrome_bridge.connected():
                        raise ValueError('Connect LotRadar Browser Reader for Facebook checks first.')
                    headless_dealer.ensure_ready()
                    with full_lock:
                        if full_job['running'] or chrome_bridge.status()['running'] or facebook_auto.bulk_status()['active']:
                            raise ValueError('A scan is already running. Let it finish or stop it before checking both links.')
                        try:
                            verify=chrome_bridge.start_verify(1200,tracked_vins={vin for vin,_ in pairs})
                        except ValueError as exc:
                            if str(exc)!='no_saved_vehicle_links_to_verify':
                                raise
                            verify={'error':'No saved dealer links to check.'}
                        full_job.update(running=True,phase='verifying_inventory',operation='check_listings',
                            started_at=utc(),finished_at=None,cancel_requested=False,scan=None,verify=verify,
                            facebook=None,error=None,partial=bool(verify.get('error')))
                    threading.Thread(target=full_scan_worker,args=(pairs,),daemon=True,
                                     name='LotRadar-Check-Listing-Links').start()
                    return self._json(200,{'ok':True,'total':len(pairs),'dealer_links':verify.get('total',0)})
                if path == '/api/facebook-auto-check':
                    if data.get('explicit_request') is not True:raise ValueError('explicit_check_request_required')
                    vin=str(data.get('vin') or '').upper()
                    comparison=store.facebook_comparison(vin)
                    return self._json(200,facebook_auto.enqueue(vin,comparison['linked_url']))
                if path == '/api/action':
                    action = data.get('action'); vin = str(data.get('vin','')).strip().upper()
                    # R13A is used-inventory-only. An old new-car record may
                    # remain on disk for history, but cannot start a new ad.
                    if action in ('create_draft','track_existing') and data.get('source') not in USED_SOURCES:
                        raise ValueError('used_inventory_only')
                    if action == 'create_draft':
                        state = store.create_draft(vin,data.get('source'))
                    elif action == 'confirm_availability':
                        state = store.confirm_used_availability(vin,data.get('source'),data.get('explicit_user_confirmation'))
                    elif action == 'edit_draft':
                        state = store.edit_draft(vin,data.get('title'),data.get('description'),data.get('price_cents'))
                    elif action == 'reconcile_draft':
                        state = store.reconcile_draft(vin,
                            explicit_review=data.get('explicit_dealer_facts_review'),
                            explicit_stock_confirmation=data.get('explicit_stock_confirmation',False),
                            conflict_ack=data.get('conflict_ack',False))
                    elif action == 'approve_draft':
                        state = store.approve_draft(vin,data.get('explicit_approval'),data.get('conflict_ack'))
                    elif action == 'rebuild_draft':
                        state = store.rebuild_draft(vin)
                    elif action == 'track_existing':
                        state = store.track_existing(vin,data.get('source'),data.get('url'),data.get('explicit_confirmation'))
                        try:facebook_auto.enqueue(vin,data.get('url'))
                        except ValueError:pass  # Tracking must not be undone if the scan queue is full.
                    elif action == 'confirm_published':
                        state = store.confirm_published(vin,data.get('url'),data.get('explicit_confirmation'))
                        try:facebook_auto.enqueue(vin,data.get('url'))
                        except ValueError:pass
                    elif action == 'relink_facebook':
                        state = store.relink_facebook(vin,data.get('url'),data.get('expected_url'),data.get('explicit_confirmation'))
                        try:facebook_auto.enqueue(vin,store.facebook_comparison(vin)['linked_url'])
                        except ValueError:pass  # Local link is saved even when the reader is unavailable.
                    elif action == 'confirm_listing_updated':
                        state = store.confirm_listing_updated(vin,data.get('explicit_confirmation'),data.get('conflict_ack'))
                    elif action == 'confirm_listing_removed':
                        state = store.confirm_listing_removed(vin,data.get('explicit_confirmation'))
                    elif action == 'complete_facebook_cleanup':
                        state = store.complete_facebook_cleanup(vin,
                            data.get('explicit_manual_removal'),data.get('explicit_local_trash'),data.get('expected_listing_url'))
                    elif action == 'trash_cleanup_listing':
                        state = store.trash_listing(vin,data.get('explicit_confirmation'),
                                                    cleanup_listing_id=str(data.get('listing_id') or ''))
                    elif action == 'trash_listing':
                        state = store.trash_listing(vin,data.get('explicit_confirmation'))
                    elif action == 'restore_listing':
                        state = store.restore_listing(vin,data.get('explicit_confirmation'),data.get('trash_id'))
                    else:
                        raise ValueError('unsupported_action; automatic_publishing_is_not_available')
                    return self._json(200, {'ok':True,'state':state})
                return self._json(404, {'error':'not_found'})
            except (ValueError, json.JSONDecodeError, TypeError) as ex:
                return self._json(400, {'ok':False, 'error':str(ex)})
            except Exception:
                return self._json(500, {'ok':False,'error':'internal_error; see server console'})
    Handler.photo_cache = photo_cache
    Handler.headless_dealer = headless_dealer
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Local LotRadar R62')
    parser.add_argument('--data-dir', default=str(default_data_dir()))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--watch-minutes', type=int, default=0,
                        help='Automatically refresh only explicitly authorized feeds at this interval (minimum 15)')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    if args.watch_minutes and not 15 <= args.watch_minutes <= 1440:
        parser.error('watch interval must be 15..1440 minutes')
    store = MarketplaceStore(args.data_dir)
    token = secrets.token_urlsafe(32)
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), create_handler(store,args.port,token))
    srv.daemon_threads = True
    if args.watch_minutes:
        def watch():
            while not stop.wait(args.watch_minutes * 60):
                try:
                    result = sync_configured(store)
                    print('Authorized feed refresh:', {k:v.get('ok') for k,v in result.items()})
                except Exception as e:
                    print('Authorized feed refresh failed:', type(e).__name__)
        stop = threading.Event()
        threading.Thread(target=watch, daemon=True).start()
    else:
        stop = None
    url = f'http://127.0.0.1:{args.port}/'
    print(f'LotRadar R62: {url}')
    print(f'Private data directory: {Path(args.data_dir).resolve()}')
    print('Never posts to Facebook. Stop with Ctrl+C.')
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if stop: stop.set()
        srv.RequestHandlerClass.photo_cache.close()
        srv.RequestHandlerClass.headless_dealer.close()
        srv.server_close()
        store.close()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        # Local diagnosis for genuine startup errors, not the normal
        # Ctrl+C shutdown. Don't store credentials, photo content, or bodies.
        trace=traceback.format_exc(limit=18)
        print('MARKETPLACE STARTUP ERROR:',trace,file=sys.stderr,flush=True)
        try:
            directory=default_data_dir()
            directory.mkdir(parents=True,exist_ok=True)
            log=directory/'marketplace_startup_error.log'
            if not log.exists() or log.stat().st_size<100_000:
                with log.open('a',encoding='utf-8') as out:
                    out.write(utc()+'\n'+trace+'\n')
        except OSError:
            pass
        sys.exit(1)
