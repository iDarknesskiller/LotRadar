"""Evidence-only Hampton dealer equipment extraction and ranking.

The source is a rendered vehicle detail page already opened by the paired Chrome
extension; this module never makes network requests. Website text is untrusted
facts, NOT instructions. No equipment is inferred from trim/model names.
"""
from __future__ import annotations
import re

SECTIONS = {
    'the highlights', 'highlighted features', 'key features', 'vehicle features',
    'included packages', 'features & options', 'equipment highlights',
    'a closer look at what’s included', "a closer look at what's included",
    'more manufacturer pre-installed items', 'all included items', 'all highlights',
}
STOP = {
    'the full specifications', 'full specifications', 'notes from the dealer',
    'price details', 'build your offer', 'finance', 'cash', 'saves 45 min. at dealership',
    'offer breakdown', 'similar vehicles', 'schedule a test drive',
    'vehicle history report', 'peace of mind', 'our dealership', 'our inventory',
    'a name you can trust', 'have questions?', 'service & parts',
    'new inventory', 'pre-owned', 'featured vehicles', 'current specials',
    'contact us', 'about us', 'privacy', 'sitemap',
}
SIGNALS = re.compile(
    r'(?i)(?:engine|motor|diesel|turbo|horsepower|\bHP\b|torque|drivetrain|\bAWD\b|\b4WD\b|\b4x4\b|'
    r'all[- ]wheel|four[- ]wheel|rear[- ]wheel|front[- ]wheel|transmission|\bCVT\b|'
    r'package|edition|leather|heated|ventilat|sunroof|moonroof|panoram|audio|sound|'
    r'navigation|infotainment|carplay|android auto|touchscreen|touch screen|bluetooth|'
    r'camera|blind spot|blindspot|cruise|parking|brak|lane|safety|assist|'
    r'tow|trail|off[- ]road|transfer case|differential|tailgate|bed liner|'
    r'headlights|wireless|charging|climate|air conditioning|seats?|seatbelt|soft top|removable roof|heavy-duty modular|bumper|skid plate|'
    r'collision|pedestrian|alert|suspension|terrain|display|screen|'
    r'keyless|remote start|push.button|steering|monitor|recognition|'
    r'hybrid|EV battery|sport tuned|LED|sensor|wheels?|\bUSB\b|Wi-Fi|hotspot)'
)
EXCLUDE = re.compile(
    r'(?i)(?:https?://|www\.|\b(?:learn more|view details|click|shop|browse|'
    r'contact us|schedule|payment|financing|offer|apply for|monthly|dealer|'
    r'carfax|warranty|terms and conditions|availability|taxes|registration|'
    r'vehicle specials|discount|savings|\d{3}[-.]\d{3}[-.]\d{4})\b)'
)
BORING = re.compile(r'(?i)(?:cupholders?|airbags?\b|spare tire|seatbelts?|'
                    r'wipers?|coat hooks?|vanity mirrors?|floor mats?|'
                    r'front crumple zones?|door pockets?|gas (?:front|rear) shock)')


def _extract_section_equipment(text, limit=120):
    """Read explicit VDP feature sections, including the expanded all-items list.

    Never harvest the general page footer, other recommended vehicles, or
    financing widgets. Returned entries are exact equipment descriptions from
    the dealership, not AI-generated vehicle specifications.
    """
    if not isinstance(text,str): return []
    lines=[' '.join(x.split()).strip() for x in text[:160000].splitlines()]
    found=[];seen=set();active=False
    for line in lines:
        low=line.casefold().strip(' :•-*')
        if low in SECTIONS or re.fullmatch(r'all\s+\d+\s+highlights',low):
            if low.startswith('all ') and low.endswith(' highlights'):
                active=False
            else:
                active=True
            continue
        if low in STOP or low.startswith(('picture may not represent','*estimated monthly payment')):
            active=False;continue
        if not active or not line: continue
        entry=re.sub(r'^[\s✔✓•\-*]+','',line).strip()
        if not 5 <= len(entry) <= 110:continue
        if EXCLUDE.search(entry) or not SIGNALS.search(entry):continue
        if re.match(r'(?i)^(?:all \d+ highlights|more manufacturer|all included|\d+ photos)',entry):continue
        key=re.sub(r'\W+','',entry.casefold())
        if key not in seen:
            seen.add(key);found.append(entry)
            if len(found)>=limit:break
    # VDP overview often joins field labels without whitespace:
    # "TransmissionCVTEngine2.5L Hybrid I4 225hpVIN...".
    # Engine displacement/cylinder type and transmission are explicit; do not
    # trust horsepower if other labeled horsepower figures disagree.
    intro=text[:9000]
    engine=re.search(r'Engine\s*((?:[0-9]\.[0-9]L)\s+(?:Hybrid\s+)?(?:I[3468]|V[468]|Flat[- ]?[46])\b)',intro,re.I)
    transmission=re.search(r'Transmission\s*(CVT|[0-9]+[- ]speed(?:\s+automatic|\s+manual)?|Automatic|Manual)(?=Engine|VIN|Stock|\s|$)',intro,re.I)
    extra=[]
    if engine:extra.append(engine.group(1).strip()+' Engine')
    if transmission:extra.append(transmission.group(1).upper()+' Transmission')
    if extra:
        found=extra+[x for x in found if x.casefold() not in {y.casefold() for y in extra}]
    return found



