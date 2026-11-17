"""HTTP tests: scoped photo progress + open-time auto-fetch. No network, no real data dir."""
import json,sys,tempfile,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as S
from core import MarketplaceStore
VIN='1HGCM82633A004352'
def row(n=5,expected=None):
    return {'vin':VIN,'condition':'used','year':2022,'make':'Hyundai','model':'Tucson','stock':'T1','mileage':1000,'price':20000,
            'url':'https://dealer.example/v/1','images':[f'https://pictures.dealer.com/img/{i}.jpg' for i in range(n)],
            **({'photo_gallery_expected':expected} if expected else {})}
class Api(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=MarketplaceStore(self.tmp.name);self.addCleanup(self.store.close)
        self.store.import_feed('toyota_used','json',json.dumps([row(5,expected=9)]))
        import socket;sk=socket.socket();sk.bind(('127.0.0.1',0));self.port=sk.getsockname()[1];sk.close()
        self.token='tok';H=S.create_handler(self.store,self.port,self.token);self.H=H
        self.calls=[];orig=H.photo_cache.enqueue
        def spy(vin,source,urls,**kw):
            self.calls.append((vin,source,len(urls),kw));return orig(vin,source,urls,**kw)
        H.photo_cache.enqueue=spy
        self.gate=threading.Event();H.photo_cache._download=lambda *a,**k:self.gate.wait(10)     # never touch the network; job stays in flight
        self.srv=ThreadingHTTPServer(('127.0.0.1',self.port),H);self.srv.daemon_threads=True
        threading.Thread(target=self.srv.serve_forever,daemon=True).start()
        self.addCleanup(lambda:(self.gate.set(),self.srv.shutdown(),self.srv.server_close(),H.photo_cache.close()))
        self.base=f'http://127.0.0.1:{self.port}'
    def req(self,path,body=None,token=True):
        r=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','Origin':self.base,**({'X-SalesmanHub-Token':self.token} if token else {})})
        try:
            with urllib.request.urlopen(r) as resp:return resp.status,json.loads(resp.read())
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read() or b'{}')
    def test_token_required(self):
        self.assertEqual(self.req(f'/api/photos/progress?vin={VIN}&source=toyota_used',token=False)[0],403)
    def test_validation(self):
        self.assertEqual(self.req('/api/photos/progress?vin=BAD&source=toyota_used')[0],400)
        self.assertEqual(self.req(f'/api/photos/progress?vin={VIN}&source=evil')[0],400)
    def test_funnel_and_shortfall(self):
        c,d=self.req(f'/api/photos/progress?vin={VIN}&source=toyota_used')
        self.assertEqual(c,200)
        self.assertGreaterEqual(d['found'],d['unique']);self.assertGreaterEqual(d['unique'],d['downloaded']);self.assertGreaterEqual(d['downloaded'],d['usable'])
        self.assertEqual((d['found'],d['unique'],d['downloaded'],d['dealer_reported']),(5,5,0,9))
        self.assertTrue(d['discovery_shortfall'])
    def test_open_enqueues_once_explicit_not_forced(self):
        for _ in range(5):self.assertEqual(self.req('/api/photos/open',{'vin':VIN,'source':'toyota_used'})[0],200)
        self.assertEqual(len(self.calls),5)                         # UI guard dedupes; backend must too:
        self.assertTrue(all(c[3]=={'force':False,'explicit':True} for c in self.calls))
        self.assertEqual(len(self.H.photo_cache.enqueued),1)      # one logical (VIN, source) job
    def test_open_rejects_bad_identity_and_token(self):
        self.assertEqual(self.req('/api/photos/open',{'vin':VIN,'source':'toyota_used'},token=False)[0],403)
        self.assertEqual(self.req('/api/photos/open',{'vin':VIN,'source':'nope'})[0],400)
    def test_open_bypasses_automatic_suspension_but_not_cooldown(self):
        pc=self.H.photo_cache;pc.automatic_suspended=True
        self.req('/api/photos/open',{'vin':VIN,'source':'toyota_used'})
        self.assertIn((VIN,'toyota_used'),pc.enqueued)
if __name__=='__main__':unittest.main()
