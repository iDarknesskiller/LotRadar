"""Bounded local queue for one-off, user-authorized Facebook listing checks.

Not a crawler, monitor, scheduler, publishing API, or source of dealer identity.
The bridge worker opens a browser tab only for a pre-linked listing ID.
No VIN is ever sourced from a Facebook page.
"""
from __future__ import annotations
from threading import RLock
from collections import deque
import secrets
import time
from core import facebook_listing_id

MAX_QUEUED = 500
JOB_TTL = 600  # Short-lived individual checks.
BULK_STALL_SECONDS = 100
READY_FRESH_SECONDS = 100
LEASE_SECONDS = 70

class FacebookAutoQueue:
    def __init__(self):
        self.lock = RLock()
        self.jobs = []
        self.completed_checks = deque(maxlen=8)
        self.by_vin = {}
        self.bulk_job_ids = []
        self.bulk_started = None
        self.bulk_skipped = 0
        self.bulk_last_progress = None
        self.reader_last_seen = None
        self.reader_ready = False
        self.reader_reason = 'Chrome Reader has not reported Facebook permission yet.'

    def _expire(self):
        now = time.monotonic()
        bulk_ids=set(self.bulk_job_ids)
        if bulk_ids and self.bulk_last_progress is not None and now-self.bulk_last_progress>BULK_STALL_SECONDS:
            for job in self.jobs:
                if job['id'] in bulk_ids and job['state'] in ('queued','checking'):
                    job.update(state='failed',detail='Batch stalled: Chrome Reader did not finish. Retry or reconnect the extension.')
            self.bulk_last_progress = None
        for job in self.jobs:
            if (job['id'] not in bulk_ids and job['state'] in ('queued','checking')
                and now-job['created_monotonic']>=JOB_TTL):
                job.update(state='expired',detail='Automatic check expired. Retry this Facebook listing to check again.')
            elif job['state']=='checking' and now-job.get('leased_monotonic',0)>LEASE_SECONDS:
                if job['attempts'] >= 2:
                    job.update(state='failed',detail='Chrome Reader did not finish. Click Check Facebook now to retry.')
                else:
                    previous_id=job['id']
                    job.update(id=secrets.token_hex(12),state='queued',
                               detail='Retrying interrupted Chrome Reader check.')
                    if previous_id in bulk_ids:
                        self.bulk_job_ids[self.bulk_job_ids.index(previous_id)]=job['id']
        self.jobs = [j for j in self.jobs if j['state'] in ('queued','checking') or now-j['created_monotonic']<9000]

    def enqueue(self,vin,url):
        listing_id = facebook_listing_id(url)
        if not listing_id:raise ValueError('facebook_listing_url_invalid')
        vin = str(vin or '').upper()
        if not vin:raise ValueError('vehicle_required')
        with self.lock:
            self._expire()
            current = self.by_vin.get(vin)
            if current and current['listing_id']==listing_id and current['state'] in ('queued','checking'):
                return self._public(current)
            if sum(j['state'] in ('queued','checking') for j in self.jobs) >= MAX_QUEUED:
                raise ValueError('facebook_auto_queue_full')
            if not any(j['state'] in ('queued','checking') for j in self.jobs):
                self.completed_checks.clear()
            job={'id':secrets.token_hex(12),'vin':vin,'listing_id':listing_id,
                 'url':'https://www.facebook.com/marketplace/item/'+listing_id,
                 'created_monotonic':time.monotonic(),'state':'queued','detail':'Waiting for connected Chrome Reader.',
                 'attempts':0,'fields':[]}
            self.jobs.append(job)
            self.by_vin[vin]=job
            return self._public(job)

    @staticmethod
    def _public(job):
        if not job:return {'ok':True,'state':'not_requested','detail':'No automatic check requested.'}
        return {'ok':True,'state':job['state'],'detail':job.get('detail',''),
                'listing_id':job['listing_id'],'fields':job.get('fields',[])}

    def status(self,vin):
        with self.lock:
            self._expire()
            return {'ok':True,**self._public(self.by_vin.get(str(vin or '').upper()))}

    def next(self):
        with self.lock:
            self._expire()
            job=next((j for j in self.jobs if j['state']=='queued'),None)
            if not job:return {'ok':True,'job':None}
            job.update(state='checking',detail='Chrome Reader is opening a temporary Facebook tab.',
                       leased_monotonic=time.monotonic(),attempts=job['attempts']+1)
            if job['id'] in self.bulk_job_ids:self.bulk_last_progress=time.monotonic()
            return {'ok':True,'job':{'id':job['id'],'url':job['url'],'listing_id':job['listing_id']},'remaining':sum(j['state']=='queued' for j in self.jobs)}

    def require_active_capture(self,job_id,listing_id):
        # Caller holds the queue lock through the capture write.
        self._expire()
        if not any(job['id']==job_id and job['listing_id']==listing_id
                   and job['state']=='checking' for job in self.jobs):
            raise ValueError('facebook_auto_job_not_active')

    def finish(self,job_id,result,detail='',fields=None):
        with self.lock:
            self._expire()
            job=next((j for j in self.jobs if j['id']==job_id),None)
            if job and job['state']=='cancelled':return {'ok':True,**self._public(job)}
            if not job or job['state']!='checking':raise ValueError('facebook_auto_job_not_active')
            if result not in ('captured','failed'):raise ValueError('facebook_auto_result_invalid')
            job['state']=result
            now=time.monotonic()
            if self.completed_checks and now-self.completed_checks[-1]>60:
                self.completed_checks.clear()
            self.completed_checks.append(now)
            if job['id'] in self.bulk_job_ids:self.bulk_last_progress=now
            job['detail']=(str(detail or '')[:180] or ('Listing details captured.' if result=='captured' else 'Could not read listing.'))
            job['fields']=[k for k in (fields or []) if k in ('title','price','mileage','description','status')][:5]
            return {'ok':True,**self._public(job)}

    def bulk_enqueue(self, pairs, *, skipped=0):
        """Only the local authenticated user's explicitly requested, pre-linked listings."""
        with self.lock:
            self._expire()
            # An in-progress batch cannot be silently replaced or doubled by another click.
            if self.bulk_job_ids:
                bulk_ids=set(self.bulk_job_ids)
                active = any(j['id'] in bulk_ids and j['state'] in ('queued','checking') for j in self.jobs)
                if active:return self.bulk_status()
            self.bulk_job_ids=[]
            self.bulk_started=time.monotonic()
            self.bulk_last_progress=time.monotonic()
            self.bulk_skipped=int(skipped)
            seen_ids=set()
            for vin,url in pairs:
                listing_id=facebook_listing_id(url)
                if not listing_id or listing_id in seen_ids:
                    self.bulk_skipped+=1
                    continue
                seen_ids.add(listing_id)
                try: result=self.enqueue(vin,url)
                except ValueError:
                    self.bulk_skipped+=1
                    continue
                job=self.by_vin.get(str(vin or '').upper())
                if not job:
                    self.bulk_skipped+=1
                    continue
                if job['id'] not in self.bulk_job_ids:self.bulk_job_ids.append(job['id'])
            return self.bulk_status()

    def bulk_status(self):
        with self.lock:
            self._expire()
            ids=set(self.bulk_job_ids)
            jobs=[j for j in self.jobs if j['id'] in ids]
            counts={k:sum(j['state']==k for j in jobs) for k in ('queued','checking','captured','failed','expired','cancelled')}
            return {'ok':True,'total':len(jobs),'skipped':self.bulk_skipped,
                    'checked':counts['captured']+counts['failed'],
                    'retryable':counts['failed']+counts['expired']+counts['cancelled'],
                    'active':bool(counts['queued'] or counts['checking']),**counts}

    def timing(self):
        with self.lock:
            self._expire()
            pending=sum(job['state'] in ('queued','checking') for job in self.jobs)
            if not pending:
                return {'state':'idle','seconds':None}
            if not self.preflight()['ready']:
                return {'state':'disconnected','seconds':None}
            samples=self.completed_checks
            if len(samples)<2 or time.monotonic()-samples[-1]>60 or samples[-1]<=samples[0]:
                return {'state':'measuring','seconds':None}
            interval=(samples[-1]-samples[0])/(len(samples)-1)
            return {'state':'estimated','seconds':max(1,round(interval*pending))}

    def report_reader(self, *, enabled, permitted):
        with self.lock:
            self.reader_last_seen=time.monotonic()
            self.reader_ready=enabled is True and permitted is True
            self.reader_reason=('Facebook Reader ready.' if self.reader_ready else
                'Open Chrome Reader and enable automatic Facebook checks and site permission.')
            return {'ok':True,'ready':self.reader_ready}

    def preflight(self):
        with self.lock:
            recent=self.reader_last_seen is not None and time.monotonic()-self.reader_last_seen<=READY_FRESH_SECONDS
            return {'ok':True,'ready':bool(recent and self.reader_ready),
                    'reason':self.reader_reason if recent else 'Chrome Reader not connected recently. Reload the extension and allow Facebook access.'}

    def cancel_bulk(self):
        with self.lock:
            self._expire()
            for job in self.jobs:
                if job['id'] in self.bulk_job_ids and job['state'] in ('queued','checking'):
                    job.update(state='cancelled',detail='Cancelled by user. Previous captured snapshots are kept.')
            self.bulk_last_progress=None
            return self.bulk_status()

    def retry_one(self,vin,url):
        # An explicit per-VIN retry can requeue an old failed/expired/cancelled job.
        return self.enqueue(vin,url)
