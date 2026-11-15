"""Persistent page refresh history; only accepted imports count as success."""
import json,time,threading
from datetime import datetime,timezone
class RefreshPolicy:
    def __init__(self,root):
        self.path=root/'dealer_refresh_history.json';self.lock=threading.RLock()
        try:self.records=json.loads(self.path.read_text())
        except (OSError,ValueError):self.records={}
    def key(self,source,url):return source+'|'+url.split('#')[0]
    def get(self,source,url):return dict(self.records.get(self.key(source,url),{}))
    def skip(self,job):
        if job.get('manual') or (job.get('priority') and not job.get('automatic_repair')):return ''
        r=self.get(job['source'],job['url']);now=time.time()
        if now-r.get('failed_at',0)<1800:return 'Retry cooldown: last failure less than 30 minutes ago'
        if not job.get('automatic_repair') and now-r.get('success_at',0)<86400:
            return f"Skipped—refreshed {max(0,int((now-r['success_at'])/3600))} hours ago"
        return ''
    def record_photos(self,source,url):
        with self.lock:
            r=self.records.setdefault(self.key(source,url),{})
            r['photos_at']=time.time()
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.records));tmp.replace(self.path)
    def record(self,source,url,success):
        with self.lock:
            r=self.records.setdefault(self.key(source,url),{})
            if success:r.update(success_at=time.time(),last_success=datetime.now(timezone.utc).isoformat(),failed_at=0)
            else:r['failed_at']=time.time()
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.records));tmp.replace(self.path)
