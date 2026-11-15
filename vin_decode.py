"""Optional vPIC lookup. Only public VINs leave the machine; dealer data is unchanged."""
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VIN_RE = re.compile(r'[A-HJ-NPR-Z0-9]{17}')

def valid_spec(field, value):
    if not isinstance(value, str): return None
    value = value.strip()
    if not value or value.lower() in {'other','unknown','n/a','na','none','-','not available','not specified'}: return None
    if field == 'body_style':
        value = value.split('/')[0].strip()
        if not re.search(r'sedan|saloon|suv|sport utility|crossover|truck|pick ?up|cab|coupe|hatch|liftback|wagon|convertible|van|\b[24] ?dr\b|\bcar\b', value, re.I): return None
    if field == 'fuel_type':
        if not re.search(r'gas|unleaded|petrol|diesel|electric|hybrid|flex|e85|ethanol', value, re.I): return None
        if value.lower() in ('regular unleaded','premium unleaded'): return 'Gasoline'
    return value

def mapped_specs(decoded):
    d=decoded or {}; b=str(d.get('body_class') or '').lower()
    body=None
    for pattern, label in [(r'sedan|saloon','Sedan'),(r'sport utility|suv|crossover|cuv','SUV'),(r'pickup','Truck'),(r'hatchback|liftback|notchback','Hatchback'),(r'coupe','Coupe'),(r'convertible|cabriolet','Convertible'),(r'minivan','Minivan'),(r'wagon','Wagon')]:
        if re.search(pattern,b): body=label;break
    e=str(d.get('electrification') or '').lower(); f=str(d.get('fuel_primary') or '').lower(); sec=str(d.get('fuel_secondary') or '').lower()
    if re.search(r'phev|plug.in',e): fuel='Plug-in hybrid'
    elif re.search(r'\bhev\b|hybrid',e): fuel='Hybrid'
    elif 'bev' in e or f=='electric': fuel='Electric'
    elif re.search(r'e85|ethanol',sec) or 'flexible' in f: fuel='Flex'
    elif 'diesel' in f: fuel='Diesel'
    elif 'gasoline' in f: fuel='Gasoline'
    else: fuel=None
    return {'body_style':body,'fuel_type':fuel}

class VinDecoder:
    def __init__(self, data_dir):
        self.path=Path(data_dir)/'vin_decode_cache.json'
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            self.cache={v:d for v,d in data.items() if VIN_RE.fullmatch(v) and isinstance(d,dict) and (d.get('body_class') or d.get('fuel_primary'))}
        except (OSError,ValueError,TypeError,AttributeError): self.cache={}
        self.lock=threading.Lock();self.request_lock=threading.Lock();self.write_lock=threading.Lock()
        self.inbox=queue.SimpleQueue();self.event=threading.Event();self.stopping=threading.Event()
        self.failures={};self.next_request=0.;self.failure_streak=0
        self.thread=threading.Thread(target=self._worker,name='LotRadar VIN specs',daemon=True);self.thread.start()

    def enqueue(self, vin):
        vin=str(vin or '').strip().upper()
        if VIN_RE.fullmatch(vin): self.inbox.put(vin);self.event.set()

    def get(self, vin):
        with self.lock:
            value=self.cache.get(str(vin or '').upper())
            return dict(value) if value else None

    def _save(self):
        with self.write_lock:
            with self.lock: snapshot=dict(self.cache)
            tmp=self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                tmp.write_text(json.dumps(snapshot,sort_keys=True),encoding='utf-8')
                for attempt in range(4):
                    try: os.replace(tmp,self.path);return
                    except PermissionError:
                        if attempt==3: raise
                        time.sleep(.05*(attempt+1))
            except OSError: pass  # Optional cache must never break a form or import.
            finally:
                try: tmp.unlink(missing_ok=True)
                except OSError: pass

    def _request(self, vins, timeout, deadline=None):
        remaining=lambda: max(0.,deadline-time.monotonic()) if deadline else timeout
        if not self.request_lock.acquire(timeout=remaining()): return False
        try:
            with self.lock:
                now=time.monotonic()
                vins=[v for v in vins if v not in self.cache and self.failures.get(v,0)<=now]
            if not vins: return True
            wait=max(0.,self.next_request-time.monotonic())
            if deadline and wait>=remaining(): return False
            if self.stopping.wait(wait): return False
            try:
                req=Request('https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/',data=urlencode({'DATA':';'.join(vins[:50]),'format':'json'}).encode(),headers={'User-Agent':'LotRadar/1.9.5','Content-Type':'application/x-www-form-urlencoded'})
                with urlopen(req,timeout=max(.001,min(timeout,remaining()))) as response:
                    rows=json.loads(response.read(4_000_000)).get('Results',[])
                if not isinstance(rows,list): raise ValueError('Invalid VIN response')
                accepted={}
                keys={'body_class':'BodyClass','fuel_primary':'FuelTypePrimary','fuel_secondary':'FuelTypeSecondary','electrification':'ElectrificationLevel','doors':'Doors','error_code':'ErrorCode'}
                for row in rows:
                    if not isinstance(row,dict): continue
                    v=str(row.get('VIN') or '').upper()
                    if v not in vins: continue
                    result={k:str(row.get(raw) or '').strip() for k,raw in keys.items()}
                    if not (result['body_class'] or result['fuel_primary']): continue
                    result['fetched_at']=datetime.now(timezone.utc).isoformat();accepted[v]=result
                with self.lock:
                    self.cache.update(accepted)
                    for v in vins:
                        if v not in accepted:self.failures[v]=time.monotonic()+3600
                        else:self.failures.pop(v,None)
                self.failure_streak=0;self.next_request=time.monotonic()+3
                if accepted:self._save()
                return True
            except Exception:
                with self.lock:
                    for v in vins:self.failures[v]=time.monotonic()+3600
                self.failure_streak+=1
                self.next_request=time.monotonic()+(30,120,600)[min(2,self.failure_streak-1)]
                return False
        finally:self.request_lock.release()

    def fetch_now(self, vin, timeout=6):
        vin=str(vin or '').strip().upper()
        if not VIN_RE.fullmatch(vin):return None
        saved=self.get(vin)
        if saved:return saved
        try:self._request([vin],timeout,deadline=time.monotonic()+timeout)
        except Exception:pass
        value=self.get(vin)
        if not value:self.enqueue(vin)
        return value

    def _worker(self):
        pending=set()
        while not self.stopping.is_set():
            self.event.clear()
            while True:
                try:pending.add(self.inbox.get_nowait())
                except queue.Empty:break
            with self.lock:
                pending.difference_update(self.cache)
                ready=[v for v in sorted(pending) if self.failures.get(v,0)<=time.monotonic()][:50]
            if ready:
                self._request(ready,15)
            else:self.event.wait(1)

    def close(self):
        self.stopping.set();self.event.set()
