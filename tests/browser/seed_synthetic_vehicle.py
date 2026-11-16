import sys,json,hashlib,random,io
from pathlib import Path
app=Path(sys.argv[1]);data=Path(sys.argv[2]);n=int(sys.argv[3]) if len(sys.argv)>3 else 30;partial=int(sys.argv[4]) if len(sys.argv)>4 else n
sys.path.insert(0,str(app))
from PIL import Image,ImageDraw
import photo_cache as P
def sorted_box(r):
    a,b,c,d=r.randrange(900),r.randrange(540),r.randrange(900),r.randrange(540);return [min(a,c),min(b,d),max(a,c)+1,max(b,d)+1]
from core import MarketplaceStore
(app/'branding').mkdir(exist_ok=True)
Image.new('RGB',(600,340),(30,60,160)).save(app/'branding'/'business_card.png')
Image.new('RGB',(1000,750),(200,40,40)).save(app/'branding'/'dedication.jpg',quality=90)
VIN='1HGCM82633A004352';SRC='toyota_used'
urls=[f'https://pictures.dealer.com/t/p{i:02d}.jpg' for i in range(1,n+1)]
st=MarketplaceStore(str(data))
st.import_feed(SRC,'json',json.dumps([{'vin':VIN,'condition':'used','year':2022,'make':'Hyundai','model':'Tucson','stock':'T1','mileage':1000,'price':20000,'url':'https://www.hamptontoyota.com/used/x.htm','images':urls,'photo_gallery_expected':n+4}]))
pc=P.PhotoCache(st.root);d=pc._directory(VIN,SRC);d.mkdir(parents=True,exist_ok=True)
rnd=random.Random(7);entries={}
for i,u in enumerate(urls[:partial],1):
    im=Image.new('RGB',(1000,640),(rnd.randrange(256),rnd.randrange(256),rnd.randrange(256)));dr=ImageDraw.Draw(im)
    for _ in range(40):dr.rectangle(sorted_box(rnd),fill=tuple(rnd.randrange(256) for _ in range(3)))
    dr.text((20,20),f'PHOTO {i:02d}',fill=(255,255,255))
    b=io.BytesIO();im.save(b,'JPEG',quality=88);blob=b.getvalue()
    f=f'{i:02d}_{hashlib.sha256(u.encode()).hexdigest()[:24]}.jpg';(d/f).write_bytes(blob)
    w,h,vh=P.photo_signature(blob)
    entries[u]={'file':f,'size':len(blob),'status':'saved','error':'','width':w,'height':h,'visual_hash':vh,'screen_version':61,'category':'vehicle','quality_reason':'ok','quality_checked':True}
pc._save(VIN,SRC,{'urls':urls,'entries':entries,'updated_at':None})
pc.close();st.close();print('seeded',len(entries),'of',n)
