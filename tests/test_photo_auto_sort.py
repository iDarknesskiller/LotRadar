"""Photo Auto Sort hotfix: first-open trigger, retry, completion stamp. Mocked AI only; no network, no paid calls."""
import http.client,json,os,sys,tempfile,threading,time,unittest,urllib.error
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import photo_classify as PC
import server as S
from core import MarketplaceStore
from PIL import Image

VIN='1HGCM82633A004352';SRC='toyota_used'
def jpeg(n):
    out=BytesIO();Image.new('RGB',(16,16),(n*37%256,n*91%256,n*53%256)).save(out,'JPEG');return out.getvalue()
def gallery(n=6):          # 01 cover, 02 dedication (no url), then n-2 classifiable photos
    return [(f'photos/{i:02d}.jpg',jpeg(i),None if i==2 else f'https://pictures.dealer.com/img/{i}.jpg') for i in range(1,n+1)]

class FakeAI:
    """Stands in for urllib.request.urlopen inside photo_classify. mode: ok | partial | http500."""
    def __init__(self,mode='ok'):self.mode,self.requests,self.images=mode,0,0
    def __call__(self,request,timeout=0):
        body=json.loads(request.data);parts=body['input'][0]['content']
        n=sum(1 for p in parts if p['type']=='input_image');self.requests+=1;self.images+=n
        if self.mode=='http500':raise urllib.error.HTTPError(request.full_url,500,'boom',{},None)
        ids=range(1,n+1 if self.mode=='ok' else n)
        text=json.dumps({'photos':[{'id':i,'category':'exterior'} for i in ids]})
        raw=json.dumps({'output':[{'content':[{'text':text}]}]}).encode()
        class R:
            def __enter__(s):return s
            def __exit__(s,*a):return False
            def read(s,_n=-1):return raw
        return R()

