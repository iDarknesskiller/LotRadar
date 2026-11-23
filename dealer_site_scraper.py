"""SalesmanHub Marketplace dealership website reader.

Runs only against the four explicitly allowlisted Hampton inventory pages and their
same-host vehicle details. Robots directives are checked before page navigation.
Never handles Facebook and never marks an incomplete website scan as complete.
Live dealership compatibility must be verified on the user's Windows PC.
"""
from __future__ import annotations
import argparse
import html as htmlmod
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote, parse_qs
from urllib.robotparser import RobotFileParser
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from vin_decode import valid_spec
from core import SOURCES, VIN_RE, normalize, valid_url

SITES = {
 'toyota_new': 'https://www.hamptontoyota.com/new-inventory/index.htm',
 'toyota_used': 'https://www.hamptontoyota.com/used-inventory/index.htm',
 'mitsubishi_new': 'https://www.hamptonmitsubishi.com/new-inventory/index.htm',
 'mitsubishi_used': 'https://www.hamptonmitsubishi.com/used-inventory/index.htm',
}
AGENT = 'SalesmanHubDealerSiteReader/1.1 (public inventory; respects robots.txt)'
MAX_SITEMAP_BYTES = 4_000_000
MAX_SITEMAP_FILES = 24
EARLY_ABORT_FAILURES = 5  # Stop dead sources before 250 pointless visits
VIN_PATTERN = re.compile(r'(?<![A-HJ-NPR-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-HJ-NPR-Z0-9])', re.I)
MAKE_NAMES = ['Alfa Romeo', 'Land Rover', 'Mercedes-Benz', 'Aston Martin', 'Rolls-Royce',
              'Toyota', 'Mitsubishi', 'Lexus', 'Subaru', 'Honda', 'Jeep', 'Ford', 'Chevrolet',
              'GMC', 'Buick', 'Kia', 'Hyundai', 'Nissan', 'Volkswagen', 'Mazda', 'Dodge',
              'Ram', 'Chrysler', 'Tesla', 'BMW', 'Audi', 'Volvo', 'Acura', 'Infiniti',
              'Lincoln', 'Cadillac', 'Porsche', 'Mini', 'Genesis', 'Polestar', 'Scion',
              'Pontiac', 'Mercury', 'Fiat', 'Suzuki', 'Hummer']
PRICE_LABEL = r'(?:Hampton Price|Internet Price|Sale Price|Our Price|Dealer Price|Selling Price|Hampton Sale Price)'


class ScanCancelled(Exception):
    """The user stopped this discovery run; nothing from the current dealer is committed."""


class ScanControl:
    """LR-009: Pause, Resume and Stop for one historical discovery run.

    The worker calls checkpoint() at dealer, navigation/scroll and sitemap-request
    boundaries. A bounded call already in flight drains; no new request starts
    after Stop. Stop also wakes a paused worker so it can exit.
    """
    def __init__(self):
        import threading
        self.cancel = threading.Event()
        self.unpaused = threading.Event()
        self.unpaused.set()

    @property
    def stopping(self):
        return self.cancel.is_set()

    @property
    def paused(self):
        return not self.unpaused.is_set() and not self.cancel.is_set()

    def pause(self):
        if not self.cancel.is_set():
            self.unpaused.clear()

    def resume(self):
        self.unpaused.set()

    def stop(self):
        self.cancel.set()
        self.unpaused.set()

    def checkpoint(self):
        self.unpaused.wait()
        if self.cancel.is_set():
            raise ScanCancelled('USER_STOPPED_SCAN')

    def sleep(self, seconds):
        self.checkpoint()
        if self.cancel.wait(max(0.0, float(seconds))):
            raise ScanCancelled('USER_STOPPED_SCAN')
        self.checkpoint()


class _NoControl:
    stopping = False
    paused = False
    def checkpoint(self):
        return None
    def sleep(self, seconds):
        time.sleep(seconds)


def allowed_vehicle_url(url: str, source: str) -> bool:
    """Exactly the approved dealership host, VDP path and matching condition."""
    if source not in SITES or not isinstance(url, str):
        return False
    try:
        p = urlsplit(url)
        host = urlsplit(SITES[source]).hostname
        expected = '/new/' if source.endswith('_new') else '/used/'
        return (p.scheme == 'https' and p.hostname == host and p.port in (None,443)
                and not p.username and not p.password and p.path.startswith(expected)
                and p.path.endswith('.htm') and len(p.path)<350 and not p.fragment)
    except (TypeError, ValueError):
        return False


def vehicle_links(index_html: str, base: str, source: str) -> list[str]:
    """Find VDP URLs in anchors AND serialized client-side data.

    Dealer.com inventory pages can initially contain only loading skeletons;
    item URLs often appear later in script data rather than <a> tags.
    All results are canonicalized, source-matched and host-allowlisted.
    """
    soup = BeautifulSoup(index_html, 'html.parser')
    candidates = [a.get('href', '') for a in soup.select('a[href]')]
    # HTML/JSON script escaping must be handled without trusting arbitrary links.
    text = htmlmod.unescape(index_html)
    text = (text.replace(r'\/', '/')
                .replace(r'\u002F', '/')
                .replace(r'\u002f', '/')
                .replace(r'\u003A', ':')
                .replace(r'\u003a', ':'))
    candidates += re.findall(
        r'(?:https?://[A-Za-z0-9.:-]+)?/(?:new|used)/[A-Za-z0-9%_./+\-]+?\.htm',
        text, flags=re.I)
    out = []
    for raw in candidates:
        try:
            absolute = urljoin(base, raw)
            p = urlsplit(absolute)
            clean = urlunsplit((p.scheme, p.netloc, p.path, '', ''))
            if allowed_vehicle_url(clean, source) and clean not in out:
                out.append(clean)
        except (TypeError, ValueError):
            continue
    return out


def sitemap_vehicle_links(gate, source: str, *, max_vehicles=250, delay=0.8, control=None):
    """Sitemap fallback when JS inventory cards never expose their VDP links.

    Reads only allowlisted same-host XML, obeys robots on every request, and
    never marks the returned list complete or infers a missing VIN is sold.
    """
    control = control or _NoControl()
    base = SITES[source]
    root = urlsplit(base)
    homepage = f'{root.scheme}://{root.netloc}'
    seeds = [homepage + '/sitemap.xml']
    # Sitemap: entries are advertised in robots.txt; do not fetch unrelated hosts.
    seeds.extend(gate.sitemaps_for(homepage))
    queue = list(dict.fromkeys(seeds))
    visited = set()
    found = []
    diagnostics = []
    while queue and len(visited) < MAX_SITEMAP_FILES and len(found) < max_vehicles:
        control.checkpoint()  # LR-009: no new sitemap request after Stop
        url = queue.pop(0)
        try:
            p = urlsplit(url)
            if p.scheme != 'https' or p.hostname != root.hostname or p.port not in (None,443) or p.username or p.password:
                continue
            if url in visited or not p.path.lower().endswith('.xml'):
                continue
            visited.add(url)
            if not gate.permitted(url):
                diagnostics.append(f'sitemap_disallowed:{p.path}')
                continue
            req = Request(url, headers={'User-Agent':AGENT,'Accept':'application/xml,text/xml,*/*'})
            with urlopen(req, timeout=18) as resp:
                if resp.status != 200:
                    raise RuntimeError('http_' + str(resp.status))
                data = resp.read(MAX_SITEMAP_BYTES + 1)
            if len(data) > MAX_SITEMAP_BYTES:
                diagnostics.append('sitemap_too_large:' + p.path)
                continue
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError('xml_dtd_not_allowed')
            xml = ET.fromstring(data)
            for entry in xml.iter():
                if not entry.tag.endswith('loc') or not entry.text:
                    continue
                candidate=htmlmod.unescape(entry.text.strip())
                if allowed_vehicle_url(candidate, source):
                    if candidate not in found:found.append(candidate)
                    if len(found)>=max_vehicles:break
                else:
                    child=urlsplit(candidate)
                    if (child.scheme=='https' and child.hostname==root.hostname
                        and child.port in (None,443) and child.path.lower().endswith('.xml')
                        and candidate not in visited and candidate not in queue):
                        # Relevant vehicle/inventory sitemaps first, without
                        # guessing endpoint names or bypassing access rules.
                        if re.search(r'inventor|vehicle|vdp|product|car|auto', candidate, re.I):
                            queue.insert(0,candidate)
                        else:
                            queue.append(candidate)
            control.sleep(delay)
        except ScanCancelled:
            raise
        except Exception as ex:
            diagnostics.append(f'{p.path}:{type(ex).__name__}:{str(ex)[:70]}')
    return found, {'sitemaps_checked':len(visited),'sitemap_warnings':diagnostics[:12]}


