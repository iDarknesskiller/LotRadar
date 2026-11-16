"""Selection order is click history: get/save/export must never reorder by gallery or category."""
import io,json,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photo_cache import select_export_frames,frame_key
from photo_selection import PhotoSelections

VIN='1HGCM82633A004352';SRC='toyota_used'
def frames(n=30):
    out=[]
    for i in range(1,n+1):
        url=None if i==2 else f'https://dealer.example/p{i:02d}.jpg'
        out.append((f'photos/{i:02d}.jpg',f'img{i}'.encode(),url))
    return out
def key(i):return frame_key(frames()[i-1])
CLICKS=[1,2,3,11,14,18,20,25,4]
class Order(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.sel=PhotoSelections(Path(self.tmp.name));self.fr=frames()
    def test_save_get_keep_click_order(self):
        keys=[key(i) for i in CLICKS]
        self.sel.save(VIN,SRC,keys,self.fr)
        self.assertEqual(self.sel.get(VIN,SRC,self.fr)['keys'],keys)
        again=PhotoSelections(Path(self.tmp.name))   # restart
        self.assertEqual(again.get(VIN,SRC,self.fr)['keys'],keys)
    def test_select_export_frames_click_order_ignores_groups(self):
        keys=[key(i) for i in CLICKS]
        groups={key(i):'interior' if i in (3,4) else 'exterior' for i in range(1,31)}
        out,rep=select_export_frames(self.fr,keys,limit=20,groups=groups)
        self.assertEqual([r['gallery_number'] for r in rep['files']],CLICKS)
        self.assertEqual([n for n,_,_ in out],[f'photos/{i:02d}.jpg' for i in range(1,10)])
        self.assertEqual([b for _,b,_ in out],[f'img{i}'.encode() for i in CLICKS])
    def test_missing_keys_reported_not_remapped(self):
        keys=[key(3),'gone-key',key(1)]
        out,rep=select_export_frames(self.fr,keys)
        self.assertEqual(rep['missing_keys'],['gone-key'])
        self.assertEqual([r['gallery_number'] for r in rep['files']],[3,1])
    def test_get_reports_missing_separately(self):
        keys=[key(5),key(2)]
        self.sel.save(VIN,SRC,keys,self.fr)
        got=self.sel.get(VIN,SRC,self.fr[:4])    # photo 5 vanished
        self.assertEqual(got['keys'],[key(2)]);self.assertEqual(got['missing_keys'],[key(5)])
    def test_default_is_cover_then_dedication(self):
        self.assertEqual(self.sel.get(VIN,SRC,self.fr)['keys'],[key(1),key(2)])
    def test_limit_enforced_on_save(self):
        with self.assertRaises(ValueError):self.sel.save(VIN,SRC,[key(i) for i in range(1,22)],self.fr)
    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):self.sel.save(VIN,SRC,[key(1),key(1)],self.fr)
    def test_source_isolation(self):
        a=[key(3),key(1)];b=[key(1),key(3)]
        self.sel.save(VIN,'toyota_used',a,self.fr);self.sel.save(VIN,'mitsubishi_used',b,self.fr)
        self.assertEqual(self.sel.get(VIN,'toyota_used',self.fr)['keys'],a)
        self.assertEqual(self.sel.get(VIN,'mitsubishi_used',self.fr)['keys'],b)
    def test_reselect_moves_to_end(self):
        keys=[key(i) for i in (1,2,3)];self.sel.save(VIN,SRC,keys,self.fr)
        keys=[key(1),key(2),key(5),key(3)];self.sel.save(VIN,SRC,keys,self.fr)
        self.assertEqual(self.sel.get(VIN,SRC,self.fr)['keys'],keys)
    def test_export_zip_json_readme_folder_agree(self):
        keys=[key(i) for i in CLICKS];self.sel.save(VIN,SRC,keys,self.fr)
        rec={'stock':'T1','year':'2022','make':'Hyundai','model':'Tucson'}
        raw,folder,_fn,rep=self.sel.export(VIN,SRC,rec,self.fr,keys)
        z=zipfile.ZipFile(io.BytesIO(raw))
        names=[n for n in z.namelist() if n.startswith('photos/')]
        self.assertEqual(names,[f'photos/{i:02d}.jpg' for i in range(1,10)])
        self.assertEqual([z.read(n) for n in names],[f'img{i}'.encode() for i in CLICKS])
        sj=json.loads(z.read('selection.json'))
        self.assertEqual([r['gallery_number'] for r in sj],CLICKS)
        readme=z.read('README.txt').decode()
        self.assertEqual([l for l in readme.splitlines() if ' = gallery ' in l],[f'photos/{i+1:02d}.jpg = gallery {g:02d}' for i,g in enumerate(CLICKS)])
        if folder is not None:
            self.assertEqual([(folder/f'{i:02d}.jpg').read_bytes() for i in range(1,10)],[f'img{i}'.encode() for i in CLICKS])
if __name__=='__main__':unittest.main()