# Only combine facts that appear in the SAME individual dealer page. Do not
# infer equipment from the trim name, VIN, marketing phrases, or manufacturer
# specifications for similar vehicles.
def _overview_features(text):
    intro=text[:14000]
    results=[]
    eng=re.search(r'(?i)Engine\s*([^\n]{3,145}?)(?=VIN|Stock\s*Number|\n|$)',intro)
    if eng:
        raw=eng.group(1).strip(' :')
        if re.search(r'(?i)\b(?:I[3468]|V[468]|4[- ]cylinder|6[- ]cylinder)\b',raw) and re.search(r'\b\d\.\d\s*L\b',raw,re.I):
            # An independent labeled horsepower field may describe engine-only
            # HP differently from total hybrid/system HP. Omit conflicting HP.
            power=re.search(r'\b(\d{2,4})\s*hp\b',raw,re.I)
            elsewhere=re.search(r'(?i)Horsepower\s*(\d{2,4})\b',intro)
            conflict=power and elsewhere and power.group(1)!=elsewhere.group(1)
            engine=re.split(r'\b\d{2,4}\s*hp\b',raw,maxsplit=1,flags=re.I)[0].strip(' ,:-')
            engine=re.sub(r'\s+',' ',engine)
            if conflict:
                results.append(engine+' Engine')
            elif power:
                torque=re.search(r'(?i)(\d{2,4})\s*(?:ft\.?\s*lbs?\.?|lb[- ]?ft)',raw)
                suffix=f' – {power.group(1)} HP'
                if torque:suffix+=f' / {torque.group(1)} LB-FT'
                results.append(engine+suffix)
            else:
                results.append(engine+' Engine')
    trans=re.search(r'(?i)Transmission\s*([^\n]{1,65}?)(?=Engine|VIN|Stock\s*Number|\n|$)',intro)
    if trans:
        raw=trans.group(1).strip(' :')
        if re.search(r'(?i)\b(?:CVT|automatic|manual|\d+[- ]speed)\b',raw):
            results.append(raw.upper()+' Transmission' if raw.upper()=='CVT' else raw+' Transmission')
    return results


def _full_spec_features(text):
    """Pick equipment from *this vehicle's* full-spec list, not from page footer.

    A rendered Dealer.com page exposes headings such as Powertrain, Seats and
    Trim, Entertainment Features, Suspension/Handling, and Safety and Security.
    We accept their short equipment lines while ignoring specs/dimensions,
    footers, finance terms, and unrelated vehicle recommendations.
    """
    lines=[re.sub(r'\s+',' ',x).strip(' \t•*-') for x in text.splitlines()]
    active=False;out=[];seen=set()
    for line in lines:
        low=line.casefold().strip(' :')
        if low in ('the full specifications','full specifications'):
            active=True;continue
        if active and low in ('notes from the dealer','price details','track your progress','peace of mind','similar vehicles','other vehicles'):
            active=False;continue
        if not active or not 5<=len(line)<=110:continue
        if line in ('Powertrain','Seats and Trim','Convenience Features','Entertainment Features','Suspension/Handling','Safety and Security','Body Exterior','Specs and Dimensions','Lighting, Visibility and Instrumentation'):
            continue
        if EXCLUDE.search(line) or not SIGNALS.search(line) or BORING.search(line):continue
        key=re.sub(r'\W+','',low)
        if key not in seen:seen.add(key);out.append(line)
    return out


