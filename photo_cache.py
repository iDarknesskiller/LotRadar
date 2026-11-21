"""Local-only dealership photo cache.

Auto-fetch static, public image assets only after a record has passed VIN/URL
identity checks. Cached photos are for private review; resale/Marketplace reuse
still requires separate rights and listing approval.
"""
from __future__ import annotations
import hashlib
import json
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from io import BytesIO
from collections import Counter, deque

from core import VIN_RE, SOURCES

ALLOWED_HOSTS = frozenset({'pictures.dealer.com','www.hamptontoyota.com','www.hamptonmitsubishi.com'})
MIME = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
MAX_PHOTOS = 250
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VEHICLE_BYTES = 180 * 1024 * 1024

# R21: photo content screening runs locally; never calls a billed AI service.
# Pillow is optional. Without it, ambiguous photographs remain in review and
# cannot be exported as if they were verified vehicle photos.
BAD_GRAPHIC = re.compile(r'(?:^|[\/_.-])(?:logo|brand|placeholder|no-photo|noimage|'
                         r'no_image|icon|sprite|carfax|advertisement|coming-soon|mitsubishi-motors|'
                         r'dealer-logo)(?:[\/_.-]|$)', re.I)

def exact_export_image_key(data):
    """Compare identical decoded pixels, never approximate vehicle angles.
    Metadata/container differences may vary while pixels stay the same.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(BytesIO(data)) as image:
            image=ImageOps.exif_transpose(image).convert('RGBA')
            return ('pixels', image.size, hashlib.sha256(image.tobytes()).digest())
    except (ImportError, OSError, ValueError):
        return ('bytes', hashlib.sha256(data).digest())

def photo_signature(data):
    """Image dimensions and perceptual difference hash for local duplicate detection.

    Hash is used only for matching photos inside the SAME VIN/source gallery.
    It does not modify original images or contact photo hosts.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        # Pillow is optional for browsing. No visual dedupe can run, but the
        # local inventory GET must never crash because of a missing module.
        return 0,0,''
    try:
        with Image.open(BytesIO(data)) as img:
            img=ImageOps.exif_transpose(img)
            width,height=img.size
            gray=img.convert('L').resize((9,8))
            pixels=list(gray.getdata())
        bits=0
        for y in range(8):
            for x in range(8):
                bits=(bits<<1)|int(pixels[y*9+x]>pixels[y*9+x+1])
        return width,height,format(bits,'016x')
    except (OSError, ValueError, TypeError):
        return 0,0,''


def pillow_available():
    try:
        from PIL import Image, ImageOps
        return True
    except ImportError:
        return False


def photo_url_reason(url):
    try:
        from urllib.parse import unquote
        path=unquote(urlsplit(url).path).lower()
        return 'graphic_in_image_filename' if BAD_GRAPHIC.search(path) else None
    except (ValueError,TypeError): return 'invalid_photo_url'


def classify_photo(data, url):
    """Conservative local pixel checks. Unknown => review, not Facebook-ready.

    This is NOT a full semantic car detector. Gallery context is required for new
    collection, and people can flag false positives for review without deleting
    the original bytes.
    """
    reason=photo_url_reason(url)
    if reason: return 'graphic',reason
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return 'review','pillow_not_installed'
    try:
        with Image.open(BytesIO(data)) as im:
            im.load()
            w,h=im.size
            if w<160 or h<120 or w/h>5.5 or w/h<0.35:
                return 'graphic','non_vehicle_image_dimensions'
            if 'A' in im.getbands():
                alpha=im.getchannel('A').resize((48,48))
                if sum(px<240 for px in alpha.getdata())>150:
                    return 'graphic','transparent_logo_or_overlay'
            rgb=ImageOps.exif_transpose(im).convert('RGB').resize((64,64))
            buckets=Counter(((r>>4,g>>4,b>>4) for (r,g,b) in rgb.getdata()))
            top=max(buckets.values())/4096
            # Images with very few color regions and a large flat background
            # are almost always logos, brand plates or placeholders, not cars.
            if len(buckets)<12 or (top>0.78 and len(buckets)<30):
                return 'graphic','flat_color_brand_graphic'
            # Detect the distinctive Hampton promo overlays as REVIEW, not as
            # a logo (the car is real, but the picture isn't export-clean).
            def overlay_colors(region):
                px=list(region.getdata());n=len(px) or 1
                red=sum(r>168 and r>g*1.45 and r>b*1.35 for r,g,b in px)/n
                white=sum(min(r,g,b)>205 for r,g,b in px)/n
                return red,white
            right=im.convert('RGB').crop((int(w*.55),int(h*.67),w,h)).resize((64,32))
            left=im.convert('RGB').crop((0,0,int(w*.36),int(h*.30))).resize((64,32))
            bottom_red,bottom_white=overlay_colors(right)
            top_red,top_white=overlay_colors(left)
            if (bottom_red>.025 and bottom_white>.17) or (top_red>.023 and top_white>.50):
                return 'review','possible_dealership_banner'
            # Low-detail ambiguous images stay review-only; avoid deleting
            # white-car or night-interior photos on a shaky color heuristic.
            if len(buckets)<65 and top>0.40:
                return 'review','low_detail_review_needed'
            return 'vehicle','local_visual_screen_passed'
    except Exception:
        return 'review','image_decode_failed'



