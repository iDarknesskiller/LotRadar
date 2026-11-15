"""Cached posting readiness; no network work during status-only checks."""
import threading,time,re
from pathlib import Path
def is_trade_in(car):
    return any(source in ('toyota_used','mitsubishi_used') and re.search(r'[A-Za-z]$',str(record.get('stock') or '').strip()) is not None for source,record in car.get('sources',{}).items())

class TradeReady:
    def __init__(self,store,photos,events):
        self.store,self.photos,self.events=store,photos,events
        self.lock=threading.RLock();self.results={};self.running=False;self.pending_prepare=None
    def source_record(self,car):
        records=car.get('sources',{})
        for source in ('toyota_used','mitsubishi_used'):
            if records.get(source,{}).get('images'):return source,records[source]
        return 'toyota_used',records.get('toyota_used',{})
    def stamp(self,vin,source,record):
        path=self.photos._directory(vin,source)/'manifest.json'
        try:st=path.stat();version=(st.st_mtime_ns,st.st_size)
        except OSError:version=None
        assets=[]
        for name in ('business_card.png','dedication.jpg'):
            try:st=(Path(__file__).parent/'branding'/name).stat();assets.append((st.st_mtime_ns,st.st_size))
            except OSError:assets.append(None)
        return (source,tuple(record.get('images') or []),record.get('photo_gallery_expected'),version,tuple(assets),self.photos.preferences().get('covers',{}).get(vin+':'+source))
    def status(self,car):
        if not is_trade_in(car):return {'ready':False,'reason':'Not a trade-in','eligible':False}
        source,record=self.source_record(car);cached=self.results.get(car['vin'],{})
        if cached.get('_stamp')!=self.stamp(car['vin'],source,record):return {'ready':False,'reason':'Readiness check pending'}
        return {k:v for k,v in cached.items() if k!='_stamp'}
    def check(self,car):
        vin=car['vin'];source,rec=self.source_record(car);urls=rec.get('images') or []
        if self.results.get(vin,{}).get('_stamp')==self.stamp(vin,source,rec):return self.status(car)
        try:
            snap=self.photos.status(vin,source,urls,analyze=False)
            expected=int(rec.get('photo_gallery_expected') or 0)
            complete=bool(urls) and snap['total']==len(set(urls)) and snap['downloaded']==snap['total'] and snap['downloaded']>=expected
            branded=False
            if complete:
                report=self.photos.business_card_diagnostic(vin,source,urls,rec.get('dealer_lead_photo'))
                branded=report['cover_ready']
                if branded:
                    cover=report['first_export_url']
                    if self.photos.preferences().get('covers',{}).get(vin+':'+source)!=cover:self.photos.set_cover(vin,source,cover,urls)
            result={'ready':complete and branded,'downloaded':snap['downloaded'],'total':max(len(set(urls)),expected),'reason':('Ready' if branded and complete else 'Missing photos' if not complete else 'Business card missing from first photo')}
        except Exception as exc:result={'ready':False,'reason':str(exc)[:160]}
        self.results[vin]={**result,'_stamp':self.stamp(vin,source,rec)}
        return result
    def start(self,vins=None,prepare=False):
        with self.lock:
            if self.running:
                if prepare:self.pending_prepare=vins
                return {'running':True,'already_running':True}
            self.running=True
        threading.Thread(target=self.run,args=(vins,prepare),daemon=True,name='trade-in-ready').start()
        return {'running':True}
    def run(self,vins,prepare):
        try:
            cars=[c for c in self.store.state()['vehicles'] if is_trade_in(c) and not c.get('listed') and (vins is None or c['vin'] in vins)]
            waiting=[]
            if prepare:self.events('','TRADE_READY_START',f'Preparing {len(cars)} vehicles; already-ready vehicles skipped')
            for car in cars:
                if self.photos.stopping.is_set():return
                result=self.check(car)
                if not prepare:continue
                vin=car['vin'];source,rec=self.source_record(car)
                self.events(source,'TRADE_READY',f"{vin}: {result['reason']}")
                if result['ready']:continue
                urls=rec.get('images') or []
                snap=self.photos.status(vin,source,urls,analyze=False)
                bad_links=any(p.get('status')=='failed' for p in snap.get('photos',[]))
                incomplete=min(250,int(rec.get('photo_gallery_expected') or 0))>len(set(urls))
                if (not urls or incomplete or bad_links) and hasattr(self,'refresh_gallery'):
                    self.events(source,'TRADE_READY_REFRESH',f'{vin}: gallery missing, incomplete or failed links; checking dealer page once')
                    self.refresh_gallery(vin,source)
                    fresh=next((c for c in self.store.state()['vehicles'] if c['vin']==vin),car)
                    car=fresh;source,rec=self.source_record(car);urls=rec.get('images') or []
                if urls:
                    self.photos.prioritize(vin,level=1)
                    self.photos.enqueue(vin,source,urls,force=True,explicit=True)
                    waiting.append((car,source))
                else:self.events(source,'TRADE_READY_REVIEW',f'{vin}: no gallery saved; Refresh vehicle required')
            while waiting and not self.photos.stopping.is_set():
                remaining=[]
                for car,source in waiting:
                    with self.photos.lock:pending=(car['vin'],source) in self.photos.enqueued
                    if pending:remaining.append((car,source));continue
                    self.results.pop(car['vin'],None)
                    result=self.check(car)
                    self.events(source,'TRADE_READY_DONE',f"{car['vin']}: {result['reason']}")
                waiting=remaining
                if waiting:self.photos.stopping.wait(.5)
            if prepare:self.events('','TRADE_READY_FINISHED','Preparation finished. Failed/missing photos or business cards remain Not ready.')
        except Exception as exc:self.events('','TRADE_READY_ERROR',str(exc)[:200])
        finally:
            with self.lock:
                self.running=False;pending=self.pending_prepare;self.pending_prepare=None
            if pending is not None:self.start(pending,prepare=True)
