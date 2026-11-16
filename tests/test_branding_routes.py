"""Branding routes: exact allowlist, content types, byte identity, graceful fallback. Synthetic images only."""
import json,shutil,socket,sys,tempfile,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import server as S
from core import MarketplaceStore
from test_installer_build import LOGO,ICO
class Branding(unittest.TestCase):
    def start(self,with_assets):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)/'app';base.mkdir()
        for n in ('index.html','app.js','styles.css','photo-selection.css'):shutil.copy(Path(S.BASE)/n,base/n)
        if with_assets:
            (base/'branding').mkdir();(base/'branding'/'lotradar_logo.png').write_bytes(LOGO);(base/'LotRadar.ico').write_bytes(ICO)
        old=S.BASE;S.BASE=base;self.addCleanup(setattr,S,'BASE',old)
        store=MarketplaceStore(Path(self.tmp.name)/'data');self.addCleanup(store.close)
        sk=socket.socket();sk.bind(('127.0.0.1',0));self.port=sk.getsockname()[1];sk.close()
        H=S.create_handler(store,self.port,'t');srv=ThreadingHTTPServer(('127.0.0.1',self.port),H);srv.daemon_threads=True
        threading.Thread(target=srv.serve_forever,daemon=True).start()
        self.addCleanup(lambda:(srv.shutdown(),srv.server_close(),H.photo_cache.close()))
    def get(self,path):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{path}') as r:return r.status,r.headers.get('Content-Type'),r.read()
        except urllib.error.HTTPError as e:return e.code,e.headers.get('Content-Type'),e.read()
    def test_logo_served_exact_bytes_png(self):
        self.start(True);c,t,b=self.get('/branding/lotradar_logo.png');self.assertEqual((c,t,b),(200,'image/png',LOGO))
        c,t,b=self.get('/favicon.ico');self.assertEqual((c,b),(200,ICO));self.assertEqual(t,'image/x-icon')
    def test_index_uses_logo_with_name_and_favicon(self):
        self.start(True);html=self.get('/')[2].decode()
        self.assertIn('class="brand-logo"',html);self.assertIn('width="112" height="112"',html);self.assertIn('alt="LotRadar"',html);self.assertIn('rel="icon"',html);self.assertIn('LOT<span>RADAR</span>',html)
    def test_fallback_without_assets(self):
        self.start(False);html=self.get('/')[2].decode()
        self.assertIn('L<span>R</span>',html);self.assertNotIn('class="brand-logo"',html);self.assertNotIn('rel="icon"',html)
        self.assertEqual(self.get('/branding/lotradar_logo.png')[0],404);self.assertEqual(self.get('/favicon.ico')[0],204)
    def test_no_arbitrary_paths(self):
        self.start(True)
        for p in ('/branding/','/branding/business_card.png','/branding/../server.py','/branding/%2e%2e/server.py','/LotRadar.ico','/branding/lotradar_logo.png/x'):
            self.assertEqual(self.get(p)[0],404,p)
    def test_corrupt_logo_is_not_used(self):
        self.start(True);(Path(S.BASE)/'branding'/'lotradar_logo.png').write_bytes(b'not a png at all, sorry')
        self.assertEqual(self.get('/branding/lotradar_logo.png')[0],404);self.assertNotIn('class="brand-logo"',self.get('/')[2].decode())
if __name__=='__main__':unittest.main()