# R5: year/make/model only. Never interpret a sitemap link as in-stock.
# The detail pages currently return 403; this mode does not request them.
KNOWN_MODELS = tuple(sorted((
    'Corolla Cross Hybrid', 'Grand Highlander Hybrid', 'Grand Highlander',
    'Outlander Sport', 'Eclipse Cross', 'Outlander PHEV', 'Crown Signia',
    'Land Cruiser', 'Corolla Cross', 'Corolla Hatchback', 'Corolla Hybrid',
    'Accord Sedan', 'Grand Cherokee', 'Santa Fe', 'Range Rover',
    'Tacoma', 'RAV4', '4Runner', 'Highlander', 'Camry', 'Corolla',
    'Prius', 'Blazer', 'Equinox', 'Civic', 'CR-V', 'HR-V',
), key=len, reverse=True))


def parse_basic_vehicle_url(url: str, source: str):
    """Infer Y/M/model from an approved, vehicle-shaped URL; no VIN or stock claim."""
    if not allowed_vehicle_url(url, source):
        return None
    path=unquote(urlsplit(url).path)
    leaf=path.rsplit('/',1)[-1]
    m=re.fullmatch(r'((?:19|20)\d{2})-(.+)-([a-f0-9]{20,})\.htm',leaf,re.I)
    if not m: return None  # ignore marketing landing pages
    year=int(m.group(1))
    if not 1980<=year<=2035:return None
    tokens=m.group(2).split('-')
    title=' '.join(tokens).strip()
    make=next((n for n in sorted(MAKE_NAMES,key=len,reverse=True)
               if title.lower().startswith(n.lower()+' ')), None)
    if not make: return None
    remainder=title[len(make):].strip()
    if not remainder: return None
    model=next((n for n in KNOWN_MODELS
                if remainder.casefold()==n.casefold() or remainder.casefold().startswith(n.casefold()+' ')),None)
    if not model: model=remainder.split()[0]
    if not model or not re.fullmatch(r'[A-Za-z0-9 -]{1,70}',model):return None
    return {'year':year,'make':make,'model':model,'source':source,'url':url,
            'confidence':'url_slug','verified':False,'availability':'unverified',
            'vin':None,'stock':None,'mileage':None,'price':None,'photos':[]}


def basic_catalog_from_links(links, source, max_vehicles=250, provenance='sitemap'):
    """Unverified discovery results are never imported as actual inventory."""
    if source not in SITES:raise ValueError('unsupported_source')
    rows=[]; seen=set()
    for url in links:
        if url in seen:continue
        seen.add(url)
        item=parse_basic_vehicle_url(url,source)
        if item:
            item['discovery_method']=provenance
            rows.append(item)
        if len(rows)>=max_vehicles:break
    return rows


