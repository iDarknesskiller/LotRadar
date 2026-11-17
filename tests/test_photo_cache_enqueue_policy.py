"""Open-time fetch must reuse cache, honor the failed-host cooldown, and never double-queue."""
import sys,tempfile,threading,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import photo_cache as P
VIN='1HGCM82633A004352';SRC='toyota_used'
URLS=[f'https://pictures.dealer.com/i/{n}.jpg' for n in range(4)]
class Policy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pc=P.PhotoCache(Path(self.tmp.name));self.gate=threading.Event()
        self.started=[];self.pc._download=lambda *a,**k:(self.started.append(a[:2]),self.gate.wait(10))
        self.addCleanup(lambda:(self.gate.set(),self.pc.close()))
    def test_repeated_explicit_open_is_one_job(self):
        for _ in range(5):self.pc.enqueue(VIN,SRC,URLS,force=False,explicit=True)
        self.assertEqual(self.pc.enqueued,{(VIN,SRC)});import time;time.sleep(.5);self.assertEqual(self.started,[(VIN,SRC)])
    def test_failed_host_cooldown_blocks_unforced_open(self):
        m=self.pc._manifest(VIN,SRC)
        m['urls']=URLS;m['entries']={URLS[0]:{'status':'failed','error':'HTTP 403'}}
        m['updated_at']=datetime.now(timezone.utc).isoformat();self.pc._save(VIN,SRC,m)
        self.pc.enqueue(VIN,SRC,URLS,force=False,explicit=True)
        self.assertEqual(self.pc.enqueued,set())
    def test_cooldown_expires_after_two_hours(self):
        m=self.pc._manifest(VIN,SRC)
        m['urls']=URLS;m['entries']={URLS[0]:{'status':'failed','error':'HTTP 403'}}
        m['updated_at']=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat();self.pc._save(VIN,SRC,m)
        self.pc.enqueue(VIN,SRC,URLS,force=False,explicit=True)
        self.assertEqual(self.pc.enqueued,{(VIN,SRC)})
    def test_suspension_bypassed_only_when_explicit(self):
        self.pc.automatic_suspended=True
        self.pc.enqueue(VIN,SRC,URLS,force=False);self.assertEqual(self.pc.enqueued,set())
        self.pc.enqueue(VIN,SRC,URLS,force=False,explicit=True);self.assertEqual(self.pc.enqueued,{(VIN,SRC)})
if __name__=='__main__':unittest.main()