class Unit(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=mock.patch.dict(os.environ,{'OPENAI_API_KEY':'test-key'});env.start();self.addCleanup(env.stop)
        self.cats=PC.PhotoCategories(self.tmp.name);self.frames=PC.classifiable(gallery())
    def run_gallery(self,ai,frames=None,cats=None):
        return (cats or self.cats).classify_gallery(VIN,SRC,frames or self.frames,opener=ai)
    def test_stamp_after_full_success_survives_restart_with_zero_calls(self):
        ai=FakeAI();res=self.run_gallery(ai)
        self.assertTrue(res['complete']);self.assertEqual((ai.requests,ai.images),(1,4))
        stamp=json.loads((Path(self.tmp.name)/'photo_categories.json').read_text())[PC.STAMPS][f'{VIN}|{SRC}']
        self.assertEqual((stamp['v'],stamp['n']),(PC.VERSION,4));self.assertTrue(stamp['at'].endswith('+00:00'))
        again=PC.PhotoCategories(self.tmp.name)
        self.assertFalse(again.needs_sort(VIN,SRC,self.frames))
        ai2=FakeAI();self.assertTrue(self.run_gallery(ai2,cats=again)['complete']);self.assertEqual(ai2.requests,0)
    def test_partial_or_failed_answer_never_stamps_and_retry_finishes(self):
        for mode in ('partial','http500'):
            res=self.run_gallery(FakeAI(mode));self.assertFalse(res['complete']);self.assertTrue(res['error'])
            self.assertTrue(self.cats.needs_sort(VIN,SRC,self.frames))
        self.assertNotIn(PC.STAMPS,self.cats.cache)
        self.assertTrue(self.run_gallery(FakeAI())['complete']);self.assertFalse(self.cats.needs_sort(VIN,SRC,self.frames))
    def test_missing_key_is_not_complete(self):
        with mock.patch.dict(os.environ,{'OPENAI_API_KEY':''}):res=self.run_gallery(FakeAI())
        self.assertFalse(res['complete']);self.assertTrue(res['error'])
    def test_changed_gallery_classifies_only_new_hashes(self):
        self.run_gallery(FakeAI());ai=FakeAI()
        bigger=PC.classifiable(gallery(7))
        self.assertTrue(self.cats.needs_sort(VIN,SRC,bigger))
        self.assertTrue(self.run_gallery(ai,bigger)['complete']);self.assertEqual(ai.images,1)
    def test_cache_coverage_beats_timestamp_and_version_invalidates(self):
        self.run_gallery(FakeAI())
        victim=PC.hashlib.sha256(self.frames[0][1]).hexdigest()
        del self.cats.cache[victim];self.assertTrue(self.cats.needs_sort(VIN,SRC,self.frames))
        self.run_gallery(FakeAI());self.assertFalse(self.cats.needs_sort(VIN,SRC,self.frames))
        with mock.patch.object(PC,'VERSION',PC.VERSION+1):self.assertTrue(self.cats.needs_sort(VIN,SRC,self.frames))
    def test_empty_gallery_is_never_stamped(self):
        self.assertFalse(self.cats.needs_sort(VIN,SRC,[]))
        self.assertFalse(self.cats.classify_gallery(VIN,SRC,[],opener=FakeAI())['complete'])
        self.assertNotIn(PC.STAMPS,self.cats.cache)
    def test_unreadable_photo_is_skipped_not_retried_forever(self):
        frames=self.frames+[('u-bad',b'not an image')];ai=FakeAI()
        self.assertTrue(self.run_gallery(ai,frames)['complete']);self.assertEqual(ai.images,4)
        self.assertFalse(self.cats.needs_sort(VIN,SRC,frames))
    def test_known_ignores_stamp_entries(self):
        self.run_gallery(FakeAI());self.assertEqual(len(self.cats.known(self.frames)),4)
    def test_sorter_dedupes_and_applies_retry_cooldown(self):
        gate=threading.Event();calls=[]
        def job(vin,source):calls.append(1);gate.wait(5);return {'error':'boom','total':3}
        sorter=PC.AutoSorter(job,spacing=0);self.addCleanup(sorter.stop)
        self.assertTrue(sorter.request(VIN,SRC));self.assertFalse(sorter.request(VIN,SRC))
        gate.set()
        for _ in range(100):
            if not sorter.state(VIN,SRC)['running']:break
            time.sleep(.05)
        self.assertEqual(len(calls),1)
        self.assertFalse(sorter.request(VIN,SRC,cooldown=60))       # automatic retry held back
        self.assertTrue(sorter.request(VIN,SRC))                    # explicit request is not

class Route(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=mock.patch.dict(os.environ,{'OPENAI_API_KEY':'test-key'});env.start();self.addCleanup(env.stop)
        self.ai=FakeAI();patch=mock.patch('photo_classify.urllib.request.urlopen',self.ai);patch.start();self.addCleanup(patch.stop)
        self.store=MarketplaceStore(self.tmp.name);self.addCleanup(self.store.close)
        self.store.import_feed('toyota_used','json',json.dumps([{'vin':VIN,'condition':'used','year':2022,'make':'Hyundai','model':'Tucson','stock':'T1',
            'mileage':1000,'price':20000,'url':'https://dealer.example/v/1','images':[f'https://pictures.dealer.com/img/{i}.jpg' for i in range(1,7)]}]))
        import socket;sk=socket.socket();sk.bind(('127.0.0.1',0));self.port=sk.getsockname()[1];sk.close()
        self.H=S.create_handler(self.store,self.port,'tok');self.H.auto_sorter.spacing=0
        self.downloads=[];orig=self.H.photo_cache.enqueue
        self.H.photo_cache.enqueue=lambda *a,**k:(self.downloads.append(a),orig(*a,**k))[1]
        self.frames=gallery();self.ready=True
        def frames_or_not_ready(*a,**k):
            if not self.ready:raise ValueError('no_export_ready_photos; download_and_screen_vehicle_photos_first')
            return list(self.frames)
        self.H.photo_cache.prepared_export_frames=frames_or_not_ready
        self.srv=ThreadingHTTPServer(('127.0.0.1',self.port),self.H);self.srv.daemon_threads=True
        threading.Thread(target=self.srv.serve_forever,daemon=True).start()
        self.addCleanup(lambda:(self.srv.shutdown(),self.srv.server_close(),self.H.auto_sorter.stop(),self.H.photo_cache.close()))
    def call(self,path,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        conn.request('POST' if body is not None else 'GET',path,None if body is None else json.dumps(body),
            {'X-SalesmanHub-Token':'tok','Origin':f'http://127.0.0.1:{self.port}','Content-Type':'application/json'})
        res=conn.getresponse();data=json.loads(res.read() or b'{}');conn.close();return res.status,data
    def open_menu(self):return self.call(f'/api/photos/selection?vin={VIN}&source={SRC}')
    def idle(self):
        for _ in range(200):
            if not self.call(f'/api/photos/classify?vin={VIN}&source={SRC}')[1]['running']:return
            time.sleep(.05)
        self.fail('sorter did not finish')
    def stamp_exists(self):
        try:return f'{VIN}|{SRC}' in json.loads((Path(self.tmp.name)/'photo_categories.json').read_text()).get(PC.STAMPS,{})
        except OSError:return False
    def test_first_open_of_downloaded_gallery_sorts_once_without_redownload(self):
        code,first=self.open_menu();self.assertEqual(code,200)
        self.assertTrue(first['auto_sort']['running'])                      # queued by the very first open
        self.idle()
        code,second=self.open_menu()
        self.assertEqual(len(second['auto_groups']),4);self.assertTrue(second['auto_sort']['complete'])
        self.assertEqual((self.ai.requests,self.ai.images),(1,4));self.assertEqual(self.downloads,[]);self.assertTrue(self.stamp_exists())
        for _ in range(3):self.open_menu()
        self.idle();self.assertEqual(self.ai.requests,1)                    # completed + unchanged: zero further calls
    def test_rapid_opens_make_one_job(self):
        for _ in range(8):self.open_menu()
        self.idle();self.assertEqual(self.ai.requests,1)
    def test_failed_sort_is_not_stamped_and_reopen_retries_after_cooldown(self):
        self.ai.mode='http500';self.open_menu();self.idle()
        status=self.call(f'/api/photos/classify?vin={VIN}&source={SRC}')[1]
        self.assertTrue(status['error']);self.assertFalse(status['complete']);self.assertFalse(self.stamp_exists())
        self.open_menu();self.idle();self.assertEqual(self.ai.requests,1)   # inside the cooldown: no paid retry loop
        self.ai.mode='ok'
        with mock.patch.object(S,'AUTO_SORT_RETRY_SECONDS',0):self.open_menu()
        self.idle();self.assertEqual(self.ai.requests,2);self.assertTrue(self.stamp_exists());self.assertEqual(self.downloads,[])
    def test_auto_sort_off_blocks_automatic_work(self):
        self.assertEqual(self.call('/api/photos/auto-sort',{'enabled':False})[0],200)
        code,data=self.open_menu();self.idle()
        self.assertEqual(code,200);self.assertFalse(data['auto_sort']['running']);self.assertEqual(self.ai.requests,0)
        self.H.photo_cache.on_finished(VIN,SRC);self.idle();self.assertEqual(self.ai.requests,0);self.assertFalse(self.stamp_exists())
    def test_unready_gallery_stays_pending_then_download_hook_sorts(self):
        self.ready=False
        self.assertEqual(self.open_menu()[0],400)
        self.H.photo_cache.on_finished(VIN,SRC);self.idle()
        self.assertEqual(self.ai.requests,0);self.assertFalse(self.stamp_exists())
        self.ready=True;self.H.photo_cache.on_finished(VIN,SRC);self.idle()
        self.assertEqual(self.ai.requests,1);self.assertTrue(self.stamp_exists())
    def test_originals_untouched(self):
        before=[b for _n,b,_u in self.frames];self.open_menu();self.idle()
        self.assertEqual([b for _n,b,_u in self.frames],before)

if __name__=='__main__':unittest.main()