def _curated_combined_facts(text):
    # This is deterministic evidence aggregation: NEVER look up a model's
    # standard equipment or infer what's installed on this particular vehicle.
    low=text.casefold();out=[]
    def has(pattern):return bool(re.search(pattern,low,re.I))
    if has(r'front locking differential') and has(r'rear locking differential'):
        out.append('Front & Rear Locking Differentials')
    if has(r'wireless apple carplay') and has(r'wireless android auto'):
        out.append('Wireless Apple CarPlay & Android Auto')
    if has(r'4wd|4x4|drive type:\s*four-wheel|four-wheel drive'):
        if has(r'electronic hi-lo 4wd selector'):
            out.append('4WD with Electronic Hi-Lo Selector')
        else:out.append('4WD')
    if has(r'12 in\. infotainment screen size|primary lcd size:\s*12') and has(r'\bsync(?:\s*4)?\b'):
        if has(r'touch screen display radio|infotainment touchscreen|12-inch infotainment touchscreen|12\.0.{0,18}(?:touch|lcd)'):
            out.append('12-Inch Infotainment Touchscreen with SYNC')
        else:out.append('12-Inch Infotainment Display with SYNC')
    if has(r'12 in\. instrument cluster screen size|12-inch (?:digital |customizable )?instrument cluster'):
        out.append('12-Inch Digital Instrument Cluster')
    if has(r'hill descent off-road driving assist|hill descent control') and has(r'hill ascent off-road driving assist|hill ascent control'):
        out.append('Hill Ascent & Descent Assist')
    if has(r'front skid plate') and has(r'rear skid plate') and has(r'powertrain skid plate'):
        out.append('Front, Rear & Powertrain Skid Plates')
    elif has(r'skid plates|skid plate\('):out.append('Skid Plates')
    if has(r'soft top removable roof|removable soft top'):
        out.append('Removable Soft Top')
    if has(r'ford performance heavy-duty modular front bumper'):
        out.append('Ford Performance Heavy-Duty Modular Front Bumper')
    if has(r'off-road tuned suspension'):
        out.append('Off-Road Tuned Suspension')
    if has(r'7-pin trailer wiring'):
        out.append('7-Pin Trailer Wiring')
    if has(r'rearview camera system|exterior parking camera rear|rearview camera'):
        out.append('Rearview Camera')
    if has(r'front automatic emergency braking') and has(r'pedestrian detection'):
        out.append('Automatic Emergency Braking with Pedestrian Detection')
    return out


def extract_dealer_equipment(text, limit=120):
    if not isinstance(text,str):return []
    limit=min(max(int(limit),1),240)
    # Prefer readable, buyer-relevant combinations at the start, but retain
    # exact source entries for transparency and reviewer inspection.
    original=_extract_section_equipment(text, limit=240)
    spec=_full_spec_features(text)
    # Combine only facts extracted from the target VDP equipment/spec sections,
    # never unscoped related-car ads or website footer text.
    extra=_overview_features(text)+_curated_combined_facts('\n'.join(original+spec))+spec
    output=[];seen=set()
    for item in extra+original:
        item=re.sub(r'(?i)Disclaimer\s*$','',item).strip()
        if not 4<=len(item)<=110 or EXCLUDE.search(item):continue
        key=re.sub(r'\W+','',item.casefold())
        if key not in seen:
            seen.add(key);output.append(item)
        if len(output)>=limit:break
    return output


def has_explicit_carfax_one_owner(text):
    """Claim only a CARFAX 1-Owner badge explicitly shown on this VDP.

    The field is deliberately distinct from accident history. A one-owner badge
    NEVER proves that CARFAX is clean or that a vehicle is accident-free.
    """
    if not isinstance(text,str):return False
    # Restrict to the top of a single vehicle detail page: avoid similar-cars,
    # dealership footer, and generic CARFAX promotional sections.
    top=text[:22000]
    end=re.search(r'(?im)^\s*(?:The highlights|The full specifications|Notes from the dealer|Similar vehicles)\s*$',top)
    if end:top=top[:end.start()]
    return bool(re.search(r'(?i)\bCARFAX\s*(?:[®:]\s*)?1[\s-]*Owner\b',top) or
                re.search(r'(?i)\b1[\s-]*Owner\s+CARFAX\b',top))


