// Only the Chrome background worker can send to the private localhost service.
// All requested URLs come from SalesmanHub's allowlisted, user-selected queue.
const ROOT='http://127.0.0.1:8765';
const READER_REVISION='R59';
let busy=false;
// R53: Live inventory DISCOVERY uses /used-inventory/index.htm, while the
// vehicle detail reader uses /used/*.htm. Keep those two allowlist scopes separate.
// An inventory index must NEVER be passed off as a verified vehicle page.
const allow=(url,kind='vehicle')=>{try{
  const u=new URL(url);
  if(u.protocol!=='https:'||!['www.hamptontoyota.com','www.hamptonmitsubishi.com'].includes(u.hostname)||
     u.username||u.password||u.hash||url.length>1000)return false;
  if(kind==='inventory_index')return u.pathname==='/used-inventory/index.htm';
  if(kind==='vehicle'||kind==='verify'||kind==null)return /^\/used\/.+\.htm$/i.test(u.pathname);
  return false;
}catch{return false;}};
async function request(path,key,body){
  const init={headers:{'X-SHM-Bridge-Key':key,'X-SHM-Reader-Rev':READER_REVISION},cache:'no-store'};
  if(body){init.method='POST';init.headers['Content-Type']='application/json';init.body=JSON.stringify(body);}
  let response;
  try { response=await fetch(ROOT+path,{...init,signal:AbortSignal.timeout(8000)}); }
  catch(e) { throw Error('LotRadar is offline. Open LotRadar to reconnect.'); }
  let data;
  try { data=await response.json(); }
  catch { throw Error('Port 8765 returned an unexpected response. Restart LotRadar Server.'); }
  if(!response.ok) {
    const reason=String(data.error||'request_rejected');
    if(reason==='chrome_extension_pairing_required')
      throw Error('Pairing key rejected. Copy the current key from LotRadar.');
    if(response.status===426)throw Error('Reader version mismatch. Reload the latest LotRadar Browser Reader.');
    throw Error(`Marketplace HTTP ${response.status}: ${reason}`);
  }
  return data;
}
function expandVehicleEquipment(){
  if(window.__shmReadExpanded)return;
  if(!/\/used\//i.test(location.pathname))return;
  const labels=/^(?:all included items|all\s+\d+\s+highlights|all highlights|show all features|show all specifications)$/i;
  let touched=0;
  for(const el of document.querySelectorAll('button,[role="button"],a[aria-controls]')){
    const label=(el.innerText||el.textContent||el.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();
    if(!labels.test(label)||el.getAttribute('aria-expanded')==='true'||!el.getClientRects().length)continue;
    try{el.click();touched++;}catch{}
    if(touched>=3)break;
  }
  if(touched)window.__shmReadExpanded=true;
  return touched;
}

function snapshotPage(){
function dealerEquipmentSections(){
  const labels=/^(?:the highlights|a closer look at what.s included|the full specifications|notes from the dealer|all included items)$/i;
  const stop=/^(?:price details|build your offer|peace of mind|schedule a test drive|other vehicles|similar vehicles|terms and conditions)$/i;
  const results=[];
  // Capture explicitly marked vehicle sections, including hidden feature
  // accordions rendered in DOM but not visible via innerText.
  const headers=[...document.querySelectorAll('h2,h3,h4,h5,[role="heading"]')].slice(0,250);
  for(const h of headers){
    const name=(h.textContent||'').replace(/\s+/g,' ').trim();
    if(!labels.test(name))continue;
    const group=[name];let e=h.nextElementSibling,steps=0;
    while(e&&steps++<35){
      const title=(e.matches?.('h2,h3,h4,h5,[role="heading"]')?e.textContent||'':'').trim();
      if(stop.test(title)||labels.test(title))break;
      const entries=[...e.querySelectorAll('li,dt,dd,tr')].slice(0,220);
      const content=entries.length ? entries.map(n=>(n.innerText||n.textContent||'').replace(/[ \t]+/g,' ').trim()).filter(Boolean).join('\n')
        : (e.innerText||e.textContent||'').replace(/[ \t]+/g,' ').trim();
      if(content&&content.length<30000)group.push(content);
      e=e.nextElementSibling;
    }
    if(group.length>1)results.push(group.join('\n'));
    if(results.join('\n').length>45000)break;
  }
  return results.join('\n').slice(0,45000);
}

  // Some Dealer.com CARFAX badges are images with ALT text rather than visible
  // paragraphs. Capture ONLY a displayed badge on the current vehicle page.
  // Never convert this into an accident-free or clean-history claim.
  const carfaxBadge=[...document.querySelectorAll('img[alt],a[aria-label],button[aria-label]')]
    .filter(el=>typeof el.getClientRects==='function'&&el.getClientRects().length>0)
    .map(el=>el.getAttribute('alt')||el.getAttribute('aria-label')||'')
    .find(v=>/\bCARFAX\s*1[\s-]*Owner\b/i.test(v));
  const visible=(document.body?.innerText||'').slice(0,68000);
  const equipment=dealerEquipmentSections();
  const text=((carfaxBadge?carfaxBadge+'\n':'')+visible+(equipment?'\n'+equipment:'')).slice(0,98000);
  const title=document.title||'';
  const low=(title+' '+text.slice(0,3500)).toLowerCase();
  if(/access denied|403 forbidden|verify you are human|captcha|unusual traffic/.test(low))
    return {outcome:'access_denied',url:location.href};
  if(/page not found|vehicle not found|404 not found|this page is in the shop|unable to locate the page you requested/.test(low))
    return {outcome:'dealer_link_unavailable',url:location.href};
  const vin=/\bVIN\s*[:#]?\s*[A-HJ-NPR-Z0-9]{17}\b/i.test(text)||
    /["'](?:vin|vehicleIdentificationNumber)["']\s*:\s*["'][A-HJ-NPR-Z0-9]{17}["']/i.test(document.documentElement.outerHTML.slice(0,500000));
  if(!vin)return {outcome:'waiting',url:location.href};
  // Curated DOM with visible text, metadata, JSON-LD and image references.
  // No cookies, page scripts, contact forms or website session tokens.
  const safe=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const titleNode=document.querySelector('h1')?.innerText||title;
  const meta=[...document.querySelectorAll('meta[property="og:title"],meta[property="og:image"]')]
    .slice(0,6).map(el=>`<meta property="${safe(el.getAttribute('property'))}" content="${safe(el.content)}">`).join('');
  const ld=[...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,6)
    .map(el=>`<script type="application/ld+json">${el.textContent?.slice(0,50000)||''}</script>`).join('')+
    `<script type="application/x-lotradar-colors">${JSON.stringify(dealerGenericColors()).replace(/</g,'\\u003c')}</script>`;
  const candidates=[];
  const assetIndices=new Map();
  const assetWidths=new Map();
  // Include lazy gallery thumbnails, full-image anchors, and every srcset size.
  // Only public, explicitly linked dealer photos are collected. No guessed URLs.
  const galleryElements=[...document.querySelectorAll(
    'img,source,a[href],[data-image-url],[data-full-image],[data-full-src],[data-zoom-image],[data-original],[data-src]'
  )].slice(0,1800);
  for(const el of galleryElements){
    for(const attr of ['data-image-url','data-full-image','data-full-src','data-zoom-image',
                       'data-src','data-original','data-lazy-src','src','href','srcset','data-srcset']){
      let values=(el.getAttribute(attr)||'').trim();
      if(!values)continue;
      values=attr.endsWith('srcset')?values.split(',').map(v=>v.trim().split(/\s+/)[0]):[values];
      for(let raw of values){
        if(raw.startsWith('//'))raw='https:'+raw;
        if(raw.startsWith('/')&&!raw.startsWith('//'))raw=new URL(raw,location.href).href;
        if(/^https:\/\/(?:pictures\.dealer\.com|www\.hamptontoyota\.com|www\.hamptonmitsubishi\.com)\//i.test(raw)
           && /\.(?:jpe?g|png|webp)(?:[?#]|$)/i.test(raw)){
          try{
            const link=new URL(raw),path=link.pathname.toLowerCase();
            // Exclude obvious dealer logos, banner graphics and placeholders.
            // The page can advertise these as img tags next to actual car photos.
            const context=((el.getAttribute('alt')||'')+' '+(el.getAttribute('title')||'')+' '+(el.getAttribute('aria-label')||'')).toLowerCase();
            // R21: never scrape every dealer.com-hosted image as a car.
            // Require vehicle-gallery context. Global logos and promotional
            // components may use the SAME dealer CDN as stock photography.
            const galleryContext=!!el.closest('[class*="gallery"],[id*="gallery"],'
              +'[class*="carousel"],[class*="slider"],[class*="thumbnail"],'
              +'[class*="vehicle-photo"],[class*="vehicle-image"],'
              +'[data-testid*="gallery"],[data-testid*="vehicle-photo"]') ||
              /(?:\bvehicle photo\b|\binterior\b|\bexterior\b|\bgallery\b|\bview photos\b)/i.test(context);
            if(!galleryContext)continue;
            if(/\b(?:carfax|one.owner badge|dealer logo|mitsubishi motors logo|brand logo|advertisement|promotional banner|dealer phone)\b/i.test(context))continue;
            if(/(?:^|[\/_.-])(logo|brand|placeholder|no-photo|no_image|noimage|generic|dealer-logo|coming-soon)(?:[\/_.-]|$)/.test(path)||
               /(?:^|\b)(dealer logo|mitsubishi motors logo|brand logo|no photo available)(?:\b|$)/.test(context))continue;
            if(link.hostname!=='pictures.dealer.com'){
              const near=el.closest('[class*="gallery"],[class*="photo"],[class*="vehicle"],[class*="carousel"],[id*="gallery"],[id*="photo"]');
              if(!near&&!/vehicle|photo|gallery|exterior|interior|stock/i.test(context))continue;
            }
            const key=link.origin+link.pathname;
            const width=Number(link.searchParams.get('w')||link.searchParams.get('width')||0);
            if(!assetIndices.has(key)){
              assetIndices.set(key,candidates.length);assetWidths.set(key,width);
              candidates.push(raw);
            }else if(width>assetWidths.get(key)){
              candidates[assetIndices.get(key)]=raw;assetWidths.set(key,width);
            }
          }catch{}
        }
        if(candidates.length>=250)break;
      }
      if(candidates.length>=250)break;
    }
    if(candidates.length>=250)break;
  }
  const photo=candidates.map(url=>`<img src="${safe(url)}">`).join('');
  const html=`<!doctype html><html><head>${meta}${ld}</head><body><h1>${safe(titleNode)}</h1><div>${safe(text)}</div>${photo}</body></html>`;
  return {outcome:'ok',html:html.slice(0,1300000),text:text.slice(0,90000),url:location.href,
    readyState:document.readyState,hasEquipment:Boolean(equipment),photoLinks:candidates.length};
}
// R60: Chrome MV3 serializes executeScript(func) *by itself*. Never call
// helpers defined in background.js from a function injected into a dealer tab.
// That context isolation bug made R59 silently keep only the seven thumbnails.
function openDealerPhotoViewer(){
 if(!/^\/used\//i.test(location.pathname))return false;
 const visible=el=>Boolean(el?.getClientRects?.().length);
 const inVehicleGallery=el=>Boolean(el.closest('[class*="gallery"],[id*="gallery"],'
    +'[class*="vehicle-photo"],[class*="vehicle-image"],[class*="media"],'
    +'[class*="carousel"],[class*="photo"],[data-testid*="gallery"]'));
 const targets=[...document.querySelectorAll('button,a,[role="button"],img,span,div')].slice(0,2500);
 let countButton=null,score=-1,expected=null;
 for(const el of targets){
  if(!visible(el))continue;
  const rect=el.getBoundingClientRect();
  if(rect.width>370||rect.height>115||rect.width<12)continue;
  const label=((el.innerText||el.textContent||'')+' '+(el.getAttribute('aria-label')||'')).replace(/\s+/g,' ').trim();
  if(label.length>115||!/(?:\b\d{1,3}\s+photos?\b|view (?:all )?photos|photo gallery|open gallery)/i.test(label))continue;
  const points=(inVehicleGallery(el)?50:0)+(/\b\d{1,3}\s+photos?\b/i.test(label)?20:0)
     +(el.matches('button,a,[role="button"]')?10:0)-label.length/20;
  if(points>score){
   score=points;countButton=el.closest('button,a,[role="button"]')||el;
   expected=Number(label.match(/\b(\d{1,3})\s+photos?\b/i)?.[1]||0)||null;
  }
 }
 if(countButton){try{countButton.click();return {opened:true,expected};}catch{}}
 const candidates=[...document.querySelectorAll('img')].filter(im=>visible(im)&&inVehicleGallery(im)
   &&im.getBoundingClientRect().width>300&&im.getBoundingClientRect().height>150);
 candidates.sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-
                      a.getBoundingClientRect().width*a.getBoundingClientRect().height);
 if(!candidates[0])return {opened:false,expected};
 try{(candidates[0].closest('button,a,[role="button"]')||candidates[0]).click();return {opened:true,expected};}catch{return false;}
}
// This ENTIRE function is serialized into the vehicle tab by executeScript.
// It does not reference dealerGalleryRoot(), a background-only variable, or
// any other remote symbol. read/advance both work in isolated MV3 contexts.
function dealerGalleryStep(action){
 if(!/^\/used\//i.test(location.pathname))return {url:'',hasNext:false};
 const visible=el=>Boolean(el?.getClientRects?.().length&&getComputedStyle(el).visibility!=='hidden');
 const good=url=>{try{const u=new URL(url,location.href);return u.protocol==='https:'&&
    ['pictures.dealer.com','www.hamptontoyota.com','www.hamptonmitsubishi.com'].includes(u.hostname)&&
    /\.(?:jpe?g|png|webp)$/i.test(u.pathname)&&!u.username&&!u.password;}catch{return false;}};
 const areas=[...document.querySelectorAll('[role="dialog"],[aria-modal="true"],dialog[open],'
   +'[class*="lightbox"],[class*="Lightbox"],[class*="fullscreen"],[class*="photo-viewer"],'
   +'[class*="image-viewer"],[class*="gallery-modal"],[class*="media-viewer"],'
   +'[class*="viewer"],[class*="Viewer"],[class*="fancybox"],[class*="pswp"],'
   +'[class*="ReactModal"],[class*="modal"]')].filter(el=>visible(el)&&el.querySelector('img'));
 let root=document.body,topScore=-1;
 for(const el of areas){
   const imgs=[...el.querySelectorAll('img')].filter(visible);
   const largest=Math.max(0,...imgs.map(im=>im.getBoundingClientRect().width*im.getBoundingClientRect().height));
   if(largest<40000)continue;
   const modal=el.matches('[role="dialog"],[aria-modal="true"],dialog[open]')?400000:0;
   const z=Number.parseInt(getComputedStyle(el).zIndex,10)||0;
   const score=largest+modal+Math.min(200000,Math.max(0,z)*100);
   if(score>topScore){root=el;topScore=score;}
 }
 const photos=[...root.querySelectorAll('img')].filter(visible).map(img=>({img,r:img.getBoundingClientRect()}))
    .filter(x=>x.r.width>240&&x.r.height>160).sort((a,b)=>b.r.width*b.r.height-a.r.width*a.r.height);
 let target=null,url='';
 for(const {img,r} of photos){
   const urls=[img.currentSrc,img.getAttribute('data-full-image'),img.getAttribute('data-zoom-image'),
     img.getAttribute('data-original'),img.getAttribute('data-src'),img.getAttribute('src'),
     img.closest('a[href]')?.getAttribute('href')].filter(Boolean);
   const picked=[...urls.slice(1,4),urls[0],...urls.slice(4)].find(good);
   if(picked){target=r;url=new URL(picked,location.href).href;break;}
 }
 const center=target?{x:target.x+target.width/2,y:target.y+target.height/2}:null;
 const candidates=[...root.querySelectorAll('button,[role="button"],a')].filter(el=>visible(el)&&
   !el.disabled&&el.getAttribute('aria-disabled')!=='true').map(el=>{
     const rect=el.getBoundingClientRect();
     const label=[el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('data-testid'),
       typeof el.className==='string'?el.className:'',el.innerText||''].filter(Boolean).join(' ').slice(0,220);
     const named=/\bnext\b|(?:^|[-_])next(?:[-_]|$)|[›»→]/i.test(label);
     const right=center&&rect.width>=16&&rect.width<=110&&rect.height>=16&&rect.height<=110
       &&rect.x+rect.width/2>center.x+target.width*.23&&rect.x<target.right+35
       &&Math.abs(rect.y+rect.height/2-center.y)<target.height*.34;
     return {el,score:(named?150:0)+(right?65:0)-(Math.abs((rect.y+rect.height/2)-(center?.y||0))/100)};
   }).filter(x=>x.score>35).sort((a,b)=>b.score-a.score);
 const next=candidates[0]?.el||null;
 // A viewer may expose the whole strip even when only one slide is visible.
 const strip=[];
 if(root!==document.body){
  for(const el of root.querySelectorAll('img,source,a[href],[data-full-image],[data-full-src]')){
   const label=[el.getAttribute('alt'),el.getAttribute('aria-label')].filter(Boolean).join(' ');
   if(/logo|placeholder|carfax|advertisement|banner/i.test(label))continue;
   const values=['data-full-image','data-full-src','data-zoom-image','data-original','data-src','srcset','data-srcset','src','href']
     .flatMap(attr=>(el.getAttribute(attr)||'').split(attr.endsWith('srcset')?',':'\u0000').map(x=>x.trim().split(/\s+/)[0]));
   for(const value of values.filter(x=>x&&good(x)))strip.push(new URL(value,location.href).href);
  }
 }
 const raw=String(root.innerText||'').slice(0,14000);
 const matches=[...raw.matchAll(/\b(\d{1,3})\s*(?:\/|of)\s*(\d{1,3})\b/gi)].filter(m=>Number(m[2])>1&&Number(m[1])<=Number(m[2]));
 const current=matches[0]?Number(matches[0][1]):null;
 const total=matches[0]?Number(matches[0][2]):null;
 if(action==='advance'){
   if(next){try{next.click();return true;}catch{}}
   if(root===document.body)return false;
   (document.activeElement&&root.contains(document.activeElement)?document.activeElement:root)
     .dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',code:'ArrowRight',bubbles:true}));
   return true;
 }
 return {url,strip,hasNext:!!next||root!==document.body,position:current,total,viewerOpen:root!==document.body};
}
async function captureAllDealerGalleryImages(tabId){
 let activation;
 try{activation=(await chrome.scripting.executeScript({target:{tabId},func:openDealerPhotoViewer}))?.[0]?.result;}
 catch(e){return {urls:[],expected:null,reason:'viewer_activation_error'};}
 if(!activation?.opened)return {urls:[],expected:activation?.expected||null,reason:'viewer_not_opened'};
 const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 await wait(650);
 const unique=new Map();let stall=0,expected=activation.expected;
 const deadline=Date.now()+65000;let steps=0, advancedFrame=null;
 for(let index=0;index<250&&Date.now()<deadline;index++){
   let frame=advancedFrame;
   advancedFrame=null;
   if(!frame){
     try{frame=(await chrome.scripting.executeScript({target:{tabId},func:dealerGalleryStep,args:['read']}))?.[0]?.result;}
     catch(e){return {urls:[...unique.values()],expected,reason:'gallery_script_error'};}
   }
   if(!frame)break;
   if(frame.total&&frame.viewerOpen)expected=Math.max(expected||0,frame.total);
   for(const photo of [frame.url,...(frame.strip||[])].filter(Boolean)){
     const u=new URL(photo),key=u.origin+u.pathname;
     const width=url=>Number(url.searchParams.get('w')||url.searchParams.get('width')||0);
     if(!unique.has(key)||width(u)>width(new URL(unique.get(key))))unique.set(key,photo);
   }
   steps++;
   if(expected&&unique.size>=expected)break;
   if(!frame.hasNext)break;
   let moved=false;
   try{moved=Boolean((await chrome.scripting.executeScript({target:{tabId},func:dealerGalleryStep,args:['advance']}))?.[0]?.result);}
   catch{break;}
   if(!moved)break;
   // Dealer galleries can animate lazily; fixed 240ms reads the OLD slide.
   let advanced=false;
   for(let tries=0;tries<9&&Date.now()<deadline;tries++){
     await wait(tries===0?140:240);
     let next;
     try{next=(await chrome.scripting.executeScript({target:{tabId},func:dealerGalleryStep,args:['read']}))?.[0]?.result;}
     catch{return {urls:[...unique.values()],expected,reason:'gallery_poll_error'};}
     if(next&&(next.url&&next.url!==frame.url ||
       next.position!=null&&frame.position!=null&&next.position!==frame.position)){
       advancedFrame=next;advanced=true;break;
     }
   }
   if(!advanced)stall++;else stall=0;
   if(stall>=2)break;
 }
 return {urls:[...unique.values()].slice(0,250),expected,
   reason:expected&&unique.size>=expected?'complete':
          unique.size?'incomplete':'viewer_no_images',steps};
}
function appendGalleryPhotosToSnapshot(snapshot,urls,expected){
 if(!snapshot||snapshot.outcome!=='ok'||!Array.isArray(urls)||!urls.length)return snapshot;
 const accepted=[];
 for(const url of urls){
   try{const u=new URL(url);if(u.protocol!=='https:'||
      !['pictures.dealer.com','www.hamptontoyota.com','www.hamptonmitsubishi.com'].includes(u.hostname)||
      !/\.(?:jpe?g|png|webp)$/i.test(u.pathname)||u.username||u.password)continue;
      accepted.push(u.href);
   }catch{}
   if(accepted.length>=250)break;
 }
 if(!accepted.length)return snapshot;
 const safe=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const tags=accepted.map(url=>`<img data-gallery-photo="true" src="${safe(url)}">`).join('');
 const html=snapshot.html||'';
 // R62: the local parser caps image links at 50. Append-at-end put
 // full-gallery interior photos AFTER the page's earlier thumbnails/related
 // assets, so they could be lost before the parser got to them. Prioritize
 // explicitly captured full-viewer frames before ordinary page imagery.
 const section=`<section data-shm-complete-gallery="1"${expected&&accepted.length>=expected?' data-gallery-verified="1"':''}>${tags}</section>`;
 const combined=/<body(?:\s[^>]*)?>/i.test(html)
   ?html.replace(/<body(?:\s[^>]*)?>/i,match=>match+section)
   :section+html;
 return {...snapshot,html:combined.slice(0,1400000),gallery_count:accepted.length};
}
async function capture(tabId,expected,linkOnly=false){
  for(let attempt=0;attempt<9;attempt++){
    await new Promise(r=>setTimeout(r,attempt===0?650:attempt<3?900:1800));
    let results;
    try{
      const [equipment]=await chrome.scripting.executeScript({target:{tabId},func:expandVehicleEquipment});
      if(equipment?.result)await new Promise(r=>setTimeout(r,600));
      results=await chrome.scripting.executeScript({target:{tabId},func:snapshotPage});
    }
    catch(e){if(attempt===8)return {outcome:'page_unavailable'};continue;}
    const data=results?.[0]?.result;
    if(data?.url){
      const actual=new URL(data.url),target=new URL(expected);
      if(actual.origin!==target.origin||
         (actual.pathname!==target.pathname&&!['dealer_link_unavailable','access_denied'].includes(data.outcome)))
        return {outcome:'page_unavailable'};
    }
    if(data?.outcome&&data.outcome!=='waiting'){
      if(data.outcome==='ok'&&!linkOnly){
        if(attempt<2&&data.readyState!=='complete')continue;
        if(attempt<2&&!data.hasEquipment&&!data.photoLinks)continue;
        // Full viewer navigation is separate from the snapshot. Any gallery
        // failure leaves the valid dealer VIN/price/equipment record intact.
        try{
          const gallery=await captureAllDealerGalleryImages(tabId);
          const updated=appendGalleryPhotosToSnapshot(data,gallery.urls,gallery.expected);
          const count=gallery.urls.length;
          const expected=gallery.expected;
          return {...updated,gallery_expected:expected,detail:`Gallery ${count}/${expected||'unknown'} (${gallery.reason||'unknown'}); refresh again if incomplete`.slice(0,120)};
        }catch{return {...data,detail:'Gallery reader error; page thumbnails preserved'};}
      }
      return data;
    }
  }
  return {outcome:'page_timeout'};
}
// Live inventory discovery. Read only links the dealership actually renders in
// this Chrome tab. No old sitemap entries, guessed VINs or stock inference.
function inventoryIndexSnapshot(){
  const anchors=[...document.querySelectorAll('a[href]')];
  const urls=[];
  const seen=new Set();
  for(const a of anchors){
    let u;
    try{u=new URL(a.href,location.href)}catch{continue;}
    if(u.protocol!=='https:'||u.hostname!==location.hostname||!/^\/used\//i.test(u.pathname)||!u.pathname.endsWith('.htm'))continue;
    const href=u.origin+u.pathname;
    if(!seen.has(href)){seen.add(href);urls.push(href);}
  }
  // Pagination is restricted again on the server to this exact inventory path.
  let next_url='';
  for(const a of anchors){
    const text=String(a.textContent||'').trim();
    const role=String(a.getAttribute('aria-label')||'')+' '+String(a.getAttribute('rel')||'');
    if(!(/^(?:next|next page|›|»|→)$/i.test(text)||/\bnext\b/i.test(role)))continue;
    try{const u=new URL(a.href,location.href);if(u.hostname===location.hostname&&u.pathname===location.pathname&&u.href!==location.href){next_url=u.href;break;}}catch{}
  }
  const text=String(document.body?.innerText||'').slice(0,18000);
  const count=text.match(/\b(\d{1,4})\s+Vehicles\b/i);
  return {urls:urls.slice(0,1200),next_url,website_total:count?Number(count[1]):null,
    readyState:document.readyState};
}
async function discoverInventory(tabId){
  const all=new Set();let last=null;let empty=0,scriptFailed=false;
  let lastScriptError='';
  for(let step=0;step<28;step++){
    await new Promise(r=>setTimeout(r,step===0?1000:450));
    try{
      const [resp]=await chrome.scripting.executeScript({target:{tabId},func:inventoryIndexSnapshot});
      const current=resp?.result;if(current){last=current;
        const previous=all.size;
        for(const url of current.urls||[])if(all.size<1000)all.add(url);
        if(all.size===previous)empty++;else empty=0;
        if(current.website_total>0&&all.size>=current.website_total&&!current.next_url)break;
        if(current.next_url&&all.size&&empty>=3&&current.readyState==='complete')break;
      }
      await chrome.scripting.executeScript({target:{tabId},func:()=>{
        const root=document.scrollingElement||document.documentElement;
        root.scrollTop=Math.min(root.scrollHeight,root.scrollTop+Math.max(550,window.innerHeight*.85));
        for(const el of document.querySelectorAll('[role="grid"],[data-testid*="inventory"],.inventory-grid')){
          if(el.scrollHeight>el.clientHeight+300)el.scrollTop+=Math.max(500,el.clientHeight*.8);
        }
      }});
      if(step>=8&&empty>=8)break;
    }catch(e){scriptFailed=true;lastScriptError=String(e?.message||e).slice(0,100);if(step>3)break;}
  }
  if(!last)return {outcome:scriptFailed?'reader_injection_failed':'page_unavailable',urls:[],
    website_total:null,detail:scriptFailed?'Chrome script injection failed: '+lastScriptError:'No readable DOM snapshot'};
  if(!all.size)return {outcome:'inventory_index',urls:[],website_total:last.website_total,
    detail:scriptFailed?'Inventory DOM partially read; script error: '+lastScriptError:'Inventory page loaded but no vehicle detail links were rendered'};
  return {outcome:'inventory_index',urls:[...all],next_url:last.next_url,
    website_total:last.website_total,html:'',text:''};
}
// Dealer.com's own normalized colors ("Silver"), keyed by VIN. Read from inline page data
// text only; scalar strings only; nothing else from page scripts is copied.
function dealerGenericColors(){
  const source=document.documentElement.outerHTML.slice(0,3000000),out=[],seen=new Set();
  const objects=source.match(/\{[^{}]{0,4000}"normalExteriorColor"[^{}]{0,4000}\}/g)||[];
  for(const body of objects.slice(0,40)){
    const pick=key=>{const m=body.match(new RegExp('"'+key+'"\\s*:\\s*"([^"\\\\]{1,40})"'));return m?m[1]:null;};
    const vin=pick('vin');
    if(!vin||!/^[A-HJ-NPR-Z0-9]{17}$/i.test(vin)||(body.match(/"vin"\s*:/g)||[]).length!==1)continue;
    const row={vin:vin.toUpperCase(),normalExteriorColor:pick('normalExteriorColor'),normalInteriorColor:pick('normalInteriorColor')};
    const key=JSON.stringify(row);if(!seen.has(key)){seen.add(key);out.push(row);}
  }
  return out;
}
async function navigate(url){
  let tab;
  try{
    tab=await chrome.tabs.create({url,active:false});
    // Chrome remains the browser. No altered UA, cookie replay or anti-bot bypass.
    return await capture(tab.id,url);
  }catch{return {outcome:'page_unavailable'};}
  finally{if(tab?.id)try{await chrome.tabs.remove(tab.id);}catch{}}
}
// Bounded dealer-only tab pool. Facebook work stays serial and separate.
let dealerPumpRunning=false;
let dealerStopRequested=false;
const dealerOwnedTabs=new Map();
async function readDealerJob(job){
  let tab;
  try{
    if(!allow(job.url,job.kind))return {outcome:'reader_url_rejected'};
    tab=await chrome.tabs.create({url:job.url,active:false});
    dealerOwnedTabs.set(job.id,tab.id);
    if(dealerStopRequested)return {outcome:'scan_stopped'};
    const result=job.kind==='inventory_index'?await discoverInventory(tab.id):await capture(tab.id,job.url,job.link_only===true);
    return result;
  }catch(e){
    // Detailed, length-bounded browser failure reason (no URL, cookies, or page content).
    const why=String(e?.message||e);
    return {outcome:/Cannot access contents|Missing host permission|Cannot access a chrome:\/\//i.test(why)?
      'reader_permission_missing':/tabs\.create|No window with id|Cannot create/i.test(why)?
      'reader_tab_open_failed':'reader_browser_error',detail:why.slice(0,120)};
  }
  finally{
    dealerOwnedTabs.delete(job.id);
    if(tab?.id)try{await chrome.tabs.remove(tab.id)}catch{}
  }
}
async function stopOwnedDealerTabs(){
  dealerStopRequested=true;
  const ids=[...dealerOwnedTabs.values()];
  dealerOwnedTabs.clear();
  await Promise.allSettled(ids.map(id=>chrome.tabs.remove(id)));
  return {status:`Dealer scan stopped. Closed ${ids.length} owned tab(s).`};
}
async function runDealerPump(key,firstJob=null,initialWorkers=2){
  const active=new Set();
  // Keep the active worker responsive while the dealer viewer renders slides.
  const heartbeat=setInterval(()=>{void request('/api/chrome-bridge/ping',key).catch(()=>{});},20000);
  // Timer drift reflects browser scheduling pressure while scans are active.
  let tick=performance.now(),lag=0;
  const pressureTimer=setInterval(()=>{
    const now=performance.now();
    lag=Math.max(0,Math.round(now-tick-500));
    tick=now;
  },500);
  let pendingFirst=firstJob;
  try{
    while(!dealerStopRequested){
      const state=pendingFirst?{job:pendingFirst,effective_workers:initialWorkers,running:true}:await request('/api/chrome-bridge/next',key);
      pendingFirst=null;
      if(dealerStopRequested)break;
      const max=Math.min(10,Math.max(2,Number(state.effective_workers)||2));
      if(state.job){
        const job=state.job;
        const work=(async()=>{
          const result=await readDealerJob(job);
          if(dealerStopRequested)return;
          try{
            await request('/api/chrome-bridge/result',key,{id:job.id,url:job.url,
              outcome:result.outcome,html:result.html,text:result.text,
              urls:result.urls,next_url:result.next_url,website_total:result.website_total,
              detail:result.detail,gallery_expected:result.gallery_expected,
              reader_lag_ms:Math.min(60000,Math.max(lag,Math.round(performance.now()-tick-500)))});
          }catch(e){
            if(dealerStopRequested||String(e.message).includes('no_matching_active_chrome_job'))return;
            // A malformed or oversized result must release its claim. A stale ID
            // is rejected by the server without importing anything twice.
            await request('/api/chrome-bridge/result',key,{id:job.id,url:job.url,
              outcome:'page_unavailable',detail:String(e.message||e).slice(0,120)}).catch(()=>{});
          }
        })();
        active.add(work);
        void work.then(()=>active.delete(work),()=>active.delete(work));
        if(active.size>=max)await Promise.race(active);
        continue;
      }
      if(active.size){await Promise.race(active);continue;}
      // Paused or no more jobs: stop opening tabs. The Resume event wakes this pump.
      if(!state.running||state.paused||!state.queued)break;
      await new Promise(r=>setTimeout(r,800));
    }
  }finally{
    await Promise.allSettled([...active]);
    clearInterval(heartbeat);clearInterval(pressureTimer);
    dealerPumpRunning=false;busy=false;
    if(!dealerStopRequested)void checkFacebookAuto();
  }
}
async function scanOne(){
  if(dealerPumpRunning||facebookAutoBusy)return {status:'Browser reader already processing a queue'};
  dealerPumpRunning=true;busy=true; // reserve synchronously before any await
  try{
    const {bridgeKey}=await chrome.storage.local.get('bridgeKey');
    if(!bridgeKey){dealerPumpRunning=false;busy=false;return {status:'Pair the extension in Marketplace first'};}
    const status=await request('/api/chrome-bridge/next',bridgeKey);
    if(!status.job){dealerPumpRunning=false;busy=false;return {status:status.paused?'Scan paused':
      'Connected. No queued vehicle. Start Scan Inventory in Marketplace.'};}
    dealerStopRequested=false;
    void runDealerPump(bridgeKey,status.job,status.effective_workers||2).catch(()=>{dealerPumpRunning=false;busy=false;});
    return {status:`Dealer scan running, up to ${status.effective_workers||2} temporary tabs now, maximum ${status.workers||2}.`};
  }catch(e){dealerPumpRunning=false;busy=false;return {error:String(e?.message||e).slice(0,180)};}
}
async function ensureScanAlarm(){
  try{
    if(!await chrome.alarms.get('salesmanhub-scan'))
      await chrome.alarms.create('salesmanhub-scan',{periodInMinutes:0.5});
  }catch(e){console.warn('LotRadar could not schedule the next reader check:',e.message);}
}
async function readerStatus(candidate){
  const {bridgeKey}=await chrome.storage.local.get('bridgeKey');
  const key=candidate??bridgeKey;
  if(!key)return {state:'unpaired'};
  try{
    const status=await request('/api/chrome-bridge/ping',key);
    if(status.reader_revision!==READER_REVISION)throw Error('Update and restart LotRadar Server to match this Reader.');
    if(candidate)await chrome.storage.local.set({bridgeKey:key});
    return {state:'connected',running:status.running,queued:status.queued,inflight:status.inflight,paused:status.paused};
  }catch(e){
    return {state:'offline',paired:Boolean(bridgeKey),error:String(e.message||e)};
  }
}
async function readerTick(){
  if((await readerStatus()).state!=='connected')return;
  void announceFacebookReadiness();
  const result=await scanOne();
  if(!result?.error)void checkFacebookAuto();
}
function startReaderHeartbeat(){
  void ensureScanAlarm().then(readerTick).catch(e=>console.warn('LotRadar reader check failed:',e.message));
}
chrome.runtime.onInstalled.addListener(startReaderHeartbeat);
chrome.runtime.onStartup.addListener(startReaderHeartbeat);
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='salesmanhub-scan')startReaderHeartbeat();});
void ensureScanAlarm();
async function captureCurrentFacebook(){
  // Runs ONLY from a user-clicked popup control. No scheduled Facebook scans.
  const {bridgeKey}=await chrome.storage.local.get('bridgeKey');
  if(!bridgeKey)throw Error('Pair Chrome Reader with Marketplace first.');
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.id||!tab.url||!/^https:\/\/(?:www\.|m\.)?facebook\.com\/marketplace\/(?:item\/\d{8,24}|edit\?)/i.test(tab.url))
    throw Error('Open a Facebook Marketplace item or your listing edit page, then click Capture.');
  const result=await chrome.scripting.executeScript({target:{tabId:tab.id},files:['facebook_reader.js']});
  const capture=result?.[0]?.result;
  if(!capture||capture.error)throw Error(capture?.error||'Could not read this listing page.');
  // Explicit limited payload. VIN, user IDs, messages, cookies, HTML and page text NEVER sent.
  const payload={url:capture.url,title:capture.title,description:capture.description,
    price:capture.price,mileage:capture.mileage,status:capture.status,explicit_capture:true};
  if(!payload.title && payload.price==null && payload.mileage==null && !payload.description)
    throw Error('Facebook fields not visible. Open your own Edit listing page and retry.');
  const saved=await request('/api/chrome-bridge/facebook-capture',bridgeKey,payload);
  return {status:`Captured ${saved.capture_fields.join(', ')||'visible listing fields'} for tracked listing ${saved.listing_id}. Open LotRadar comparison to review.`};
}
// A one-off inspection is queued ONLY when the user links a listing in Marketplace
// or explicitly clicks Check Facebook now. No background monitoring of Facebook.
const FB_SITE='https://www.facebook.com/*';
let facebookAutoBusy=false;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const listingIdFromUrl=url=>{
  try {const u=new URL(url);
    if(u.protocol!=='https:'||u.hostname!=='www.facebook.com')return '';
    const id=u.pathname.match(/^\/marketplace\/item\/(\d{8,24})\/?$/)?.[1];
    return id||'';
  } catch{return '';}
};
async function waitForFacebookTab(tabId,expectedId){
  // Give React a limited time to render the selected listing. No site-wide DOM dump.
  for(let attempt=0;attempt<7;attempt++){
    await sleep(attempt===0?1400:1100);
    const current=await chrome.tabs.get(tabId);
    const u=new URL(current.url||'about:blank');
    if(u.protocol==='about:'||u.hostname==='')continue;
    if(u.hostname==='www.facebook.com' && /^\/(?:login|checkpoint|recover)\/?/.test(u.pathname))
      throw Error('Facebook login required. Sign in normally in Chrome, then retry.');
    if(u.hostname!=='www.facebook.com'||!/^\/marketplace\/(?:edit|item\/)/.test(u.pathname))
      throw Error('Facebook redirected away from the listing. Sign in, then retry.');
    let data;
    try {data=(await chrome.scripting.executeScript({target:{tabId},files:['facebook_reader.js']}))?.[0]?.result;}
    catch(e){if(attempt===6)throw Error('Facebook page cannot be read: '+String(e.message||e).slice(0,100));continue;}
    const pageUrl=data?.url||'';
    let actual='';try{const page=new URL(pageUrl);actual=page.pathname.match(/^\/marketplace\/item\/(\d{8,24})\/?$/)?.[1]||
      (page.pathname==='/marketplace/edit'?page.searchParams.get('listing_id'):'');}catch{}
    if(actual!==expectedId)throw Error('Facebook listing ID changed on navigation. Capture stopped.');
    if(data?.error)throw Error(data.error);
    if(data?.title||data?.description||data?.price!=null||data?.mileage!=null)return data;
  }
  return null;
}
async function captureQueuedFacebook(job,key){
  const id=listingIdFromUrl(job.url);
  if(!id||id!==job.listing_id)throw Error('Queued Facebook listing ID invalid.');
  let tab;
  try{
    // Prefer the user's edit form because Marketplace often hides description/mileage on item pages.
    const editUrl='https://www.facebook.com/marketplace/edit?listing_id='+id;
    tab=await chrome.tabs.create({url:editUrl,active:false});
    let capture=null;
    try{capture=await waitForFacebookTab(tab.id,id);}catch(e){
      if(/listing ID changed/i.test(e.message))throw e;
    }
    {
      // Always check the actual linked item. A readable edit form alone
      // cannot tell us whether the public listing link still loads.
      await chrome.tabs.update(tab.id,{url:job.url});
      const fallback=await waitForFacebookTab(tab.id,id);
      if(fallback)capture=capture?{...fallback,
        title:capture.title||fallback.title,
        description:capture.description||fallback.description,
        price:capture.price??fallback.price,
        mileage:capture.mileage??fallback.mileage,
        status:capture.status!=='unknown'?capture.status:fallback.status,
        url:capture.url}:fallback;
    }
    if(!capture)throw Error('Facebook did not expose listing details. Check that your account can open the listing.');
    const payload={url:capture.url,title:capture.title,description:capture.description,
      price:capture.price,mileage:capture.mileage,status:capture.status,explicit_capture:true,attempt_id:job.id};
    const saved=await request('/api/chrome-bridge/facebook-capture',key,payload);
    if(saved.listing_id!==id)throw Error('Saved listing ID did not match the queued item.');
    return {result:'captured',fields:saved.capture_fields||[],detail:'Facebook listing captured; temporary tab closed.'};
  } finally {if(tab?.id)try{await chrome.tabs.remove(tab.id);}catch{}}
}
async function announceFacebookReadiness(){
  try{
    const {bridgeKey,facebookAutoEnabled=false}=await chrome.storage.local.get(['bridgeKey','facebookAutoEnabled']);
    if(!bridgeKey)return;
    const permitted=await chrome.permissions.contains({origins:[FB_SITE]});
    await request('/api/chrome-bridge/facebook-auto-readiness',bridgeKey,
      {enabled:facebookAutoEnabled===true,permitted:permitted===true});
  }catch{} // Health report never affects the existing dealer scanner.
}
async function checkFacebookAuto(){
  if(facebookAutoBusy||busy)return {status:'Reader busy; queued check will retry.'};
  facebookAutoBusy=true; // Reserve the single browser workload slot BEFORE asynchronous permission reads.
  let nextQueued=false;
  try{
    const {bridgeKey,facebookAutoEnabled=false}=await chrome.storage.local.get(['bridgeKey','facebookAutoEnabled']);
    if(!bridgeKey)return {status:'Pair Chrome Reader with Marketplace before automatic checking.'};
    const permission=await chrome.permissions.contains({origins:[FB_SITE]});
    await announceFacebookReadiness();
    if(!permission||!facebookAutoEnabled)return {status:'Open Chrome Reader and enable Facebook checks once.'};
    const next=await request('/api/chrome-bridge/facebook-auto-next',bridgeKey);
    const job=next.job;
    if(!job)return {status:'Connected. No Facebook listing queued.'};
    let outcome;
    try{outcome=await captureQueuedFacebook(job,bridgeKey);}
    catch(e){outcome={result:'failed',detail:String(e?.message||e).slice(0,170),fields:[]};}
    await request('/api/chrome-bridge/facebook-auto-finish',bridgeKey,{id:job.id,...outcome});
    nextQueued=Number(next.remaining||0)>0;
    return {status:outcome.result==='captured'?`Saved Facebook listing ${job.listing_id}. Tab closed.`:
      `Facebook check failed: ${outcome.detail}`};
  }catch(e){return {error:String(e?.message||e).slice(0,180)};}
  finally{
    facebookAutoBusy=false;
    // Continue this explicit batch sequentially; the existing 30s alarm is a
    // backup if MV3 suspends the worker. Never open concurrent Facebook tabs.
    if(nextQueued)setTimeout(()=>{void checkFacebookAuto()},2000);
  }
}
function fillVehicleForm(fields){
  return (async()=>{
    if(location.origin!=='https://www.facebook.com'||!/^\/marketplace\/create\/vehicle\/?$/.test(location.pathname))
      return {error:'Open the Facebook vehicle creation form.'};
    const filled=[], review=[], already=[], reasons={};
    fields={...fields};
    const norm=value=>String(value||'').replace(/\s+/g,' ').trim().toLowerCase();
    const visible=el=>el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden';
    const labelsFor=el=>[
      el.getAttribute('aria-label'),el.getAttribute('placeholder'),
      ...(el.getAttribute('aria-labelledby')||'').split(/\s+/).filter(Boolean).map(id=>document.getElementById(id)?.textContent),
      ...Array.from(el.labels||[],label=>label.textContent),
      el.closest('label')?.textContent,
      el.querySelector?.('label')?.textContent
    ].map(norm).filter(Boolean);
    const find=(selector,labels)=>{
      const matches=[...document.querySelectorAll(selector)].filter(el=>visible(el)&&!el.disabled&&
        el.getAttribute('aria-disabled')!=='true'&&labelsFor(el).some(label=>labels.includes(label)));
      return matches.length===1?matches[0]:null;
    };
    const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const equal=(name,a,b)=>['Price','Mileage'].includes(name)?String(a??'').replace(/[^0-9]/g,'')===String(b??'').replace(/[^0-9]/g,''):norm(a)===norm(b);
    const POPUP='[role="listbox"],[role="menu"]';
    const allPopups=()=>[...document.querySelectorAll(POPUP)].filter(visible);
    // Facebook's header, navigation and chat can hold menus that are not part of this form.
    const pageChrome=el=>!!el.closest('[role="banner"],[role="navigation"],[role="complementary"]');
    const expandedBoxes=()=>[...document.querySelectorAll('[role="combobox"][aria-expanded="true"],[aria-haspopup][aria-expanded="true"]')].filter(visible);
    // Menus already on screen before Fill belong to the page, unless a form field is open (then it is that field's menu).
    const baseline=new Set(expandedBoxes().length?[]:allPopups());
    const menus=()=>allPopups().filter(el=>!baseline.has(el)&&!pageChrome(el));
    const click=el=>{el.scrollIntoView?.({block:'center'});el.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));el.click();};
    async function closeMenus(){
      if(!menus().length)return true;
      const active=document.activeElement||document.body;
      active.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true}));
      active.dispatchEvent(new KeyboardEvent('keyup',{key:'Escape',code:'Escape',bubbles:true}));
      await pause(120);
      if(menus().length){const heading=[...document.querySelectorAll('h1,[role="heading"]')].find(visible);click(heading||document.body);}
      for(let i=0;i<10&&menus().length;i++)await pause(100);
      return menus().length===0;
    }
    async function waitFor(selector,labels){
      for(let i=0;i<50;i++){
        const control=find(selector,labels);
        if(control)return control;
        const exact=[...document.querySelectorAll(selector)].filter(el=>visible(el)&&!el.disabled&&el.getAttribute('aria-disabled')!=='true'&&labels.includes(norm(el.innerText)));
        if(exact.length===1)return exact[0];
        await pause(200);
      }
      return null;
    }
    // An option's own label: aria-label, else its first visible text line (ignores swatches/check marks).
    const optionName=el=>{const lines=String(el.innerText||el.textContent||'').split('\n').map(v=>v.trim()).filter(Boolean);return el.getAttribute('aria-label')||lines[0]||'';};
    const looseLabel=v=>norm(v).replace(/[-‐–]/g,' ').replace(/\s+/g,' ');
    const optionLabels=el=>[...new Set([el.getAttribute('aria-label'),optionName(el),el.innerText,el.textContent].map(looseLabel).filter(Boolean))];
    function matchOption(options,value,name){
      for(const want of [].concat(value)){
        const wanted=looseLabel(want);if(!wanted)continue;
        const exact=options.filter(el=>optionLabels(el).includes(wanted));
        if(exact.length===1)return exact[0];if(exact.length>1)continue;
        // Numbers and model names need exact matches; never guess a year/trim.
        if(['Year','Model'].includes(name)||/^\d+$/.test(wanted))continue;
        const prefix=options.filter(el=>optionLabels(el).some(label=>label.startsWith(wanted+' ')||wanted.startsWith(label+' ')));
        if(prefix.length===1)return prefix[0];
      }
      return null;
    }
    async function text(name,labels,value,multiline=false){
      if(value==null||String(value).trim()===''){review.push(name);reasons[name]='LotRadar has no mapped value';return;}
      const control=await waitFor(multiline?'textarea,[contenteditable="true"][role="textbox"]':'input:not([type]),input[type="text"],input[type="number"],input[type="tel"]',labels);
      if(!control||control.readOnly){review.push(name);return;}
      if(norm(control.value??control.textContent)){if(!equal(name,control.value??control.textContent,value)){review.push(name);reasons[name]='Existing value differs; kept unchanged';}else already.push(name);return;}
      const next=String(value);
      if(control.maxLength>=0&&next.length>control.maxLength){review.push(name);return;}
      if(control.isContentEditable)control.textContent=next;
      else Object.getOwnPropertyDescriptor(control instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set.call(control,next);
      control.dispatchEvent(new InputEvent('input',{bubbles:true,data:next,inputType:'insertText'}));
      control.dispatchEvent(new Event('change',{bubbles:true}));
      await pause(150);
      if(equal(name,control.value??control.textContent,next))filled.push(name);
      else review.push(name);
    }
    async function chooseOnce(name,labels,value,allowText=false,replaceConfirmed=false){
      const values=[].concat(value).filter(v=>v!=null&&String(v).trim()!=='');
      if(!values.length){review.push(name);reasons[name]='LotRadar has no mapped value';return;}
      value=values[0];
      const isWanted=text=>values.some(v=>looseLabel(text)===looseLabel(v));
      if(!await closeMenus()){review.push(name);reasons[name]='Previous menu would not close';return;}
      await waitFor('select,[role="combobox"],[aria-haspopup="listbox"],[aria-haspopup="menu"]'+(allowText?',input':''),labels);
      const native=find('select',labels);
      if(native){
        if(!replaceConfirmed&&native.value&&native.selectedOptions[0]&&!labels.includes(norm(native.selectedOptions[0].textContent))){
          if(!isWanted(native.selectedOptions[0].textContent))review.push(name);else already.push(name);
          return;
        }
        const options=values.map(v=>[...native.options].filter(option=>!option.disabled&&looseLabel(option.textContent)===looseLabel(v))).find(list=>list.length)||[];
        if(options.length!==1){review.push(name);reasons[name]='No option for '+values.join(' / ');return;}
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(native,options[0].value);
        native.dispatchEvent(new Event('input',{bubbles:true}));
        native.dispatchEvent(new Event('change',{bubbles:true}));
        filled.push(name);return;
      }
      const selector='[role="combobox"],[aria-haspopup="listbox"],[aria-haspopup="menu"]';
      const exact=[...document.querySelectorAll(selector)].filter(el=>visible(el)&&!el.disabled&&el.getAttribute('aria-disabled')!=='true'&&
        labels.includes(norm(el.innerText)));
      let control=exact.length===1?exact[0]:find(selector,labels);
      if(!control){if(allowText)await text(name,labels,value);else{review.push(name);reasons[name]='Field did not appear within 10 seconds';}return;}
      // A non-placeholder value is owned by the user. Do not overwrite it.
      const displayed=norm(control.value||control.innerText);
      if(!replaceConfirmed&&displayed&&!labels.includes(displayed)){
        if(!isWanted(displayed)&&!values.some(v=>labels.some(label=>displayed===label+' '+looseLabel(v)))){review.push(name);reasons[name]='Existing value differs; kept unchanged';}else already.push(name);
        return;
      }
      const before=new Set(allPopups());
      const alreadyOpen=control.getAttribute('aria-expanded')==='true';
      const fieldTexts=()=>new Map([...document.querySelectorAll(selector)].filter(visible)
        .map(el=>[labelsFor(el)[0]||'',norm(el.innerText||el.value)]).filter(([key])=>key&&!labels.includes(key)));
      try {
        if(!alreadyOpen)click(control);
        let popup=null;
        // Accept only a menu that belongs to THIS field: the linked one, or one that appeared after our click
        // while the field reports itself open. A slow menu from an earlier field must never be used here.
        for(let i=0;i<40;i++){
          await pause(100);
          const linked=document.getElementById(control.getAttribute('aria-controls')||control.getAttribute('aria-owns')||'');
          if(linked&&visible(linked)){popup=linked;break;}
          if(control.getAttribute('aria-expanded')==='false')continue;
          const rect=control.getBoundingClientRect(),gap=el=>{const r=el.getBoundingClientRect();return Math.min(Math.abs(r.top-rect.bottom),Math.abs(r.bottom-rect.top));};
          const fresh=menus().filter(el=>alreadyOpen||!before.has(el)).sort((x,y)=>gap(x)-gap(y));
          if(fresh.length){popup=fresh[0];break;}
        }
        if(!popup){
          // Our click may still open a menu late. Wait briefly so the finally-block closes it before the next field.
          for(let i=0;i<15&&!menus().some(el=>!before.has(el));i++)await pause(100);
          review.push(name);reasons[name]='Menu did not open';return;
        }
        let wanted=looseLabel(value);
        const hasWord=(text,word)=>(' '+text+' ').includes(' '+word+' ');
        const reflectsChoice=el=>el&&[el.value,el.innerText,el.getAttribute('aria-label')].map(looseLabel)
          .some(actual=>actual===wanted||labels.some(label=>actual===label+' '+wanted||(actual.startsWith(label+' ')&&hasWord(actual.slice(label.length),wanted))));
        const confirmed=()=>{
          // Reacquire controls after React replaces the original element.
          const current=[...document.querySelectorAll(selector)].filter(el=>visible(el)&&reflectsChoice(el));
          return (control.isConnected!==false&&reflectsChoice(control))||current.some(el=>labelsFor(el).some(label=>labels.includes(label)||label===labels[0]+' '+wanted)||norm(el.innerText)===labels[0]+' '+wanted);
        };
        const popupOpen=()=>popup.isConnected&&visible(popup)&&getComputedStyle(popup).pointerEvents!=='none';
        const readOptions=()=>[...popup.querySelectorAll('[role="option"],[role="menuitem"],[role="menuitemradio"]')]
          .filter(el=>visible(el)&&el.getAttribute('aria-disabled')!=='true');
        // Options can arrive after the menu itself (spinner first). Wait for them instead of giving up.
        for(let i=0;i<40&&popupOpen()&&!readOptions().length;i++)await pause(100);
        const ancestors=[];for(let el=popup;el&&el!==document.body&&el!==document.documentElement;el=el.parentElement)ancestors.push(el);
        const seen=new Set();
        const scrollables=()=>[...ancestors,...popup.querySelectorAll('*')].filter(el=>el&&el!==document.body&&
          el.clientHeight>0&&el.scrollHeight>el.clientHeight+2&&/auto|scroll/.test(getComputedStyle(el).overflowY));
        // Reset to the start: years and makes can be virtualized and open mid-list.
        for(const el of scrollables()){el.scrollTop=0;el.dispatchEvent(new Event('scroll',{bubbles:true}));}
        await pause(120);
        let stalled=0;
        for(let page=0;page<30;page++){
          if(!popupOpen()){review.push(name);reasons[name]='Menu closed before an option was chosen';return;}
          const options=readOptions();
          options.forEach(el=>seen.add(optionName(el)));
          const matched=matchOption(options,values,name);
          if(matched){
            wanted=looseLabel(optionName(matched));
            const label=optionName(matched),othersBefore=fieldTexts();
            touched.add(name);
            // Facebook can ignore a click while the menu is still animating open. If the menu is still
            // open and nothing changed, click the same option again (at most 3 clicks), then keep waiting
            // up to 5 s in total for React to show the choice.
            let target=matched,waited=0;
            for(let clicks=0;clicks<3&&target;clicks++){
              target.scrollIntoView({block:'nearest'});click(target);
              for(let wait=0;wait<5;wait++){await pause(100);waited++;if(confirmed())break;}
              if(confirmed()||!popupOpen())break;
              target=matchOption(readOptions(),[label],name);
            }
            let ok=confirmed();
            for(;!ok&&waited<50;waited++){await pause(100);ok=confirmed();}
            // Safety: a click must not change any other field (wrong-menu protection).
            const after=fieldTexts();
            for(const [key,text] of othersBefore)if(after.has(key)&&after.get(key)!==text){
              const other=key.replace(/\b\w/g,c=>c.toUpperCase());
              review.push(other);reasons[other]='Changed while LotRadar filled '+name+'; check it';
            }
            if(!ok){review.push(name);reasons[name]='Chose '+label+' but Facebook did not show it within 5 seconds';return;}
            filled.push(name);
            return;
          }
          let moved=false;
          for(const el of scrollables()){
            const previous=el.scrollTop;
            el.scrollTop=Math.min(el.scrollHeight-el.clientHeight,previous+Math.max(40,Math.floor(el.clientHeight*.75)));
            el.dispatchEvent(new Event('scroll',{bubbles:true}));
            moved=moved||el.scrollTop>previous;
          }
          if(!moved){options[options.length-1]?.scrollIntoView({block:'start'});if(++stalled>=3)break;}else stalled=0;
          await pause(120);
        }
        review.push(name);reasons[name]='No option for '+values.join(' / ')+(seen.size?'; menu showed: '+[...seen].filter(Boolean).slice(0,25).join(', '):'; menu had no readable options after 4 seconds');
      } finally {
        if(!await closeMenus()){if(!review.includes(name))review.push(name);reasons[name]='Menu did not close after selection';}
      }
    }
    const touched=new Set();
    async function choice(...args){
      const name=args[0];
      for(let attempt=0;attempt<2;attempt++){
        const start=review.length;
        await chooseOnce(...args);
        if(!review.slice(start).includes(name)){
          if(attempt>0){
            if(!review.includes(name))delete reasons[name];
            // Our first attempt set it, Facebook was just slow to show it: report it as filled, not "already".
            const i=already.lastIndexOf(name);if(i>=0&&touched.has(name)){already.splice(i,1);filled.push(name);}
          }
          return;
        }
        if(attempt===0){for(let i=review.length-1;i>=start;i--)if(review[i]===name)review.splice(i,1);await pause(350);}
      }
    }
    // <lotradar-color-map>
    // Facebook color labels, best first. generic = dealer's normalized color (Dealer.com
    // normalExteriorColor/normalInteriorColor); factory = marketing name ("Celestite").
    const colorCandidates=(generic,factory)=>{
      const PLACEHOLDER=/^(other|unknown|n\/a|na|none|null|undefined|-|not available|not specified)?$/;
      const SYNONYMS={'Gray':['Gray','Grey'],'Off white':['Off white','Off-white','Off White']};
      const BASIC=['off white','charcoal','burgundy','turquoise','beige','silver','black','white','gray','grey',
        'blue','brown','gold','green','pink','purple','red','orange','yellow','tan'];
      // Factory names with no color word. Extend only with evidence (dealer generic or window sticker).
      const ALIASES={
        'celestite':'Gray','underground':'Gray','ice cap':'White','blueprint':'Blue','bronze oxide':'Brown',
        'wind chill pearl':'White','blizzard pearl':'White','super white':'White','iridescent pearl tricoat':'White',
        'lunar rock':'Gray','heavy metal':'Gray','magnetic gray':'Gray',
        'midnight black':'Black','ebony':'Black','ash':'Gray','graphite':'Gray','medium soft ceramic':'Gray',
        'warm ivory':'Beige','ivory':'Beige','moonstone':'Beige','terra':'Brown','mudbath':'Tan',
        'smoked mesquite':'Brown','wave maker':'Blue'
      };
      const title=c=>c==='grey'?'Gray':c==='off white'?'Off white':c.replace(/\b\w/g,x=>x.toUpperCase());
      const fromText=value=>{
        const text=norm(value).replace(/[^a-z0-9/ -]/g,' ').replace(/\s+/g,' ').trim();
        if(PLACEHOLDER.test(text))return null;
        if(ALIASES[text])return ALIASES[text];
        for(const [name,label] of Object.entries(ALIASES))if(new RegExp('^'+name+'\\b').test(text))return label;
        let best=null,at=Infinity;
        for(const c of BASIC){const m=new RegExp('(^|[^a-z])'+c).exec(text);   // word START only: Redline->Red, not Titanium->Tan
          if(m&&m.index<at){best=c;at=m.index;}}
        return best?title(best):null;
      };
      const out=[];
      for(const label of [fromText(generic),fromText(factory)])
        if(label)for(const s of (SYNONYMS[label]||[label]))if(!out.includes(s))out.push(s);
      return out;
    };
    // </lotradar-color-map>
    const mapChoice=(value,groups)=>{
      const key=norm(value);
      for(const [label,aliases] of Object.entries(groups))if([norm(label),...aliases].includes(key))return label;
      return value;
    };
    if(/^(other|unknown|n\/a|na|none|-|not available|not specified)$/.test(norm(fields.fuel_type)))fields.fuel_type=null;
    if(!/sedan|saloon|suv|sport utility|crossover|truck|pick ?up|cab|coupe|hatch|liftback|wagon|convertible|van|\b[24] ?dr\b|\bcar\b/.test(norm(fields.body_style)))fields.body_style=null;
    const fuel=norm(fields.fuel_type),body=norm(fields.body_style),trans=norm(fields.transmission);
    if(/plug.?in|phev/.test(fuel))fields.fuel_type='Plug-in hybrid';
    else if(/hybrid|gas.?electric|hev/.test(fuel))fields.fuel_type='Hybrid';
    else if(/\bflex(?:ible)?\b|\be85\b/.test(fuel))fields.fuel_type='Flex';
    else if(/diesel/.test(fuel))fields.fuel_type='Diesel';
    else if(/gasoline|unleaded|petrol/.test(fuel))fields.fuel_type='Gasoline';
    else if(/electric|bev/.test(fuel))fields.fuel_type='Electric';
    if(/sport.utility|suv|crossover/.test(body))fields.body_style='SUV';
    else if(/pickup|crew.?cab|double.?cab|truck/.test(body))fields.body_style='Truck';
    else if(/sedan|\b4\s*(?:dr|door)\s+car\b/.test(body))fields.body_style='Sedan';
    else if(/hatchback/.test(body))fields.body_style='Hatchback';
    else if(/coupe|\b2\s*(?:dr|door)\s+car\b/.test(body))fields.body_style='Coupe';
    else if(/mini[ -]?van/.test(body))fields.body_style='Minivan';
    if(/automatic|cvt/.test(trans))fields.transmission='Automatic transmission';
    else if(/manual/.test(trans))fields.transmission='Manual transmission';
    await choice('Vehicle type',['vehicle type'],fields.vehicle_type||'Car/Truck');
    // Stop only when the field exists but could not be set; a form without the field continues.
    if(review.includes('Vehicle type')&&!/^Field did not appear/.test(reasons['Vehicle type']||'')){
      reasons['Vehicle type']=(reasons['Vehicle type']||'Not selected')+'. The rest of the form appears only after Vehicle type is chosen: choose it, then press Fill again';
      return {filled:[...new Set(filled)],already:[...new Set(already)],review:[...new Set(review)],reasons,stopped:true};
    }
    await choice('Year',['year','model year'],fields.year);
    await choice('Make',['make'],fields.make,true);
    await choice('Model',['model'],fields.model,true);
    await text('Mileage',['mileage','odometer'],fields.mileage);
    await text('Price',['price','asking price'],fields.price);
    await choice('Body style',['body style'],mapChoice(fields.body_style,{'Truck':['pickup','pickup truck','crew cab','double cab','regular cab','supercrew'],'SUV':['sport utility','sport utility vehicle','crossover'],'Minivan':['mini-van'],'Coupe':['2dr coupe'],'Sedan':['4dr sedan']}));
    await choice('Exterior color',['exterior color','exterior colour'],colorCandidates(fields.exterior_color_generic,fields.exterior_color));
    await choice('Interior color',['interior color','interior colour'],colorCandidates(fields.interior_color_generic,fields.interior_color));
    await choice('Fuel type',['fuel type'],mapChoice(fields.fuel_type,{
      'Gasoline':['gas','unleaded','gasoline fuel'], 'Diesel':['diesel fuel'],
      'Hybrid':['hybrid electric','gas/electric hybrid','hev'],
      'Plug-in hybrid':['plug-in hybrid electric','phev','plug in hybrid'],
      'Electric':['bev','battery electric','electric fuel system'], 'Flex':['flex fuel','flex-fuel','e85']
    }));
    await choice('Transmission',['transmission'],mapChoice(fields.transmission,{
      'Automatic transmission':['automatic','cvt','e-cvt','continuously variable','continuously variable transmission'], 'Manual transmission':['manual']
    }));
    const modelYear=Number(fields.year),currentYear=new Date().getFullYear();
    const condition=Number.isFinite(modelYear)&&modelYear>=currentYear-2?'Excellent':'Very good';
    await choice('Vehicle condition',['vehicle condition','condition'],condition,false,true);
    // Owner confirmed this declaration for vehicles prepared through LotRadar.
    async function checkCleanTitle(){
      const name='Clean title';
      const selector='input[type="checkbox"],[role="checkbox"]';
      const checked=el=>el.checked===true||el.getAttribute('aria-checked')==='true';
      const matches=()=>[...document.querySelectorAll(selector)].filter(el=>{
        if(!visible(el)||el.disabled||el.getAttribute('aria-disabled')==='true')return false;
        if(labelsFor(el).some(label=>label.includes('this vehicle has a clean title')))return true;
        // Facebook sometimes renders the text beside an unlabeled checkbox.
        // Restrict ancestor matching to a small container with exactly one box.
        let parent=el.parentElement;
        for(let depth=0;parent&&depth<4;depth++,parent=parent.parentElement){
          const label=norm(parent.innerText||parent.textContent);
          if(label.length<=350&&label.includes('this vehicle has a clean title')&&
             parent.querySelectorAll(selector).length===1)return true;
        }
        return false;
      });
      for(let attempt=0;attempt<25;attempt++){
        const boxes=matches();
        if(boxes.length>1){review.push(name);reasons[name]='Multiple matching checkboxes; select manually';return;}
        if(boxes.length===1){
          if(checked(boxes[0])){already.push(name);return;}
          click(boxes[0]);
          for(let verify=0;verify<15;verify++){
            await pause(100);
            const current=matches();
            if(current.length===1&&checked(current[0])){filled.push(name);return;}
          }
          review.push(name);reasons[name]='Checkbox did not confirm selection';return;
        }
        await pause(200);
      }
      review.push(name);reasons[name]='Clean-title checkbox not found';
    }
    await checkCleanTitle();
    await text('Description',['description','vehicle description'],fields.description,true);
    if(!fields.body_style)reasons['Body style']='Body style (dealer site and VIN lookup have none)';
    if(!fields.fuel_type)reasons['Fuel type']='Fuel type (dealer site and VIN lookup have none)';
    return {filled:[...new Set(filled)],already:[...new Set(already)],review:[...new Set(review)],reasons};
  })();
}
const isVehicleFormUrl=url=>{try{
  const page=new URL(url);
  return page.origin==='https://www.facebook.com'&&/^\/marketplace\/create\/vehicle\/?$/.test(page.pathname);
}catch{return false;}};
const formStorageKey=tabId=>'vehicle-form:'+tabId;
chrome.tabs.onRemoved.addListener(tabId=>{
  chrome.storage.session.remove(formStorageKey(tabId)).catch(()=>{});
});
chrome.tabs.onUpdated.addListener((tabId,change)=>{
  if(change.url&&!isVehicleFormUrl(change.url)){
    chrome.storage.session.remove(formStorageKey(tabId)).catch(()=>{});
  }
});
async function openVehicleForm(handoff){
  if(typeof handoff!=='string'||!/^[A-Za-z0-9_-]{32}$/.test(handoff))throw Error('Invalid LotRadar draft.');
  const {bridgeKey}=await chrome.storage.local.get('bridgeKey');
  if(!bridgeKey)throw Error('Pair Chrome Reader with LotRadar first.');
  const claim=await request('/api/chrome-bridge/vehicle-form',bridgeKey,{operation:'claim',handoff,tab_id:0});
  if(!claim.claimed)return {ok:true};
  const url='https://www.facebook.com/marketplace/create/vehicle/';
  const windows=await chrome.windows.getAll({windowTypes:['normal']});
  const browser=windows.find(win=>win.focused)||windows[0];
  const tab=browser
    ? await chrome.tabs.create({windowId:browser.id,url})
    : (await chrome.windows.create({url,type:'normal'})).tabs?.[0];
  if(!Number.isInteger(tab?.id))throw Error('Chrome could not open a vehicle form tab.');
  try {
    await request('/api/chrome-bridge/vehicle-form',bridgeKey,{operation:'bind',handoff,tab_id:tab.id});
    await chrome.storage.session.set({[formStorageKey(tab.id)]:handoff});
    let ready=false;
    for(let n=0;n<55;n++){
      const current=await chrome.tabs.get(tab.id);
      if(/facebook\.com\/(login|checkpoint)/i.test(current.url||'')){
        await request('/api/chrome-bridge/vehicle-form',bridgeKey,{operation:'login',handoff,tab_id:tab.id});
        await chrome.windows.update(current.windowId,{focused:true});
        return {error:'Sign in to Facebook, then retry.'};
      }
      if(current.status==='complete'&&isVehicleFormUrl(current.url)){
        const [probe]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>!!document.querySelector('input[type="password"]')});
        await request('/api/chrome-bridge/vehicle-form',bridgeKey,{operation:probe?.result?'login':'ready',handoff,tab_id:tab.id});
        await chrome.windows.update(current.windowId,{focused:true});ready=true;break;
      }
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    if(!ready)throw Error('Facebook did not finish loading. Retry.');
  } catch(error) {
    await request('/api/chrome-bridge/vehicle-form',bridgeKey,{operation:'failed',handoff,tab_id:tab.id}).catch(()=>{});
    throw error;
  }
  return {ok:true};
}
let autofillBusy=false;
async function autofillVehicleForm(){
 if(autofillBusy)return {error:"Autofill is already running."};
 autofillBusy=true;try{return await runAutofillVehicleForm();}finally{autofillBusy=false;}
}
async function runAutofillVehicleForm(){
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.id||!isVehicleFormUrl(tab.url))return {error:'Open the Facebook vehicle creation form first.'};
  const {bridgeKey}=await chrome.storage.local.get('bridgeKey');
  if(!bridgeKey)return {error:'Pair Chrome Reader with LotRadar first.'};
  const storageKey=formStorageKey(tab.id);
  const handoff=(await chrome.storage.session.get(storageKey))[storageKey];
  if(!handoff)return {error:'Open the Facebook form from the matching vehicle in LotRadar first.'};
  const {fields}=await request('/api/chrome-bridge/vehicle-form',bridgeKey,{operation:'read',handoff,tab_id:tab.id});
  const [outcome]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:fillVehicleForm,args:[fields]});
  const result=outcome?.result;
  if(!result||result.error)return {error:result?.error||'Facebook’s form was not available.'};
  const parts=[];
  if(result.filled.length)parts.push('Filled: '+result.filled.join(', ')+'.');
  if(result.already?.length)parts.push('Already set: '+result.already.join(', ')+'.');
  if(result.review.length)parts.push('Needs you: '+result.review.map(name=>name+' ('+(result.reasons?.[name]||'Selection could not be verified')+')').join(', ')+'.');
  return {status:parts.join(' ')+' Add photos and review the form before publishing.'};
}
chrome.runtime.onMessage.addListener((msg,source,send)=>{
  if(msg?.action==='open-vehicle-form'){
    if(source.frameId!==0||!source.url?.startsWith(ROOT+'/'))return;
    openVehicleForm(msg.handoff).then(send).catch(error=>send({error:String(error.message||error)}));
    return true;
  }
  if(msg?.action==='fill-vehicle-form'){
    if(source.url!==chrome.runtime.getURL('popup.html'))return;
    autofillVehicleForm().then(send).catch(e=>send({error:String(e.message||e)}));
    return true;
  }
  if(msg?.action==='facebook-auto-check'){announceFacebookReadiness().then(()=>checkFacebookAuto()).then(send).catch(e=>send({error:String(e.message||e)}));return true;}
  if(msg?.action==='capture-facebook'){captureCurrentFacebook().then(send).catch(e=>send({error:String(e.message||e).slice(0,200)}));return true;}
  if(msg?.action==='scan-stop'){stopOwnedDealerTabs().then(send).catch(e=>send({error:String(e.message||e)}));return true;}
  if(msg?.action==='run'){scanOne().then(send).catch(e=>send({error:String(e.message||e)}));return true;}
  if(msg?.action==='check'||msg?.action==='pair'){
    if(msg.action==='pair'&&(source.url!==chrome.runtime.getURL('popup.html')||
       !/^[A-Za-z0-9_-]{32,80}$/.test(msg.key||''))){
      send({state:'offline',error:'Enter the current LotRadar pairing key.'});
      return;
    }
    readerStatus(msg.action==='pair'?msg.key:undefined).then(result=>{
      send(result);
      if(msg.action==='pair'&&result.state==='connected')startReaderHeartbeat();
    }).catch(e=>send({state:'offline',error:String(e.message||e)}));
    return true;
  }
});