def scan_basic_source(source, *, max_vehicles=250, delay=0.8, progress=None, control=None):
    """Discover unverified YMM entries, WITHOUT requesting vehicle detail pages.

    Inventory pages are attempted first. Sitemaps are fallback and never
    establish stock availability. Respects robots.txt and rate limits.
    LR-009: ``control`` (ScanControl) stops the run between bounded requests.
    """
    control = control or _NoControl()
    if source not in SITES:raise ValueError('unsupported_source')
    if not 1<=max_vehicles<=800:raise ValueError('invalid_vehicle_limit')
    if delay<0.5:raise ValueError('minimum_request_delay_500ms')
    control.checkpoint()
    target=SITES[source]; gate=RobotsGate()
    if not gate.permitted(target):raise RuntimeError('robots_disallow_inventory_index')
    control.checkpoint()
    if progress:progress('loading_inventory',discovered=0,parsed=0,visited=0,failed=0)
    links=[];warnings=[]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError('playwright_not_installed; launcher must repair setup') from e
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            ctx=browser.new_context(viewport={'width':1440,'height':950},locale='en-US')
            page=ctx.new_page()
            control.checkpoint()
            page.goto(target,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(2200)
            stagnant=0
            for _ in range(12):
                control.checkpoint()  # LR-009: Stop/Pause between scroll passes
                old=len(links)
                for u in vehicle_links(page.content(),target,source):
                    if u not in links:links.append(u)
                if len(links)>=max_vehicles or stagnant>=3:break
                page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
                page.wait_for_timeout(900)
                stagnant=(stagnant+1) if len(links)==old else 0
        finally:
            browser.close()
    verified_card_links=len(links)
    control.checkpoint()
    rows=basic_catalog_from_links(links,source,max_vehicles,'inventory_page')
    if len(rows)<10:
        more,report=sitemap_vehicle_links(gate,source,max_vehicles=max_vehicles,delay=delay,control=control)
        warnings=report.get('sitemap_warnings',[])
        known={r['url'] for r in rows}
        for r in basic_catalog_from_links(more,source,max_vehicles,'sitemap'):
            if r['url'] not in known and len(rows)<max_vehicles:
                rows.append(r);known.add(r['url'])
    if not rows:
        raise RuntimeError('NO_BASIC_CATALOG: no vehicle-shaped URLs discovered on inventory pages or permitted sitemaps')
    if progress:progress('catalog_discovered',discovered=len(rows),parsed=len(rows),visited=0,failed=0)
    return {'source':source,'scanned_at':datetime.now(timezone.utc).isoformat(),
            'records':rows,'count':len(rows),'index_candidates':verified_card_links,
            'warnings':warnings,'verified':False,'partial':True,
            'notice':'URL-derived names only. No VIN, stock, availability, price or photos verified.'}


# R6 staged enrichment: information from a page the user can open and copy.
# The local server must NOT attempt a blocked HTTP request when capturing text.
def enrich_basic_from_visible_text(text: str, candidate: dict) -> dict:
    """Extract labelled fields from a user-provided VDP page snapshot.

    It is not proof of on-lot availability; copied content may be stale and all
    snapshots remain in the unverified catalog until separately confirmed.
    """
    if not isinstance(text,str) or not 20<=len(text)<=200_000:
        raise ValueError('page_text_length_invalid')
    if not isinstance(candidate,dict) or not parse_basic_vehicle_url(candidate.get('url',''),candidate.get('source','')):
        raise ValueError('basic_candidate_invalid')
    clean=BeautifulSoup(text,'html.parser').get_text(' ',strip=True) if re.search(r'<(?:html|body|h1)\b',text,re.I) else text
    clean=htmlmod.unescape(clean)
    if len(clean)>200_000:raise ValueError('page_text_length_invalid')
    # A candidate URL is a routing aid, never a source of VIN, stock or price.
    suffixes=[m[len(str(candidate['model'])):].strip().split()[0]
              for m in KNOWN_MODELS if m.casefold().startswith(str(candidate['model']).casefold()+' ') ]
    exclude_more=(r'(?!\s+(?:'+ '|'.join(map(re.escape,suffixes))+r')\b)') if suffixes else ''
    identity=re.compile(r'\b'+str(candidate['year'])+r'\s+'+
         re.escape(str(candidate['make'])).replace('\\ ',r'\s+')+r'\s+'+
         re.escape(str(candidate['model'])).replace('\\ ',r'\s+')+r'\b'+exclude_more,re.I)
    if not identity.search(re.sub(r'\s+',' ',clean)):
        raise ValueError('page_vehicle_identity_mismatch')
    matches={v.upper() for v in re.findall(r'\bVIN\s*(?:\#|:)?\s*([A-HJ-NPR-Z0-9]{17})\b',clean,re.I)
             if VIN_RE.fullmatch(v.upper())}
    # The page must not be assigned to one car if visible labelled VINs conflict.
    if len(matches)>1:raise ValueError('multiple_conflicting_vins_in_snapshot')
    vin=next(iter(matches),None)
    stockmatch=re.search(r'\bStock\s+(?:Number|No\.?|#)\s*[:#]?\s*([A-Z0-9-]{2,40})\b',clean,re.I)
    if not stockmatch: stockmatch=re.search(r'\bStock\s*[:#]\s*([A-Z0-9-]{2,40})\b',clean,re.I)
    stock=stockmatch.group(1).upper() if stockmatch and re.search(r'\d',stockmatch.group(1)) else None
    odo=re.search(r'\b(?:Odometer|Mileage)\s*[:#]?\s*([\d,]{1,9})\s*(?:mi(?:les?)?\b)?',clean,re.I)
    mileage=int(odo.group(1).replace(',','')) if odo else None
    if mileage is not None and not 0<=mileage<=2_000_000:raise ValueError('invalid_odometer')
    # Price precedence: advertised Hampton/internet/sale price first; only use
    # generic Price if no named dealer price. TSRP/MSRP are separate labels and
    # cannot masquerade as a negotiated/selling price.
    price=None;price_label=None
    price_types=(('Hampton Price',r'Hampton\s+Price'),
                 ('Internet Price',r'Internet\s+Price'),
                 ('Sale Price',r'Sale\s+Price'),
                 ('Selling Price',r'Selling\s+Price'),
                 ('Price',r'Price'),
                 ('TSRP',r'TSRP'),
                 ('MSRP',r'MSRP'))
    for label,patt in price_types:
        forms=[r'\$\s*([\d,]+(?:\.\d{2})?)\s+'+patt+r'\b',
               r'\b'+patt+r'\s*[:\-]?\s*\$\s*([\d,]+(?:\.\d{2})?)']
        for f in forms:
            raw=re.findall(f,clean,flags=re.I)
            for n in raw:
                try: amount=float(n.replace(',',''))
                except ValueError:continue
                if 1000<=amount<=5_000_000:
                    price=f'{amount:.2f}';price_label=label;break
            if price:break
        if price:break
    missing=[k for k,v in (('vin',vin),('stock',stock),('price',price),
                           ('mileage',mileage)) if v is None]
    return {'vin':vin,'stock':stock,'price':price,'price_label':price_label,
            'mileage':mileage,'captured_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'capture_method':'user_opened_visible_page','fields_missing':missing,
            'field_count':4-len(missing),'details_complete':not missing,
            'availability':'unverified','note':'Copied page details do not prove current inventory or photo rights.'}


def _text(soup):
    return ' '.join(soup.stripped_strings)


def _labeled(text, label, pattern, default=''):
    match = re.search(r'\b'+label+r'\s*[:#]?\s*'+pattern, text, flags=re.I)
    return match.group(1).strip() if match else default


def _title_parts(raw_title):
    title = re.sub(r'^(?:(?:new|pre[- ]owned|used|certified)\s+)+','',raw_title,flags=re.I)
    m = re.search(r'\b((?:19|20)\d{2})\s+(.+)',title)
    if not m:
        raise ValueError('vehicle_year_not_identifiable')
    year=int(m.group(1)); remainder=m.group(2).strip()
    make = next((x for x in sorted(MAKE_NAMES,key=len,reverse=True) if remainder.lower().startswith(x.lower()+' ')), None)
    if not make:
        raise ValueError('vehicle_make_not_identifiable')
    rest = remainder[len(make):].strip()
    if not rest:
        raise ValueError('vehicle_model_not_identifiable')
    # Keep the visible VDP title consistent with the URL's longest known model.
    # Previously `Outlander Sport ES` became model `Outlander`, trim `Sport ES`,
    # while URL parsing correctly returned `Outlander Sport`; the Chrome bridge
    # then rejected a real car as an identity mismatch. Match at a word boundary
    # and use the same curated model list as basic-catalog URL discovery.
    model = next((name for name in KNOWN_MODELS
                  if rest.casefold() == name.casefold() or
                  rest.casefold().startswith(name.casefold() + ' ')), rest.split()[0])
    trim = rest[len(model):].strip()
    return year,make,model,trim


def _structured_vehicles(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            root=json.loads(script.string or script.get_text() or '{}')
        except (ValueError, TypeError):
            continue
        stack=[root]
        while stack:
            node=stack.pop()
            if isinstance(node,list): stack.extend(node)
            elif isinstance(node,dict):
                stack.extend([v for k,v in node.items() if k in ('@graph','itemListElement','item','mainEntity','offers') and isinstance(v,(dict,list))])
                types=node.get('@type') or []
                if isinstance(types,str): types=[types]
                if any(x in types for x in ('Vehicle','Car','Product','IndividualProduct')):
                    yield node


def _extract_price(text: str, soup, structured):
    """Read a confirmed advertised vehicle selling price, never monthly/fees.

    R57: dealer HTML repeats prices inside payment calculators and footer text.
    Previously choosing the *last* labeled occurrence could select a stale or
    non-selling price. Prefer the first valid explicitly labeled price in the
    vehicle header, then a valid generic selling Price label, then JSON-LD.
    """
    from decimal import Decimal, InvalidOperation

    def real_vehicle_price(raw):
        try:
            value = Decimal(str(raw).replace('$', '').replace(',', '').strip())
            if value.is_finite() and Decimal('1000') <= value <= Decimal('5000000'):
                return str(value)
        except (InvalidOperation, ValueError, TypeError):
            pass
        return None

    # The header/overview precedes financing calculators and legal disclaimers.
    head = re.split(r'\b(?:The overview|A closer look at what|Build Your Offer|Price details)\b',
                    text, maxsplit=1, flags=re.I)[0]
    sections = [head] + ([text] if head != text else [])
    named = [
        rf'\$\s*([\d,]+(?:\.\d{{2}})?)\s*{PRICE_LABEL}\b',
        rf'\b{PRICE_LABEL}\b\s*[:\-]?\s*\$\s*([\d,]+(?:\.\d{{2}})?)',
    ]
    generic = [r'\$\s*([\d,]+(?:\.\d{2})?)\s+Price\b',
               r'\bPrice\s*[:\-]?\s*\$\s*([\d,]+(?:\.\d{2})?)']
    # Exact selling-price labels are stronger than a generic Price heading.
    for section in sections:
        for patterns in (named, generic):
            for pattern in patterns:
                for match in re.finditer(pattern, section, flags=re.I):
                    result = real_vehicle_price(match.group(1))
                    if result is not None:
                        return result
    offers = structured.get('offers') if isinstance(structured, dict) else None
    if isinstance(offers,list):
        offers = next((v for v in offers if isinstance(v,dict) and v.get('price')),None)
    if isinstance(offers,dict):
        return real_vehicle_price(offers.get('price'))
    return None


def _find_images(soup, structured, page_url='', lead=''):
    """Read actual photo links, including Dealer.com gallery anchors/srcsets.

    No invented stock images; only explicitly published HTTPS asset URLs from
    the dealer host or the dealer image CDN are retained.
    """
    candidates=([lead] if lead else [])+[tag.get('src','') for tag in soup.select('[data-shm-complete-gallery] img[data-gallery-photo]')]
    if not soup.select_one('[data-shm-complete-gallery][data-gallery-verified]'):
        if isinstance(structured,dict):
            raw=structured.get('image',[])
            candidates.extend(raw if isinstance(raw,list) else [raw])
        for meta in soup.select('meta[property="og:image"], meta[name="twitter:image"]'):
            candidates.append(meta.get('content',''))
        for tag in soup.select('img, source, a[href]'):
            for attr in ('data-src','data-original','data-lazy-src','data-image-url',
                         'src','href','data-zoom-image'):
                if tag.get(attr): candidates.append(tag[attr])
            for attr in ('srcset','data-srcset'):
                if tag.get(attr):
                    candidates.extend(piece.strip().split(' ')[0] for piece in tag[attr].split(','))
    # Keep one image per CDN asset path. srcsets often repeat each photo with
    # 320px/640px/1024px width variants, which otherwise waste the 50-photo cap.
    by_asset={}
    for item in candidates:
        if isinstance(item,dict):item=item.get('url','')
        if not isinstance(item,str):continue
        raw=htmlmod.unescape(item.strip())
        if raw.startswith('//'):raw='https:'+raw
        if raw.startswith('/'):raw=urljoin(page_url,raw)
        try:
            p=urlsplit(raw)
            if not (p.scheme=='https' and (p.hostname or '').lower() in
                ('pictures.dealer.com','www.hamptontoyota.com','www.hamptonmitsubishi.com')
                and not p.username and not p.password and p.port in (None,443)
                and p.path.lower().endswith(('.jpg','.jpeg','.png','.webp'))):continue
            key=(p.hostname.lower(),p.path.lower())
            sizes=parse_qs(p.query)
            width=max([int(x) for k in ('w','width') for x in sizes.get(k,[]) if str(x).isdigit()] or [0])
            if key not in by_asset or width>by_asset[key][0]:
                by_asset[key]=(width,raw)
        except (ValueError,TypeError):continue
        if len(by_asset)>=250:break
    # Vehicle CDN gallery URLs are more reliable than generic site/brand images.
    out=[raw for _,raw in by_asset.values()]
    out.sort(key=lambda u: (0 if lead and urlsplit(u).path.lower()==urlsplit(lead).path.lower() else 1,
                            0 if urlsplit(u).hostname=='pictures.dealer.com' else 1))
    return out


def _find_vehicle_vin(soup, text, raw_html, structured):
    """Only accept explicitly labeled VDP VINs, never a suggested-car VIN."""
    # Prefer a visible VIN label adjacent to a single 17-character value.
    for pattern in (
        r'\bVIN\s*(?:\:|\#)?\s*([A-HJ-NPR-Z0-9]{17})\b',
        r'\bVehicle Identification Number\s*(?:\:|\#)?\s*([A-HJ-NPR-Z0-9]{17})\b',
    ):
        m=re.search(pattern,text,flags=re.I)
        if m and VIN_RE.fullmatch(m.group(1).upper()):return m.group(1).upper()
    for key in ('vehicleIdentificationNumber','vin','VIN'):
        value=structured.get(key) if isinstance(structured,dict) else None
        if isinstance(value,str) and VIN_RE.fullmatch(value.strip().upper()):
            return value.strip().upper()
    # Other markup may contain recommendations. Use only an unambiguous VIN.
    candidates=[]
    for tag in soup.select('[data-vin], [data-vehicle-vin], [itemprop="vehicleIdentificationNumber"], [itemprop="vin"]'):
        for value in (tag.get('data-vin'), tag.get('data-vehicle-vin'),tag.get('content'),tag.get_text(' ',strip=True)):
            if isinstance(value,str) and VIN_RE.fullmatch(value.strip().upper()):
                candidates.append(value.strip().upper())
    raw=htmlmod.unescape(raw_html).replace(r'\"','"')
    for pattern in (
        r'["\'](?:vehicleIdentificationNumber|vin|VIN)["\']\s*[:=]\s*["\']([A-HJ-NPR-Z0-9]{17})["\']',
        r'\bdata-(?:vehicle-)?vin\s*=\s*["\']([A-HJ-NPR-Z0-9]{17})["\']',
    ):
        candidates.extend(v.upper() for v in re.findall(pattern,raw,flags=re.I))
    valid=set(v for v in candidates if VIN_RE.fullmatch(v))
    return next(iter(valid)) if len(valid)==1 else None


def read_static_vdp(url, source, *, photos_approved=False):
    """Second, same-host public view when a live browser only returns a JS shell.

    The robots gate and allowlisted URL must already have been checked by the caller.
    This is a normal public HTTP request, not a bypass or crawler impersonation.
    """
    if not allowed_vehicle_url(url,source):
        raise ValueError('fallback_vdp_not_allowed')
    req=Request(url,headers={'User-Agent':AGENT,'Accept':'text/html,application/xhtml+xml'})
    with urlopen(req,timeout=18) as response:
        final=response.geturl()
        if final!=url and urlsplit(final).path!=urlsplit(url).path:
            raise ValueError('fallback_redirected_to:'+urlsplit(final).path[:80])
        if response.status!=200:
            raise ValueError('fallback_http_'+str(response.status))
        raw=response.read(5_000_001)
    if len(raw)>5_000_000:
        raise ValueError('fallback_html_too_large')
    return parse_vehicle_page(raw.decode('utf-8','replace'),url,source,photos_approved=photos_approved)


def classify_non_vehicle_page(page_text, final_url, original_url, http_status=None):
    """Explain genuinely missing data instead of 250 generic VIN failures."""
    if http_status is not None and http_status >= 400:
        return f'vdp_http_{http_status}'
    if urlsplit(final_url).path != urlsplit(original_url).path:
        return f'vdp_redirected_to:{urlsplit(final_url).path[:100]}'
    lowered=page_text.lower()
    if any(word in lowered for word in ('access denied','automated requests','unusual traffic','verify you are human','captcha')):
        return 'vdp_access_challenge'
    if any(word in lowered for word in ('vehicle not found','no longer available','page not found','404 not found')):
        return 'vdp_removed_or_expired'
    if len(page_text.strip()) < 100:
        return 'vdp_empty_or_loading_shell'
    return 'vdp_missing_vin_after_render'


def _specs_from_lines(text):
    """Read bounded label/value lines, without crossing blank lines or headings."""
    aliases = {
        'fuel_type': ['standard fuel economy fuel type', 'fuel type', 'recommended fuel'],
        'body_style': ['body style', 'body type', 'body/seating'],
        'transmission': ['transmission'],
        'exterior_color': ['exterior color', 'exterior colour'],
        'interior_color': ['interior color', 'interior colour'],
    }
    labels = {label for values in aliases.values() for label in values}
    lines = [line.strip() for line in str(text or '').splitlines()]
    result = {}
    for field, names in aliases.items():
        for name in names:
            candidates = []
            for index, line in enumerate(lines):
                match = re.fullmatch(re.escape(name) + r'[ \t]*:[ \t]*(.*)', line, re.I)
                if match:
                    value = match.group(1).strip()
                    if not value and index + 1 < len(lines):
                        value = lines[index + 1]
                elif line.lower() == name and index + 1 < len(lines):
                    value = lines[index + 1]
                else:
                    continue
                if (not 1 < len(value) <= 100 or ':' in value or
                        value.lower().rstrip(':') in labels):
                    continue
                if field == 'body_style':
                    value = value.split('/')[0].strip()
                value = valid_spec(field, value)
                if value: candidates.append(value)
            unique = {value.casefold(): value for value in candidates}
            if len(unique) == 1:
                result[field] = next(iter(unique.values()))
                break
            if len(unique) > 1:
                break  # Conflicting values need review, not a guess.
    return result



_GENERIC_COLOR_KEYS = {'normalExteriorColor': 'exterior_color_generic', 'normalInteriorColor': 'interior_color_generic'}


def _dealer_generic_colors(html, vin):
    """Dealer.com's own normalized colors ("Silver", "Gray") for THIS page's VIN.

    The page data holds a flat object such as
    {"vin":"4T1K61AK6RU845062",...,"normalExteriorColor":"Silver","normalInteriorColor":"Black"}.
    Similar-vehicle widgets add objects for other VINs, so only the object that
    carries this VIN is read, and conflicting answers return nothing."""
    found = {}
    if not vin or not html:
        return {}
    for match in re.finditer(r'\{[^{}]{0,8000}\}', html[:3_000_000]):
        body = match.group(0)
        vins = re.findall(r'"vin"\s*:\s*"([^"\\]*)"', body)
        if len(re.findall(r'"vin"\s*:', body)) != 1 or len(vins) != 1 or vins[0].upper() != str(vin).upper():
            continue
        for key, field in _GENERIC_COLOR_KEYS.items():
            value = re.search(r'"' + key + r'"\s*:\s*"([^"]{1,40})"', body)
            value = valid_spec(field, value.group(1)) if value else None
            if value:
                found.setdefault(field, set()).add(value.strip().title())
    return {field: values.pop() for field, values in found.items() if len(values) == 1}


def parse_vehicle_page(html: str, url: str, source: str, *, photos_approved=False, rendered_text='') -> dict:
    if not allowed_vehicle_url(url,source):
        raise ValueError('vdp_not_allowed_for_source')
    soup=BeautifulSoup(html,'html.parser')
    text=(' '.join([rendered_text.strip(), _text(soup)]) if rendered_text else _text(soup))
    structured=list(_structured_vehicles(soup))
    main=next((x for x in structured if x.get('vehicleIdentificationNumber') or x.get('vin')),structured[0] if structured else {})
    title_tag=soup.find('h1')
    meta_title=soup.select_one('meta[property="og:title"]')
    title=(title_tag.get_text(' ',strip=True) if title_tag else '') or (meta_title.get('content','') if meta_title else '')
    vin=_find_vehicle_vin(soup,text,html,main)
    if not vin:
        raise ValueError('vdp_missing_vin_after_render')
    if not title:
        raise ValueError('vdp_missing_title')
    year,make,model,trim=_title_parts(title)
    matched=next((item for item in structured
                  if str(item.get('vehicleIdentificationNumber') or item.get('vin') or '').upper()==vin),{})
    main=matched or (main if not (main.get('vehicleIdentificationNumber') or main.get('vin')) else {})
    price=_extract_price(text,soup,main)
    stock=_labeled(text,r'Stock\s*(?:Number|#|No\.?)*',r'((?=[A-Z0-9-]*\d)[A-Z0-9-]{2,40})')
    mileage=_labeled(text,r'(?:Mileage|Odometer)',r'([\d,]+)\s*(?:miles?|mi\b)?')
    specs={}
    # Use only structured specs tied to the VIN read from this vehicle page.
    for field,key in (('exterior_color','color'),('interior_color','vehicleInteriorColor'),
                      ('engine','vehicleEngine'),('transmission','vehicleTransmission'),
                      ('drivetrain','driveWheelConfiguration'),('fuel_type','fuelType'),('body_style','bodyType')):
        value=matched.get(key)
        if isinstance(value,dict):
            value=value.get('name') or value.get('engineType')
        if isinstance(value,str) and 0<len(value.strip())<=100:
            value=valid_spec(field,value)
            if value: specs[field]=value
    # Conservative visible label/value fallback. Never parse flattened page text
    # across unrelated sections, and never replace VIN-matched structured values.
    spec_labels = {'exterior color':'exterior_color', 'interior color':'interior_color',
                   'engine':'engine', 'transmission':'transmission', 'drivetrain':'drivetrain',
                   'fuel type':'fuel_type', 'body style':'body_style', 'body type':'body_style',
                   'body/seating':'body_style'}
    for label in soup.find_all(['dt', 'th', 'span', 'div']):
        if label.find(['dt','th','span','div']):
            continue
        key = spec_labels.get(label.get_text(' ', strip=True).strip(': ').lower())
        if not key or specs.get(key):
            continue
        value_node = label.find_next_sibling()
        if value_node is None:
            continue
        value = value_node.get_text(' ', strip=True)
        if value and len(value) <= 100 and value.strip(': ').lower() not in spec_labels:
            value=valid_spec(key,value)
            if value: specs[key] = value
    # Preserve line boundaries from captured visible/accordion text. Structured
    # VIN-matched values and explicit DOM pairs keep precedence.
    for spec_text in (rendered_text, soup.get_text('\n', strip=True)):
        for key, value in _specs_from_lines(spec_text).items():
            if not specs.get(key):
                specs[key] = value
    # Dealer's own normalized colors (used for Facebook's fixed color list).
    for key, value in _dealer_generic_colors(html, vin).items():
        specs.setdefault(key, value)
    # Capture the VDP's lead separately. The interactive viewer can open on a
    # later slide and its carousel order is not evidence of the listing cover.
    declared=matched.get('image') or []
    declared=declared if isinstance(declared,list) else [declared]
    primary=soup.select_one('meta[property="og:image"]')
    options=declared[:1]+([primary.get('content','')] if primary else [])
    lead=''
    for item in options:
        if isinstance(item,dict):item=item.get('url') or item.get('contentUrl')
        if not isinstance(item,str) or not item.strip():continue
        candidate=urljoin(url,item.strip())
        if (valid_url(candidate,image=True) and
            not re.search(r'(?:^|[\/_.-])(?:logo|placeholder|no-photo|noimage|generic|default|coming-soon)(?:[\/_.-]|$)',
                          urlsplit(candidate).path,re.I)):
            lead=candidate
            break
    images=_find_images(soup,main,url,lead)
    # Preserve the actual URL variant selected by the gallery deduper.
    lead=next((image for image in images if lead and urlsplit(image).netloc.lower()==urlsplit(lead).netloc.lower()
               and urlsplit(image).path.lower()==urlsplit(lead).path.lower()),'')
    desc='Advertised dealership prices and availability are subject to change. Confirm with the dealership before posting.'
    disclosure_match=re.search(r'(?:\*?Pricing may include|\*?Picture may not represent|All prices (?:plus|are plus)|Dealer doc fee)\b.{0,700}',text, re.I)
    if disclosure_match: desc=disclosure_match.group(0)[:800]
    if price is None:
        ref=re.search(r'\$\s*([\d,]+(?:\.\d{2})?)\s+(TSRP|MSRP)\b',text,re.I)
        if ref:
            desc=f'Reference {ref.group(2).upper()}: ${ref.group(1)}. Not a confirmed selling price. '+desc
    # Return a feed-shaped record, not only the internal normalized representation:
    # import_feed() normalizes once more and expects an actual `price` field.
    record={'vin':vin,'year':year,'make':make,'model':model,'trim':trim,
            'stock':stock,'price':price,'mileage':mileage,'url':url,'images':images,'dealer_lead_photo':lead,
            'images_approved':photos_approved,'availability':'available','disclaimer':desc,'specifications':specs}
    normalize(source,record)  # validate before the record enters a scan result
    return record


class RobotsGate:
    def __init__(self):
        self.parsers={}
        self.declared_sitemaps={}
    def permitted(self,url):
        p=urlsplit(url)
        root=f'{p.scheme}://{p.netloc}'
        if root not in self.parsers:
            robots=f'{root}/robots.txt'
            # Fail closed when robots cannot be retrieved. No bypass.
            try:
                req=Request(robots,headers={'User-Agent':AGENT})
                with urlopen(req,timeout=15) as res:
                    if res.status!=200:raise RuntimeError(f'robots HTTP {res.status}')
                    data=res.read(1_000_000).decode('utf8','replace')
                rp=RobotFileParser();rp.set_url(robots);rp.parse(data.splitlines())
                self.parsers[root]=rp
                self.declared_sitemaps[root]=[line.split(':',1)[1].strip() for line in data.splitlines()
                    if line.lower().startswith('sitemap:')]
            except Exception as ex:
                raise RuntimeError(f'robots_unavailable_stop_scanning: {type(ex).__name__}') from ex
        return bool(self.parsers[root].can_fetch(AGENT,url))
    def sitemaps_for(self,root):
        # Initialize the robots rules before discovering site-index locations.
        self.permitted(root+'/')
        return self.declared_sitemaps.get(root,[])


class ScanFailure(RuntimeError):
    """Structured diagnostic that the local server can serialize without secrets."""
    def __init__(self, code, samples=None):
        super().__init__(code)
        self.samples = samples or []


def scan_source(source, *, max_vehicles=250, photos_approved=False, delay=0.8,
                progress=None):
    """Discover inventory VDPs via rendered cards or compliant sitemap fallback.

    Website scans are deliberately PARTIAL. Empty or invalid scrapes raise a
    diagnostic failure and never update the database.
    """
    if source not in SOURCES:raise ValueError('unsupported_source')
    if not 1<=max_vehicles<=800:raise ValueError('invalid_vehicle_limit')
    if delay<0.5:raise ValueError('minimum_request_delay_500ms')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as ex:
        raise RuntimeError('playwright_not_installed; launcher must repair setup') from ex
    target=SITES[source]
    gate=RobotsGate()
    if not gate.permitted(target):raise RuntimeError('robots_disallow_inventory_index')
    rows=[];failures=[];discovered=[];discovery={'index_links':0,'featured_links':0,'sitemaps_checked':0,'sitemap_warnings':[]}
    def update(phase,**numbers):
        if progress:progress(phase,**numbers)
    update('loading_inventory',discovered=0,parsed=0)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            # Use Playwright's real browser UA. A fabricated headless-only UA
            # can cause Dealer.com to serve empty skeleton markup.
            context=browser.new_context(viewport={'width':1440,'height':950},locale='en-US')
            page=context.new_page()
            page.goto(target,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(2000)
            stagnant=0
            for step in range(24):
                batch=vehicle_links(page.content(),target,source)
                for link in batch:
                    if link not in discovered:discovered.append(link)
                if len(discovered)>=max_vehicles:break
                before=len(discovered)
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(1250)
                for label in (r'Load more',r'Show more',r'See more',r'Next page'):
                    try:
                        btn=page.get_by_role('button',name=re.compile(label,re.I))
                        if btn.count() and btn.first.is_visible():
                            btn.first.click(timeout=2500);page.wait_for_timeout(1200)
                            break
                    except Exception:pass
                for link in vehicle_links(page.content(),target,source):
                    if link not in discovered:discovered.append(link)
                stagnant=stagnant+1 if len(discovered)==before else 0
                if stagnant>=6:break
            discovery['index_links']=len(discovered)
            # Public featured pages typically render actual VDP anchors, even
            # when the main inventory SPA is nothing but loading skeletons.
            if len(discovered)<10:
                condition='new' if source.endswith('_new') else 'pre-owned'
                featured=f'{urlsplit(target).scheme}://{urlsplit(target).netloc}/featured-vehicles/{condition}.htm'
                try:
                    if gate.permitted(featured):
                        page.goto(featured,wait_until='domcontentloaded',timeout=30000)
                        page.wait_for_timeout(750)
                        found=vehicle_links(page.content(),featured,source)
                        discovery['featured_links']=len(found)
                        for link in found:
                            if link not in discovered:discovered.append(link)
                except Exception as e:
                    discovery['featured_warning']=f'{type(e).__name__}: {str(e)[:80]}'
            active_links=set(discovered)
            update('inventory_discovered',discovered=len(discovered),parsed=0)
            # Sitemaps are a last resort, not proof of current stock. VDPs
            # discovered *only* via sitemap are imported as PENDING.
            if len(discovered)<10:
                more,report=sitemap_vehicle_links(gate,source,max_vehicles=max_vehicles,delay=delay)
                discovery.update(report)
                for link in more:
                    if link not in discovered:discovered.append(link)
                    if len(discovered)>=max_vehicles:break
            # Generic model landing pages can look like VDP links; do not visit
            # them just because a sitemap happens to contain /new/*.htm.
            filtered = [u for u in discovered if re.search(r'/(?:19|20)\d{2}-[^/]+-[a-f0-9]{20,}\.htm$',urlsplit(u).path,re.I)]
            if filtered:
                discovery['model_landing_links_excluded'] = len(discovered)-len(filtered)
                discovered = filtered
            if not discovered:
                raise RuntimeError('NO_VDP_LINKS: Inventory cards did not load and accessible sitemaps had no VDP URLs. '
                                   'No data was changed. Check website access/robots rules and attach scan diagnostics.')
            detail=context.new_page()
            sample_failures=[]
            consecutive_failures=0
            consecutive_denied=0
            total=len(discovered[:max_vehicles])
            for n,url in enumerate(discovered[:max_vehicles],1):
                found_vin='';found_stock=''
                page_status=None
                final_url=url
                page_title=''
                body_snippet=''
                try:
                    if not gate.permitted(url):
                        raise ValueError('robots_disallow_detail')
                    response=detail.goto(url,wait_until='domcontentloaded',timeout=35000)
                    page_status=response.status if response else None
                    final_url=detail.url
                    if urlsplit(final_url).path != urlsplit(url).path:
                        raise ValueError(f'vdp_redirected_to:{urlsplit(final_url).path[:100]}')
                    if page_status and page_status>=400:
                        raise ValueError(f'vdp_http_{page_status}')
                    # Dealer.com loads vehicle details after DOMContentLoaded. Wait
                    # for an actual labeled VIN, NOT merely an h1 loading skeleton.
                    try:
                        detail.wait_for_function(r'''() => {
                          const t = document.body?.innerText || '';
                          const hasVisibleVin = /\bVIN\s*[:#]?\s*[A-HJ-NPR-Z0-9]{17}\b/i.test(t);
                          const hasStructuredVin = /["'](?:vin|vehicleIdentificationNumber)["']\s*:\s*["'][A-HJ-NPR-Z0-9]{17}["']/i.test(document.documentElement.outerHTML);
                          return hasVisibleVin || hasStructuredVin;
                        }''',timeout=10000)
                    except Exception:
                        pass  # Parser emits a diagnostic from the rendered page.
                    rendered=detail.locator('body').inner_text(timeout=3000) if detail.locator('body').count() else ''
                    html=detail.content()
                    page_title=detail.title()[:100]
                    body_snippet=re.sub(r'\s+',' ',rendered).strip()[:180]
                    if not _find_vehicle_vin(BeautifulSoup(html,'html.parser'),rendered,html,{}):
                        # Try a conventional public HTML request. It sometimes
                        # contains server-rendered vehicle data unavailable in
                        # a JS client that never hydrated on this PC.
                        try:
                            rec=read_static_vdp(url,source,photos_approved=photos_approved)
                        except Exception as fallback_error:
                            raise ValueError(classify_non_vehicle_page(rendered,final_url,url,page_status)+
                                '; static_fallback:'+str(fallback_error)[:78]) from fallback_error
                    else:
                        rec=parse_vehicle_page(html,url,source,photos_approved=photos_approved,rendered_text=rendered)
                    if url not in active_links:
                        rec['availability']='pending'  # sitemap alone never proves in-stock
                    if not rec.get('stock') or rec.get('mileage') is None or not rec.get('images'):
                        rec['scan_missing_fields']=[x for x in ('stock','mileage','images') if not rec.get(x)]
                    rows.append(rec)
                    found_vin=rec.get('vin','');found_stock=rec.get('stock','')
                    consecutive_failures=0
                    consecutive_denied=0
                except Exception as ex:
                    reason=str(ex)[:160]
                    # Page excerpt is deliberately short and does not contain
                    # cookies, credentials, HTML, personal messages or tokens.
                    evidence={'url':url,'reason':reason,'status':page_status,
                              'final_url':final_url,'title':page_title,
                              'body_excerpt':body_snippet}
                    failures.append(evidence)
                    if len(sample_failures)<EARLY_ABORT_FAILURES:sample_failures.append(evidence)
                    consecutive_failures+=1
                    if page_status == 403: consecutive_denied += 1
                    else: consecutive_denied = 0
                # One honest progress event per attempted vehicle detail page.
                # No fabricated source output; fields come from this actual navigation/parser.
                update('reading_vehicles',discovered=len(discovered),parsed=len(rows),
                       visited=n,failed=len(failures),last_url=url[:180],
                       last_http_status=page_status,last_vin=found_vin,last_stock=found_stock,
                       last_failure=failures[-1]['reason'] if failures and consecutive_failures else '')
                if not rows and consecutive_denied>=2:
                    update('early_abort',discovered=len(discovered),parsed=0,visited=n,failed=len(failures),
                           last_failure='SITE_ACCESS_RESTRICTED_403',
                           stop_reason='HTTP 403 on two sampled vehicle pages; VIN parser not reached')
                    raise ScanFailure('SITE_ACCESS_RESTRICTED_403: dealer denied two detail page requests. '
                      'No further automated requests attempted for this section. Transfer a permitted '
                      'inventory export or use the working scanner output.', sample_failures)
                if not rows and consecutive_failures>=EARLY_ABORT_FAILURES:
                    update('early_abort',discovered=len(discovered),parsed=0,visited=n,failed=len(failures),
                           last_failure='VDP_SAMPLE_FAILED',stop_reason='First five VDPs produced zero valid vehicles')
                    raise ScanFailure('VDP_SAMPLE_FAILED: first '+str(EARLY_ABORT_FAILURES)+
                      ' detail URLs had no usable VINs. Stopped to avoid a wasteful full-site scan.',sample_failures)
                time.sleep(delay)
        finally:browser.close()
    if not rows:
        reasons='; '.join(f['reason'] for f in failures[:3]) or 'unknown'
        raise RuntimeError('ZERO_VALID_VINS: discovered '+str(len(discovered))+
                           ' URLs but parsed no usable VIN records. First failures: '+reasons)
    complete_details=sum(bool(r.get('vin') and r.get('stock') and r.get('model') and r.get('images')
                              and (r.get('mileage') is not None or source.endswith('_new'))) for r in rows)
    update('finished',discovered=len(discovered),parsed=len(rows),complete_details=complete_details)
    return {'source':source,'vehicles':rows,'scraper':{
        'scanned_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'listing_pages_discovered':len(discovered),'detail_parsed':len(rows),
        'complete_vehicle_records':complete_details,
        'sitemap_only_pending':sum(r['availability']=='pending' for r in rows),
        'failures':failures[:200],
        'discovery':discovery,'is_full_snapshot':False,
        'notice':'Website scans are partial. Missing VINs never imply sold. Photos require separate permission.'}}


def main():
    ap=argparse.ArgumentParser(description='Hampton public dealership website scraper - internal preview')
    ap.add_argument('--source',choices=list(SOURCES)+['all'],default='all')
    ap.add_argument('--output-dir',default=str(Path.home()/'MarketplaceScannerScans'))
    ap.add_argument('--max-vehicles',type=int,default=250)
    ap.add_argument('--delay',type=float,default=0.8)
    ap.add_argument('--photos-approved',action='store_true',help='Only use if the dealer has permitted image reuse')
    ap.add_argument('--import-into-store',action='store_true',help='Import partial scan into private Marketplace SQLite store')
    ap.add_argument('--data-dir',help='Override private Marketplace data directory')
    args=ap.parse_args()
    dest=Path(args.output_dir).expanduser().resolve();dest.mkdir(parents=True,exist_ok=True)
    sources=SOURCES if args.source=='all' else [args.source]
    errors=[]
    for src in sources:
        try:
            output=scan_source(src,max_vehicles=args.max_vehicles,photos_approved=args.photos_approved,delay=args.delay)
            if not output['vehicles']:raise RuntimeError('no_valid_vin_records; prior_store_untouched')
            path=dest/(src+'_website_PARTIAL.json')
            path.write_text(json.dumps(output,indent=2),encoding='utf8')
            print(src, len(output['vehicles']), 'VINs =>',path,'failures=',len(output['scraper']['failures']))
            if args.import_into_store:
                from core import MarketplaceStore
                from server import default_data_dir
                store=MarketplaceStore(args.data_dir or default_data_dir())
                try:print('Imported:',store.import_feed(src,'json',json.dumps(output),complete=False))
                finally:store.close()
        except Exception as ex:
            print(src,'SCAN FAILED',type(ex).__name__,str(ex))
            errors.append(src)
    if errors:raise SystemExit(2)
if __name__=='__main__':main()


# Offline external inventory transfer adapter; never calls dealership websites.
import csv
import io
from collections import defaultdict
HOSTS = {'www.hamptontoyota.com':'toyota','hamptontoyota.com':'toyota',
         'www.hamptonmitsubishi.com':'mitsubishi','hamptonmitsubishi.com':'mitsubishi'}
MAX_BYTES = 12_000_000
GROUP_KEYS = set(SOURCES)

def keymap(record):
    return {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in record.items()}

def val(d, *aliases):
    for alias in aliases:
        v = d.get(re.sub(r'[^a-z0-9]', '', alias.lower()))
        if v is not None and v != '':
            return v
    return None

def unwrap(root):
    if isinstance(root, list):
        return [(None, r) for r in root]
    if not isinstance(root, dict):
        raise ValueError('export_root_must_be_object_or_array')
    out = []
    # Source-grouped data, including a saved Marketplace diagnostics wrapper.
    for source in SOURCES:
        item = root.get(source)
        if isinstance(item, list):
            out.extend((source, row) for row in item)
        elif isinstance(item, dict):
            inner = item.get('vehicles', item.get('inventory', item.get('items', [])))
            if isinstance(inner, list): out.extend((source, row) for row in inner)
    if out:return out
    for wrapper in ('results','data','sources','inventory'):
        value = root.get(wrapper)
        if isinstance(value, dict):
            try:
                nested=unwrap(value)
                if nested:return nested
            except ValueError:pass
    group = root.get('source') if root.get('source') in SOURCES else None
    for key in ('vehicles','inventory','items','records','listings','results','data'):
        rows=root.get(key)
        if isinstance(rows,list):return [(group, row) for row in rows]
    if 'vin' in keymap(root):return [(group,root)]
    raise ValueError('no_inventory_rows_found_in_export')

def parse_export(content, fmt):
    if not isinstance(content,str) or not 0 < len(content.encode('utf-8')) <= MAX_BYTES:
        raise ValueError('invalid_export_size')
    if fmt=='csv':
        return [(None,row) for row in csv.DictReader(io.StringIO(content.lstrip('\ufeff')))]
    if fmt=='json':
        return unwrap(json.loads(content))
    raise ValueError('export_must_be_json_or_csv')

def determine_source(fields, grouped=None, fallback=None):
    source=val(fields,'source','source_id','inventory_source') or grouped
    if isinstance(source,str) and source.strip().lower() in SOURCES:
        return source.strip().lower()
    url=val(fields,'url','vehicle_url','vdp_url','detail_url','link','listing_url')
    dealer=''
    condition=''
    if isinstance(url,str) and url.startswith('https://'):
        u=urlsplit(url)
        dealer=HOSTS.get((u.hostname or '').lower(),'')
        if u.path.startswith('/new/'):condition='new'
        elif u.path.startswith('/used/'):condition='used'
    hint=str(val(fields,'dealer','dealership','dealer_name','store','location') or '').lower()
    if not dealer:
        if 'hampton toyota' in hint or hint=='toyota':dealer='toyota'
        if 'hampton mitsubishi' in hint or hint=='mitsubishi':dealer='mitsubishi'
    kind=str(val(fields,'condition','new_used','vehicle_condition','type') or '').lower().strip()
    if kind in ('new','n'):condition='new' if not condition else condition
    if kind in ('used','u','pre-owned','preowned','pre owned'):condition='used' if not condition else condition
    inferred=f'{dealer}_{condition}' if dealer and condition else None
    if isinstance(source,str) and source.strip().lower() in SOURCES:
        inferred=source.strip().lower()
    if fallback in SOURCES:
        if inferred and inferred!=fallback:
            raise ValueError('fallback_source_conflicts_with_record')
        return fallback
    if inferred in SOURCES:return inferred
    raise ValueError('dealer_and_condition_not_identifiable')

def convert(group, raw, fallback=None):
    if not isinstance(raw,dict):raise ValueError('export_row_not_object')
    d=keymap(raw)
    source=determine_source(d,group,fallback)
    price=val(d,'hampton_price','internet_price','sale_price','selling_price','dealer_price','price','msrp')
    images=val(d,'images','photos','image_urls','photo_urls','photo_list','pictures','image','photo') or []
    if isinstance(images,list):
        images=[(i.get('url') or i.get('src') or i.get('href')) if isinstance(i,dict) else i for i in images]
        images=[i for i in images if isinstance(i,str) and i.startswith('https://')][:250]
    if isinstance(images,dict):images=[v for v in images.values() if isinstance(v,str) and v.startswith('https://')][:250]
    if isinstance(images,str):
        images=[s.strip() for s in re.split(r'[|;\n]',images) if s.strip()]
    record={
      'vin':val(d,'vin','vehicle_vin','vehicle_identification_number','vehicle_identification_number'),
      'year':val(d,'year','model_year'),
      'make':val(d,'make','manufacturer','vehicle_make'),
      'model':val(d,'model','vehicle_model'),
      'trim':val(d,'trim','series','vehicle_trim') or '',
      'stock':val(d,'stock','stock_number','stock_no','stock_id','stocknum') or '',
      'mileage':val(d,'mileage','odometer','miles','mileage_miles'),
      'price':price,
      'url':val(d,'url','vehicle_url','vdp_url','detail_url','listing_url','link') or '',
      'images':images,
      'images_approved':False,  # importing does not grant photo publishing permission
      'availability':str(val(d,'availability','inventory_status','status') or 'pending').lower(),
      'disclaimer':str(val(d,'disclaimer','price_disclaimer') or '')[:800],
    }
    # Force consistency between the claimed source and actual dealer VDP URL.
    url=record['url']
    if url:
        u=urlsplit(str(url)); actual=HOSTS.get((u.hostname or '').lower())
        if actual and not source.startswith(actual+'_'):
            raise ValueError('source_conflicts_with_dealer_url')
        if actual and u.path.startswith('/new/') and not source.endswith('_new'):
            raise ValueError('new_vehicle_url_source_mismatch')
        if actual and u.path.startswith('/used/') and not source.endswith('_used'):
            raise ValueError('used_vehicle_url_source_mismatch')
    normalize(source,record)
    return source,record

def prepare(content, fmt, fallback=None):
    if fallback not in (None, 'auto', *SOURCES):raise ValueError('invalid_fallback_source')
    pairs=parse_export(content,fmt)
    if len(pairs)>25000:raise ValueError('too_many_inventory_rows')
    if not pairs:raise ValueError('empty_inventory_export')
    groups=defaultdict(list); errors=[]; seen=defaultdict(set)
    for i,(source,row) in enumerate(pairs,1):
        try:
            dest,converted=convert(source,row,fallback if fallback!='auto' else None)
            if converted['vin'] in seen[dest]:
                # Duplicate same-source VIN needs review, never silently replace.
                raise ValueError('duplicate_vin_in_source_export')
            seen[dest].add(converted['vin'])
            groups[dest].append(converted)
        except (ValueError,TypeError) as ex:
            errors.append({'row':i,'reason':str(ex)[:90]})
    if not groups:raise ValueError('no_valid_rows; first_errors='+', '.join(e['reason'] for e in errors[:3]))
    return {'groups':dict(groups),'preview':{'received':len(pairs),'valid':sum(len(x) for x in groups.values()),
        'rejected':len(errors),'by_source':{k:len(v) for k,v in groups.items()},'sample_rejections':errors[:15],
        'complete':False,'photo_publishing_permission':False}}