# ---- No colors in listing text -------------------------------------------
# Facebook has its own Exterior/Interior color fields. The dealer's build data
# names trim-part colors that are often wrong for the actual car ("Black Mirror
# Color" next to "Door mirrors: body-color"), so the post never mentions color.
_COLOR = (r'(?:black|white|gr[ae]y|silver|red|blue|green|brown|beige|tan|gold|bronze|charcoal|ivory|'
          r'ebony|graphite|ash|chrome|argent|gunmetal|burgundy|maroon|orange|yellow|purple|pink|'
          r'copper|champagne|pearl|metallic|mica|tri-?coat|tricoat|clear coat|satin|gloss(?:y)?|matte|piano)')
_SHADE = r'(?:(?:light|dark|medium|bright|deep|jet|midnight|gloss|satin|matte)\s+)'
# Brand and feature names that contain a color word but are not colors.
_PROTECT = re.compile(r'(?i)\b(?:blue\s*link|blue\s*cruise|bluecruise|bluetooth|black\s*box|red\s*line\s+(?:tach|limit)|'
                      r'white\s*noise|green\s*(?:mode|zone)|silverado|graphite\s*brake)\b')
_COLOR_LINE = re.compile(r'(?i)\bcolou?r(?:ed|s)?\b|\bcolou?r-keyed\b|\bbody-colou?r(?:ed)?\b|\bpaint(?:ed)?\b|\btwo-tone\b')
_COLOR_WORD = re.compile(r'(?i)(?<![\w-])' + _SHADE + r'?' + _COLOR + r'(?![\w-])')
_PART = re.compile(r'(?i)\b(?:roof rails?|rails?|upholstery|fabric|cloth|leather(?:ette)?|softex|suede|seats?|wheels?|rims?|console|glass)\b')
_FILLER = re.compile(r'(?i)^(?:and|w/|with|&|/|-|,|accents?|stitching|trim|finish(?:er)?|inserts?|exterior|interior|'
                     r'window trim|tailpipe finisher|exhaust tip|grille|moldings?|bezels?|rocker panels?|'
                     r'door handles?|mirrors?|bumpers?|spoiler|\s)*$')


def listing_text(item, record=None):
    """Equipment line as it may appear in a post, or None to leave it out.

    Lines that exist to describe a color are dropped. A color word on a real
    feature is removed ("Black Leather Seats" -> "Leather Seats"). The vehicle's
    own paint and interior names are never repeated in the post."""
    if not isinstance(item, str):
        return None
    text = re.sub(r'\s+', ' ', item).strip()
    if not 4 <= len(text) <= 110:
        return None
    if _COLOR_LINE.search(text):
        return None
    specs = (record or {}).get('specifications') or {}
    for key in ('exterior_color', 'interior_color', 'exterior_color_generic', 'interior_color_generic'):
        name = str(specs.get(key) or '').strip()
        # Plain color words ("Black") are handled below by removing the word, not the whole line.
        if len(name) >= 3 and _COLOR_WORD.sub('', name).strip(' /-&,') and re.search(r'(?i)(?<![\w-])' + re.escape(name) + r'(?![\w-])', text):
            return None
    protected = {}
    def keep(m):
        protected[f'\x00{len(protected)}\x00'] = m.group(0)
        return f'\x00{len(protected)-1}\x00'
    work = _PROTECT.sub(keep, text)
    if not _COLOR_WORD.search(work):
        return text
    work = _COLOR_WORD.sub(' ', work)
    work = re.sub(r'\s*(?:/|&|,|\bw/)\s*(?=$)', '', work)
    work = re.sub(r'^\s*(?:/|&|,|-|w/|and|with)\s*', '', work, flags=re.I)
    work = re.sub(r'\s+', ' ', work).strip(' ,/-&:')
    for token, original in protected.items():
        work = work.replace(token, original)
    # What is left must still be equipment; a paint name ("Super White" -> "Super") is not.
    if (len(work) < 4 or _FILLER.match(work) or not re.search(r'[A-Za-z]{3}', work)
            or not (SIGNALS.search(work) or _PART.search(work))):
        return None
    return work


def listing_features(record):
    """Positions match record['features'] so AI-chosen IDs stay valid; None = never shown."""
    return [listing_text(x, record) for x in (record.get('features') or [])]