# R23: Contacts shown in a distinct white lower-right plate can be replaced
# locally. Never erase/remove the dealer's top logo and never touch originals.
# Require a recognizable red-on-white phone plate before we draw anything.
def replace_contact_plate(data, phone):
    digits=re.sub(r'\D','',str(phone or ''))
    if len(digits)!=10:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
        with Image.open(BytesIO(data)) as original:
            img=ImageOps.exif_transpose(original).convert('RGB')
        w,h=img.size
        if w<280 or h<190 or w/h>3.3 or w/h<0.6:
            return None
        # Scan only the customary lower-right sticker area.
        # Red characters sitting inside an otherwise white plate are distinctive.
        pixels=img.load()
        reds=[]
        step=max(1,min(w,h)//480)
        for y in range(int(h*.64),int(h*.91),step):
            for x in range(int(w*.53),int(w*.985),step):
                r,g,b=pixels[x,y]
                if r>170 and r-g>57 and r-b>55 and g<175:
                    reds.append((x,y))
        if len(reds)<max(12,int(w*h*.0003)/(step*step)):
            return None
        minx=min(x for x,y in reds);maxx=max(x for x,y in reds)
        miny=min(y for x,y in reds);maxy=max(y for x,y in reds)
        if maxx-minx<w*.16 or maxx-minx>w*.48 or maxy-miny>h*.11:
            return None
        x0=max(int(w*.51),minx-int(w*.015));x1=min(w,maxx+int(w*.045))
        y0=max(int(h*.60),miny-int(h*.016));y1=min(h,maxy+int(h*.115))
        if x1-x0<w*.20 or y1-y0<h*.09:
            return None
        region=img.crop((x0,y0,x1,y1)).resize((80,40))
        white=sum(min(rgb)>196 for rgb in region.getdata())/3200
        if white<.45:
            return None
        draw=ImageDraw.Draw(img)
        draw.rectangle((x0,y0,x1,y1),fill=(251,251,251))
        pad=max(2,int((x1-x0)*.025))
        def font_fit(value,maxh,maxw):
            for size in range(max(10,int(maxh)),7,-1):
                try: font=ImageFont.truetype('arial.ttf',size)
                except OSError:
                    try:font=ImageFont.truetype('DejaVuSans-Bold.ttf',size)
                    except OSError:return ImageFont.load_default()
                bb=draw.textbbox((0,0),value,font=font)
                if bb[2]-bb[0]<=maxw and bb[3]-bb[1]<=maxh:return font
            return ImageFont.load_default()
        number=f'{digits[:3]}-{digits[3:6]}-{digits[6:]}'
        font=font_fit(number,int((y1-y0)*.42),(x1-x0)-pad*2)
        subfont=font_fit('Lafayette, LA',int((y1-y0)*.20),(x1-x0)-pad*2)
        bb=draw.textbbox((0,0),number,font=font)
        tw=bb[2]-bb[0]
        draw.text((x0+(x1-x0-tw)/2,y0+pad),number,fill=(206,35,25),font=font)
        bb=draw.textbbox((0,0),'Lafayette, LA',font=subfont)
        draw.text((x0+(x1-x0-(bb[2]-bb[0]))/2,y1-(bb[3]-bb[1])-pad),
                  'Lafayette, LA',fill=(21,26,33),font=subfont)
        output=BytesIO();img.save(output,format='JPEG',quality=93,subsampling=0)
        return output.getvalue()
    except (OSError,ValueError,TypeError):
        return None

# R55: user-supplied promo images are read only from this guarded Marketplace
# branding directory. Source dealership photos and cached originals stay intact.
BRANDING_DIR=Path(__file__).resolve().parent / 'branding'


def _phone_plate_bounds(img):
    """Only recognize the red digits inside a white lower-right dealer sticker.

    Return None rather than risk painting over an ordinary car photo or logo.
    """
    w,h=img.size
    if w<320 or h<220 or w/h>3.3 or w/h<.6:
        return None
    rgb=img.convert('RGB')
    pixels=rgb.load()
    step=max(1,min(w,h)//480)
    reds=[]
    for y in range(int(h*.64),int(h*.91),step):
        for x in range(int(w*.53),int(w*.985),step):
            r,g,b=pixels[x,y]
            if r>170 and r-g>57 and r-b>55 and g<175:
                reds.append((x,y))
    if len(reds)<max(12,int(w*h*.0003)/(step*step)):
        return None
    # Keep only the densest horizontal band of red: the phone digits. Small red
    # or amber details elsewhere in the search box (side-marker lights, brake
    # calipers, reflections) must not stretch the sticker bounds.
    gap=max(2,int(h*.015))
    bands=[];current=[]
    for point in sorted(reds,key=lambda p:p[1]):
        if current and point[1]-current[-1][1]>gap:
            bands.append(current);current=[]
        current.append(point)
    if current:bands.append(current)
    reds=max(bands,key=len)
    if len(reds)<max(12,int(w*h*.0003)/(step*step)):
        return None
    minx=min(x for x,y in reds);maxx=max(x for x,y in reds)
    miny=min(y for x,y in reds);maxy=max(y for x,y in reds)
    if maxx-minx<w*.16 or maxx-minx>w*.48 or maxy-miny>h*.11:
        return None
    x0=max(int(w*.51),minx-int(w*.015))
    x1=min(w,maxx+int(w*.045))
    y0=max(int(h*.60),miny-int(h*.016))
    y1=min(h,maxy+int(h*.115))
    if x1-x0<w*.20 or y1-y0<h*.09:
        return None
    region=rgb.crop((x0,y0,x1,y1)).resize((80,40))
    white=sum(min(px)>196 for px in region.getdata())/3200
    if white<.45:
        return None
    # Require sticker to be in the lower-right quadrant, not just red text.
    if x0 < w*.49 or y0 < h*.58 or x1 < w*.76:
        return None
    return x0,y0,x1,y1


def overlay_business_card_on_sticker(data,card_bytes):
    """Overlay the UNMODIFIED full business card on the phone sticker in an export copy.

    Returns None when no confident sticker is found. Never alters the source.
    """
    try:
        from PIL import Image, ImageOps, ImageDraw
        with Image.open(BytesIO(data)) as src:
            base=ImageOps.exif_transpose(src).convert('RGB')
        bounds=_phone_plate_bounds(base)
        if bounds is None:
            return None
        with Image.open(BytesIO(card_bytes)) as brand:
            brand=ImageOps.exif_transpose(brand).convert('RGBA')
            brand.load()
        w,h=base.size
        left,top,right,bottom=bounds
        aspect=brand.width/max(1,brand.height)
        # Keep all card contents. Sizing is based on the sticker plus a small
        # safety margin, so the old dealership phone is fully hidden.
        margin=0  # The sticker may reach the actual bottom/right image edge.
        target_right=w
        target_bottom=h
        card_width=max(round(w*.36),round(target_right-left+w*.012))
        card_width=min(card_width,round(w*.54))
        card_height=round(card_width/aspect)
        # Expand only if required to cover the full detected sticker vertically.
        if target_bottom-card_height>top:
            card_height=target_bottom-top+round(h*.01)
            card_width=round(card_height*aspect)
        if card_width>round(w*.58) or card_height>round(h*.46):
            return None
        x=target_right-card_width
        y=target_bottom-card_height
        if x>left or y>top or target_right<right or target_bottom<bottom:
            return None
        resampling=getattr(Image,'Resampling',Image)
        card=brand.resize((card_width,card_height),resampling.LANCZOS)
        base.paste(card,(x,y),card)
        out=BytesIO()
        base.save(out,format='JPEG',quality=94,subsampling=0)
        return out.getvalue()
    except (OSError,ValueError,TypeError):
        return None


def dedication_export_image(data):
    """Make the supplied dedication picture large enough for a photo gallery.

    Upscaling is interpolation only: no new photographic detail is invented.
    """
    from PIL import Image, ImageOps
    with Image.open(BytesIO(data)) as img:
        img=ImageOps.exif_transpose(img).convert('RGB')
        img.load()
    resampling=getattr(Image,'Resampling',Image)
    size=1080
    img=ImageOps.contain(img,(size,size),method=resampling.LANCZOS)
    if img.size!=(size,size):
        canvas=Image.new('RGB',(size,size),(9,14,20))
        x=(size-img.width)//2;y=(size-img.height)//2
        canvas.paste(img,(x,y));img=canvas
    out=BytesIO();img.save(out,format='JPEG',quality=94,subsampling=0)
    return out.getvalue()


def clean_url(raw):
    if not isinstance(raw, str) or len(raw) > 2048: return None
    try:
        u = urlsplit(raw.strip())
        if (u.scheme != 'https' or (u.hostname or '').lower() not in ALLOWED_HOSTS
            or u.username or u.password or u.port not in (None, 443)
            or not u.path.lower().endswith(('.jpg','.jpeg','.png','.webp'))):
            return None
        return raw.strip()
    except ValueError: return None


def sniff_image(raw):
    if raw.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if raw.startswith(b'RIFF') and raw[8:12] == b'WEBP': return 'image/webp'
    return None


class CheckedRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not clean_url(newurl):
            raise ValueError('image_redirect_not_allowlisted')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_image(url):
    """Bounded public asset request; no cookies, credentials, bypass or proxy tricks."""
    if not clean_url(url): raise ValueError('image_url_not_allowlisted')
    opener = build_opener(CheckedRedirect)
    with opener.open(Request(url, headers={'Accept':'image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8'}), timeout=12) as r:
        if not clean_url(r.geturl()): raise ValueError('image_final_url_not_allowlisted')
        header_type = (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if header_type not in MIME: raise ValueError('response_not_supported_image')
        declared = r.headers.get('Content-Length')
        if declared and int(declared) > MAX_IMAGE_BYTES: raise ValueError('image_exceeds_size_limit')
        data = r.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES: raise ValueError('image_exceeds_size_limit')
        media_type = sniff_image(data)
        if media_type not in MIME or media_type != header_type: raise ValueError('image_signature_mismatch')
        return data, MIME[media_type]


def fullsize_photo_url(url):
    parsed=urlsplit(url)
    if parsed.hostname!='pictures.dealer.com':return url
    directory,sep,name=parsed.path.rpartition('/')
    if not name.startswith('thumb_'):return url
    return parsed._replace(path=directory+sep+name[6:]).geturl()

def recover_fullsize(url,downloader):
    candidate=fullsize_photo_url(url)
    data,ext=downloader(candidate)
    width,height,visual_hash=photo_signature(data)
    if width<550 or height<300:raise ValueError('fullsize_photo_still_too_small')
    return data,ext

class VehiclePriorityQueue(queue.Queue):
    def __init__(self,priorities,levels):
        super().__init__(maxsize=2500)
        self.priorities=priorities
        self.levels=levels
    def rank(self,job):
        deadline=self.priorities.get(job[0],0)
        return (self.levels.get(job[0],2),deadline) if deadline>time.time() else (0,0)
    def _get(self):
        # Most recent posting request first; stable FIFO for bulk work.
        best=max(range(len(self.queue)),key=lambda i:self.rank(self.queue[i]))
        item=self.queue[best];del self.queue[best];return item
    def has_priority(self,level=0):
        with self.mutex:return any(self.rank(job)[0]>level for job in self.queue)

class PhotoCache:
    def __init__(self, root, *, downloader=fetch_image, restore_trade_vins=None):
        self.root = Path(root).resolve() / 'vehicle_photos'
        self.root.mkdir(parents=True, exist_ok=True)
        self.preferences_path = self.root.parent / 'marketplace_photo_settings.json'
        self._preparing = threading.Lock()
        self.downloader = downloader
        self.lock = threading.RLock()
        self.priorities={}
        self.priority_levels={}
        self.foreground_scan_pending=lambda:False
        # Called with (vin, source) after a photo job finishes normally (not stopped/yielded/rescheduled).
        self.on_finished=None
        self.jobs = VehiclePriorityQueue(self.priorities,self.priority_levels)
        self.enqueued = set()
        self.reschedule = {}
        self.progress_jobs = {}
        self.progress_recent = deque(maxlen=18)
        self.progress_samples = deque(maxlen=40)
        self.progress_active = None
        self.progress_started = None
        self.queue_path=self.root.parent/'photo_queue.json'
        self.pending_records={}
        self.paused=False
        self.stopping=threading.Event()
        self.active_jobs={}
        self.completed_times=deque(maxlen=120)
        self.queue_generation=0
        self.automatic_suspended=False
        self.trade_scope_fixed=False
        self._restore_queue()
        if restore_trade_vins is not None and not self.trade_scope_fixed:self._fix_trade_scope(set(restore_trade_vins))
        self.workers=[threading.Thread(target=self._worker,name=f'photo-worker-{i}',daemon=True) for i in range(3)]
        for worker in self.workers:worker.start()
        self.worker=self.workers[0]

    def _fix_trade_scope(self,allowed):
        # One-time recovery before workers start. Preserve explicit VIN and bulk jobs.
        with self.lock:
            removed={key for key in self.enqueued if key[0] not in allowed and self.priority_levels.get(key[0])==1}
            kept=[]
            while True:
                try:
                    job=self.jobs.get_nowait();self.jobs.task_done()
                    if (job[0],job[1]) not in removed:kept.append(job)
                except queue.Empty:break
            for key in removed:
                self.enqueued.discard(key);self.pending_records.pop(key,None);self.progress_jobs.pop(key,None)
            for vin in list(self.priorities):
                if vin not in allowed and self.priority_levels.get(vin)==1:
                    self.priorities.pop(vin,None);self.priority_levels.pop(vin,None)
            for job in kept:self.jobs.put_nowait(job)
            self.trade_scope_fixed=True;self._persist_queue()
            self.progress_recent.append({'at':datetime.now(timezone.utc).isoformat(),'message':f'Trade-in scope fix: removed {len(removed)} non-trade-in focused jobs; saved photos retained'})

    def _persist_queue(self):
        payload={'version':1,'trade_scope_fixed':self.trade_scope_fixed,'paused':self.paused,'automatic_suspended':self.automatic_suspended,'jobs':list(self.pending_records.values()),'priorities':self.priorities,'priority_levels':self.priority_levels}
        temp=self.queue_path.with_suffix('.tmp')
        temp.write_text(json.dumps(payload),encoding='utf-8')
        os.replace(temp,self.queue_path)

    def _restore_queue(self):
        with self.lock:
            try:
                saved=json.loads(self.queue_path.read_text('utf-8'))
                self.trade_scope_fixed=saved.get('trade_scope_fixed') is True
                self.paused=saved.get('paused') is True
                self.automatic_suspended=saved.get('automatic_suspended') is True
                self.priorities.update({v:float(expiry) for v,expiry in saved.get('priorities',{}).items() if isinstance(expiry,(int,float)) and expiry>time.time()})
                self.priority_levels.update({v:int(level) for v,level in saved.get('priority_levels',{}).items() if level in (1,2)})
                records=saved.get('jobs',[])
            except (OSError,ValueError,TypeError):
                # Upgrade/recovery: the old queue was RAM-only. Recover unfinished
                # manifests once, without re-requesting complete cached galleries.
                records=[]
                for path in self.root.glob('*/*/manifest.json'):
                    try:
                        manifest=json.loads(path.read_text('utf-8'))
                        entries=manifest.get('entries',{})
                        if any(not entries.get(u,{}).get('file') or not (path.parent/entries[u]['file']).is_file() for u in manifest.get('urls',[])):
                            records.append({'vin':path.parent.parent.name,'source':path.parent.name,'urls':manifest.get('urls',[]),'force':False})
                    except (OSError,ValueError,KeyError):continue
            for record in records[:2500]:
                try:
                    vin,source=record['vin'],record['source'];self._directory(vin,source)
                    urls=list(dict.fromkeys(u for u in record['urls'] if clean_url(u)))[:MAX_PHOTOS]
                    if not urls:continue
                    key=(vin,source)
                    if key in self.enqueued:continue
                    self._track_queue(vin,source,self.status(vin,source,urls,analyze=False))
                    self.pending_records[key]={'vin':vin,'source':source,'urls':urls,'force':bool(record.get('force'))}
                    self.enqueued.add(key);self.jobs.put_nowait((vin,source,tuple(urls),bool(record.get('force')),self.queue_generation))
                except (KeyError,ValueError,TypeError,queue.Full):continue
            self._persist_queue()

    def priority_level(self,vin):
        return self.priority_levels.get(vin,2) if self.priorities.get(vin,0)>time.time() else 0

    def has_priority_work(self):
        with self.lock:return not self.paused and any(self.priority_level(v)>0 for v,s in self.enqueued)

    def prioritize(self,vin,level=2):
        vin=str(vin).upper()
        if not VIN_RE.fullmatch(vin):raise ValueError('invalid_photo_identity')
        with self.lock:
            self.priority_levels[vin]=max(level,self.priority_level(vin))
            self.priorities[vin]=time.time()+(86400 if level==1 else 1800)
            self.priorities={v:e for v,e in self.priorities.items() if e>time.time()}
            self.jobs.priorities=self.priorities
            self._persist_queue()
            self.progress_recent.append({'at':datetime.now(timezone.utc).isoformat(),'message':f'Priority photos: {vin} moved ahead of bulk downloads'})
        return self.progress()

    def clear_queue(self):
        with self.lock:
            self.queue_generation+=1
            self.automatic_suspended=True
            self.paused=False
            while True:
                try:self.jobs.get_nowait();self.jobs.task_done()
                except queue.Empty:break
            self.enqueued.clear();self.pending_records.clear();self.reschedule.clear()
            self.priorities.clear();self.priority_levels.clear()
            self.progress_jobs.clear();self.progress_recent.clear();self.completed_times.clear()
            self._persist_queue()
        return self.progress()

    def control(self,paused):
        with self.lock:
            if not paused:self.automatic_suspended=False
            self.paused=bool(paused);self.completed_times.clear();self._persist_queue()
        return self.progress()

    def close(self):
        self.stopping.set()
        with self.lock:self._persist_queue()
        for worker in self.workers:worker.join(timeout=.2)

    def _wait_photo_slot(self,generation=None):
        while self.paused and generation==self.queue_generation and not self.stopping.wait(.1):pass
        return not self.stopping.is_set() and (generation is None or generation==self.queue_generation)

    # R26: settings stay under the user's local Marketplace data directory,
    # never in the app installation or browser extension. Export copies only.
    def preferences(self):
        with self.lock:
            try:
                cfg=json.loads(self.preferences_path.read_text('utf-8'))
                if not isinstance(cfg,dict): cfg={}
            except (ValueError,OSError,TypeError): cfg={}
            phone=str(cfg.get('contact_number') or '')
            phone=phone if re.fullmatch(r'[0-9]{10}',phone) else ''
            covers=cfg.get('covers') if isinstance(cfg.get('covers'),dict) else {}
            return {'contact_number':phone,'auto_replace':bool(cfg.get('auto_replace',False)) and bool(phone),
                    'covers':covers}

    def _write_preferences(self, value):
        self.preferences_path.parent.mkdir(parents=True,exist_ok=True)
        stage=self.preferences_path.with_suffix('.new')
        stage.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
        os.replace(stage,self.preferences_path)

    def set_preferences(self, number, auto_replace):
        digits=re.sub(r'[^0-9]','',str(number or ''))
        if digits and len(digits)!=10:raise ValueError('contact_number_must_contain_10_digits')
        if not isinstance(auto_replace,bool):raise ValueError('auto_replace_must_be_boolean')
        with self.lock:
            value=self.preferences()
            value.update(contact_number=digits,auto_replace=bool(auto_replace and digits))
            self._write_preferences(value)
        return {'contact_number':digits,'auto_replace':value['auto_replace']}

    def set_cover(self,vin,source,url,urls):
        if not VIN_RE.fullmatch(str(vin or '')) or source not in SOURCES:
            raise ValueError('invalid_photo_identity')
        if not isinstance(url,str) or url not in urls or not clean_url(url):
            raise ValueError('cover_photo_not_in_vehicle_gallery')
        status=self.status(vin,source,urls)
        match=next((p for p in status['photos'] if p['url']==url),None)
        if not match or match['category']=='graphic' or photo_url_reason(url) or match.get('duplicate_of') is not None:
            raise ValueError('cannot_use_graphic_or_duplicate_as_cover')
        with self.lock:
            prefs=self.preferences()
            prefs['covers'][vin+':'+source]=url
            self._write_preferences(prefs)
        return {'index':match['index'],'manual':True}

    def cover_choice(self,vin,source,urls,status=None,*,lead_url=None):
        status=status or self.status(vin,source,urls)
        photos=[p for p in status['photos'] if p.get('category')!='graphic' and
                p.get('duplicate_of') is None and clean_url(p['url']) and not photo_url_reason(p['url'])]
        if not photos:return {'index':None,'manual':False}
        saved=self.preferences().get('covers',{}).get(vin+':'+source)
        manual=next((p for p in photos if p['url']==saved),None)
        if manual:return {'index':manual['index'],'manual':True}
        # Dealer gallery order is usually a stronger exterior-view signal than
        # pixel count. A large wheel detail must not beat the first whole-car shot.
        # Exclude thumbnails only if a sufficiently sharp alternative exists.
        hi=[p for p in photos if not p['downloaded'] or
            (p.get('width',0)>=550 and p.get('height',0)>=300)]
        ranked=hi or photos
        lead=next((p for p in ranked if p['url']==lead_url),None)
        if lead:return {'index':lead['index'],'manual':False}
        ranked.sort(key=lambda p:(p['index'], 0 if p['downloaded'] else 1))
        return {'index':ranked[0]['index'],'manual':False}

    def prepared_variant(self,vin,source,item,number):
        digits=re.sub(r'[^0-9]','',str(number or ''))
        if len(digits)!=10 or not item.get('downloaded') or item.get('quality_reason')!='possible_dealership_banner':
            return None
        try:
            blob,_=self.read_photo(vin,source,item['index'],self._manifest(vin,source).get('urls',[]))
            sig=hashlib.sha256(blob).hexdigest()[:12]
            key=hashlib.sha256(digits.encode()).hexdigest()[:8]
            name=f'prepared_{item["index"]:02d}_{sig}_{key}.jpg'
            path=self._directory(vin,source)/name
            if path.is_file():return path.read_bytes()
            edited=replace_contact_plate(blob,digits)
            if not edited:return None
            temp=path.with_suffix('.new')
            temp.write_bytes(edited);os.replace(temp,path)
            return edited
        except (OSError,ValueError,TypeError):return None

    def prepare_all_cached(self):
        # Rebuild pre-approved export copies in background, no network calls.
        if not self._preparing.acquire(blocking=False):return
        try:
            prefs=self.preferences()
            if not prefs['auto_replace']:return
            processed=0
            for mf in self.root.glob('*/*/manifest.json'):
                if processed>=2000:break
                vin=mf.parent.parent.name;source=mf.parent.name
                if not VIN_RE.fullmatch(vin) or source not in SOURCES:continue
                try:
                    urls=self._manifest(vin,source).get('urls',[])
                    for item in self.status(vin,source,urls)['photos']:
                        if item['quality_reason']=='possible_dealership_banner' and item['downloaded'] and item.get('duplicate_of') is None:
                            self.prepared_variant(vin,source,item,prefs['contact_number'])
                            processed+=1
                            if processed%20==0:time.sleep(0.1)  # yield to live requests
                except Exception:
                    # One damaged cached vehicle never stops background preparation.
                    continue
        finally:self._preparing.release()

    def _directory(self, vin, source):
        vin = str(vin or '').upper()
        if not VIN_RE.fullmatch(vin) or source not in SOURCES:
            raise ValueError('invalid_photo_identity')
        return self.root / vin / source

    def _manifest(self, vin, source):
        p = self._directory(vin, source) / 'manifest.json'
        try:
            value=json.loads(p.read_text('utf-8'))
            if not isinstance(value, dict): return {}
            # Preserve originals; a malformed cache index must not crash Inventory.
            if not isinstance(value.get('urls',[]),list): value['urls']=[]
            if not isinstance(value.get('entries',{}),dict): value['entries']={}
            return value
        except (OSError, ValueError): return {}

    def _save(self, vin, source, manifest):
        d=self._directory(vin, source)
        d.mkdir(parents=True, exist_ok=True)
        tmp=d/'manifest.json.new'
        tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
        os.replace(tmp, d/'manifest.json')

    def status(self, vin, source, urls=None, *, analyze=True):
        # R27: card-grid status is fast and must not open/decode hundreds of
        # photos. Photo analysis remains available for explicit operations.
        with self.lock:
            manifest=self._manifest(vin,source)
            supplied=(urls if urls is not None else manifest.get('urls',[]))
            if not isinstance(supplied,(list,tuple)):supplied=[]
            accepted=[x for x in supplied if clean_url(x)][:MAX_PHOTOS]
            if urls is not None:
                accepted=list(dict.fromkeys(accepted))
            can_analyze = pillow_available()
            entries=manifest.get('entries',{})
            result=[]
            for idx,url in enumerate(accepted):
                entry=entries.get(url,{})
                if not isinstance(entry,dict): entry={}
                file=entry.get('file') or ''
                if not isinstance(file,str) or '/' in file or '\\' in file: file=''
                available=bool(file and (self._directory(vin, source)/file).is_file())
                if available and analyze and can_analyze and (not entry.get('quality_checked') or not entry.get('visual_hash') or entry.get('screen_version') != 61):
                    try:
                        blob=(self._directory(vin,source)/file).read_bytes()
                        category,reason=classify_photo(blob,url) if entry.get('screen_version')!=61 or not entry.get('quality_checked') else (entry.get('category','review'),entry.get('quality_reason','unknown'))
                        checked=(reason!='pillow_not_installed')
                        width,height,visual_hash=photo_signature(blob)
                        changed=(entry.get('category')!=category or entry.get('quality_reason')!=reason
                                 or entry.get('quality_checked')!=checked
                                 or entry.get('width')!=width or entry.get('height')!=height
                                 or entry.get('visual_hash')!=visual_hash or entry.get('screen_version')!=61)
                        entry.update(category=category,quality_reason=reason,quality_checked=checked,
                                     width=width,height=height,visual_hash=visual_hash,screen_version=61)
                        if changed:
                            entries[url]=entry
                            manifest['entries']=entries
                            self._save(vin,source,manifest)
                    except Exception:
                        # Corrupt or oversized images must be isolated per photo, not abort /api/state.
                        category,reason='review','unreadable_cached_file'
                        entry.update(category=category,quality_reason=reason)
                category=entry.get('category','review')
                # A photo can be downloaded yet excluded from all vehicle
                # thumbnails and Facebook exports; original stays untouched.
                excluded=category=='graphic' or bool(entry.get('manual_hidden'))
                result.append({'index':idx,'downloaded':available,'status':('excluded' if excluded and available else 'saved') if available else entry.get('status','not_downloaded'),
                               'error':entry.get('error','') if not available else '',
                               'url':url,'size':entry.get('size',0) if available else 0,
                               'category':category,'excluded':excluded,
                               'quality_reason':entry.get('quality_reason','not_yet_downloaded'),
                               'width':entry.get('width',0),'height':entry.get('height',0),
                               'visual_hash':entry.get('visual_hash',''),'duplicate_of':None})
            # R61: dealership galleries may have many near-identical interiors or
            # adjacent angles. Perceptual hashing can incorrectly remove them.
            # Suppress ONLY byte-identical cached copies (same SHA-256).
            # The cost is paid on explicit analysis/export, not fast inventory GET.
            exact={}
            if analyze:
                for item in result:
                    if not item['downloaded'] or item['category']=='graphic':continue
                    try:
                        filename=entries.get(item['url'],{}).get('file')
                        if not filename:continue
                        digest=hashlib.sha256((self._directory(vin,source)/filename).read_bytes()).hexdigest()
                    except OSError:continue
                    previous=exact.get(digest)
                    if previous is None:
                        exact[digest]=item['index']
                    else:
                        item['duplicate_of']=previous
                        item['excluded']=True
                        item['status']='duplicate'
                        item['quality_reason']='same_file_exact_duplicate'
            return {'vin':vin,'source':source,'total':len(accepted),
                    'downloaded':sum(x['downloaded'] for x in result),
                    'pending':any((vin,source) == (v,s) for v,s in self.enqueued),
                    'photos':result,'storage':'LocalAppData/MarketplaceScanner/data/vehicle_photos',
                    'usable':sum(p['downloaded'] and not p['excluded'] for p in result),
                    'excluded':sum(p['excluded'] and p['downloaded'] for p in result),
                    'reuse_permission_implied':False,
                    'photo_analysis_available':can_analyze,
                    'analysis_deferred':not analyze}

    def _track_queue(self, vin, source, snapshot):
        # Called under the queue lock; no disk reads in console polling.
        if not self.enqueued:
            self.progress_jobs.clear()
            self.progress_recent.clear()
            self.progress_samples.clear()
        self.progress_jobs[(vin, source)] = {
            p['url']: 'cached' if p['downloaded'] else 'pending'
            for p in snapshot['photos']}

    def progress(self):
        with self.lock:
            counts = Counter(state for job in self.progress_jobs.values() for state in job.values())
            total = sum(counts.values())
            remaining = counts['pending']
            saved = counts['saved'] + counts['cached']
            pending = len(self.enqueued)
            timing = {'state': 'measuring' if pending else 'idle', 'seconds': None}
            if self.paused:timing={'state':'paused','seconds':None}
            elif pending and remaining and len(self.completed_times)>=6:
                span=self.completed_times[-1]-self.completed_times[0]
                if span>1 and time.monotonic()-self.completed_times[-1]<20:
                    timing={'state':'estimated','seconds':max(1,int(remaining*span/(len(self.completed_times)-1)))}
            return {'pending': pending, 'total': total, 'saved': saved,
                    'cached': counts['cached'], 'failed': counts['failed'], 'skipped': counts['skipped'],
                    'processed': total - remaining, 'remaining': remaining,
                    'active': next(iter(self.active_jobs.values()),None),
                    'priority_vins':[v for v,e in self.priorities.items() if e>time.time() and any(v==vin for vin,src in self.enqueued)],
                    'active_jobs':list(self.active_jobs.values()),'automatic_suspended':self.automatic_suspended,'paused':self.paused,'workers':len(self.workers),
                    'timing': timing, 'recent': list(self.progress_recent),
                    'items': [{'vin': v, 'source': src} for v, src in sorted(self.enqueued)[:10]]}

    def enqueue(self, vin, source, urls, *, force=False, explicit=False):
        accepted = list(dict.fromkeys(x for x in urls if clean_url(x)))[:MAX_PHOTOS]
        if not accepted: return self.status(vin,source,[])
        with self.lock:
            if self.automatic_suspended and self.priority_level(vin)<2 and not explicit:return self.status(vin,source,accepted,analyze=False)
            d=self._directory(vin,source)
            manifest=self._manifest(vin,source)
            same_urls=manifest.get('urls') == accepted
            if not same_urls:
                entries=manifest.get('entries',{})
                manifest={'urls':accepted,'entries':{url:entries[url] for url in accepted if url in entries},'updated_at':None}
                self._save(vin,source,manifest)
            key=(vin,source)
            snapshot=self.status(vin,source,accepted,analyze=False)
            needs_upgrade=any(fullsize_photo_url(u)!=u and (int(e.get('width') or 0)<550 or int(e.get('height') or 0)<300) for u,e in manifest.get('entries',{}).items())
            if snapshot['downloaded']==snapshot['total'] and not needs_upgrade:
                self.progress_recent.append({'at':datetime.now(timezone.utc).isoformat(),'message':f'{vin}: Already downloaded; saved photos reused'})
                return snapshot  # Already cached: no duplicate queue or CDN requests.
            # A blocked or temporarily unavailable image host must not be hammered
            # every time a vehicle gets rescanned. The user's Download button uses force.
            if not force and manifest.get('updated_at') and (any(p['status']=='failed' for p in snapshot['photos']) or any(e.get('error') for e in manifest.get('entries',{}).values())):
                try:
                    last=datetime.fromisoformat(manifest['updated_at'])
                    if (datetime.now(timezone.utc)-last).total_seconds()<7200:
                        return snapshot
                except (ValueError,TypeError):pass
            if key in self.enqueued and same_urls:
                if force and not self.pending_records.get(key,{}).get("force"):
                    self.pending_records[key]["force"]=True
                    self._persist_queue()
                self.progress_recent.append({'at':datetime.now(timezone.utc).isoformat(),'message':f'{vin}: Already queued; existing job retained'})
                return snapshot
            self.pending_records[key]={'vin':vin,'source':source,'urls':accepted,'force':force or self.pending_records.get(key,{}).get('force',False)}
            self._persist_queue()
            if key in self.enqueued:
                self._track_queue(vin,source,snapshot)
                self.reschedule[key]=force or self.reschedule.get(key,False)
            else:
                try:
                    self.jobs.put_nowait((vin,source,tuple(accepted),force,self.queue_generation))
                    self._track_queue(vin,source,snapshot)
                    self.enqueued.add(key)
                except queue.Full: raise ValueError('photo_download_queue_full')
        return self.status(vin,source,accepted,analyze=False)

    def _worker(self):
        while not self.stopping.is_set():
            try:vin,source,urls,force,generation=self.jobs.get(timeout=.2)
            except queue.Empty:continue
            key=(vin,source)
            try:self._download(vin,source,urls,force,generation)
            except Exception as exc:
                with self.lock:self.progress_recent.append({'at':datetime.now(timezone.utc).isoformat(),'message':f'Photo job error {vin}: {str(exc)[:100]}'})
            finally:
                with self.lock:
                    if self.active_jobs.get(key,{}).get("generation")==generation:self.active_jobs.pop(key,None)
                    if not self.stopping.is_set() and generation==self.queue_generation:
                        if key in self.reschedule:
                            retry=self.reschedule.pop(key)
                            latest=self._manifest(vin,source).get('urls',[])
                            self.jobs.put_nowait((vin,source,tuple(latest),retry,self.queue_generation))
                        else:
                            self.enqueued.discard(key);self.pending_records.pop(key,None)
                            for url,state in self.progress_jobs.get(key,{}).items():
                                if state=='pending':self.progress_jobs[key][url]='skipped'
                        self._persist_queue()
                    finished=not self.stopping.is_set() and generation==self.queue_generation and key not in self.enqueued
                    self.progress_recent.append({'at':datetime.now(timezone.utc).isoformat(),'message':f'Photo job stopped: {vin}' if self.stopping.is_set() else (f'Photo job yielded: {vin}' if key in self.enqueued else f'Photo job finished: {vin}')})
                self.jobs.task_done()
                if finished and self.on_finished:
                    try:self.on_finished(vin,source)
                    except Exception:pass   # sorting must never affect downloads

    def _download(self,vin,source,urls,force,generation=None):
        if generation is None:generation=self.queue_generation
        used=0
        consecutive_errors=0
        for index,url in enumerate(urls):
            if not self._wait_photo_slot(generation):return
            started=time.monotonic()
            while not self.stopping.is_set():
                with self.lock:
                    if generation!=self.queue_generation:return
                    force=force or self.pending_records.get((vin,source),{}).get("force",False)
                    level=self.priority_level(vin)
                    if self.jobs.has_priority(level):
                        self.reschedule[(vin,source)]=force or self.reschedule.get((vin,source),False)
                        return
                    higher=any(self.priority_level(v)>level for v,src in self.enqueued)
                if not higher and not (level<2 and self.foreground_scan_pending()):break
                if self.stopping.wait(.1):return
            if self.stopping.is_set():return
            with self.lock:
                manifest=self._manifest(vin,source)
                if manifest.get('urls') != list(urls): return  # URL set changed; old run is stale.
                entry=manifest.get('entries',{}).get(url,{})
                local=entry.get('file') or ''
                upgrade=bool(local and (self._directory(vin,source)/local).is_file()) and fullsize_photo_url(url)!=url and (int(entry.get('width') or 0)<550 or int(entry.get('height') or 0)<300)
                if local and (self._directory(vin,source)/local).is_file() and not upgrade:
                    self.progress_jobs.setdefault((vin,source), {})[url] = 'cached'
                    used+=int(entry.get('size',0));continue
            with self.lock:
                self.active_jobs[(vin,source)] = {'vin': vin, 'source': source, 'index': index + 1, 'total': len(urls),'generation':generation}
                started=time.monotonic()
            attempted = False
            digest=hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]
            try:
                # A blocked photo CDN should not consume 50 full network timeouts
                # for one vehicle. Keep skipped URLs visible for explicit retry.
                if consecutive_errors>=3 and not force:
                    raise ValueError('download_paused_after_three_failures')
                if used>=MAX_VEHICLE_BYTES: raise ValueError('vehicle_photo_budget_reached')
                attempted = True
                if upgrade:
                    data,ext=recover_fullsize(url,self.downloader)
                else:
                    if fullsize_photo_url(url)!=url:
                        try:data,ext=recover_fullsize(url,self.downloader)
                        except Exception:data,ext=self.downloader(url)
                    else:data,ext=self.downloader(url)
                if not data or len(data)>MAX_IMAGE_BYTES or not sniff_image(data): raise ValueError('invalid_image_response')
                used+=len(data)
                if used>MAX_VEHICLE_BYTES: raise ValueError('vehicle_photo_budget_reached')
                file=f'{index+1:02d}_{digest}{ext}'
                d=self._directory(vin,source);d.mkdir(parents=True,exist_ok=True)
                tmp=d/(file+'.new');tmp.write_bytes(data);os.replace(tmp,d/file)
                category,reason=classify_photo(data,url)
                width,height,visual_hash=photo_signature(data)
                update={'file':file,'size':len(data),'status':'saved','error':'','width':width,'height':height,'visual_hash':visual_hash,'screen_version':61,
                        'category':category,'quality_reason':reason,'quality_checked':reason!='pillow_not_installed'}
                consecutive_errors=0
            except Exception as exc:
                if str(exc)!='download_paused_after_three_failures':
                    consecutive_errors+=1
                update={**entry,'error':'Full-size retry: '+str(exc)[:80]} if upgrade and local else {'status':'failed','error':str(exc)[:100]}
            with self.lock:
                m=self._manifest(vin,source)
                if m.get('urls') != list(urls): return
                m.setdefault('entries',{})[url]=update
                m['updated_at']=datetime.now(timezone.utc).isoformat()
                self._save(vin,source,m)
                if generation!=self.queue_generation:return
                status = 'saved' if update.get('status') == 'saved' else ('failed' if attempted else 'skipped')
                self.progress_jobs.setdefault((vin,source), {})[url] = status
                if attempted:
                    self.completed_times.append(time.monotonic())
                    self.progress_samples.append(max(.08, time.monotonic() - started + .08))
                self.progress_recent.append({'at': datetime.now(timezone.utc).isoformat(),
                    'message': f'{vin} · photo {index+1}/{len(urls)} · {status}'})
            if update.get('status')=='failed':
                if self.stopping.wait(min(8,2**min(consecutive_errors,3))):return
            if update.get('status')=='saved' and update.get('quality_reason')=='possible_dealership_banner':
                prefs=self.preferences()
                if prefs['auto_replace']:
                    item={'index':index,'downloaded':True,'quality_reason':'possible_dealership_banner'}
                    self.prepared_variant(vin,source,item,prefs['contact_number'])
            time.sleep(.08)  # Never flood the image CDN.

    def read_photo(self,vin,source,index,urls,*,snapshot=None,manifest=None):
        # Only serve images still associated with the CURRENT saved vehicle record.
        if not isinstance(index,int) or index<0 or index>=len(urls): raise ValueError('invalid_photo_index')
        with self.lock:
            status=snapshot if snapshot is not None else self.status(vin,source,urls,analyze=False)
            if not status['photos'][index]['downloaded']: raise ValueError('photo_not_cached')
            item=(manifest if manifest is not None else self._manifest(vin,source))['entries'][urls[index]]['file']
            if not re.fullmatch(r'[0-9]{2,3}_[a-f0-9]{24}\.(?:jpg|png|webp)',item):
                raise ValueError('invalid_cached_filename')
            path=self._directory(vin,source)/item
            data=path.read_bytes()
            media_type=sniff_image(data)
            if not media_type or len(data)>MAX_IMAGE_BYTES: raise ValueError('photo_cache_corrupted')
            return data,media_type

    def usable_indices(self,vin,source,urls):
        quality=self.status(vin,source,urls)
        usable=[x for x in quality['photos'] if x['downloaded'] and not x['excluded']]
        usable.sort(key=lambda x:(int(x.get('width') or 0)*int(x.get('height') or 0),int(x.get('size') or 0)),reverse=True)
        return [x['index'] for x in usable]

    def usable_urls(self,vin,source,urls):
        indices=self.usable_indices(vin,source,urls)
        return [urls[i] for i in indices]

    def prepared_for_zip(self,vin,source,urls,contact_number=None,*,lead_url=None):
        return [(name,blob) for name,blob,_ in
                self.prepared_export_frames(vin,source,urls,contact_number,lead_url=lead_url)]

    def cached_business_card(self,blob,card):
        digest=hashlib.sha256(b'card-overlay-v2'+blob+card).hexdigest()
        folder=self.root/'_branding_cache';folder.mkdir(exist_ok=True)
        path=folder/(digest+'.jpg');miss=folder/(digest+'.none')
        if path.is_file():return path.read_bytes()
        if miss.is_file():return None
        result=overlay_business_card_on_sticker(blob,card)
        target=path if result else miss
        tmp=folder/(digest+'.'+str(threading.get_ident())+'.tmp')
        tmp.write_bytes(result or b'');os.replace(tmp,target)
        return result

    def prepared_export_frames(self,vin,source,urls,contact_number=None,*,lead_url=None,status_snapshot=None,manifest_snapshot=None):
        """Facebook-ready export frames with original URLs for cover selection.

        Dealer photos are read only. No image cache, dealer record or user data is
        modified by making an export ZIP. Unverified graphics stay excluded.
        """
        out=[]
        status=status_snapshot if status_snapshot is not None else self.status(vin,source,urls)
        manifest=manifest_snapshot if manifest_snapshot is not None else self._manifest(vin,source)
        prefs=self.preferences()
        chosen=prefs['contact_number'] if contact_number is None and prefs['auto_replace'] else (contact_number or '')
        cover_index=self.cover_choice(vin,source,urls,status,lead_url=lead_url)['index']
        ordered=sorted(status['photos'],key=lambda item:(item['index']!=cover_index,item['index']))
        card_path=BRANDING_DIR/'business_card.png'
        dedication_path=BRANDING_DIR/'dedication.jpg'
        # Name the exact branding files so the UI can say what is wrong (never "still fetching").
        missing=[p.name for p in (card_path,dedication_path) if not p.is_file()]
        if missing:
            raise ValueError('branding_assets_missing: '+', '.join(missing)+'; reinstall_R56')
        card_bytes=card_path.read_bytes()
        if not card_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('branding_assets_invalid: business_card.png; reinstall_R56')
        try:
            dedication_bytes=dedication_export_image(dedication_path.read_bytes())
        except Exception as exc:
            raise ValueError('branding_assets_invalid: dedication.jpg; reinstall_R56') from exc
        vehicle_photos=[]
        branded_urls=set()
        seen_export_images=set()
        for item in ordered:
            if not item['downloaded'] or item['category']=='graphic' or item.get('duplicate_of') is not None:
                continue
            i=item['index']
            try:
                blob,mime=self.read_photo(vin,source,i,urls,snapshot=status,manifest=manifest)
            except (ValueError,OSError):
                continue
            image_key=exact_export_image_key(blob)
            if image_key in seen_export_images:
                continue
            seen_export_images.add(image_key)
            # Prefer the supplied business card over the original white/red
            # dealership phone sticker. Never overlay on unrelated car regions.
            branded=self.cached_business_card(blob,card_bytes)
            if branded:
                branded_urls.add(item['url'])
                vehicle_photos.append((branded,'.jpg',item['url']))
            elif not item['excluded']:
                # Clean original, unchanged.
                vehicle_photos.append((blob,MIME[mime],item['url']))
        if not vehicle_photos:
            return []
        # User preference: a successfully branded vehicle photo always leads.
        vehicle_photos.sort(key=lambda frame:frame[2] not in branded_urls)
        # The second downloaded image is ALWAYS the original dedication design
        # (resampled to gallery size). Keep filenames sequential for Facebook.
        blob,ext,url=vehicle_photos[0]
        out.append(('photos/01'+ext,blob,url))
        out.append(('photos/02.jpg',dedication_bytes,None))
        for position,(blob,ext,url) in enumerate(vehicle_photos[1:],start=3):
            out.append((f'photos/{position:02d}{ext}',blob,url))
        return out

    def business_card_diagnostic(self,vin,source,urls,lead_url=None):
        status=self.status(vin,source,urls)
        card=(BRANDING_DIR/'business_card.png').read_bytes()
        manifest=self._manifest(vin,source)
        rows=[];branded=[]
        for item in status['photos']:
            row={k:item.get(k) for k in ('index','url','downloaded','width','height','category','quality_reason','duplicate_of','error','status')}
            row['download_error']=manifest.get('entries',{}).get(item['url'],{}).get('error','')
            row['business_card_ready']=False
            if item['downloaded'] and item.get('category')!='graphic' and item.get('duplicate_of') is None:
                try:
                    raw,_=self.read_photo(vin,source,item['index'],urls,snapshot=status,manifest=manifest)
                    row['business_card_ready']=bool(self.cached_business_card(raw,card))
                    if row['business_card_ready']:branded.append(item['url'])
                    else:row['card_reason']='No confidently detected dealership phone sticker'
                except (ValueError,OSError) as exc:row['card_reason']=str(exc)
            else:row['card_reason']='Not downloaded, excluded graphic, or duplicate'
            rows.append(row)
        frames=self.prepared_export_frames(vin,source,urls,lead_url=lead_url,status_snapshot=status,manifest_snapshot=manifest)
        first=frames[0][2] if frames else None
        return {'vin':vin,'source':source,'branded_photos':len(branded),'cover_ready':bool(first and first in branded),
                'first_export_url':first,'export_count':len(frames),'downloaded':status['downloaded'],
                'total':status['total'],'photos':rows}

    def cached_for_zip(self,vin,source,urls):
        out=[]
        status=self.status(vin,source,urls)
        for i,url in enumerate(urls[:MAX_PHOTOS]):
            if i>=len(status['photos']) or status['photos'][i]['excluded'] or not status['photos'][i]['downloaded']:
                continue
            try:
                data,mime=self.read_photo(vin,source,i,urls)
                ext=MIME[mime]
                out.append((f'photos/{i+1:02d}{ext}',data))
            except (ValueError,OSError): continue
        return out
# Add to photo_cache.py (module level). Pure function: no disk, no network.
DEDICATION_KEY = 'dedication'


def frame_key(frame):
    """Stable identity of an export frame: the dealer source URL, or 'dedication'.
    Keys survive refreshes and re-ordering; positions (01, 02...) do not."""
    _name, _blob, url = frame
    return url or DEDICATION_KEY


def select_export_frames(frames, keys=None, *, limit=None, groups=None):
    """Return (selected_frames, report) for the ZIP and the Facebook upload.

    frames: prepared_export_frames() output, already in gallery order
            [('photos/01.jpg', bytes, url), ('photos/02.jpg', bytes, None), ...]
    keys:   the user's selection (frame keys). None = everything (old behavior).
    Order is the validated click order of `keys` (never gallery or category order), and the
    chosen files are renumbered 01..N with no gaps so file order = upload order.
    `groups` is accepted for compatibility and intentionally ignored.
    Keys that no longer exist (photo removed on refresh) are reported, not guessed."""
    available = [frame_key(f) for f in frames]
    avail_set = set(available)
    if keys is None:
        wanted = list(available)
        missing = []
    else:
        if not isinstance(keys, (list, tuple)) or not all(isinstance(k, str) for k in keys):
            raise ValueError('invalid_photo_selection')
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate_photo_selection_keys')
        wanted = [k for k in keys if k in avail_set]
        missing = [k for k in keys if k not in avail_set]
    if limit is not None and len(wanted) > limit:
        raise ValueError(f'too_many_photos_selected; {len(wanted)} selected, limit {limit}')
    if not wanted:
        raise ValueError('no_photos_selected')
    by_key = {frame_key(f): f for f in frames}
    out, rows = [], []
    for position, key in enumerate(wanted, start=1):
        name, blob, url = by_key[key]
        ext = name[name.rfind('.'):] if '.' in name else '.jpg'
        new_name = f'photos/{position:02d}{ext}'
        out.append((new_name, blob, url))
        rows.append({'file': new_name, 'gallery_number': available.index(key) + 1, 'key': key})
    return out, {'selected': len(out), 'available': len(frames), 'missing_keys': missing, 'files': rows}