def feature_category(raw):
    s=raw.casefold()
    if re.search(r'\b\d\.\d\s*l\b.*(?:v[468]|i[3468])|\b(?:diesel engine|twin.turbo v6|horsepower|\d+ hp|\d+ lb-ft)\b',s):return 'powertrain'
    if re.search(r'\b(?:awd|4wd|4x4)\b|all[- ]wheel drive|four[- ]wheel drive|front[- ]wheel drive|rear[- ]wheel drive',s):return 'drivetrain'
    if re.search(r'transmission|\bcvt\b',s):return 'transmission'
    if re.search(r'locking differential|off[- ]road|skid plate|tow|trailer|bumper|soft top|removable roof|hill (ascent|descent)|transfer case|upfitter switches|package|edition',s):return 'capability'
    if re.search(r'heated front seats|heated seats|ventilated seats|leatherette upholstery|leather seats|panoramic|moonroof|sunroof',s):return 'comfort'
    if re.search(r'carplay|android auto|wireless charging|navigation|premium audio|infotainment|touchscreen|touch screen|instrument cluster|\bsync\b',s):return 'technology'
    if re.search(r'blind.spot|rear cross.traffic|adaptive cruise|lane keeping|lane centering|parking assist|surround.view|pedestrian|collision|emergency brak',s):return 'safety'
    if re.search(r'camera|rearview monitor',s):return 'camera'
    if re.search(r'led headlights|led taillights|high beam|headlight',s):return 'lighting'
    return 'other'


def feature_score(raw):
    s=raw.casefold();cat=feature_category(raw)
    if BORING.search(s) or re.search(r'ventilated disc|stabilizer bar|strut tower bar|shock type|cup.?holder|power outlet|manual adjustments|warning warnings|\blamp failure\b',s):return -100
    if re.search(r'engine start/cabin|coolant temperature|low oil pressure|engine location|motor none|generator starter|visual warning pre-collision|audible warning pre-collision|emergency braking preparation|post-collision safety system impact sensor',s):return -100
    base={'powertrain':170,'drivetrain':164,'transmission':153,'capability':148,
          'comfort':130,'technology':141,'safety':115,'camera':111,'lighting':76,'other':50}[cat]
    if re.search(r'front & rear locking differential|front and rear locking differential',s):base+=52
    if re.search(r'\b\d\.\d\s*l\b.*(?:turbo|diesel|v6|v8)',s):base+=50
    if re.search(r'ford performance heavy-duty modular|off-road tuned suspension|removable soft top',s):base+=40
    if re.search(r'front, rear & powertrain skid plates|hill ascent & descent',s):base+=32
    if re.search(r'12-inch infotainment touchscreen|wireless apple carplay & android auto',s):base+=35
    if re.search(r'12-inch digital instrument cluster|7-pin trailer wiring',s):base+=20
    if re.search(r'heated front seats|ventilated seats|panoramic|premium audio',s):base+=27
    if re.search(r'adaptive cruise|blind spot|rear cross traffic',s):base+=12
    if re.search(r'leather steering|leather shift|automatic high beam|seat manual',s):base-=45
    return base


def _concept(item):
    s=item.casefold()
    for pattern,name in [
        (r'front & rear locking differential|(?:front|rear) locking differential','locking-diffs'),
        (r'carplay|android auto','phone-integration'),
        (r'12-inch infotainment|12 in\. infotainment|sync infotainment|touch screen display radio|12\.0.{0,10}lcd','infotainment'),
        (r'12-inch digital instrument cluster|12 in\. instrument cluster','instrument-cluster'),
        (r'\b(?:awd|4wd|4x4)\b|four-wheel drive|drive type: four-wheel','drive'),
        (r'\d[- ]speed.*transmission|transmission.*\d[- ]speed|cvt transmission','transmission'),
        (r'\b\d\.\d\s*l\b.*(?:engine|v6|v8|i4)|\d+ hp.*\d+ lb-ft','engine'),
        (r'off-road tuned suspension|monotube.*shock','offroad-suspension'),
        (r'front, rear & powertrain skid plates|(?:front|rear|powertrain) skid plate|\bskid plates\b','skid-plates'),
        (r'hill (?:ascent|descent)','hill-assist'),
        (r'rearview camera|exterior parking camera rear|rearview monitor','backup-camera'),
        (r'front automatic emergency braking|pedestrian detection.*(?:brak|pre-collision)|automatic emergency braking','emergency-braking'),
        (r'\bheated front seats\b|\bheated seats\b','heated-seats'),
        (r'removable soft top|soft top removable roof','roof'),
        (r'\b(?:led|auto.high.beam).*headlight','headlights'),
    ]:
        if re.search(pattern,s):return name
    return re.sub(r'\W+','',s)


def select_features(items, limit=15, indices=None, record=None):
    """Select substantial, diverse, source-supported features, not warnings.

    Positions are preserved (None = not usable) so AI-selected indices always
    point at the same equipment line. Color lines never qualify."""
    values=[listing_text(x, record) for x in (items or [])]
    ranked=sorted(((i,v) for i,v in enumerate(values) if v),key=lambda p:(-feature_score(p[1]),p[0]))
    usable=[i for i,v in ranked if feature_score(v)>=60]
    if indices is not None:
        requested=[]
        for i in indices:
            if type(i) is int and i in usable and i not in requested:requested.append(i)
        order=requested+[i for i in usable if i not in requested]
    else:order=usable
    offroad=any(v and re.search(r'locking differential|off-road tuned|skid plate|ford performance.*bumper',v,re.I) for v in values)
    quotas={'powertrain':2,'drivetrain':1,'transmission':1,'capability':6 if offroad else 4,
            'comfort':3,'technology':3 if offroad else 5,'safety':3 if offroad else 4,'camera':1,'lighting':1,'other':1}
    result=[];buckets={};used_concepts=set()
    for index in order:
        value=values[index];cat=feature_category(value);concept=_concept(value)
        if concept in used_concepts or buckets.get(cat,0)>=quotas[cat]:continue
        used_concepts.add(concept);buckets[cat]=buckets.get(cat,0)+1
        result.append(value)
        if len(result)>=limit:break
    return result


def verified_title(record):
    # Clean repeated dealership trim from the displayed title only.
    from core import dealer_vehicle_title
    title=dealer_vehicle_title(record)
    facts=' '.join(record.get('features') or [])
    if (re.search(r'\b4WD\b|\b4x4\b|four[- ]wheel drive|drive type:\s*four-wheel',facts,re.I)
        and not re.search(r'\b(?:4WD|4x4|AWD)\b',title,re.I)):
        title+=' 4x4'
    return title[:125]


def render_post(record, source, dealer, *, indices=None, highlights=None):
    """Stable output format. Never puts price/miles/stock/VIN into the post."""
    features=select_features(record.get('features') or [],indices=indices,record=record)
    clean=listing_features(record)
    out=[f'🔥 {verified_title(record)} 🔥']
    # Highlights use ONLY exact verified features, not inferred sales claims.
    if highlights is not None:
        chosen=[]
        all_items=clean
        for i in highlights:
            if isinstance(i,int) and not isinstance(i,bool) and 0<=i<len(all_items) and all_items[i] and i not in chosen and (feature_category(all_items[i]) in ('powertrain','capability') and feature_score(all_items[i])>=140 or re.search(r'panoramic|premium audio|heated and ventilated',all_items[i],re.I)):
                chosen.append(i)
            if len(chosen)>=2:break
        head=[all_items[i] for i in chosen]
    else:
        engine=[x for x in features if feature_category(x)=='powertrain' and feature_score(x)>=160]
        special=[x for x in features if feature_category(x)=='capability' and feature_score(x)>=165]
        luxury=[x for x in features if re.search(r'panoramic|premium audio|heated and ventilated',x,re.I)]
        head=(engine[:1] + (special[:1] if special else luxury[:1]))[:2]
    if record.get('carfax_one_owner') is True:
        out.extend(['', '⭐ CARFAX 1-OWNER ⭐'])
    if head:
        head=head[:2]
        out.append('')
        out.extend(f'🔥 {x.upper().rstrip(".! ")}! 🔥' for x in head)
    if features:
        out.append('')
        out.extend('✔️ '+x for x in features)
    out.extend(['',f'📍 {dealer} – Lafayette, LA', '🗣️ Hablamos Español','',
        '📞 Message me for:', '👉 Availability', *(['👉 Cash Purchase Details'] if record.get('cash_only') is True else ['👉 Financing Options']),
        '👉 More Photos or Video', '👉 To Schedule a Test Drive'])
    return '\n'.join(out)[:5000]
