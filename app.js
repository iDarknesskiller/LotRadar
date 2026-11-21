/* SalesmanHub Marketplace Manager Cycle 5 (internal preview).
 * No Facebook login or publishing code. All writes go to local tokenized API.
 */
'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={all:'Used inventory',trade:'Trade-in priority',drafts:'Listing drafts',published:'Tracked on Facebook',outstock:'Out of Stock',deletelisting:'Delete Listing'};
const sourceLabels={toyota_new:'Toyota • New',toyota_used:'Toyota • Used',mitsubishi_new:'Mitsubishi • New',mitsubishi_used:'Mitsubishi • Used'};
const usedSources=['toyota_used','mitsubishi_used'];
const isTradeInStock=stock=>/[A-Za-z]$/.test(String(stock||'').trim());
const isTradeInVehicle=r=>Object.entries(r.sources||{}).some(([src,rec])=>usedSources.includes(src)&&isTradeInStock(rec.stock));
const holdLabels={condition_conflict:'Condition conflict',vehicle_description_conflict:'Vehicle details disagree',price_conflict:'Different dealer prices',unconfirmed_price:'Unconfirmed price',photo_approval_required:'Photos unavailable or unapproved',missing_from_feed_recheck:'Missing from source: verify',availability_needs_confirmation:'Availability needs confirmation',demo_sample_not_publishable:'Demonstration only • not publishable',inventory_stale:'Inventory check older than 72 hours'};
let state={vehicles:[],feeds:{},summary:{vehicles:0,shared_used:0,needs_attention:0,drafts:0,published_confirmed:0,quarantined:0}};
let basicCatalog={schema:1,sources:{}},csrf='',tab='trade',search='',selectedVin='',toastTimer,siteScanTimer,scanDockEnabled=false,lastScanJob=null,selectedBasic=null;
let basicVisible=60,vehicleVisible=60,liveVerifyTimer=null;
// R32: prevent overlapping status requests and redraw storms. No new background work.
let photoStatusPendingKey='',liveVerifyStatusPending=false,siteScanStatusPending=false,searchRenderTimer=null;
let gallery={vin:'',source:'',index:0,cache:null,pictures:[],initial:true};

// Phase 1: selections affect local exports only, never Facebook posting.
let photoSelection={vin:'',source:'',keys:[],saved:null,limit:20,ready:false,missing:[],dirty:false,error:''};
let photoGridExpanded=false;
let photoProgress={vin:'',source:'',data:null,revision:'',watching:''},photoOpenGuard=new Map();

let photoSaveTimer=null,photoSaveChain=Promise.resolve();
const exportFrameKey=photo=>photo.kind==='dedication'?'dedication':photo.url;
function orderedPhotoKeys(){const have=new Set(exportPreview.photos.map(exportFrameKey));return photoSelection.keys.filter(k=>have.has(k));}
function selectionActive(){return photoSelection.ready&&photoSelection.vin===exportPreview.vin&&photoSelection.source===exportPreview.actualSource;}
async function loadPhotoSelection(p){
 const saved=await api(`/api/photos/selection?vin=${encodeURIComponent(p.vin)}&source=${encodeURIComponent(p.actualSource)}`);
 if(exportPreview!==p)return;
 if(saved.source!==p.actualSource)throw Error('Photo source changed; refresh preview');
 photoSelection={vin:p.vin,source:p.actualSource,keys:[...saved.keys],groups:saved.groups||{},autoGroups:saved.auto_groups||{},classifyAvailable:!!saved.classify_available,autoSort:saved.auto_sort||{},saved:saved.saved?[...saved.keys]:null,limit:saved.limit,ready:true,missing:saved.missing_keys||[],dirty:false,error:''};
 watchSortStartedByOpen(p,saved.auto_sort);
}
// The open request can queue a sort AFTER the progress panel already read "Ready"; show it and follow it to the end.
function watchSortStartedByOpen(p,sort){
 const d=photoProgress.data;
 if(!sort?.running||!d||photoProgress.vin!==p.vin||['queued','downloading','sorting'].includes(d.stage))return;
 photoProgress={...photoProgress,data:{...d,stage:'sorting',sorting:{running:true,classified:sort.classified||0,total:sort.total||0,error:''}}};
 updatePhotoProgressInPlace();void watchPhotoProgress(p.vin,p.actualSource);
}
function persistPhotoSelection(){
 clearTimeout(photoSaveTimer);
 if(!selectionActive()||!photoSelection.dirty)return Promise.resolve();
 const current=photoSelection,version=current.version||0,body={vin:current.vin,source:current.source,keys:orderedPhotoKeys(),limit:current.limit,groups:current.groups||{}};
 photoSaveChain=photoSaveChain.catch(()=>{}).then(()=>api('/api/photos/selection',body)).then(result=>{if(photoSelection===current){current.saved=[...body.keys];if((current.version||0)===version){current.dirty=false;current.missing=[];}}}).catch(e=>{notify('Photo selection was not saved: '+e.message,true);throw e;});
 return photoSaveChain;
}
function selectionChanged(){photoSelection.dirty=true;photoSelection.version=(photoSelection.version||0)+1;const strip=document.querySelector('.gallery-thumbs'),left=strip?strip.scrollLeft:0,top=strip?strip.scrollTop:0,focusLabel=document.activeElement?.getAttribute?.('aria-label'),limitFocus=document.activeElement?.matches?.('[data-photo-limit]');renderDetail();const again=document.querySelector('.gallery-thumbs');if(again){again.scrollLeft=left;again.scrollTop=top;};if(focusLabel)document.querySelector(`[aria-label="${CSS.escape(focusLabel)}"]`)?.focus({preventScroll:true});if(limitFocus)document.querySelector('[data-photo-limit]')?.focus({preventScroll:true});if(again){again.scrollLeft=left;again.scrollTop=top;};clearTimeout(photoSaveTimer);photoSaveTimer=setTimeout(()=>{void persistPhotoSelection().catch(()=>{});},400);}
// Selection order IS click history: append on select, remove on deselect, re-select appends again.
function togglePhotoKey(key){
 if(!selectionActive())return false;
 const at=photoSelection.keys.indexOf(key);
 if(at>=0)photoSelection.keys=photoSelection.keys.filter(k=>k!==key);
 else if(orderedPhotoKeys().length>=photoSelection.limit){photoSelection.notice=`Limit reached: select no more than ${photoSelection.limit} photos.`;notify(photoSelection.notice);renderPhotoControls();return false;}
 else photoSelection.keys=[...photoSelection.keys,key];
 photoSelection.notice='';selectionChanged();return true;
}
function selectPhotoPreset(){photoSelection.keys=exportPreview.photos.slice(0,2).map(exportFrameKey);photoSelection.notice='';selectionChanged();}
function photoSelectionToolbar(){
 if(!selectionActive())return photoSelection.error?'<p class="photo-selection-note">Photo selection didn’t load · <button type="button" data-act="retry-photo-selection">Retry</button></p>':'<p class="photo-selection-note">Loading photo selection…</p>';
 const keys=orderedPhotoKeys(),count=keys.length;
 const warning=photoSelection.notice||(count>photoSelection.limit?`Select no more than ${photoSelection.limit} photos.`:count===0?'Select at least one photo.':'');
 const selected=keys.map((key,n)=>{const i=exportPreview.photos.findIndex(p=>exportFrameKey(p)===key);return `<button type="button" class="selected-photo-thumb" data-gallery-index="${i}" data-preview-only="1" aria-label="Preview selected photo ${n+1}">${exportPreview.urls.has(i)?`<img src="${esc(exportPreview.urls.get(i))}" alt="Selected photo ${n+1}">`:'<span class="preview-thumb-pending">Loading…</span>'}<span>${String(n+1).padStart(2,'0')}</span></button>`;}).join('');
 return `<div class="selected-photo-heading"><strong>Selected photos · ${count}</strong><button type="button" class="btn secondary" data-photo-default>Reset to 01 + 02</button></div><div class="selected-photo-strip" aria-label="Selected photos in download order">${selected||'<span>No photos selected</span>'}</div>${warning?`<p class="photo-selection-note" role="status">${esc(warning)}</p>`:''}<p class="photo-selection-note">Photos download in the order you select them.</p>`;
}
function renderPhotoControls(){
 const strip=document.querySelector('.gallery-thumbs'),left=strip?.scrollLeft||0,top=strip?.scrollTop||0,label=document.activeElement?.getAttribute?.('aria-label');
 renderDetail();if(label)document.querySelector(`[aria-label="${CSS.escape(label)}"]`)?.focus({preventScroll:true});
 const again=document.querySelector('.gallery-thumbs');if(again){again.scrollLeft=left;again.scrollTop=top;}
}
const selectionStyle=document.createElement('link');selectionStyle.rel='stylesheet';selectionStyle.href='/photo-selection.css?v=ordered-picker-1';document.head.append(selectionStyle);
document.addEventListener('click',e=>{if(e.target.closest('[data-photo-default]'))selectPhotoPreset();});
document.addEventListener('change',e=>{
 if(e.target.matches('[data-photo-check]')){const index=Number(e.target.dataset.photoCheck),p=exportPreview.photos[index];if(!p||!selectionActive())return;gallery.index=index;if(!togglePhotoKey(exportFrameKey(p)))e.target.checked=photoSelection.keys.includes(exportFrameKey(p));}
});

let exportPreview={enabled:false,vin:'',source:'',revision:'',photos:[],urls:new Map(),pending:new Set(),failed:new Map(),counts:null,loading:false,error:'',actualSource:''};
// Plain-text reason for a failed export preview. A branding problem must never read as "photos still
// fetching": the downloaded originals are fine, only the business card / dedication images are missing.
function exportPreviewErrorText(error){
 const text=String(error||'');
 const brand=/^branding_assets_(missing|invalid)(?::\s*([^;]+))?/.exec(text);
 if(brand){
  const files=(brand[2]||'business_card.png, dedication.jpg').trim();
  return `Export preview needs LotRadar's branding images: ${files} ${brand[1]==='missing'?'missing':'damaged'} in the program's branding folder. Downloaded vehicle photos are not affected. Reinstall or re-download LotRadar to restore them.`;
 }
 if(/^no_export_ready_photos/.test(text))return 'No export photos ready yet. Download the car photos first.';
 return 'Export preview unavailable: '+text;
}
function resetExportPreview(){
 if(selectionActive())void persistPhotoSelection().catch(()=>{});
 for(const value of exportPreview.urls.values())URL.revokeObjectURL(value);
 exportPreview={enabled:false,vin:'',source:'',revision:'',photos:[],urls:new Map(),pending:new Set(),failed:new Map(),counts:null,loading:false,error:'',actualSource:''};
}
// R62: fetch the actual export bytes in a small background queue. No permanent
// 'Loading' boxes for 5+; each thumbnail eventually loads or shows a real error.
// All media URLs are revoked when leaving/changing the vehicle.
function updateExportFrameUI(index){
 const p=exportPreview;
 if(selectedVin!==p.vin||gallery.source!==p.source||!p.enabled)return;
 const buttons=document.querySelectorAll(`#detail-overlay [data-gallery-index="${index}"]`);
 for(const button of buttons){
  const place=button.querySelector('.preview-thumb-pending');
  if(place){
   if(p.urls.has(index)){
    const img=document.createElement('img');img.src=p.urls.get(index);img.loading='lazy';
    img.alt=`Export photo ${index+1}`;place.replaceWith(img);
   }else if(p.failed.has(index)){
    place.textContent='Retry photo';place.classList.add('preview-thumb-failed');
    button.title='Preview failed: click to retry';
   }
  }
 }
 if(gallery.index===index){
  const stage=document.querySelector('#detail-overlay .gallery-stage');
  if(stage&&p.urls.has(index)){
   stage.replaceChildren();const img=document.createElement('img');
   img.src=p.urls.get(index);img.alt=`Export photo ${index+1}`;stage.appendChild(img);
  }else if(stage&&p.failed.has(index)){
   stage.textContent=`Preview photo ${index+1} unavailable. Select its thumbnail to retry.`;
  }
 }
 const progress=document.querySelector('#detail-overlay .photo-preview-progress');
 if(progress){const ready=p.urls.size,failed=p.failed.size,total=p.photos.length;
  progress.textContent=`Preview images: ${ready}/${total} ready${failed?` · ${failed} failed (retry available)`:''}`;
 }
}
// Cache bytes, not object URLs: closing a drawer still releases its DOM URLs.
const previewBlobCache=new Map();
let previewBlobBytes=0;
const previewBlobLimit=48*1024*1024;
function cachedPreviewBlob(key){
 const blob=previewBlobCache.get(key);
 if(blob){previewBlobCache.delete(key);previewBlobCache.set(key,blob);}
 return blob;
}
function rememberPreviewBlob(key,blob){
 if(blob.size>previewBlobLimit)return;
 const old=previewBlobCache.get(key);if(old)previewBlobBytes-=old.size;
 previewBlobCache.delete(key);previewBlobCache.set(key,blob);previewBlobBytes+=blob.size;
 while(previewBlobBytes>previewBlobLimit){const first=previewBlobCache.keys().next().value;previewBlobBytes-=previewBlobCache.get(first).size;previewBlobCache.delete(first);}
}
async function loadExportPreviewFrame(index){
 const p=exportPreview;
 if(!p.enabled||!p.revision||index<0||index>=p.photos.length||p.urls.has(index)||p.pending.has(index))return;
 p.pending.add(index);
 try{
  const path=`/api/photos/export-preview?vin=${encodeURIComponent(p.vin)}&source=${encodeURIComponent(p.source)}&index=${index}&rev=${encodeURIComponent(p.revision)}`;
  const cached=cachedPreviewBlob(path);
  if(cached){p.failed.delete(index);p.urls.set(index,URL.createObjectURL(cached));updateExportFrameUI(index);return;}
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),25000);
  let response;
  try{response=await fetch(path,{headers:{'X-SalesmanHub-Token':csrf},cache:'no-store',signal:controller.signal});}
  finally{clearTimeout(timeout);}
  if(!response.ok){const err=await response.json().catch(()=>({}));throw Error(err.error||'Preview image unavailable');}
  const blob=await response.blob();
  rememberPreviewBlob(path,blob);
  if(exportPreview!==p||!p.enabled)return;
  p.failed.delete(index);
  p.urls.set(index,URL.createObjectURL(blob));
  updateExportFrameUI(index);
 }catch(err){if(exportPreview===p){p.failed.set(index,String(err?.message||err));updateExportFrameUI(index);}}
 finally{p.pending.delete(index);}
}
async function fillExportPreviewThumbnails(p){
 // Loading one photo after another can take time, so use two modest workers.
 // Avoid flooding the backend/CDN; this is only locally prepared export data.
 let next=4;
 const worker=async()=>{
  while(exportPreview===p&&p.enabled&&next<p.photos.length){
   const index=next++;
   await loadExportPreviewFrame(index);
  }
 };
 await Promise.all([worker(),worker()]);
}
async function toggleExportPreview(){
 if(!selectedVin||!gallery.source)return;
 if(exportPreview.enabled&&exportPreview.loading)return;
 const vin=selectedVin,source=gallery.source;
 resetExportPreview();const p=exportPreview;
 p.enabled=true;p.loading=true;p.vin=vin;p.source=source;gallery.index=0;
 renderDetail();
 try{
  const path=`/api/photos/export-preview?vin=${encodeURIComponent(vin)}&source=${encodeURIComponent(source)}`;
  const response=await fetch(path,{headers:{'X-SalesmanHub-Token':csrf},cache:'no-store'});
  const data=await response.json();
  if(!response.ok||!data.ok)throw Error(data.error||'No export-ready images');
  if(exportPreview!==p||selectedVin!==vin||gallery.source!==source)return;
  p.revision=data.revision;p.photos=data.photos||[];p.actualSource=data.photo_source||source;
  p.counts=data.photo_counts||null;p.error='';p.loading=false;
  try{await loadPhotoSelection(p);}catch(error){if(exportPreview===p)photoSelection={vin:p.vin,source:p.actualSource,keys:[],saved:null,limit:20,ready:false,missing:[],dirty:false,error:String(error.message||error)};}
  if(exportPreview!==p)return;
  renderDetail();
  // Warm the cover/dedication and nearest shots, then progressively fill the
  // rest of the strip. The user can still select a frame immediately.
  await loadExportPreviewFrame(0);
  if(exportPreview!==p)return;
  await Promise.all([1,2,3].map(i=>loadExportPreviewFrame(i)));
  if(exportPreview===p)void fillExportPreviewThumbnails(p);
 }catch(err){if(exportPreview===p){p.loading=false;p.error=String(err.message||err);renderDetail();notify(exportPreviewErrorText(p.error),true);}}
}

let globalPhotoSettings={contact_number:'',auto_replace:false};
let refreshingVin='';
let facebookCompareCache=new Map(),facebookCompareOpenVin='';
// R47: unsaved URL edits survive background rerenders until explicitly locked.
let facebookUrlEdit=null;
let facebookAutoStatus=new Map(),facebookAutoWatchSerial=0;
let facebookBulkStatusTimer=null,facebookBulkPending=false,facebookBulkLastCaptured=0;
let recentFieldChanges=new Map(),fieldFlashTimer=null;
// Unsaved AI/text preview survives status polling and rerenders, but never replaces a saved draft.
let draftEditBuffer=null;
const money=cents=>cents==null||!Number.isFinite(Number(cents))||Number(cents)<=0?'Verify dealer price':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(Number(cents)/100);
const collapseRepeatTrim=(text,trim)=>{let value=String(text||'').trim(),tail=' '+String(trim||'').trim();if(tail===' ')return value;while(value.toLowerCase().endsWith((tail+tail).toLowerCase()))value=value.slice(0,-tail.length).trimEnd();return value;};
const name=r=>{const model=collapseRepeatTrim(r.model,r.trim),trim=String(r.trim||'').trim();return `${r.year} ${r.make} ${model}${trim&&!model.toLowerCase().endsWith(trim.toLowerCase())?' '+trim:''}`};
const trackedPlaceholder='Existing personal Marketplace listing tracked by user';
const isUsedVehicle=r=>Object.keys(r.sources||{}).some(s=>usedSources.includes(s));
const primary=r=>r.sources.toyota_used||r.sources.mitsubishi_used||Object.values(r.sources)[0];
const hasChanged=r=>Boolean(r.draft?.changed_since_draft);
const alertNeeded=r=>r.holds.length>0||hasChanged(r)||Boolean(r.draft?.review_state);
const validHttps=url=>{try{const p=new URL(url);return p.protocol==='https:'&&!p.username&&!p.password}catch{return false}};
const dealerLink=(source,record)=>{try{const u=new URL(record?.url||'');
  const host=source==='toyota_used'?'www.hamptontoyota.com':source==='mitsubishi_used'?'www.hamptonmitsubishi.com':'';
  return u.protocol==='https:'&&u.hostname===host&&/^\/used\/.+\.htm$/i.test(u.pathname)&&!u.username&&!u.password?u.href:'';
 }catch{return '';}};
const isBrandGraphic=url=>{
 try { const pathname=new URL(url).pathname.toLowerCase();
  return /(?:^|[\/_.-])(logo|brand|placeholder|no-photo|no_image|noimage|generic|dealer-logo|coming-soon|mitsubishi-motors)(?:[\/_.-]|$)/i.test(pathname);
 } catch {return true;}
};
// R22: screen for publishing, but do not blank an entire inventory grid while
// local downloads or Pillow screening are pending. Every fallback is PREVIEW ONLY.
// Rejected local graphics are NEVER used as previews or exported by this UI.
const isDealerPreviewUrl=url=>{
 try { const u=new URL(url);return u.protocol==='https:'&&
   ['pictures.dealer.com','www.hamptontoyota.com','www.hamptonmitsubishi.com'].includes(u.hostname)&&
   /\.(?:jpg|jpeg|png|webp)$/i.test(u.pathname)&&!isBrandGraphic(url);
 }catch{return false;}
};
// Gallery uses one photo per image identity, not one per CDN resize URL.
// Visual duplicates with different paths are identified by the local cache.
const imageIdentity=url=>{try{const u=new URL(url);return u.hostname.toLowerCase()+decodeURIComponent(u.pathname).toLowerCase()}catch{return String(url)}};
const photoResolutionScore=(url,item)=>{let declared=0;try{const u=new URL(url);declared=Number(u.searchParams.get('w')||u.searchParams.get('width')||0)}catch{};
 return (Number(item?.width)||0)*(Number(item?.height)||0)*1000+declared;};
const photoInfo=r=>{
 for(const source of usedSources){
  const rec=r.sources[source];if(!rec)continue;
  const blocked=new Set(rec.photo_graphic_indices||[]);
  const usable=new Set(rec.photo_usable_indices||[]);
  const review=new Set(rec.photo_review_preview_indices||[]);
  const choose=index=>{
   if(!Number.isInteger(index)||index<0||blocked.has(index)||!rec.images?.[index])return null;
   const cached=usable.has(index)||review.has(index);
   const url=cached?`/api/photo?vin=${encodeURIComponent(r.vin)}&source=${encodeURIComponent(source)}&index=${index}`:rec.images[index];
   if(!localOrHttps(url)||(!cached&&!isDealerPreviewUrl(url)))return null;
   return {url,preview:!usable.has(index),index,source};
  };
  const manual=rec.photo_cover_manual?choose(rec.photo_cover_index):null;
  if(manual)return {url:manual.url,preview:manual.preview};
  const lead=rec.dealer_lead_photo?choose(rec.images?.indexOf(rec.dealer_lead_photo)):null;
  if(lead)return {url:lead.url,preview:lead.preview};
  // Older records have no explicit lead metadata. Keep the dealer's stored
  // order even when a later interior photo finishes downloading first.
  for(const [index] of (rec.images||[]).entries()){
   const picked=choose(index);
   if(picked)return {url:picked.url,preview:picked.preview};
  }
 }
 return {url:'',preview:false};
};
const photo=r=>photoInfo(r).url;
const localOrHttps=url=>validHttps(url)||/^\/api\/photo\?vin=/.test(String(url||''));
const photoApproved=r=>Object.values(r.sources).some(q=>q.images_approved&&q.images.length);
const statusText=r=>r.draft?({READY_TO_REVIEW:'Listing draft',READY_FOR_MANUAL_PUBLISH:'Listing draft',USER_CONFIRMED_PUBLISHED:'Tracked on Facebook',USER_CONFIRMED_REMOVED:'User confirmed removed'}[r.draft.status]||r.draft.status):'Not listed';
let cleanupIssues={},cleanupLoading=false,cleanupError='',checkingListingLinks=false;
const cleanupRank=r=>0;
const cleanupIssueText=issue=>{
 const labels={unavailable:'Link unavailable',check_failed:'Check failed · retry',inventory_review:'Inventory status needs review'};
 return issue.dealer.map(check=>`${sourceLabels[check.source]} · ${labels[check.outcome]}`)
  .concat(issue.facebook?[`Facebook · ${labels[issue.facebook.outcome]}`]:[]);
};
async function refreshCleanupStatus(){
 if(cleanupLoading)return;
 cleanupLoading=true;
 try{
  const response=await api('/api/cleanup-status');
  const changed=cleanupError||JSON.stringify(cleanupIssues)!==JSON.stringify(response.issues);
  cleanupIssues=response.issues||{};cleanupError='';
  if(changed){renderStats();renderGrid();}
 }catch(e){
  if(cleanupError!==e.message){cleanupError=e.message;if(tab==='outstock'||tab==='deletelisting')renderGrid();}
 }finally{cleanupLoading=false;}
}
const safeFacebookUrl=url=>{try{const p=new URL(url);if(p.protocol!=='https:'||!['facebook.com','www.facebook.com','m.facebook.com'].includes(p.hostname)||p.username||p.password||!(p.port===''||p.port==='443'))return '';const path=p.pathname.replace(/\/$/,'');const m=/^\/marketplace\/item\/(\d{8,24})$/.exec(path);const id=m?.[1]||(path==='/marketplace/edit'?(p.searchParams.get('listing_id')||''):'');return /^\d{8,24}$/.test(id)?`https://www.facebook.com/marketplace/item/${id}`:'';}catch{return '';}};

const compareSnapshot=r=>{const first=primary(r)||{},srcs=Object.keys(r.sources||{}).filter(s=>usedSources.includes(s));
 const stock=(srcs.map(k=>r.sources[k]).find(q=>isTradeInStock(q.stock))||srcs.map(k=>r.sources[k]).find(q=>q.stock)||first).stock||'';
 return {model:name(first),mileage:first.mileage==null?'':Number(first.mileage),stock:String(stock),price:first.price_cents==null?'':Number(first.price_cents),status:statusText(r)};};
function cleanupFieldChanges(){const now=Date.now();for(const [vin,entry] of recentFieldChanges){if(!entry||entry.until<=now)recentFieldChanges.delete(vin);}}
function scheduleFieldFlashCleanup(){clearTimeout(fieldFlashTimer);cleanupFieldChanges();if(!recentFieldChanges.size)return;
 const next=Math.min(...[...recentFieldChanges.values()].map(v=>v.until));
 fieldFlashTimer=setTimeout(()=>{cleanupFieldChanges();render();},Math.max(80,next-Date.now()+60));}
function captureFieldChanges(previous,next){const before=new Map((previous?.vehicles||[]).map(v=>[v.vin,v]));const now=Date.now();
 for(const vehicle of (next?.vehicles||[])){const prior=before.get(vehicle.vin);if(!prior)continue;const a=compareSnapshot(prior),b=compareSnapshot(vehicle),changed=[];
  for(const key of Object.keys(b))if(String(a[key])!==String(b[key]))changed.push(key);
  if(changed.length)recentFieldChanges.set(vehicle.vin,{fields:new Set(changed),until:now+4500});
 }
 cleanupFieldChanges();scheduleFieldFlashCleanup();}
const fieldUpdated=(vin,key)=>{const entry=recentFieldChanges.get(vin);if(!entry)return false;if(entry.until<=Date.now()){recentFieldChanges.delete(vin);return false;}return entry.fields.has(key);};

function hideToast(){clearTimeout(toastTimer);const n=$('toast');n.classList.remove('shown');}
function installScanDockClose(){const dock=$('scan-dock');if(!dock||dock.querySelector('.scan-dock-close'))return;const btn=document.createElement('button');btn.type='button';btn.className='scan-dock-close';btn.setAttribute('aria-label','Close scan status');btn.textContent='×';btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();scanDockEnabled=false;dock.hidden=true;});dock.append(btn);}
// All protected Marketplace endpoints (GET and POST) require the local session token.
// A restarted Marketplace server rotates that token, so renew once after a 403.
async function api(path,body){
 const bootstrap=path==='/api/bootstrap';
 const options=()=>body===undefined
  ?{headers:csrf&&!bootstrap?{'X-SalesmanHub-Token':csrf}:{},cache:'no-store'}
  :{method:'POST',headers:{'Content-Type':'application/json','X-SalesmanHub-Token':csrf},body:JSON.stringify(body)};
 let res=await fetch(path,options()),json=await res.json();
 if(!bootstrap&&res.status===403&&['session_token_required','missing_local_session_token'].includes(String(json?.error||''))){
  // The rejected request was not executed. Refresh the token and retry it once.
  const renewed=await fetch('/api/bootstrap',{cache:'no-store'});
  const session=await renewed.json();
  if(!renewed.ok||typeof session.csrf!=='string'||!session.csrf)throw Error('Marketplace session expired. Reload Marketplace to reconnect.');
  csrf=session.csrf;
  res=await fetch(path,options());json=await res.json();
 }
 if(!res.ok||json.ok===false)throw Error(json.error||`HTTP ${res.status}`);
 return json;
}
function notify(message,isError=false){clearTimeout(toastTimer);const n=$('toast');n.classList.toggle('error',isError);n.innerHTML=`<span class="toast-text">${esc(message)}</span><button type="button" class="toast-close" aria-label="Close message">×</button>`;n.querySelector('.toast-close')?.addEventListener('click',hideToast,{once:true});n.classList.add('shown');toastTimer=setTimeout(()=>n.classList.remove('shown'),4200);}
async function reload(){setState(await api('/api/state'));}
function setState(s){
 const old=state.vehicles.find(v=>v.vin===selectedVin);
 const next=s.vehicles.find(v=>v.vin===selectedVin);
 const changed=old&&next&&usedSources.some(source=>
   JSON.stringify(old.sources[source]?.images||[])!==JSON.stringify(next.sources[source]?.images||[]));
 if(changed){resetExportPreview();gallery.cache=null;}
 captureFieldChanges(state,s);state=s;render();
 if(changed){void toggleExportPreview();void refreshPhotoStatus();}
}
function render(){renderStats();renderFeeds();renderGrid();if(selectedVin)renderDetail();}
async function loadPhotoSettings(){
 try{
  const response=await fetch('/api/photo-settings',{headers:{'X-SalesmanHub-Token':csrf}});
  if(!response.ok)throw Error('Photo settings unavailable');
  let settings=await response.json();
  if(!settings.contact_number){
   let old='';try{old=localStorage.getItem('marketplace_photo_contact')||''}catch{}
   if(old.replace(/\D/g,'').length===10){
     settings=await api('/api/photo-settings',{contact_number:old,auto_replace:true});
   }
  }
  globalPhotoSettings={contact_number:settings.contact_number||'',auto_replace:Boolean(settings.auto_replace)};
 }catch(e){notify('Photo settings unavailable: '+e.message,true)}
}
function installPhotoSettings(){
 const host=document.querySelector('.header-buttons')||document.querySelector('.intro');
 if(host&&!$('btn-photo-settings')){
  const btn=document.createElement('button');btn.type='button';btn.id='btn-photo-settings';
  btn.className='btn secondary';btn.textContent='⚙ Photo settings';btn.dataset.photoSettingsOpen='1';host.append(btn);
 }
 if(!$('photo-settings-overlay')){
  const modal=document.createElement('div');modal.id='photo-settings-overlay';modal.className='overlay';modal.hidden=true;
  modal.innerHTML=`<button class="overlay-dim" type="button" data-photo-settings-close aria-label="Close photo settings"></button>
    <section class="modal photo-settings-modal" role="dialog" aria-modal="true" aria-labelledby="photo-settings-title">
    <div class="photo-settings-head"><div><div class="eyebrow">GLOBAL PHOTO WORKFLOW</div><h2 id="photo-settings-title">Marketplace photo settings</h2></div><button type="button" class="close" data-photo-settings-close aria-label="Close">×</button></div>
    <form id="photo-settings-form" class="import-form"><label>Default contact phone number
    <input id="photo-settings-number" type="tel" inputmode="tel" maxlength="20" autocomplete="tel" placeholder="337-366-0674"></label>
    <label class="check-row"><input id="photo-settings-auto" type="checkbox"><span>Automatically prepare separate copies with my number when Hampton's contact sticker is recognized.</span></label>
    <p class="muted">One setting for every used vehicle. Runs locally without paid AI calls. Originals never change. Unknown banners are excluded from Facebook export.</p>
    <div class="photo-settings-footer"><button class="btn secondary" type="button" data-photo-settings-close>Cancel</button><button class="btn primary" type="submit">Save photo settings</button></div></form></section>`;
  document.body.append(modal);
  $('photo-settings-form').addEventListener('submit',async e=>{
   e.preventDefault();const value=$('photo-settings-number').value;
   const digits=value.replace(/\D/g,'');if(digits&&digits.length!==10)return notify('Enter a 10-digit number.',true);
   try{
    const saved=await api('/api/photo-settings',{contact_number:digits,auto_replace:$('photo-settings-auto').checked});
    globalPhotoSettings={contact_number:saved.contact_number,auto_replace:saved.auto_replace};
    try{localStorage.setItem('marketplace_photo_contact',saved.contact_number)}catch{}
    $('photo-settings-overlay').hidden=true;if(selectedVin)renderDetail();
    notify('Photo settings saved. Existing photos are preparing in the background.');
   }catch(err){notify('Could not save photo settings: '+err.message,true)}
  });
 }
 document.addEventListener('click',e=>{
  if(e.target.closest('[data-photo-settings-open]')){
   e.preventDefault();e.stopPropagation();
   $('photo-settings-number').value=globalPhotoSettings.contact_number;
   $('photo-settings-auto').checked=globalPhotoSettings.auto_replace;
   $('photo-settings-overlay').hidden=false;
  }
  if(e.target.closest('[data-photo-settings-close]')){
   e.preventDefault();e.stopPropagation();$('photo-settings-overlay').hidden=true;
  }
 },true);
}
function renderStats(){const used=state.vehicles.filter(isUsedVehicle);const cards=[['Trade-ins',used.filter(isTradeInVehicle).length],['Used vehicles',used.length],['Link issues',Object.keys(cleanupIssues).length],['Listing alerts',used.filter(r=>r.draft?.review_state).length],['Confirmed on FB',used.filter(r=>r.listed).length]];
 $('stats').innerHTML=cards.map(([k,n])=>`<article class="stat"><div class="label">${esc(k)}</div><div class="number">${Number(n||0)}</div></article>`).join('');}
function renderFeeds(){const names=usedSources;$('feed-status').innerHTML=names.map(n=>{const f=state.feeds[n];return `<span class="feed-chip ${f&&!f.last_complete?'error':''}" title="${esc(f?.last_import||'Not imported')}">${esc(sourceLabels[n])} • ${f?`${f.last_accepted} loaded${f.last_complete?'':' (partial)'}`:'No import'}</span>`;}).join('');}
const inventoryFilterIds=['inventory-min','inventory-max','inventory-age','inventory-year','inventory-sort'];
const inventorySortPairs=[
 ['refreshed-old','refreshed-new'],['price-low','price-high'],['age-new','age-old'],['year-old','year-new'],['az','za']
];
function renderInventorySortDirection(){
 const sort=$('inventory-sort').value;
 for(const [index,id] of ['inventory-sort-up','inventory-sort-down'].entries()){
  const button=$(id);
  button.setAttribute('aria-pressed',String(inventorySortPairs.some(pair=>pair[index]===sort)));
  button.title=sort==='priority'?(index===0?'Price: low to high':'Price: high to low'):(index===0?'Sort ascending':'Sort descending');
 }
}
const ageInDays=(r,now=Date.now())=>{
 const first=Date.parse(r.first_seen);
 return Number.isFinite(first)?Math.max(0,Math.floor((now-first)/86400000)):null;
};
function lastRefreshedAt(car){
 const dates=usedSources.map(source=>Date.parse(car.sources?.[source]?.last_seen)).filter(Number.isFinite);
 return dates.length?Math.max(...dates):null;
}
const inventoryNames=new Intl.Collator('en-US',{numeric:true,sensitivity:'base'});
function getVisible(){
 const [minInput,maxInput,age,year,sort]=inventoryFilterIds.map(id=>$(id).value);
 const min=minInput===''?null:Math.round(Number(minInput)*100);
 const max=maxInput===''?null:Math.round(Number(maxInput)*100);
 const needle=search.trim().toLowerCase();
 const now=Date.now();
 const rows=state.vehicles.filter(r=>{
  if(!isUsedVehicle(r))return false;
  if((tab==='trade'||tab==='all')&&cleanupIssues[r.vin]?.probable_out_of_stock)return false;
  if(tab==='trade'&&(!isTradeInVehicle(r)||r.listed))return false;
  if(tab==='drafts'&&!(r.draft&&!['USER_CONFIRMED_PUBLISHED','USER_CONFIRMED_REMOVED'].includes(r.draft.status)))return false;
  if(tab==='published'&&!r.listed)return false;
   if(tab==='outstock'&&( !cleanupIssues[r.vin] || r.listed || isPendingCleanupVin(r.vin)))return false;
  if(year&&String(r.year)!==year)return false;
  return `${r.vin} ${r.make} ${r.model} ${r.year} ${Object.values(r.sources).map(s=>s.stock).join(' ')}`.toLowerCase().includes(needle);
 }).map(car=>({car,age:ageInDays(car,now),price:cardDealerPrice(car).cents}));
 const matching=rows.filter(row=>{
  if((min!==null||max!==null)&&row.price===null)return false;
  if(min!==null&&row.price<min||max!==null&&row.price>max)return false;
  if(age==='')return true;
  if(row.age===null)return false;
  if(age==='0')return row.age===0;
  if(age==='7')return row.age<=7;
  if(age==='30')return row.age>=8&&row.age<=30;
  return row.age>=31;
 });
 const compareKnown=(a,b,direction)=>a===null?(b===null?0:1):b===null?-1:(a-b)*direction;
 const priority=(a,b)=>tab==='outstock'?cleanupRank(a)-cleanupRank(b):
  Number(isTradeInVehicle(b))-Number(isTradeInVehicle(a))||Number(alertNeeded(b))-Number(alertNeeded(a))||b.year-a.year;
 return matching.sort((a,b)=>{
  if(tab==='trade'){const ready=Number(!!b.car.posting_ready?.ready)-Number(!!a.car.posting_ready?.ready);if(ready)return ready;}
  let order=0;
  if(sort==='refreshed-new'||sort==='refreshed-old')order=compareKnown(lastRefreshedAt(a.car),lastRefreshedAt(b.car),sort==='refreshed-new'?-1:1);
  else if(sort==='price-low'||sort==='price-high')order=compareKnown(a.price,b.price,sort==='price-low'?1:-1);
  else if(sort==='age-new'||sort==='age-old')order=compareKnown(a.age,b.age,sort==='age-new'?1:-1);
  else if(sort==='year-new'||sort==='year-old')order=(a.car.year-b.car.year)*(sort==='year-new'?-1:1);
  else if(sort==='az'||sort==='za')order=inventoryNames.compare(`${a.car.make} ${a.car.model}`,`${b.car.make} ${b.car.model}`)*(sort==='az'?1:-1);
  else order=priority(a.car,b.car);
  return order||a.car.vin.localeCompare(b.car.vin);
 }).map(row=>row.car);
}
function renderInventoryCounts(){
 renderInventorySortDirection();
 const used=state.vehicles.filter(isUsedVehicle);
 const years=[...new Set(used.map(r=>r.year).filter(Number.isInteger))].sort((a,b)=>b-a);
 const picker=$('inventory-year'),selected=picker.value;
 const yearOptions='<option value="">All years</option>'+years.map(year=>`<option value="${year}">${year}</option>`).join('');
 if(picker.dataset.years!==years.join(',')){
  picker.innerHTML=yearOptions;
  picker.value=years.some(year=>String(year)===selected)?selected:'';
  picker.dataset.years=years.join(',');
 }
 $('inventory-loaded').textContent=tab==='trade'?`${used.filter(isTradeInVehicle).length.toLocaleString()} trade-ins loaded`:`${used.length.toLocaleString()} vehicles loaded`;
 const toPost=$('inventory-to-post'),unposted=used.filter(r=>isTradeInVehicle(r)&&!r.listed&&!cleanupIssues[r.vin]?.probable_out_of_stock).length;
 toPost.hidden=tab!=='trade';
 toPost.textContent=`${unposted.toLocaleString()} to post`;
}
// R59: Always show an actual dealer price instead of replacing it with a
// generic cross-source warning. Price disagreement still remains a backend
// approval hold. Prefer a valid selected source or the freshest observed
// source; do not invent a price if neither dealer supplied one.
const cardDealerPrice=r=>{
 const options=usedSources.map(source=>({source,record:r.sources?.[source]}))
   .filter(x=>Number.isSafeInteger(Number(x.record?.price_cents))&&Number(x.record.price_cents)>0);
 if(!options.length)return {label:money(null),cents:null,warning:'',conflict:false};
 const preferred=r.draft?.source;
 const selected=options.find(x=>x.source===preferred)||[...options].sort((a,b)=>
   Date.parse(b.record.last_seen||'1970-01-01')-Date.parse(a.record.last_seen||'1970-01-01'))[0];
 const prices=new Set(options.map(x=>Number(x.record.price_cents)));
 const conflict=prices.size>1;
 return {label:money(selected.record.price_cents),cents:Number(selected.record.price_cents),conflict,
   warning:conflict?'Saved dealer source prices differ. Refresh both dealer pages and verify before posting.':''};
};
function renderGrid(){updateDeleteListingBadge();const readyButton=document.querySelector('[data-act="get-trade-ready"]');if(readyButton)readyButton.hidden=tab!=='trade';renderInventoryCounts();const a=getVisible();$('inventory-matches').textContent=`${Math.min(a.length,vehicleVisible).toLocaleString()} of ${a.length.toLocaleString()} shown`;$('section-title').textContent=labels[tab];$('vehicle-grid').classList.remove('cleanup-list');$('crumb-view').textContent=labels[tab].toUpperCase();document.querySelectorAll('[data-tab]').forEach(e=>{e.classList.toggle('selected',e.dataset.tab===tab);e.setAttribute('aria-current',e.dataset.tab===tab?'page':'false');});
 if(tab==='deletelisting')return renderDeleteListing();
 if(!a.length&&tab==='trade'&&state.vehicles.some(isUsedVehicle)){
  $('vehicle-more-row').hidden=true;
  $('vehicle-grid').innerHTML=`<div class="empty"><strong>${search?'No matching unposted vehicles':'No unposted used vehicles'}</strong><p>${search?'Clear or change the search.':'Run Scan Inventory to look for newly added units.'}</p></div>`;
  return;
 }
 if(!a.length&&tab==='outstock'){
  $('vehicle-more-row').hidden=true;
  $('vehicle-grid').innerHTML=`<div class="empty"><strong>${cleanupError?'Could not load link checks':search?'No matching link issues':'No link issues found'}</strong><p>${esc(cleanupError||'Run Verify Inventory and Check Facebook under More scans to update this view.')}</p></div>`+removedRecoveryHtml();
  return;
 }
 if(!a.length){$('vehicle-more-row').hidden=true;$('vehicle-grid').innerHTML=`<div class="empty"><strong>${state.vehicles.some(isUsedVehicle)?'No matching used vehicles':'Ready for your first used inventory scan'}</strong><p>${state.vehicles.some(isUsedVehicle)?'Adjust your filters to see more used vehicles.':'Scan Toyota Used and Mitsubishi Used in the background.'}</p><button class="btn secondary" data-act="open-import">Import inventory</button></div>`;return;}
 const shown=a.slice(0,vehicleVisible);$('vehicle-more-row').hidden=shown.length===a.length;$('vehicle-show-more').textContent=`Load ${Math.min(60,a.length-shown.length)} more used vehicles (${a.length-shown.length} remaining)`;
 $('vehicle-grid').innerHTML=shown.map(r=>{const first=primary(r),srcs=Object.keys(r.sources).filter(s=>usedSources.includes(s)),imageInfo=photoInfo(r),photoUrl=imageInfo.url,priceInfo=cardDealerPrice(r),price=priceInfo.label;
 const stock=(srcs.map(k=>r.sources[k]).find(q=>isTradeInStock(q.stock))||srcs.map(k=>r.sources[k]).find(q=>q.stock)||first).stock||'MISSING';
 const mileage=first.mileage!=null&&Number.isFinite(Number(first.mileage))?Number(first.mileage).toLocaleString('en-US')+' mi':'Mileage pending';
 const refreshing=refreshingVin===r.vin;
 const facebookLink=r.listed?safeFacebookUrl(r.draft?.published_url||''):'';
 const issue=cleanupIssues[r.vin],age=ageInDays(r);
 return `<article class="vehicle-card" data-vin="${esc(r.vin)}" ${tab==='outstock'?`data-cleanup-vin="${esc(r.vin)}"`:''} tabindex="0" role="button" aria-label="Open ${esc(name(first))}">
  <div class="vehicle-photo"><span class="photo-empty" aria-hidden="true">▱</span><span class="photo-failed-note">Photo pending review or download</span>${photoUrl&&localOrHttps(photoUrl)?`<img loading="lazy" alt="${esc(name(first))}" src="${esc(photoUrl)}">`:''}${isTradeInVehicle(r)?'<span class="photo-label trade-pill trade-photo-badge">★ TRADE-IN PRIORITY</span>':''}</div>
  <div class="vehicle-main">
    <div class="card-stock-row"><strong class="stock-number ${fieldUpdated(r.vin,'stock')?'flash-green':''}">STOCK ${esc(stock)}</strong><strong class="card-mileage ${fieldUpdated(r.vin,'mileage')?'flash-green':''}" title="Mileage from dealer listing">${esc(mileage)}</strong></div>
    <div class="vehicle-card-head"><h3 class="${fieldUpdated(r.vin,'model')?'flash-green':''}">${esc(name(first))}</h3><div class="price ${fieldUpdated(r.vin,'price')?'flash-green':''}" title="${esc(priceInfo.warning||'Price from saved dealer record. Check live price before posting.')}">${esc(price)}${priceInfo.conflict?'<span class="price-review-dot" aria-label="Review differing dealer records" title="Dealer records disagree; refresh to verify"> •</span>':''}</div></div>
    ${tab==='trade'?`<div class="inventory-card-age"><strong>${r.posting_ready?.ready?'✓ Ready':'Not ready'}</strong>${r.posting_ready?.ready?'':' · '+esc(r.posting_ready?.reason||'Readiness check pending')}</div>`:''}
    <div class="inventory-card-age" title="Time since this VIN was first saved in LotRadar">${age===null?'Load date unavailable':age===0?'Loaded less than 1 day ago':`Loaded ${age} day${age===1?'':'s'} ago`}</div>
    <div class="inventory-card-age">${usedSources.filter(src=>r.sources?.[src]).map(src=>`${esc(sourceLabels[src])}: ${r.last_successful_refresh?.[src]?'Refreshed '+esc(new Date(r.last_successful_refresh[src]).toLocaleString()):'Last successful refresh not recorded'}`).join('<br>')}</div>
    <div class="vehicle-vin-row"><span>VIN</span><strong title="${esc(r.vin)}">${esc(r.vin)}</strong></div>
    ${facebookLink?'<div class="vehicle-facebook-state">✓ Tracked on Facebook</div>':''}
    ${issue?`<div class="vehicle-dealer-warning"><strong>⚠ ${issue.probable_out_of_stock?'Possibly unavailable · verify at dealership':'Needs availability review'}</strong>${cleanupIssueText(issue).map(line=>`<div>${esc(line)}</div>`).join('')}</div>`:''}
    <div class="vehicle-card-actions">
      <button class="card-photos" type="button" data-photos-vin="${esc(r.vin)}" title="Export screened vehicle photos">↓ Download photos</button>
      <button class="card-refresh" type="button" data-refresh-vin="${esc(r.vin)}" ${refreshing?'disabled':''} title="Refresh this VIN in the background" aria-label="Refresh stock ${esc(stock)}">${refreshing?'⏳ Refreshing…':'⟳ Refresh this vehicle'}</button>
      ${facebookLink?`<a class="btn secondary card-facebook-open" data-card-facebook href="${esc(facebookLink)}" target="_blank" rel="noopener noreferrer" aria-label="Open tracked Facebook listing for ${esc(name(first))}">Open Facebook ↗</a>`:''}
      ${tab==='outstock'?`<button type="button" class="btn ghost fb-cleanup-move" data-outstock-remove="${esc(r.vin)}" title="Only after you have verified the vehicle is unavailable at the dealership">Confirm out of stock &amp; remove</button>`:''}
    </div>
  </div></article>`}).join('')+(tab==='outstock'?removedRecoveryHtml():'');document.querySelectorAll('.vehicle-photo img').forEach(img=>img.addEventListener('error',()=>{img.hidden=true}));}
function openDetail(vin){if(!state.vehicles.some(v=>v.vin===vin))return;if(selectedVin!==vin)facebookUrlEdit=null;const car=state.vehicles.find(v=>v.vin===vin);facebookCompareOpenVin=car?.draft?.published_url?vin:'';if(selectedVin!==vin)draftEditBuffer=null;resetExportPreview();selectedVin=vin;gallery={vin,source:'',index:0,cache:null,pictures:[],initial:true};$('detail-overlay').hidden=false;renderDetail();void toggleExportPreview();void refreshPhotoStatus();void startPhotoAutoFetch(vin);if(car?.draft?.published_url)void loadFacebookComparison();}
function closeOverlay(which){
 if(which==='chrome-bridge'){$('chrome-pair-key').value='';$('chrome-pair-controls').hidden=true;}
 $(which+'-overlay').hidden=true;
 if(which==='detail'){resetExportPreview();facebookUrlEdit=null;selectedVin='';gallery={vin:'',source:'',index:0,cache:null,pictures:[],initial:true};}
 if(which==='scan-console'){
  // Hiding the dialog never stops the server-side scan or its polling timer.
  scanDockEnabled=Boolean(lastScanJob && (lastScanJob.running||(lastScanJob.completed||[]).length));
  updateScanDock(lastScanJob);
 }
}
function openScanConsole(){
 scanDockEnabled=false;
 $('scan-dock').hidden=true;
 $('scan-console-overlay').hidden=false;
}
function updateScanDock(job){
 const dock=$('scan-dock');if(!dock)return;
 const hasScan=Boolean(job&&(job.running||(job.completed||[]).length));
 dock.hidden=!scanDockEnabled||!hasScan||!$('scan-console-overlay').hidden;
 if(!hasScan)return;
 const completed=(job.completed||[]).length,total=(job.sources||[]).length||2,failed=(job.errors||[]).length;
 const percent=job.running?Math.min(99,Math.round(completed/total*100)):100;
 dock.classList.toggle('failed',!job.running&&failed>0);
 dock.classList.toggle('running',!!job.running);
 $('scan-dock-title').textContent=job.running?'Scanning dealer websites':failed?`Scan finished · ${failed} failed`:'Dealer scan finished';
 $('scan-dock-subtitle').textContent=job.running?`${completed}/${total} sections completed · Click to reopen`:'Click to review scan output';
 $('scan-dock-percent').textContent=(!job.running&&failed)?'FAILED':percent+'%';
}

const selectedRecord=r=>{const pick=$('draft-source');const name=pick?.value||r.draft?.source||Object.keys(r.sources)[0];return r.sources[name]||primary(r);};
function sectionHeader(text){return `<div class="detail-block"><h3>${text}</h3>`;}

// Polling/progress re-renders must never steal focus, caret, selection or scroll from a field the user is typing in.
function captureEditState(){
 const el=document.activeElement,drawer=$('drawer-content');
 const st={drawerTop:drawer?drawer.scrollTop:0,id:'',start:0,end:0,dir:'none',top:0};
 if(el&&el.id&&drawer&&drawer.contains(el)&&el.matches('input,textarea,select')){
  st.id=el.id;st.top=el.scrollTop||0;
  try{st.start=el.selectionStart;st.end=el.selectionEnd;st.dir=el.selectionDirection||'none';}catch{}
 }
 return st;
}
function restoreEditState(st){
 const drawer=$('drawer-content');if(!st||!drawer)return;
 if(st.id){const el=document.getElementById(st.id);if(el){el.focus({preventScroll:true});
  try{if(st.start!=null&&el.setSelectionRange)el.setSelectionRange(st.start,st.end,st.dir);}catch{}
  el.scrollTop=st.top;}}
 drawer.scrollTop=st.drawerTop;
}
function renderDetail(){
 const r=state.vehicles.find(v=>v.vin===selectedVin);
 if(!r){closeOverlay('detail');return;}
 const first=primary(r),d=r.draft;
 const chosen=d?.source&&r.sources[d.source]?r.sources[d.source]:first;
 $('drawer-title').textContent=`${first.stock?'#'+first.stock+' · ':''}${name(first)}`;
 if(draftEditBuffer && d&&(draftEditBuffer.vin!==r.vin||draftEditBuffer.updated_at!==d.updated_at||draftEditBuffer.snapshot_hash!==d.snapshot_hash))draftEditBuffer=null;
 const title=d?.description===trackedPlaceholder?collapseRepeatTrim(d?.title||name(first),chosen?.trim||first.trim):(draftEditBuffer?.title??d?.title??name(first));
 const description=draftEditBuffer?.description??d?.description??'';
 const isPublished=d?.status==='USER_CONFIRMED_PUBLISHED',isRemoved=d?.status==='USER_CONFIRMED_REMOVED';
 const isLocked=isPublished||isRemoved;
 $('prepare-facebook-form').hidden=!d||isLocked;
 const gallerySource=(r.sources.toyota_used?.images?.length?'toyota_used':r.sources.mitsubishi_used?.images?.length?'mitsubishi_used':r.sources.toyota_used?'toyota_used':'mitsubishi_used');
 if(gallery.source!==gallerySource){resetExportPreview();gallery.source=gallerySource;gallery.index=0;gallery.cache=null;gallery.initial=true;}
 const record=r.sources[gallerySource]||chosen;
 const originals=record?.images||[];
 const cached=(gallery.cache?.vin===r.vin&&gallery.cache.source===gallerySource)?gallery.cache:null;
 const graphics=new Set(record?.photo_graphic_indices||[]),bySource=new Map();
 originals.forEach((url,index)=>{
   const item=cached?.photos?.find(p=>p.index===index);
   if(graphics.has(index)||item?.category==='graphic'||item?.duplicate_of!=null||isBrandGraphic(url)||!isDealerPreviewUrl(url))return;
   const picture={index,url,src:item?.downloaded?`/api/photo?vin=${encodeURIComponent(r.vin)}&source=${encodeURIComponent(gallerySource)}&index=${index}`:url,
    exportReady:Boolean(item?.downloaded&&!item?.excluded),branded:item?.quality_reason==='possible_dealership_banner',
    lowResolution:Boolean(item?.downloaded&&item?.width&&item?.height&&item.width*item.height<600000)};
   const identity=imageIdentity(url),previous=bySource.get(identity);
   if(!previous||photoResolutionScore(url,item)>photoResolutionScore(previous.url,cached?.photos?.find(p=>p.index===previous.index)))bySource.set(identity,picture);
 });
 const originalPictures=[...bySource.values()].sort((a,b)=>a.index-b.index);
 const previewActive=true;
 const previewReady=exportPreview.vin===r.vin&&exportPreview.source===gallerySource&&!exportPreview.loading&&Boolean(exportPreview.revision);
 const pictures=(previewReady?exportPreview.photos.map((item,i)=>({
   index:i,url:item.url,src:exportPreview.urls.get(i)||'',kind:item.kind,cover:item.cover,
   title:item.kind==='dedication'?'Dedication photo':item.cover?'Business-card cover / clean car photo':'Export vehicle photo'
 })) :[]);
 gallery.pictures=pictures;
 const cover=record?.photo_cover_index;
 if(gallery.initial&&!previewActive){const index=pictures.findIndex(pic=>pic.index===cover);gallery.index=index>=0?index:0;gallery.initial=false;}
 gallery.index=Math.max(0,Math.min(gallery.index,Math.max(0,pictures.length-1)));
 const active=pictures[gallery.index],main=active?.src||'';
 if(previewReady&&!main&&!exportPreview.failed.has(gallery.index))void loadExportPreviewFrame(gallery.index);
 // <photo-grid-thumbnails>
 // Gallery order. A number badge shows each selected photo's click-order position.
 const selOrder=selectionActive()?orderedPhotoKeys():[];
 const thumbnails=pictures.map((pic,i)=>{const key=exportFrameKey(pic),order=selOrder.indexOf(key),checked=order>=0;
  return `<div class="photo-pick ${checked?'':'unselected'}"><button class="gallery-thumb ${gallery.index===i?'chosen':''}" type="button" data-gallery-index="${i}" aria-pressed="${checked}" aria-label="Photo ${i+1}${checked?', selected '+(order+1):', not selected'} · ${pic.title}" title="${esc(pic.title)}">${pic.src?`<img src="${esc(pic.src)}" loading="lazy" alt="Photo ${i+1}">`:`<span class="preview-thumb-pending ${exportPreview.failed.has(i)?'preview-thumb-failed':''}">${exportPreview.failed.has(i)?'Retry photo':exportPreview.pending.has(i)?'Preparing':'Queued'}</span>`}<span>${String(i+1).padStart(2,'0')}</span>${checked?`<b class="photo-order-badge" aria-hidden="true">${String(order+1).padStart(2,'0')}</b>`:''}</button>${previewReady?`<label><input type="checkbox" data-photo-check="${i}" aria-label="Use photo ${String(i+1).padStart(2,'0')} on Facebook" ${checked?'checked':''} ${!selectionActive()?'disabled':''}> ${checked?'✓ '+String(order+1).padStart(2,'0'):'—'}</label>`:''}</div>`;}).join('');
 // </photo-grid-thumbnails>
const imageAudit=photoProgressPanel();
 const modelValue=name(first),mileageValue=first.mileage!=null&&Number.isFinite(Number(first.mileage))?Number(first.mileage).toLocaleString('en-US'):'',stockValue=chosen.stock||first.stock||'';
 const fields=[['model','Model',modelValue],['mileage','Mileage',mileageValue],['stock','Stock',stockValue]];
 const quick=fields.map(([key,label,value])=>`<div class="copy-field ${fieldUpdated(r.vin,key)?'flash-green':''}"><label for="quick-${key}">${label}</label><div class="copy-control"><input type="text" id="quick-${key}" class="quick-select" value="${esc(value)}" readonly title="Click to select ${label.toLowerCase()}"><button class="btn ghost" type="button" data-act="copy-${key}" ${!value?'disabled':''} aria-label="Copy ${label}">⧉ Copy</button></div></div>`).join('');
 const sources=Object.entries(r.sources).filter(([k])=>usedSources.includes(k)).map(([k,q])=>`<option value="${k}" ${d?.source===k?'selected':''}>${esc(sourceLabels[k])}</option>`).join('');
 let posting='';
 if(!d){
  posting=`<div class="fb-link-inline"><label for="existing-fb-url">Facebook Marketplace link</label><div class="fb-link-row"><input id="existing-fb-url" type="url" placeholder="https://www.facebook.com/marketplace/item/..."><button class="btn secondary" type="button" data-act="track-existing">Link Facebook</button></div><label class="fb-ack"><input type="checkbox" id="existing-confirm">This is my existing listing</label></div>`;
 }else if(!isLocked){
  posting=`<div class="fb-link-inline"><label for="published-url">Facebook Marketplace link</label><div class="fb-link-row"><input id="published-url" type="url" placeholder="Paste your published Facebook URL"><button class="btn secondary" type="button" data-act="confirm-published">Link Facebook</button></div><label class="fb-ack"><input id="published-confirm" type="checkbox">I personally published this listing</label></div>`;
 }else if(isPublished){
  const edit=facebookUrlEdit?.vin===r.vin?facebookUrlEdit:null;
  const editable=Boolean(edit),displayUrl=editable?edit.url:d.published_url;
  posting=`<div class="fb-url-field"><label for="tracked-facebook-url">Facebook Marketplace</label>
   <div class="fb-url-control ${editable?'unlocked':''}">
    <input id="tracked-facebook-url" type="url" inputmode="url" spellcheck="false" autocomplete="off" maxlength="2048" value="${esc(displayUrl)}" ${editable?'':'readonly'} aria-label="Facebook Marketplace listing URL" title="${editable?'Edit URL, then click the unlocked padlock to save':'Locked. Click the padlock to edit this link'}">
    <button class="fb-url-lock" type="button" data-act="toggle-fb-url" aria-label="${editable?'Save and lock Facebook URL':'Unlock Facebook URL for editing'}" aria-pressed="${editable?'true':'false'}" title="${editable?'Save and lock':'Unlock to edit'}">${editable?'🔓':'🔒'}</button>
   </div>
   <div class="fb-url-foot"><a href="${esc(d.published_url)}" target="_blank" rel="noopener noreferrer">Open Facebook ↗</a></div>
  </div>`;
 }
 const photoSourceChoices=usedSources.filter(k=>r.sources[k]);
 const dealerLinks=photoSourceChoices.map(source=>{
  const url=dealerLink(source,r.sources[source]);
  return url?`<a class="btn secondary dealer-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="Dealer facts are verified separately from photo export">Open ${source==='toyota_used'?'Toyota':'Mitsubishi'} dealer ↗</a>`:'';
 }).join('');
 const bothDealers=r.sources.toyota_used&&r.sources.mitsubishi_used;
 const specLabels={exterior_color:'Exterior',interior_color:'Interior',engine:'Engine',transmission:'Transmission',drivetrain:'Drivetrain',fuel_type:'Fuel',body_style:'Body style'};
 const specs=Object.entries(chosen.specifications||{}).filter(([key])=>Object.hasOwn(specLabels,key));
 const equipment=chosen.features||[];
 const dealerFacts=specs.length||equipment.length?`<details class="detail-block"><summary>Dealer specs &amp; equipment</summary>
  ${specs.length?`<dl>${specs.map(([key,value])=>`<dt>${specLabels[key]}</dt><dd>${esc(value)}</dd>`).join('')}</dl>`:''}
  ${equipment.length?`<ul>${equipment.map(value=>`<li>${esc(value)}</li>`).join('')}</ul>`:''}</details>`:'';
 const dealerComparison=bothDealers?`<div class="dealer-source-compare">Both dealers: same VIN · Price ${r.sources.toyota_used.price_cents===r.sources.mitsubishi_used.price_cents?'matches':'differs / verify'} · Mileage ${r.sources.toyota_used.mileage===r.sources.mitsubishi_used.mileage?'matches':'differs / verify'}. Comparison only; Toyota photos preferred.</div>`:'';
 const listingDeleteAction=isPublished?`<button class="btn ghost fb-quick-delete" type="button" data-act="trash-listing" title="Move this local Facebook tracking record to 30-day Trash. Facebook post is not deleted">🗑 Delete listing</button>`:'';
 const draftActions=d?.description===trackedPlaceholder?'':d?`<div class="draft-action-row"><button class="btn primary" type="button" data-act="copy-full-post">⧉ Copy full post</button><button class="btn secondary" type="button" data-act="copy-description">Copy description</button><button class="btn secondary" type="button" data-act="copy-title">Copy title</button></div>`:'';
 const sourceEntries=Object.entries(r.sources).filter(([key])=>usedSources.includes(key));
 const draftSourceInput=!d?(sourceEntries.length===1
  ?`<input id="draft-source" type="hidden" value="${esc(sourceEntries[0][0])}">`
  :`<label class="photo-source-compact draft-source-inline">Dealership <select id="draft-source" aria-label="Draft dealership source">${sources}</select></label>`):'';
 // Tracked Facebook listings display descriptions only inside the comparison table, not twice.
 const descriptionArea=d?.description===trackedPlaceholder?
   `<input id="draft-title" type="hidden" value="${esc(title)}"><input id="draft-description" type="hidden" value="${esc(d.description)}">`:
  d?`<div class="description-editor"><div class="description-heading"><label for="draft-description">${d.copy_saved?'Saved listing description':'AI / Listing Description'}</label><span id="ai-preview-status" class="ai-inline-status" role="status" hidden></span></div><textarea id="draft-description" maxlength="5000" spellcheck="true" ${isLocked?'readonly':''}>${esc(description)}</textarea><div class="description-controls">${isLocked?`<input type="hidden" id="draft-title" value="${esc(title)}">`:''}${!isLocked?`<button class="btn secondary" type="button" data-act="ai-draft">✨ Generate AI description</button><button class="btn secondary" type="button" data-act="save-draft">Save description</button><details class="draft-tools"><summary>More editing options</summary><div class="field"><label for="draft-title">Editable Facebook title</label><input id="draft-title" type="text" maxlength="130" value="${esc(title)}"></div><button class="btn ghost" data-act="rebuild-draft" type="button">Rebuild from dealer facts</button></details>`:''}<span class="draft-saved-state" id="copy-save-state">${d.copy_saved?'Saved':'Unsaved edits stay here until saved'}</span></div></div>`:
  `<div class="empty-draft-note">Generate your first listing draft to copy the description.</div>`;
 const selectedDealer=d?r.sources[d.source]:null;
 const fieldsToEnter=selectedDealer?[
  !selectedDealer.price_cents?'price':'',
  selectedDealer.mileage==null?'mileage':''
 ].filter(Boolean):[];
 const draftFieldNotice=d&&!isLocked&&fieldsToEnter.length
  ?`<p class="muted">Enter ${fieldsToEnter.join(' and ')} on Facebook. The dealer record has no value for ${fieldsToEnter.length===1?'this field':'these fields'}.</p>`:'';

 const stockConfirmation=d&&!isLocked&&selectedDealer&&selectedDealer.fresh&&!selectedDealer.missing_count&&
   !['available','sold','unavailable'].includes(selectedDealer.availability)
   ?`<div class="fb-review-confirm"><button class="btn secondary" type="button" data-act="confirm-availability">Confirm current stock</button>
      <small>Confirm only after checking this vehicle with ${esc(sourceLabels[d.source])}.</small></div>`:'';
 const fbComparison=d?.published_url?`<details class="fb-compare" ${facebookCompareOpenVin===r.vin?'open':''}>
  <summary>Facebook vs Dealer <span class="fb-compare-small">Read-only comparison</span></summary>
  <div class="fb-compare-inner"><div class="fb-compare-head"><span>Current captured Facebook details compared with Hampton. Use Refresh vehicle to check both sites.</span></div>
   <p class="muted" id="fb-auto-status" role="status" aria-live="polite">${esc(facebookAutoStatus.get(r.vin)?.detail||'Open Chrome Reader once and enable automatic Facebook checks.')}</p>
   <div class="fb-compare-content" id="facebook-compare-content">${renderFacebookRows(facebookCompareCache.get(r.vin))}</div>
  </div></details>`:'';
 const mainAction=d?'':`<button class="btn primary" type="button" data-act="create-draft" ${sourceEntries.length?'':'disabled'}>Create listing draft →</button>`;
 const editState=captureEditState();
 $('drawer-content').innerHTML=`<div class="posting-photo-area">
  <div class="export-preview-default"><strong>Facebook photo preview</strong><span>Exact exported images · Business card + dedication #2 · ${previewReady?(exportPreview.actualSource==='mitsubishi_used'?'Mitsubishi backup':'Toyota primary'):'Toyota preferred, Mitsubishi backup'}</span></div>
 <div class="gallery-stage">${main?`<img src="${esc(main)}" alt="${esc(modelValue)} ${previewActive?'export':'source'} photo ${gallery.index+1}">`:`<span class="muted">${previewActive?(exportPreview.loading?'Preparing exact export preview…':previewReady?(exportPreview.failed.has(gallery.index)?'Photo unavailable. Select its thumbnail to retry.':'Loading exported photo…'):(exportPreview.error?esc(exportPreviewErrorText(exportPreview.error)):'No export photos ready yet.')):'No vehicle photos captured yet.'}</span>`}</div>
  ${previewReady?photoSelectionToolbar():''}
  <div class="photo-grid-heading"><button type="button" class="btn secondary" data-act="toggle-photo-grid" aria-expanded="${photoGridExpanded}" aria-controls="photo-thumbnail-grid">${photoGridExpanded?'▴ Collapse photos':'▾ Show all photos'} (${pictures.length})</button></div>
  <div class="posting-thumb-row ${photoGridExpanded?'photo-grid-row':''}"><div id="photo-thumbnail-grid" class="gallery-thumbs ${photoGridExpanded?'photo-grid-expanded':''}" aria-label="${previewActive?'Exported':'Vehicle'} photos">${thumbnails}</div><span class="photo-count">${pictures.length?`${gallery.index+1} / ${pictures.length}`:exportPreview.loading?'Preparing…':exportPreview.error?'Preview unavailable':'0 photos'}</span></div>
  ${imageAudit}
  <div class="posting-photo-tools">${active?.url&&!active.cover?`<button class="btn primary" type="button" data-act="set-cover">Set photo ${String(gallery.index+1).padStart(2,'0')} as cover</button>`:''}<button class="btn secondary" type="button" data-act="download-photo-zip" ${!selectionActive()||!orderedPhotoKeys().length||orderedPhotoKeys().length>photoSelection.limit?'disabled':''}>↓ Download ${selectionActive()?orderedPhotoKeys().length:0} photos (ZIP)</button><button class="btn secondary" type="button" data-act="open-photo-folder">Open folder</button>${dealerLinks}</div>${dealerComparison}
 </div>
 <section class="posting-workspace" aria-label="Listing copy tools"><div class="copy-workspace-head"><h3>Quick Copy</h3>${listingDeleteAction}</div><div class="quick-copy-grid">${quick}</div>
 ${draftActions}${descriptionArea}${draftFieldNotice}${dealerFacts}${stockConfirmation}${posting}${fbComparison}
 <div class="posting-footer"><button type="button" class="btn secondary" data-dismiss="detail">Close</button><div class="draft-footer-actions">${draftSourceInput}${mainAction}</div></div></section>`;
 restoreEditState(editState);
 document.querySelectorAll('#detail-overlay .gallery-stage img,#detail-overlay .gallery-thumbs img').forEach(image=>image.addEventListener('error',()=>{image.hidden=true}));
}
// R41: authorized one-time Facebook checks, never a recurring Facebook crawler.
function wakeChromeReader(){window.dispatchEvent(new CustomEvent('salesmanhub:scan-control',{detail:{action:'start'}}));}
function signalFacebookAutoCheck(){window.dispatchEvent(new Event('salesmanhub:facebook-auto-check'));}
function formatFacebookBulkStatus(result){
 const checked=(result.captured||0)+(result.failed||0),expired=result.expired||0,total=result.total||0;
 const done=total>0 && checked+expired>=total;
 return total===0?'No tracked Facebook listings to check.':
  `Facebook checked ${checked}/${total} · ${result.captured||0} captured (may be partial) · ${result.failed||0} failed${expired?' · '+expired+' expired (not read)':''}${(result.skipped||0)?' · '+result.skipped+' skipped':''}${done?' · Finished':''}`;
}
async function refreshFacebookBulkStatus(){
 if(facebookBulkPending)return;
 facebookBulkPending=true;
 try{
  const response=await fetch('/api/facebook-auto-bulk-status',{headers:{'X-SalesmanHub-Token':csrf},cache:'no-store'});
  if(!response.ok)throw Error('Bulk status unavailable');
  const result=await response.json();const box=$('fb-bulk-progress'),button=$('btn-facebook-scan');
  if(box){box.hidden=!result.total&&!result.skipped;box.textContent=formatFacebookBulkStatus(result);}
  if(button){button.disabled=Boolean(result.active||checkingListingLinks);button.textContent=result.active?`Checking Facebook ${result.checked||0}/${result.total||0}`:checkingListingLinks?'Checking dealer links…':'↻ Check Facebook';}
  const cancel=$('btn-facebook-cancel');if(cancel)cancel.hidden=!result.active;
  const retry=$('btn-facebook-retry');if(retry)retry.hidden=Boolean(result.active)||!result.retryable;
  const captured=Number(result.captured||0);
  if(captured>facebookBulkLastCaptured&&selectedVin&&facebookCompareOpenVin===selectedVin){
    facebookCompareCache.delete(selectedVin);
    void loadFacebookComparison();
  }
  facebookBulkLastCaptured=captured;
  if(result.active&&!facebookBulkStatusTimer){facebookBulkStatusTimer=setInterval(()=>{if(!document.hidden)void refreshFacebookBulkStatus()},2500);}
  if(!result.active&&facebookBulkStatusTimer){clearInterval(facebookBulkStatusTimer);facebookBulkStatusTimer=null;}
 }catch(e){
  const box=$('fb-bulk-progress');
  box.hidden=false;box.textContent='Facebook check status unavailable. Retrying…';
  if(!facebookBulkStatusTimer)facebookBulkStatusTimer=setInterval(()=>{if(!document.hidden)void refreshFacebookBulkStatus()},2500);
 }
 finally{facebookBulkPending=false;}
}
async function cancelFacebookBulk(){
 try{await api('/api/facebook-auto-cancel-all',{explicit_request:true});notify('Facebook batch cancelled. Captured snapshots are preserved.');}
 catch(e){notify('Could not cancel Facebook checks: '+String(e.message||e),true);}
 finally{await refreshFacebookBulkStatus();}
}
async function retryFailedFacebook(){
 facebookBulkLastCaptured=0;
 try{
  const result=await api('/api/facebook-auto-retry-failed',{explicit_request:true});
  if(result.total){signalFacebookAutoCheck();notify(`${result.total} failed/expired Facebook listing(s) queued for retry.`);}
  else notify('No previously failed Facebook listings need retrying.');
 }catch(e){notify('Facebook retry failed: '+String(e.message||e),true);}
 finally{await refreshFacebookBulkStatus();}
}
async function fetchMissingInventoryPhotos(){
 const button=$('btn-fetch-missing-photos');button.disabled=true;
 try{
  const result=await api('/api/fetch-missing-photos',{explicit_request:true});
  if(!result.queued)return notify(result.eligible?'Eligible vehicles have no valid saved dealer links.':'All vehicles have at least 10 usable downloaded photos.');
  openScanConsole();wakeChromeReader();
  if(siteScanTimer)clearInterval(siteScanTimer);
  siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);
  await refreshSiteScanStatus();
  notify(`Fetching galleries for ${result.vehicles} vehicles below 10 photos. Collecting available gallery photos, not stopping at 10.`);
 }catch(e){notify('Photo fetch could not start: '+e.message,true);}
 finally{button.disabled=false;}
}

async function recheckOutstock(){
 const button=$('btn-recheck-outstock');button.disabled=true;
 try{
  const result=await api('/api/recheck-outstock',{explicit_request:true});
  if(!result.vehicles)return notify('No vehicles in Out of Stock need rechecking.');
  checkingListingLinks=true;
  wakeChromeReader();
  if(!fullScanPollTimer)fullScanPollTimer=setInterval(refreshFullScanStatus,2800);
  openScanConsole();
  await refreshFullScanStatus();
  notify(`Rechecking all ${result.vehicles} Out of Stock vehicles: ${result.dealer_links} dealer links, then ${result.facebook_links} Facebook links.`);
 }catch(e){notify('Out of Stock recheck could not start: '+e.message,true);}
 finally{button.disabled=false;}
}

async function checkAllFacebook(){
 facebookBulkLastCaptured=0;
 const button=$('btn-facebook-scan');if(button)button.disabled=true;
 try{
  const result=await api('/api/facebook-auto-check-all',{explicit_request:true});
  if(!result.total)return notify('No tracked Facebook listings found. Link an existing listing first.');
  checkingListingLinks=true;
  wakeChromeReader();
  if(!fullScanPollTimer)fullScanPollTimer=setInterval(refreshFullScanStatus,2800);
  openScanConsole();
  await refreshFullScanStatus();
  notify(`Checking ${result.dealer_links} dealer link(s), then ${result.total} Facebook listing(s).`);
 }catch(e){notify('Facebook check-all failed: '+String(e?.message||e),true);}
 finally{await refreshFacebookBulkStatus();}
}

async function watchFacebookAuto(vin){
 const serial=++facebookAutoWatchSerial;
 for(let i=0;i<35;i++){
  if(serial!==facebookAutoWatchSerial)break;
  await new Promise(r=>setTimeout(r,i===0?400:1200));
  if(serial!==facebookAutoWatchSerial)break;
  try{
   const response=await fetch('/api/facebook-auto-status?vin='+encodeURIComponent(vin),
       {headers:{'X-SalesmanHub-Token':csrf},cache:'no-store'});
   if(!response.ok)break;
   const current=await response.json();
   const previous=facebookAutoStatus.get(vin);
   facebookAutoStatus.set(vin,current);
   if(selectedVin===vin){const label=$('fb-auto-status');if(label)label.textContent=current.detail||current.state;}
   if(['captured','failed','expired'].includes(current.state)){
    if(current.state==='captured'&&selectedVin===vin)await loadFacebookComparison();
    else if(current.state==='failed')notify('Facebook check: '+current.detail,true);
    break;
   }
  }catch{break;}
 }
}
async function checkLinkedFacebookNow(vin){
 try{
  const result=await api('/api/facebook-auto-retry',{vin,explicit_request:true});
  facebookAutoStatus.set(vin,result);
  if(selectedVin===vin)renderDetail();
  signalFacebookAutoCheck();
  void watchFacebookAuto(vin);
  notify('Facebook check queued. Chrome Reader will open and close its own temporary tab.');
 }catch(e){notify('Facebook check could not start: '+String(e.message||e),true);}
}
async function linkAndCheckFacebook(action,vin,payload){
 try{
  const result=await api('/api/action',{action,vin,...payload});
  setState(result.state);
  facebookCompareOpenVin=vin;
  if(selectedVin===vin)renderDetail();
  signalFacebookAutoCheck();
  void watchFacebookAuto(vin);
  notify('Facebook listing linked. Chrome Reader will check it automatically after one-time permission is enabled.');
 }catch(e){notify('Facebook link failed: '+String(e.message||e),true);}
}
window.addEventListener('salesmanhub:facebook-auto-result',e=>{
 const status=String(e.detail?.status||''),error=String(e.detail?.error||'');
 if(status==='unavailable')return notify(error||'Chrome Reader unavailable. Reload extension and Marketplace tab.',true);
 const message=error||status;
 if(/enable automatic|pair chrome reader|permission/i.test(message))notify(message,true);
});
// R39 Facebook snapshots are separate from dealer records and never update VINs.
function fbCompareCell(value,key,side){
 if(value===null||value===undefined||value==='')return `<span class="fb-unknown">Not captured</span>`;
 const raw=String(value),preview=raw.length>110?raw.slice(0,107)+'…':raw;
 const shown=key==='price'?'$'+Number(raw).toLocaleString('en-US'):
   key==='mileage'?Number(raw).toLocaleString('en-US')+' mi':preview;
 return `<div class="fb-compare-cell"><span title="${esc(raw.slice(0,500))}">${esc(shown)}</span><button type="button" class="btn ghost" data-act="copy-facebook-compare" data-side="${side}" data-field="${key}">⧉ Copy</button></div>`;
}
function renderFacebookRows(data){
 if(!data)return `<p class="muted">Reading saved comparison… Refresh vehicle to recheck the dealership and Facebook listing.</p>`;
 const rows=data.rows||[];
 const body=rows.map(row=>`<tr><th>${esc(row.label)}</th><td>${fbCompareCell(row.dealer,row.key,'dealer')}</td><td>${fbCompareCell(row.facebook,row.key,'facebook')}</td><td class="fb-compare-result ${row.state==='different'?'different':row.state==='match'?'matched':''}">${row.state==='different'?'Different':row.state==='match'?'Match':'Unknown'}</td></tr>`).join('');
 return `<p class="muted">Listing ${esc(data.listing_id)} · ${data.captured_at?'Captured '+esc(data.captured_at):'No captured fields yet'} · ${esc(data.capture_count||0)} snapshot(s) · Status: ${esc(data.facebook_status||'unknown')}</p>
  <div class="fb-compare-scroll"><table class="fb-compare-table"><thead><tr><th>Field</th><th>Hampton / local draft</th><th>Facebook capture</th><th>Result</th></tr></thead><tbody>${body}</tbody></table></div>
  <p class="muted">Unknown is not a mismatch. Facebook snapshots never change dealer facts or your saved listing. You edit Facebook manually.</p>`;
}
async function loadFacebookComparison(){
 const vin=selectedVin;if(!vin)return;
 facebookCompareOpenVin=vin;
 try{
   const response=await fetch('/api/facebook-comparison?vin='+encodeURIComponent(vin),{headers:{'X-SalesmanHub-Token':csrf},cache:'no-store'});
   const data=await response.json();if(!response.ok||data.ok===false)throw Error(data.error||'Cannot load comparison');
   facebookCompareCache.set(vin,data);
   if(selectedVin===vin)renderDetail();
 }catch(e){notify('Facebook comparison: '+String(e.message||e),true)}
}
async function copyFacebookComparison(button){
 const data=facebookCompareCache.get(selectedVin),field=button?.dataset.field,side=button?.dataset.side;
 if(!data||!['title','price','mileage','description'].includes(field)||!['dealer','facebook'].includes(side))return;
 const row=data.rows.find(x=>x.key===field);if(!row)return;
 return copyToClipboard(String(row[side]??''),`${side==='dealer'?'Dealer':'Facebook'} ${row.label}`);
}
async function refreshPhotoStatus(){
 const vin=selectedVin,source=gallery.source;
 if(!vin||!source||document.hidden)return;
 const key=vin+'|'+source;
 if(photoStatusPendingKey===key)return;
 photoStatusPendingKey=key;
 try{
  const result=await fetch('/api/photo-status?vin='+encodeURIComponent(vin)+'&source='+encodeURIComponent(source),
   {headers:{'X-SalesmanHub-Token':csrf}});
  if(!result.ok)return;
  const data=await result.json();
  if(selectedVin!==vin||gallery.source!==source)return;
  const changed=JSON.stringify((gallery.cache?.photos||[]).map(p=>[p.downloaded,p.excluded,p.status]))!==JSON.stringify(data.photos.map(p=>[p.downloaded,p.excluded,p.status]));
  const previousHadPhotos=Boolean(gallery.cache?.photos);
  gallery.cache=data;
  gallery.cachePreviouslyPresent=previousHadPhotos;
  const status=$('gallery-cache-status');
  if(status){const failed=data.photos.filter(p=>p.status==='failed').length;status.textContent=`${data.usable}/${data.total} usable vehicle images · ${data.excluded} hidden${data.pending?' · Downloading…':''}${failed?' · '+failed+' failed':''}`;}
  if(changed){
   // First status snapshot is informational; no export changed on disk merely
   // because the drawer learned its cache state for the first time.
   const previousHadPhotos=Boolean(gallery.cachePreviouslyPresent);
   const r=state.vehicles.find(v=>v.vin===vin);
   if(r?.sources?.[source])r.sources[source].photo_usable_indices=data.photos.filter(p=>p.downloaded&&!p.excluded).map(p=>p.index);
   renderGrid();renderDetail();
  }
 }catch{} // Photo failures do not interfere with inventory or typed draft edits.
 finally{if(photoStatusPendingKey===key)photoStatusPendingKey='';}
}
async function setCoverPhoto(){
 const vin=selectedVin,source=exportPreview.actualSource;
 const pic=gallery.pictures[gallery.index];
 if(!pic?.url||!vin||!source||exportPreview.vin!==vin)return;
 try{
  const res=await api('/api/photo-cover',{vin,source,url:pic.url});
  const record=state.vehicles.find(v=>v.vin===vin)?.sources?.[source];
  if(record){
   record.photo_cover_index=res.cover.index;
   record.photo_cover_manual=res.cover.manual;
  }
  renderGrid();
  if(selectedVin===vin){
   resetExportPreview();
   await toggleExportPreview();
  }
  notify('Cover photo saved. Branded photos take priority in the photo ZIP.');
 }catch(e){notify('Cover selection failed: '+e.message,true)}
}
// ---- Photo progress: ONE canonical, source-scoped model (GET /api/photos/progress) ----
const PHOTO_STAGE_LABEL={queued:'Queued',downloading:'Downloading',sorting:'Sorting',ready:'Ready',partial:'Partial',unavailable:'Unavailable'};
const PHOTO_FAIL_LABEL={blocked_by_host:'Blocked by dealer host',not_found:'Not found',timeout:'Timed out',tls_error:'Secure connection failed',too_large:'Too large',not_an_image:'Not a valid image',download_failed:'Download failed',not_downloaded:'Not downloaded yet'};
function photoProgressPanel(){
 const d=photoProgress.data;
 if(!d||photoProgress.vin!==selectedVin)return '<div class="photo-audit-panel" role="status"><span>Checking photos…</span></div>';
 const label=PHOTO_STAGE_LABEL[d.stage]||d.stage,busy=['queued','downloading','sorting'].includes(d.stage);
 const sorting=d.stage==='sorting'&&d.sorting?.total?` ${d.sorting.classified}/${d.sorting.total}`:'';
 const text=d.stage==='downloading'&&d.unique?`Downloading ${d.downloaded}/${d.unique}`:label+sorting;
 const bar=busy&&d.stage==='downloading'&&d.unique?`<progress max="${d.unique}" value="${d.downloaded}" aria-label="${esc(text)}"></progress>`:busy?`<progress aria-label="${esc(text)}"></progress>`:`<progress max="1" value="${d.stage==='ready'?1:d.unique?d.downloaded/d.unique:0}" aria-label="${esc(text)}"></progress>`;
 const sel=selectionActive()?orderedPhotoKeys().length:0;
 const reasons=Object.entries(d.failure_reasons||{}).map(([k,n])=>`<li>${esc(PHOTO_FAIL_LABEL[k]||k)}: ${n}</li>`).join('');
 const failures=d.failed?`<details class="photo-failures"><summary>Failures (${d.failed})</summary><ul>${reasons}</ul><button type="button" class="btn secondary" data-act="download-photos">Retry failed</button></details>`:'';
 const note=d.discovery_shortfall?`<small>The dealer reports ${d.dealer_reported} photos but only ${d.unique} links were captured.</small>`:d.sorting?.error?'<small>Sorting unavailable</small>':'';
 return `<div class="photo-audit-panel" role="status" aria-live="polite"><div class="photo-progress-bar"><span>${esc(text)}</span>${bar}</div><span class="photo-funnel">Found ${d.found} → Unique ${d.unique} → Downloaded ${d.downloaded} → Usable ${d.usable} · Selected ${sel}</span>${note}${failures}</div>`;
}
function photoFetchKey(vin,source){return vin+'|'+source;}
async function startPhotoAutoFetch(vin){
 const source=gallery.source;if(!vin||!source)return;
 const key=photoFetchKey(vin,source),last=photoOpenGuard.get(key)||0;
 let data=null;
 try{
  if(Date.now()-last>600000){photoOpenGuard.set(key,Date.now());data=await api('/api/photos/open',{vin,source});}
  else data=await api(`/api/photos/progress?vin=${encodeURIComponent(vin)}&source=${encodeURIComponent(gallery.source)}`);
 }catch(e){if(selectedVin===vin)photoProgress={vin,source,data:{stage:'unavailable',found:0,unique:0,downloaded:0,usable:0,failed:0,failure_reasons:{},sorting:{}},revision:'',watching:''};if(selectedVin===vin)renderDetail();return;}
 if(selectedVin!==vin)return;
 photoProgress={vin,source:data.source,data,revision:data.revision,watching:photoProgress.vin===vin?photoProgress.watching:''};
 renderDetail();void watchPhotoProgress(vin,data.source);
}
function updatePhotoProgressInPlace(){
 const node=document.querySelector('.photo-audit-panel');
 if(!node){return;}
 const html=photoProgressPanel();if(!html)return;
 const t=document.createElement('div');t.innerHTML=html;const fresh=t.firstElementChild;
 if(fresh&&fresh.outerHTML!==node.outerHTML)node.replaceWith(fresh);
}
async function watchPhotoProgress(vin,source){
 const token=photoFetchKey(vin,source)+'#'+Date.now();
 if(photoProgress.watching&&photoProgress.watching.startsWith(photoFetchKey(vin,source)+'#'))return;
 photoProgress.watching=token;
 try{
  while(selectedVin===vin&&photoProgress.watching===token){
   const d=photoProgress.data;
   if(!d||!['queued','downloading','sorting'].includes(d.stage))break;
   await new Promise(r=>setTimeout(r,2000));
   if(selectedVin!==vin||photoProgress.watching!==token)break;
   if(document.hidden)continue;
   const next=await api(`/api/photos/progress?vin=${encodeURIComponent(vin)}&source=${encodeURIComponent(source)}`);
   if(selectedVin!==vin||photoProgress.watching!==token)break;
   const stageChanged=next.stage!==d.stage&&!['queued','downloading'].includes(next.stage);   // rebuild once per real stage change, not per photo
   photoProgress={...photoProgress,data:next,revision:next.revision};
   if(stageChanged)await rebuildExportPreviewKeepingState();else updatePhotoProgressInPlace();
  }
 }catch{}
 finally{if(photoProgress.watching===token)photoProgress.watching='';}
}
// Rebuild the export preview after a REAL revision change. Keeps VIN/source, selection order, scroll and focus.
async function rebuildExportPreviewKeepingState(){
 const vin=selectedVin;if(!vin||!gallery.source)return;
 const strip=document.querySelector('.gallery-thumbs'),left=strip?.scrollLeft||0,top=strip?.scrollTop||0,label=document.activeElement?.getAttribute?.('aria-label'),index=gallery.index;
 try{await persistPhotoSelection();}catch{return;}
 await toggleExportPreview();
 if(selectedVin!==vin)return;
 gallery.index=Math.min(index,Math.max(0,exportPreview.photos.length-1));renderDetail();
 const again=document.querySelector('.gallery-thumbs');if(again){again.scrollLeft=left;again.scrollTop=top;}
 if(label)document.querySelector(`[aria-label="${CSS.escape(label)}"]`)?.focus({preventScroll:true});
}
async function requestPhotoDownloads(){
 try{
  const result=await api('/api/photos/download',{vin:selectedVin,source:gallery.source,force:true});
  const photos=result.photos;
  notify(photos.downloaded===photos.total?`All ${photos.total} saved photo links are downloaded. Use Refresh vehicle to discover new dealer photos.`:
    `Fetching missing photos: ${photos.downloaded}/${photos.total} downloaded.`);
  void refreshPhotoStatus();
 }catch(e){notify(e.message,true)}
}
const photoExportsInProgress=new Set();
async function downloadPhotoZip(targetVin,sourceChoice){
 const vin=targetVin||selectedVin,car=state.vehicles.find(v=>v.vin===vin),source=sourceChoice||(car?.sources.toyota_used?'toyota_used':'mitsubishi_used');

 if(photoExportsInProgress.has(vin))return notify('Already preparing this vehicle’s photo ZIP.');
 photoExportsInProgress.add(vin);
 try{
  let response,prepare=true;
  if(selectionActive()&&photoSelection.vin===vin&&photoSelection.source===source)await persistPhotoSelection();   // a failed save aborts: no ZIP claiming the order was saved
  const selection=selectionActive()&&photoSelection.vin===vin&&photoSelection.source===source?orderedPhotoKeys():undefined;
  if(selection!==undefined){if(!selection.length||selection.length>photoSelection.limit)throw Error('Check photo selection and limit');}
  const deadline=Date.now()+300000;
  while(Date.now()<deadline){
   response=await fetch('/api/photos/export',{method:'POST',headers:{'Content-Type':'application/json','X-SalesmanHub-Token':csrf},
    body:JSON.stringify({vin,source,prepare,...(selection===undefined?{}:{selection})})});
   if(response.ok)break;
   const status=await response.json();
   if(status.error!=='photo_download_pending')throw Error(status.error||'Photo export unavailable');
   notify(`Preparing photo ZIP: ${status.downloaded}/${status.total} downloaded.`);
   prepare=false;
   await new Promise(resolve=>setTimeout(resolve,2500));
  }
  if(!response?.ok)throw Error('Photo downloads are still running. Try Download photo ZIP again after they finish.');
  const blob=await response.blob(),u=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=u;link.download=response.headers.get('Content-Disposition')?.match(/filename="([^\"]+)"/)?.[1]||`Dealer_Photos_${vin}_${source}.zip`;document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(u),1500);notify(selection===undefined?'Photo ZIP downloaded with available photos. See README.txt for missing-photo counts.':`Downloaded ${response.headers.get('X-LotRadar-Selected')||selection.length} photos${Number(response.headers.get('X-LotRadar-Missing'))?' · '+response.headers.get('X-LotRadar-Missing')+' selected photos are no longer available':''}${response.headers.get('X-LotRadar-Folder-Warning')?' · '+response.headers.get('X-LotRadar-Folder-Warning'):''}`);
 }catch(e){notify(e.message,true)}
 finally{photoExportsInProgress.delete(vin);}
}
async function dispatch(action,data={}){try{const res=await api('/api/action',{action,vin:selectedVin,...data});setState(res.state);notify(action==='confirm_listing_updated'?'Facebook update noted. Dealership availability is verified separately.':'Saved to local inventory history.');}catch(e){const message=String(e?.message||'');if(message.includes('inventory_not_verified_available'))return notify(action==='confirm_listing_updated'?'Facebook update was not recorded. Dealer availability is still unverified; refresh the vehicle and retry.':'Current stock is not verified. New-post approval requires availability confirmation.',true);if(message.includes('dealer_information_changed')){try{await reload()}catch{}notify('Dealer details changed. Refresh synced data is ready. Updated fields will flash green.',true);return;}notify(message,true);}}
async function generateAiDraft(){
 const vin=selectedVin,vehicle=state.vehicles.find(v=>v.vin===vin),draft=vehicle?.draft;
 if(!draft)return notify('Create a draft first.',true);
 const button=document.querySelector('[data-act="ai-draft"]');
 if(button){button.disabled=true;button.textContent='Generating description…';}
 try{
  const answer=await api('/api/ai-draft',{vin,source:draft.source,explicit_user_request:true});
  if(selectedVin!==vin)return;
  const target=$('draft-description');
  if(!target)return;
  const status=$('ai-preview-status');
  if(answer.ai_used===true && typeof answer.description==='string' && answer.description.trim()){
    const incoming=answer.description.slice(0,5000);
    target.value=incoming;
    draftEditBuffer={vin,title:$('draft-title')?.value||draft.title,description:incoming,
      updated_at:draft.updated_at,snapshot_hash:draft.snapshot_hash};
    if(status){status.textContent='AI listing loaded. This preview is not saved until you click Save description.';status.hidden=false;}
    notify('AI description ready. Click Save description to keep this version.');
  }else{
    // IMPORTANT: never let the cost-free fallback replace an edited or AI draft.
    const reason=String(answer.fallback_reason||'No verified equipment or AI not available');
    const detail=String(answer.provider_detail||'');
    if(status){status.textContent=`AI did not generate a listing: ${reason}${detail?' ('+detail+')':''}. Your current text is unchanged. Rebuild from dealer facts is available as a separate action.`;status.hidden=false;}
    notify('AI did not generate. Existing description preserved.',true);
  }
 }catch(e){
  const note=$('ai-preview-status');
  if(note){note.textContent='Could not reach the local Marketplace AI service. Your existing saved draft is unchanged. Use Rebuild from dealer facts for the no-cost listing.';note.hidden=false;}
  notify(`AI generator: ${String(e.message||e)}`,true);
 }
 finally{if(button){button.disabled=false;button.textContent='✨ AI feature-based listing';}}
}
// R31: Copy the visible, potentially unsaved preview. Never replace or
// accidentally persist the user's typed draft during a clipboard action.
function currentDraftText(){
 const car=state.vehicles.find(v=>v.vin===selectedVin),d=car?.draft;
 return {title:$('draft-title')?.value??draftEditBuffer?.title??d?.title??'',
  description:$('draft-description')?.value??draftEditBuffer?.description??d?.description??''};
}
function fullPostText(){
 const {title,description}=currentDraftText();const content=description.trim();
 if(!content)return title.trim();
 const normalized=s=>s.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
 // Generated dealer-backed descriptions commonly already include a decorated
 // title such as 🔥 YEAR MAKE MODEL 🔥. Don't duplicate it.
 const firstLine=content.split(/\r?\n/)[0]||'';
 if(normalized(firstLine)&&(normalized(firstLine).includes(normalized(title))||normalized(title).includes(normalized(firstLine))))return content;
 return title.trim()?`${title.trim()}\n\n${content}`:content;
}
async function copyToClipboard(value,label,source){
 if(!String(value).trim())return notify(`${label} is missing.`,true);
 try{
  if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(String(value));
  else throw Error('clipboard_unavailable');
  notify(`${label} copied.`);
 }catch(e){
  const field=source?$(source):null;
  if(field){field.focus();field.select();return notify(`Select & copy ${label.toLowerCase()} with Ctrl+C.`)}
  const fallback=document.createElement('textarea');fallback.value=String(value);fallback.readOnly=true;
  fallback.style.cssText='position:fixed;opacity:0;top:0;left:0;';document.body.append(fallback);fallback.select();
  const ok=document.execCommand?.('copy');fallback.remove();notify(ok?`${label} copied.`:`Clipboard blocked for ${label.toLowerCase()}; use Ctrl+C.`,!ok);
 }
}
async function copyField(k){
 const car=state.vehicles.find(v=>v.vin===selectedVin),d=car?.draft;
 if(!car)return;
 const first=primary(car);
 const spec={model:[name(first),'Model','quick-model'],mileage:[first.mileage!=null?String(Math.trunc(Number(first.mileage))):'','Mileage','quick-mileage'],stock:[(d&&car.sources[d.source]?.stock)||first.stock||'','Stock','quick-stock'],title:[currentDraftText().title,'Title','draft-title'],description:[currentDraftText().description,'Description','draft-description'],price:[d?.price_cents>0?String(d.price_cents/100):'','Price',null]};
 const item=spec[k];if(item)return copyToClipboard(...item);
}
async function copyFullPost(){return copyToClipboard(fullPostText(),'Full post','draft-description')}
async function copyListing(){return copyFullPost()}
async function downloadTransferKit(){
 const vin=selectedVin;

 try{
  const response=await fetch('/api/transfer-kit',{method:'POST',headers:{'Content-Type':'application/json','X-SalesmanHub-Token':csrf},body:JSON.stringify({vin})});
  if(!response.ok){const obj=await response.json();throw Error(obj.error||'Cannot export listing kit');}
  const blob=await response.blob(),u=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=u;a.download='Marketplace_Transfer_'+vin+'.zip';document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(u),1500);notify('Transfer kit saved with downloaded photos where available. You publish manually.');
 }catch(e){notify(e.message,true);}
}
async function openListingTrash(){
 let overlay=$('marketplace-trash-overlay');
 if(!overlay){overlay=document.createElement('div');overlay.id='marketplace-trash-overlay';overlay.className='overlay';
  overlay.innerHTML=`<button class="overlay-dim" type="button" data-trash-close aria-label="Close trash"></button><section class="modal marketplace-trash-modal" role="dialog" aria-modal="true" aria-labelledby="trash-heading"><div class="drawer-top"><div><div class="eyebrow">LOCAL LISTING HISTORY</div><h2 id="trash-heading">Listing Trash · 30 days</h2></div><button type="button" class="close" data-trash-close aria-label="Close trash">×</button></div><p class="muted">Only SalesmanHub tracking records are in this trash. Facebook posts are never deleted or changed.</p><div id="trash-list-items" aria-live="polite"></div></section>`;
  document.body.append(overlay);
  overlay.addEventListener('click',e=>{if(e.target.closest('[data-trash-close]')){overlay.hidden=true;return;}
   const restore=e.target.closest('[data-restore-vin]');if(restore){void restoreTrashedListing(restore.dataset.restoreVin,Number(restore.dataset.restoreId));}});
 }
 overlay.hidden=false;
 try{const response=await fetch('/api/listing-trash',{headers:{'X-SalesmanHub-Token':csrf},cache:'no-store'});
  const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Could not load Trash');
  $('trash-list-items').innerHTML=result.items.length?result.items.map(row=>`<div class="fb-trash-item"><div><strong>${esc(row.title||row.vin)}</strong><small>${esc(row.vin)} · Restorable until ${esc(row.expires_at.slice(0,10))}</small><a href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">Facebook link ↗</a></div><button class="btn secondary" type="button" data-restore-vin="${esc(row.vin)}" data-restore-id="${Number(row.id)}">Restore</button></div>`).join(''):'<p class="muted">Trash is empty.</p>';
 }catch(e){$('trash-list-items').textContent='Could not load listing Trash: '+String(e.message||e);}
}
async function restoreTrashedListing(vin,trashId){
 try{const result=await api('/api/action',{action:'restore_listing',vin,trash_id:trashId,explicit_confirmation:true});setState(result.state);notify('Listing restored to SalesmanHub. Facebook post was unchanged.');await openListingTrash();}
 catch(e){notify('Restore failed: '+String(e.message||e),true);}
}
// R47: validate in the browser for fast feedback; backend repeats every check.
function facebookItemId(raw){
 try{const u=new URL(String(raw||'').trim());const match=u.pathname.match(/^\/marketplace\/item\/([0-9]{8,24})\/?$/);
  return u.protocol==='https:'&&['facebook.com','www.facebook.com','m.facebook.com'].includes(u.hostname)&&!u.username&&!u.password&&(u.port===''||u.port==='443')&&match?match[1]:'';
 }catch{return '';}
}
async function toggleFacebookUrl(){
 const vin=selectedVin,car=state.vehicles.find(v=>v.vin===vin),oldUrl=car?.draft?.published_url;
 if(!vin||!oldUrl)return;
 if(facebookUrlEdit?.vin!==vin){facebookUrlEdit={vin,url:oldUrl,saving:false};renderDetail();const input=$('tracked-facebook-url');input?.focus();input?.select();return;}
 const edit=facebookUrlEdit;if(edit.saving)return;
 const entered=String($('tracked-facebook-url')?.value??edit.url).trim();edit.url=entered;
 if(entered===oldUrl){facebookUrlEdit=null;renderDetail();return;}
 const newId=facebookItemId(entered),oldId=facebookItemId(oldUrl);
 if(!newId)return notify('Enter a valid Facebook Marketplace item URL before locking.',true);
 if(newId!==oldId&&!window.confirm('This URL belongs to a different Facebook listing ID. Replace the local link for this vehicle? The old Facebook capture remains in local history. Nothing will change on Facebook.'))return;
 edit.saving=true;const btn=document.querySelector('[data-act="toggle-fb-url"]');if(btn)btn.disabled=true;
 try{
  const response=await api('/api/action',{action:'relink_facebook',vin,url:entered,expected_url:oldUrl,explicit_confirmation:true});
  facebookUrlEdit=null;facebookCompareCache.delete(vin);facebookAutoStatus.delete(vin);
  setState(response.state);
  if(selectedVin===vin){void loadFacebookComparison();}
  if(newId!==oldId){signalFacebookAutoCheck();void watchFacebookAuto(vin);}
  notify(newId!==oldId?'Facebook link saved and locked. New listing check queued.':'Facebook URL saved and locked.');
 }catch(e){edit.saving=false;renderDetail();notify('Could not save Facebook link: '+String(e.message||e),true);}
}
async function trashTrackedListing(vin){
 if(!window.confirm('Move this listing to SalesmanHub Trash for 30 days? You can restore it before expiry. This will NOT delete or change the Facebook post.'))return;
 try{const result=await api('/api/action',{action:'trash_listing',vin,explicit_confirmation:true});facebookCompareCache.delete(vin);facebookAutoStatus.delete(vin);if(selectedVin===vin)closeOverlay('detail');setState(result.state);notify('Local listing moved to 30-day Trash. Facebook post untouched.');}
 catch(e){notify('Could not move listing to Trash: '+String(e.message||e),true);}
}
let cardRepairPolling=false;
function showCardRepairStatus(r){
 let status=$('business-card-repair-status');
 if(!status){status=document.createElement('div');status.id='business-card-repair-status';status.className='muted';status.setAttribute('role','status');$('dealer-console-body').prepend(status);}
 status.textContent=r.error?'Business-card repair failed: '+r.error:`Business cards: ${r.running?'Checking':'Finished'} ${r.checked||0}/${r.total||0} · ${r.repaired||0} covers saved · ${r.ready||0} ready · ${r.skipped||0} skipped · ${r.needs_review||0} need review${r.current?' · '+r.current:''}`;
 const button=document.querySelector('[data-act="refresh-business-cards"]');
 if(button){button.disabled=!!r.running;button.textContent=r.running?'Checking business cards…':'Refresh business cards';}
}
async function watchCardRepair(){
 if(cardRepairPolling)return;
 cardRepairPolling=true;
 try{
  for(;;){
   const r=await api('/api/business-card-repair',{operation:'status'});showCardRepairStatus(r);
   if(!r.running){
    // Completion and failure remain in Live Scanner.
    previewBlobCache.clear();previewBlobBytes=0;
    if(selectedVin&&!$('detail-overlay').hidden){resetExportPreview();await toggleExportPreview();}
    break;
   }
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
 }catch(e){showCardRepairStatus({error:'Could not read repair status: '+e.message,running:false});}
 finally{cardRepairPolling=false;}
}
async function onDetailAction(action){
 if(action==='get-trade-ready'){try{await api('/api/trade-ready',{prepare:true,vins:getVisible().filter(isTradeInVehicle).map(r=>r.vin)});$('dealer-console-body').hidden=false;$('dealer-console-toggle').textContent='Hide console';await refreshDealerConsole();}catch(e){notify(e.message,true);}return;}

 if(action==='refresh-business-cards'||action==='business-card-report'){
  try{
   const report=await api('/api/business-card-repair',{operation:action==='refresh-business-cards'?'start':'report'});
   if(action==='refresh-business-cards'){$('dealer-console-body').hidden=false;$('dealer-console-toggle').textContent='Hide console';$('dealer-console-toggle').setAttribute('aria-expanded','true');showCardRepairStatus(report);void watchCardRepair();}
   else{const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='LotRadar_Business_Card_Diagnostic.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  }catch(e){notify(e.message,true);}return;
 }

 if(action==='clear-photo-queue'){try{await api('/api/photo-queue-control',{action:'clear'});notify('Photo queue cleared. Saved photos kept. Automatic photo fetching is off until Resume; individual vehicle downloads still work.');}catch(e){notify(e.message,true);}return;}
 if(action==='pause-photo-queue'||action==='resume-photo-queue'){try{await api('/api/photo-queue-control',{action:action==='pause-photo-queue'?'pause':'resume'});notify(action==='pause-photo-queue'?'Photos paused. Saved progress retained.':'Photo downloads resumed.');}catch(e){notify(e.message,true);}return;}
 const r=state.vehicles.find(x=>x.vin===selectedVin);if(!r)return;
 if(action==='toggle-fb-url')return toggleFacebookUrl();
 if(action==='create-draft'){
  const source=$('draft-source')?.value||usedSources.find(k=>r.sources[k]);
  const button=$('drawer-content').querySelector('[data-act="create-draft"]');
  if(!source||!button||button.disabled)return;
  button.disabled=true;
  button.textContent='Creating draft…';
  try{
   const result=await api('/api/action',{action:'create_draft',vin:r.vin,source});
   setState(result.state);
   notify('Listing draft created. Use Prepare Facebook form at the top.');
  }catch(e){
   const messages={
    identity_conflict_must_be_resolved_first:'The dealers disagree about the vehicle identity. Refresh the vehicle before creating a draft.',
    dealer_price_required:'An older LotRadar Server still requires a price. Stop the server with Ctrl+C and reopen LotRadar.',
    approved_photos_required:'An older LotRadar Server still requires photos. Stop the server with Ctrl+C and reopen LotRadar.',
    unknown_vehicle_source:'The selected dealer record is missing. Refresh the vehicle and retry.'
   };
   const error=String(e?.message||'');
   notify(messages[error]||('Could not create listing draft: '+error),true);
  }finally{
   button.disabled=false;
   button.textContent='Create listing draft →';
  }
  return;
 }
 if(action==='track-existing'){
  const url=$('existing-fb-url')?.value?.trim()||'';
  if(!$('existing-confirm')?.checked)return notify('Confirm that you personally verified this Facebook listing.',true);
  if(!/^https:\/\/(?:www\.|m\.)?facebook\.com\/marketplace\/item\/[0-9]+\/?(?:\?.*)?$/i.test(url))
   return notify('Enter a Facebook Marketplace item link before tracking.',true);
  return linkAndCheckFacebook('track_existing',selectedVin,{source:$('draft-source')?.value||usedSources.find(k=>r.sources[k]),url,explicit_confirmation:true});
 }
 if(action==='save-draft'){
   const title=$('draft-title').value,description=$('draft-description').value;
   try {const res=await api('/api/action',{action:'edit_draft',vin:selectedVin,title,description,price_cents:null});
     draftEditBuffer=null;setState(res.state);notify('Description saved. Future vehicle refreshes will not overwrite it.');}
   catch(e){notify('Save failed: '+e.message,true);}
   return;
 }
 if(action==='ai-draft')return generateAiDraft();
 if(action==='confirm-availability'){
  if(!r.draft||!r.sources[r.draft.source])return;
  if($('draft-title')?.value.trim()!==r.draft.title||$('draft-description')?.value.trim()!==r.draft.description)
   return notify('Save your draft edits before confirming stock.',true);
  if(!confirm(`I confirmed this vehicle is currently in stock with ${sourceLabels[r.draft.source]}. Save confirmation?`))return;
  return dispatch('confirm_availability',{source:r.draft.source,explicit_user_confirmation:true});
 }
 if(action==='rebuild-draft'){draftEditBuffer=null;return dispatch('rebuild_draft');}
 if(action==='load-facebook-comparison')return loadFacebookComparison();
 if(action==='check-facebook-auto')return checkLinkedFacebookNow(selectedVin);
 if(action==='trash-listing')return trashTrackedListing(selectedVin);
 if(action==='copy-model')return copyField('model');
 if(action==='copy-mileage')return copyField('mileage');
 if(action==='copy-stock')return copyField('stock');
 if(action==='copy-full-post')return copyFullPost();
 if(action==='show-posting'){const n=$('posting-steps');if(n){n.open=true;n.scrollIntoView({behavior:'smooth',block:'nearest'});}return;}
 if(action==='copy-draft')return copyListing();
 if(action==='copy-title')return copyField('title');
 if(action==='copy-price')return copyField('price');
 if(action==='copy-description')return copyField('description');
 if(action==='download-kit')return downloadTransferKit();
 if(action==='refresh-vehicle'){
  const unsaved=r.draft&&($('draft-description')?.value!==r.draft.description||$('draft-title')?.value!==r.draft.title);
  if(unsaved)return notify('Save your description first, then refresh the vehicle. Unsaved edits will not be discarded.',true);
  return refreshOneVehicle(selectedVin);
 }
 if(action==='toggle-photo-grid'){photoGridExpanded=!photoGridExpanded;renderDetail();document.querySelector('[data-act="toggle-photo-grid"]')?.focus({preventScroll:true});return;}
 if(action==='set-cover')return setCoverPhoto();
 if(action==='download-photos')return requestPhotoDownloads();
 if(action==='retry-export-preview'){resetExportPreview();return toggleExportPreview();}
 if(action==='retry-photo-selection'){const p=exportPreview;try{await loadPhotoSelection(p);}catch(e){if(exportPreview===p)photoSelection.error=String(e.message||e);}if(exportPreview===p)renderDetail();return;}
 if(action==='open-photo-folder'){try{await api('/api/photos/open-folder',{vin:selectedVin});}catch(e){notify(e.message,true)}return;}
 if(action==='download-photo-zip')return downloadPhotoZip(selectedVin,exportPreview.actualSource||gallery.source);
 if(action==='gallery-prev'||action==='gallery-next'){const total=exportPreview.photos.length;if(!total)return;gallery.index=(gallery.index+(action==='gallery-prev'?-1:1)+total)%total;renderDetail();return;}
 if(action==='open-facebook'){
  if($('draft-title')?.value.trim()!==r.draft?.title||$('draft-description')?.value.trim()!==r.draft?.description){
   $('draft-description')?.scrollIntoView({block:'center'});
   return notify('Save your description edits before opening Facebook.',true);
  }
  if(window.lotradarFormBusy)return;
  window.lotradarFormBusy=true;
  const button=$('prepare-facebook-form'),original=button.textContent;
  button.disabled=true;
  let handoff=null;
  const call=async(path,body)=>{
   const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);
   try{const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-SalesmanHub-Token':csrf},body:JSON.stringify(body),signal:controller.signal});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Connection failed');return result;
   }finally{clearTimeout(timer);}
  };
  try{
   button.textContent='Connecting… 5s';
   ({handoff}=await call('/api/prepare-vehicle-form',{vin:r.vin,explicit_request:true}));
   window.dispatchEvent(new CustomEvent('lotradar:vehicle-form',{detail:{handoff}}));
   const start=Date.now();let launched=false,ready=false;
   while(Date.now()-start<20000){
    const elapsed=Date.now()-start;
    if(elapsed>=5000&&!launched){launched=true;await call('/api/vehicle-form-control',{handoff,operation:'launch'});}
    button.textContent=launched?`Opening Chrome… ${Math.max(0,Math.ceil((20000-elapsed)/1000))}s`:`Connecting… ${Math.max(0,Math.ceil((5000-elapsed)/1000))}s`;
    const status=await call('/api/vehicle-form-control',{handoff,operation:'status'});
    if(status.result==='ready'){ready=true;break;}
    if(status.result==='login')throw Error('Sign in to Facebook, then retry.');
    if(status.result==='failed')throw Error('Reader could not open the form. Check Chrome and retry.');
    await new Promise(resolve=>setTimeout(resolve,250));
   }
   if(!ready)throw Error('Reader did not connect. Load and pair LotRadar Reader in the Chrome profile that opened, then retry.');
   notify('Facebook is ready. Open LotRadar Reader and click Fill vehicle form.');
   handoff=null;
  }catch(e){notify(e.name==='AbortError'?'LotRadar connection timed out. Retry.':e.message,true);}
  finally{
   if(handoff)void call('/api/vehicle-form-control',{handoff,operation:'cancel'}).catch(()=>{});
   window.lotradarFormBusy=false;button.disabled=false;button.textContent=original;
  }
  return;
 }
 if(action==='confirm-published')return linkAndCheckFacebook('confirm_published',selectedVin,{url:$('published-url').value,explicit_confirmation:$('published-confirm').checked});
 if(action==='confirm-listing-updated')return dispatch('confirm_listing_updated',{explicit_confirmation:$('updated-confirm').checked,conflict_ack:$('updated-price-confirm')?.checked===true});
 if(action==='confirm-listing-removed')return dispatch('confirm_listing_removed',{explicit_confirmation:$('removed-confirm').checked});
}
function scanEta(timing,queue="Dealer queue"){
 const state=timing?.state;
 if(state==='estimated'&&Number.isFinite(timing.seconds)){
  const minutes=Math.floor(timing.seconds/60),seconds=timing.seconds%60;
  return `${queue} ETA ~${minutes?minutes+'m ':''}${seconds}s`;
 }
 return {paused:`${queue} ETA paused`,disconnected:`${queue} ETA unavailable · Reader offline`,
  discovering:`${queue} ETA pending · Discovering pages`,measuring:`${queue} ETA pending · Measuring completed work`}[state]||'';
}
function renderScanConsole(job){
 lastScanJob=job;
 const sources=Array.isArray(job.sources)&&job.sources.length?job.sources:usedSources;
 const done=new Set(job.completed||[]),p=job.progress?.[job.current]||{};
 const totals=Object.values(job.progress||{}).reduce((t,x)=>{
  for(const k of ['discovered','visited','parsed','failed'])t[k]+=Number(x?.[k]||0);
  return t;
 },{discovered:0,visited:0,parsed:0,failed:0});
 // Stage completion, not inventory success. Failures remain red even at 100%.
 const discovered=Number(p.discovered||0),visited=Number(p.visited||0);
 const detailRatio=discovered>0?Math.min(.98,visited/discovered):0;
 const pct=Math.round(100*((job.completed?.length||0)+(job.running?detailRatio:0))/Math.max(1,sources.length));
 const finished=!job.running&&(job.completed||[]).length>0;
 const displayPct=finished?100:Math.min(99,pct);
 $('scan-progress-fill').style.width=displayPct+'%';
 $('scan-progress-fill').parentElement.setAttribute('aria-valuenow',String(displayPct));
 $('scan-progress-fill').parentElement.setAttribute('aria-label','Dealership scan stages processed; not a successful inventory import count');
 $('scan-console-dealer').textContent=job.running?(sourceLabels[job.current]||'Connecting to dealership'):'Dealer scan '+(finished?'finished':'idle');
 $('scan-console-status').textContent=job.running?`${(p.phase||'connecting').replaceAll('_',' ')} · ${displayPct}% processed`:(finished?`${(job.errors||[]).length} failed section(s)`:'Idle');
 const siteTotals=Object.values(job.progress||{}).reduce((t,x)=>t+Number(x?.website_total||0),0);
 $('scan-console-counts').textContent=`${job.completed?.length||0}/${sources.length} sections · ${totals.visited}/${totals.discovered} vehicle pages · ${totals.parsed} valid VINs · ${totals.failed} failed`+
   (job.mode==='chrome_inventory_full'&&siteTotals?` · Dealer site shows ${siteTotals} vehicles; ${totals.discovered} links discovered${totals.discovered<siteTotals?' (INCOMPLETE)':''}`:'');
 $('scan-console-eta').textContent=finished?`Elapsed ${Math.floor((job.elapsed_seconds||0)/60)}m ${(job.elapsed_seconds||0)%60}s`:
   job.running?(scanEta(job.timing)||'ETA unavailable'):'';
 const errorSources=new Set((job.errors||[]).map(e=>e.source));
 $('scan-source-strip').innerHTML=sources.map(src=>{
  const status=errorSources.has(src)?'FAILED':done.has(src)?'DONE':src===job.current?'LIVE':'PENDING';
  const label=(sourceLabels[src]||src).replace(' • ',' ');
  return `<span>${esc(label)} · ${status}</span>`;
 }).join(' / ');
 const box=document.querySelector('.scan-console');
 box.classList.toggle('is-scanning',!!job.running);box.classList.toggle('is-failed',!job.running&&!!(job.errors||[]).length);
 const items=Array.isArray(job.events)?job.events:[];
 const blocked=items.some(ev=>/HTTP 403|vdp_http_403|access_denied|CHROME_ACCESS_DENIED/i.test(String(ev.message||'')));
 const note=$('scan-console-blocked');
 note.hidden=!blocked;
 if(blocked)note.textContent='HTTP 403 · The headless detail scanner was denied. Chrome Auto Scan uses a regular installed browser and stops separately if it is also denied. No invented VINs.';
 const log=$('scan-console-log'),stick=log.scrollTop+log.clientHeight>=log.scrollHeight-40;
 log.innerHTML=items.length?items.map(ev=>{
  const stage=String(ev.stage||'EVENT');
  const failure=stage==='FAILED'||stage==='CHROME_FAILED'||stage==='EARLY_ABORT'||(stage==='FINISH'&&(job.errors||[]).length>0)||/HTTP 403|vdp_http_403/i.test(String(ev.message||''));
  const good=['IMPORTED','FINISH','CONNECT','START','INVENTORY_DISCOVERED','CHROME_START','CHROME_OPEN','CHROME_PARSED','CHROME_SECTION_END'].includes(stage)&&!failure;
  const time=(ev.at||'').slice(11,19);
  const color=failure?'fail':good?'pass':stage==='VDP'?'tick':'terminal-muted';
  return `<div class="${color}"><span class="term-time">[${esc(time)}]</span> <span class="term-source">${esc(sourceLabels[ev.source]||ev.source||'MANAGER')}</span> <span class="term-sep">&gt;</span> <span class="term-stage">${esc(stage)}</span> <span class="term-sep">&gt;</span> <span class="term-message">${esc(ev.message||'')}</span></div>`;
 }).join(''):'No scanner events yet. Press Scan Inventory to start.';
 if(stick)log.scrollTop=log.scrollHeight;
 updateScanDock(job);
 void pollDealerScanControls();
}
let fullScanPollTimer=null, fullScanPending=false, lastScanPhase='';
async function refreshFullScanStatus(){
 if(fullScanPending||document.hidden)return;
 fullScanPending=true;
 try{
  const response=await fetch('/api/full-scan-status',{cache:'no-store',headers:{'X-SalesmanHub-Token':csrf}});
  if(!response.ok)return;
  const data=await response.json();const f=data.full||{};
  const node=$('full-scan-progress'),button=$('btn-full-scan');
  const outstock=f.operation==='recheck_outstock';
  const checking=f.operation==='check_listings'||outstock;
  checkingListingLinks=checking&&f.running;
  if(f.running&&f.phase==='checking_facebook'&&lastScanPhase!==f.phase)signalFacebookAutoCheck();
  lastScanPhase=f.phase;
  const label=outstock?'Out of Stock recheck':checking?'Listing link check':'Full Scan';
  if(f.running||['completed','failed','stopped'].includes(f.phase)){
   node.hidden=false;const text=({scanning_inventory:'Scanning current dealer inventory',verifying_inventory:checking?'Checking dealer links for tracked listings':'Verifying saved dealer links and missing equipment',checking_facebook:'Checking tracked Facebook listings',completed:label+' finished',failed:label+' failed',stopped:label+' stopped'})[f.phase]||String(f.phase||'');
   node.textContent=text+(f.partial?' · Some checks incomplete':'')+(f.error?' · '+f.error:'');
  }
  button.disabled=Boolean(f.running);
  const stop=$('btn-full-stop');
  stop.hidden=!f.running;
  stop.disabled=Boolean(f.cancel_requested);
  stop.textContent=f.cancel_requested?`Stopping ${label}…`:`Stop ${label}`;
  if(!f.running&&fullScanPollTimer){clearInterval(fullScanPollTimer);fullScanPollTimer=null;}
  if(!f.running&&['completed','stopped'].includes(f.phase)){
   void reload();void refreshCleanupStatus();void refreshLiveVerifyStatus();void refreshFacebookBulkStatus();void refreshSiteScanStatus();
  }
 }catch{}finally{fullScanPending=false;}
}

// R52: responsive dealer scanner controls. No DOM-derived URLs or VINs sent to Chrome.
function installDealerScanControls(){
 const scan=$('btn-quick-scan');if(!scan||$('scan-tabs'))return;
 const holder=document.createElement('div');holder.className='dealer-scan-controls';
 holder.innerHTML=`<label class="dealer-tab-picker" for="scan-tabs">Tab limit
  <select id="scan-tabs" aria-label="Concurrent dealer scan tabs">
   <option value="2">2</option><option value="4">4</option><option value="6">6</option>
   <option value="8">8</option><option value="10" selected>10</option><option value="12">12</option><option value="16">16</option><option value="20">20</option>
  </select></label><span id="scan-tab-budget" class="muted" hidden></span>
 <button id="scan-pause" type="button" class="btn secondary" hidden>Ⅱ Pause</button>
 <button id="scan-stop" type="button" class="btn secondary" hidden>■ Stop</button>`;
 scan.insertAdjacentElement('afterend',holder);
 $('scan-tabs').addEventListener('change',async e=>{
  try {const count=Number(e.target.value);const res=await api('/api/chrome-scan-control',{action:'workers',workers:count});
    updateDealerScanControls(res.control);notify(`Dealer scan can use up to ${count} temporary Chrome tabs.`);}
  catch(error){notify('Could not change tab count: '+error.message,true);void pollDealerScanControls();}
 });
 $('scan-pause').addEventListener('click',async()=>{
  const paused=$('scan-pause').dataset.paused==='1';
  try {const res=await api('/api/chrome-scan-control',{action:paused?'resume':'pause'});
    updateDealerScanControls(res.control);
    if(paused)window.dispatchEvent(new CustomEvent('salesmanhub:scan-control',{detail:{action:'resume'}}));
    notify(paused?'Scanner resumed.':'Paused. Open tabs may finish; no new dealer tabs open.');}
  catch(error){notify('Pause/Resume failed: '+error.message,true);}
 });
 $('scan-stop').addEventListener('click',async()=>{
  if(!confirm('Stop dealer scanning now? Completed imports stay saved, and remaining vehicles will not be scanned.'))return;
  try {const res=await api('/api/chrome-scan-control',{action:'stop'});
    window.dispatchEvent(new CustomEvent('salesmanhub:scan-control',{detail:{action:'stop'}}));
    updateDealerScanControls(res.control);
    notify('Scanner stopped. Partial results preserved; no sold status inferred.');
    await refreshSiteScanStatus();void refreshFullScanStatus();}
  catch(error){notify('Stop failed: '+error.message,true);}
 });
}
function updateDealerScanControls(control){
 if(!control)return;
 const picker=$('scan-tabs'),pause=$('scan-pause'),stop=$('scan-stop');
 if(!picker)return;
 const n=[2,4,6,8,10,12,16,20].includes(Number(control.workers))?Number(control.workers):2;
 if(document.activeElement!==picker)picker.value=String(n);
 const running=Boolean(control.running);
 const budget=$('scan-tab-budget');
 const effective=control.effective_workers||n;
 budget.hidden=!running;
 budget.textContent=`${effective} of ${n} tabs${control.throttled?' · Slowed down':''}`;
 pause.hidden=!running;stop.hidden=!running;
 pause.dataset.paused=control.paused?'1':'0';
 pause.textContent=control.paused?'▶ Resume':'Ⅱ Pause';
 pause.title=control.paused?'Continue queued dealer pages':'Let open tabs finish; stop opening new ones';
 const verifyPause=$('live-verify-pause');
 verifyPause.dataset.paused=control.paused?'1':'0';
 verifyPause.textContent=control.paused?'Resume verification':'Pause verification';
}
async function pollDealerScanControls(){
 try{const result=await api('/api/chrome-bridge/dashboard');updateDealerScanControls(result);}catch{}
}

async function beginInventoryScan(quick=false){
 quick=quick===true;
 try{
  const health=await api('/api/chrome-bridge/dashboard');
  if(health.dealer_engine!=='headless'&&!health.connected){await showChromeScanner();return notify('Connect the Chrome Reader in Settings, then start the scan again.',true);}
  const res=await api('/api/start-site-scan',{explicit_user_request:true,mode:'chrome',sources:usedSources,
     photos_approved:true,max_vehicles:850,skip_existing:quick,discover_live:true});
  wakeChromeReader();
  openScanConsole();notify(quick?'Quick Scan: Toyota first; skip loaded links; fully collect new vehicles at both dealers.':'Live dealer inventory discovery started. Existing vehicles will be rescanned for equipment.');
  if(siteScanTimer)clearInterval(siteScanTimer);
  siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);
  await refreshSiteScanStatus();
  return res;
 }catch(e){notify('Inventory scan not started: '+e.message,true);}
}
async function beginFullScan(){
 if(!confirm('Full Scan will read current dealer inventory, verify saved links, and check your tracked Facebook listings. Start the full workflow?'))return;
 try{
  const health=await api('/api/chrome-bridge/dashboard');
  if(health.dealer_engine!=='headless'&&!health.connected){await showChromeScanner();return notify('Connect Chrome Reader before Full Scan.',true);}
  await api('/api/full-scan-start',{explicit_user_request:true});
  wakeChromeReader();
  $('btn-full-stop').hidden=false;
  $('full-scan-progress').hidden=false;
  $('full-scan-progress').textContent='Full Scan started · Discovering live inventory links…';
  if(!fullScanPollTimer)fullScanPollTimer=setInterval(refreshFullScanStatus,2800);
  if(siteScanTimer)clearInterval(siteScanTimer);
  siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);
  notify('Full Scan started. The local server will advance through dealer scan, verification and Facebook checks.');
  await refreshFullScanStatus();
 }catch(e){notify('Full Scan not started: '+e.message,true);}
}
async function stopFullScan(){
 if(!confirm('Stop Full Scan? Completed results stay saved.'))return;
 const stop=$('btn-full-stop');
 stop.disabled=true;
 try{
  await api('/api/chrome-scan-control',{action:'stop'});
  window.dispatchEvent(new CustomEvent('salesmanhub:scan-control',{detail:{action:'stop'}}));
 }catch(e){stop.disabled=false;notify('Could not stop Full Scan: '+e.message,true);}
 await refreshFullScanStatus();
}
async function changeVerification(action){
 if(action==='stop'&&!confirm('Stop dealer verification? Completed results stay saved.'))return;
 try{
  const result=await api('/api/chrome-scan-control',{action});
  updateDealerScanControls(result.control);
  if(action!=='pause')window.dispatchEvent(new CustomEvent('salesmanhub:scan-control',{detail:{action}}));
  await refreshLiveVerifyStatus();
 }catch(e){notify('Verification control failed: '+e.message,true);}
}
async function verifyInventory(){
 try{
  const r=await api('/api/verify-inventory',{}),v=r.verification,t=v.totals;
  const issues=Object.entries(t).filter(([k])=>!['vehicles','source_records'].includes(k)&&t[k]>0).map(([k,val])=>`${k.replaceAll('_',' ')}: ${val}`);
  const msg=`LOCAL CHECK · ${t.vehicles} vehicles / ${t.source_records} dealer records · ${issues.length?issues.join(' · '):'Saved fields complete'}`;
  $('verify-summary').textContent=msg;
  $('verify-result').hidden=false;
  $('verify-result').textContent=msg;
  $('live-verify-overlay').hidden=false;
  $('live-verify-status').textContent='Requesting live dealer comparison for saved dealership links…';
  try{
   const response=await api('/api/start-live-verify',{explicit_user_request:true,limit:1200,repair_missing:true});
  wakeChromeReader();
   renderLiveVerify(response.verification);
   notify('Verifying saved links at both dealers; refreshing details and retrying missing photos after exact-VIN confirmation.');
  }catch(e){
   $('live-verify-status').textContent='Local check complete. Live check unavailable: '+e.message;
   notify('Live dealer verification could not start. Check the server status.',true);
  }
 }catch(e){notify('Verification failed: '+e.message,true)}
}
function renderLiveVerify(v){
 if(!v)return;
 const pct=v.total?Math.round(100*v.checked/v.total):0;
 $('live-verify-progress').value=v.checked||0;
 $('live-verify-progress').max=Math.max(1,v.total||0);
 $('live-verify-status').textContent=`${v.running?'Checking live dealer links':v.interrupted?'Verification stopped':'Verification completed'} · ${v.checked}/${v.total} checked (${pct}%) · ${v.matched} matched · ${v.review} needs review · ${v.unreachable} unreachable · ${v.inconclusive} inconclusive${v.skipped_due_to_limit?' · '+v.skipped_due_to_limit+' links SKIPPED (limit); verification incomplete':''}`;
 const rows=(v.findings||[]).slice(-250);
 const details=rows.map(f=>`${sourceLabels[f.source]||f.source||'Dealer'} | ${f.vin||'VIN missing'} | ${f.status} | ${(f.issues||[]).join(', ')||'Live identity and known fields matched'}${f.details?.reason?' | '+f.details.reason:''}`);
 $('live-verify-findings').textContent=details.length?details.join('\n'):'Waiting for the dealer scanner to read the first saved vehicle link…';
 $('live-verify-stop').hidden=!v.running;
 $('live-verify-pause').hidden=!v.running;
 if(v.running)void pollDealerScanControls();
 if(v.running&&!liveVerifyTimer)liveVerifyTimer=setInterval(()=>{if(!document.hidden)void refreshLiveVerifyStatus()},1800);
 if(!v.running&&liveVerifyTimer){clearInterval(liveVerifyTimer);liveVerifyTimer=null;}
}
async function refreshLiveVerifyStatus(){
 if(liveVerifyStatusPending)return;
 liveVerifyStatusPending=true;
 try{const resp=await fetch('/api/live-verify-status',{cache:'no-store',headers:{'X-SalesmanHub-Token':csrf}});const r=await resp.json();if(!resp.ok)throw Error(r.error||'HTTP '+resp.status);if(r.verification?.started_at)renderLiveVerify(r.verification);}
 catch(e){$('live-verify-status').textContent='Could not refresh verification: '+e.message;}
 finally{liveVerifyStatusPending=false;}
}

let dealerConsoleBusy=false,readinessCheckedAt=0,readinessAwaiting=false,readinessWasBusy=false;
// Refresh inventory during scans and photo work without rebuilding the open editor.
let liveInventoryBusy=false, liveInventoryWasActive=false;
async function refreshLiveInventory(active){
 if(document.hidden||liveInventoryBusy)return;
 if(!active&&!liveInventoryWasActive)return;
 liveInventoryWasActive=true; // Keep final refresh pending if the request fails.
 liveInventoryBusy=true;
 const previous=state;
 try{
  const next=await api('/api/state');
  // A user action may have loaded newer state while this request was in flight.
  if(state!==previous)return;
  if(JSON.stringify(next)!==JSON.stringify(state)){
   captureFieldChanges(state,next);
   state=next;
   renderStats();
   renderGrid();
  }
  liveInventoryWasActive=!!active;
 }finally{liveInventoryBusy=false;}
}
async function refreshDealerConsole(){
 if(dealerConsoleBusy||document.hidden)return;
 dealerConsoleBusy=true;
 try{
  const d=await api('/api/dealer-connection-console'),w=d.worker||{},scan=d.scan||{},verify=d.verify||{},fb=d.facebook||{},full=d.full||{},photos=d.photo_downloads||{},fbJobs=d.facebook_jobs||{};
  const activity=[];
  const load=w.system_load;
  if(load?.available)activity.push(`PC CPU ${load.cpu_percent}% · RAM ${load.available_gb} GB free`);
  if(w.performance_reason)activity.push(w.performance_reason);
  const progress=Object.values(scan.progress||{});
  if(scan.running)activity.push(`Dealer pages ${progress.reduce((n,x)=>n+(x.visited||0),0)}/${progress.reduce((n,x)=>n+(x.discovered||0),0)} discovered · ${progress.reduce((n,x)=>n+(x.skipped_existing||0),0)} loaded links skipped`);
  if(verify.running)activity.push(`Verification ${verify.checked||0}/${verify.total||0}`);
  if(fb.active||fbJobs.pending)activity.push(`Facebook ${fb.captured||0} captured, ${fbJobs.pending||0} pending`);
  let photoControls=$('photo-queue-controls');
  if(!photoControls){photoControls=document.createElement('div');photoControls.id='photo-queue-controls';$('dealer-console-eta').parentElement.appendChild(photoControls);}
  photoControls.innerHTML=`<button type="button" class="btn secondary" data-act="${photos.paused||photos.automatic_suspended?'resume':'pause'}-photo-queue">${photos.automatic_suspended?'Resume automatic photos':photos.paused?'Resume photos':'Pause photos'}</button> <button type="button" class="btn secondary" data-act="clear-photo-queue">Clear photo queue</button> <span>${photos.workers||3} photo workers${photos.paused?' · Paused':''}</span>`;
  if(photos.priority_vins?.length)activity.push(`Priority photos: ${photos.priority_vins.slice(0,3).join(', ')}${photos.priority_vins.length>3?' · +'+(photos.priority_vins.length-3)+' more':''}`);
  if(photos.pending)activity.push(`Photos ${photos.processed||0}/${photos.total||0} processed · ${photos.saved||0} saved · ${photos.failed||0} failed · ${photos.skipped||0} skipped · ${photos.pending} vehicle jobs pending · ${scanEta(photos.timing,'Photos')}`);
  if(full.running)activity.push(`Full scan · ${String(full.phase||'running').replaceAll('_',' ')}`);
  const photoFocus=!(scan.running||w.running||verify.running||fb.active||fbJobs.pending||full.running)&&!!photos.total;
  if(photoFocus&&!photos.pending)activity.push(`Photos finished · ${photos.saved||0}/${photos.total||0} saved · ${photos.failed||0} failed · ${photos.skipped||0} skipped`);
  $('dealer-console-summary').textContent=activity.join('  /  ');
  $('dealer-console-eta').textContent=photoFocus?scanEta(photos.timing,'Photos'):scanEta(d.dealer_timing||scan.timing,verify.running?'Verification':'Dealer queue');
  $('dealer-console-facebook-eta').textContent=scanEta(fbJobs.timing,'Facebook');
  $('dealer-console-reader').textContent=`${w.connected?'Reader connected':'Reader disconnected'} · ${w.paused?'Paused':w.running?'Running':'Idle'} · ${w.active_count||0} active / ${w.waiting_count||0} queued${w.running&&w.effective_workers?` · ${w.effective_workers}/${w.worker_limit} tabs${w.throttled?' · Slowed down':''}`:''}`;
  if(!w.running&&!photoFocus&&(fb.active||fbJobs.pending)){
   $('dealer-console-reader').textContent=`Facebook checks · ${fbJobs.pending||0} queued/working`;
  }
  if(photoFocus){
   const active=photos.active;
   $('dealer-console-reader').textContent=photos.pending?
    `Downloading photos · ${photos.processed||0}/${photos.total||0} processed${active?` · ${active.vin} · photo ${active.index}/${active.total}`:''}`:
    `Photo downloads finished${photos.failed||photos.skipped?' · Some photos need retry':''}`;
  }
  const log=$('dealer-console-activity');
  const stick=log.scrollTop+log.clientHeight>=log.scrollHeight-30;
  const consoleEvents=[...(scan.recent||[]),...(photos.recent||[]).map(e=>({...e,source:'',stage:'PHOTO'}))]
    .sort((a,b)=>String(a.at||'').localeCompare(String(b.at||'')));
  const repair=d.business_card_repair||{};
  if(repair.running||repair.total||repair.error)showCardRepairStatus(repair);
  const queueLines=[
   ...(repair.running||repair.total||repair.error?[`Business-card repair: ${repair.running?'Running':'Finished'} · ${repair.checked||0}/${repair.total||0} checked · ${repair.ready||0} ready · ${repair.repaired||0} covers saved · ${repair.needs_review||0} need review · ${repair.skipped||0} skipped${repair.error?' · '+repair.error:''}`]:[]),
   `Dealer queue: ${w.active_count||0} active / ${w.waiting_count||0} waiting`,
   ...(w.active||[]).map(j=>`  Working: ${sourceLabels[j.source]||j.source} · ${j.vin||j.vehicle}`),
   ...(w.waiting||[]).slice(0,4).map(j=>`  Next: ${sourceLabels[j.source]||j.source} · ${j.vin||j.vehicle}`),
   `Photo queue: ${photos.pending||0} vehicle jobs · ${photos.remaining||0} photos remaining`,
   ...(photos.active_jobs||[photos.active].filter(Boolean)).map(active=>`  Downloading: ${active.vin} · ${active.index}/${active.total}`),
   `Facebook queue: ${fbJobs.pending||0} waiting/working · ${fb.captured||0} captured · ${fb.failed||0} failed`,
   ...(d.facebook_jobs?.items||[]).slice(0,4).map(j=>`  ${j.state}: ${j.vin}`),
   `Verification: ${verify.checked||0}/${verify.total||0} checked`,
   '', 'Recent activity:'];
  const entries=queueLines.join('\n')+'\n'+consoleEvents.slice(-200).map(e=>`[${(e.at||'').slice(11,19)}] ${sourceLabels[e.source]||'LotRadar'} ${e.stage}: ${e.message||''}`).join('\n')||'No scan activity yet.';
  if(log.textContent!==entries){log.textContent=entries;if(stick)log.scrollTop=log.scrollHeight;}
  $('dealer-console-updated').textContent='Updated '+new Date().toLocaleTimeString();
  const anyScan=!!(scan.running||photos.pending||w.running||verify.running||fb.active||fbJobs.pending||repair.running||d.trade_ready_running);
  if(!readinessCheckedAt||(readinessWasBusy&&!anyScan)||(anyScan&&Date.now()-readinessCheckedAt>=60000)){readinessCheckedAt=Date.now();await api('/api/trade-ready',{prepare:false});readinessAwaiting=true;}
  else if(readinessAwaiting&&!d.trade_ready_running){readinessAwaiting=false;liveInventoryWasActive=true;await refreshLiveInventory(anyScan);}
  readinessWasBusy=anyScan;
  if(!anyScan||Date.now()-(window.lastTradeRefresh||0)>=60000){window.lastTradeRefresh=Date.now();await refreshLiveInventory(anyScan);}
 }catch(e){$('dealer-console-eta').textContent='';$('dealer-console-facebook-eta').textContent='';$('dealer-console-reader').textContent='Connection check unavailable: '+String(e.message||e).slice(0,110);}
 finally{dealerConsoleBusy=false;}
}
async function refreshSiteScanStatus(){
 if(siteScanStatusPending)return;
 siteScanStatusPending=true;
 try{
  const response=await fetch('/api/site-scan-status',{headers:{'X-SalesmanHub-Token':csrf}});
  if(!response.ok)throw Error(`Scan status HTTP ${response.status}`);
  const job=await response.json();
  renderScanConsole(job);
  const names=job.completed.map(k=>sourceLabels[k]||k);
  const outcomes=Object.entries(job.results||{}).map(([src,r])=> job.mode==='basic'?
     `${sourceLabels[src]||src}: ${r.catalog_candidates||0} unverified Y/M/model links (not inventory)`:
     job.mode?.startsWith('chrome')?`${sourceLabels[src]||src}: ${r.accepted||0} imported from ${r.live_discovered??'discovered'} links, ${r.failed||0} failed${r.coverage?` · Price ${r.coverage.price||0}, mileage ${r.coverage.mileage||0}, stock ${r.coverage.stock||0}, equipment ${r.coverage.equipment||0}, specs ${r.coverage.specifications||0}, photo links ${r.coverage.photo_links||0} · Galleries matched ${r.coverage.gallery_complete||0}, known short ${r.coverage.gallery_incomplete||0}`:''}${r.coverage_incomplete?' · SITE COVERAGE INCOMPLETE':''} · availability unverified`:`${sourceLabels[src]||src}: ${r.parsed||0} parsed, ${r.accepted||0} imported, ${r.complete_details??'not measured'} detail-complete${r.pending?' ('+r.pending+' sitemap-only, review availability)':''}`);
  const errors=(job.errors||[]).map(e=>`${sourceLabels[e.source]||e.source} FAILED: ${e.reason}`);
  if(job.running){
   const p=job.progress?.[job.current];
   $('site-scan-status').textContent=`Scanning ${sourceLabels[job.current]||'starting'} • ${job.completed.length}/${job.sources?.length||2} sources finished`+
       (p?` • ${p.phase}: ${p.discovered||0} links, ${job.mode==='basic'?'basic names':'VINs'} ${p.parsed||0}, ${p.failed||0} errors`:'');
  }else if(job.completed.length){
   $('site-scan-status').textContent=[`Scan finished: ${job.completed.length}/${job.sources?.length||2} sections, ${errors.length} failed`,...outcomes,...errors].join(' | ');
  }else{
   $('site-scan-status').textContent='';
  }
  $('btn-scan-console').hidden=!job.completed.length&&!job.running;
  if(!job.running&&siteScanTimer){clearInterval(siteScanTimer);siteScanTimer=null;await reload();await refreshCleanupStatus();await loadBasicCatalog();
   notify(errors.length?`Dealer scan failed for ${errors.length} section(s). Download the diagnostic report.`:
    job.mode==='basic'?'Basic catalog ready. Year/make/model entries remain unverified and are not Facebook-ready.':'Full detail scan finished. Review imports and photos.',!!errors.length);}
 }catch(e){notify('Unable to read website scan status: '+e.message,true);}
 finally{siteScanStatusPending=false;}
}
async function downloadScanDiagnostics(){
 try{
  const response=await fetch('/api/site-scan-status',{headers:{'X-SalesmanHub-Token':csrf}});
  if(!response.ok)throw Error('Scan diagnostic access failed');
  const job=await response.json();
  const raw=new Blob([JSON.stringify(job,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(raw),a=document.createElement('a');
  a.href=url;a.download='Hampton_Dealer_Scan_Diagnostics.json';document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1500);notify('Scan diagnostic saved. No Facebook credentials included.');
 }catch(e){notify(e.message,true);}
}

async function loadBasicCatalog(){
 try{
  const response=await fetch('/api/basic-catalog',{headers:{'X-SalesmanHub-Token':csrf}});
  if(!response.ok)throw Error('basic catalog HTTP '+response.status);
  basicCatalog=await response.json();renderBasicCatalog();
 }catch(e){$('basic-catalog-list').textContent='Unable to load basic catalog: '+e.message;}
}
function renderBasicCatalog(){
 const list=usedSources.flatMap(src=>(basicCatalog.sources?.[src]?.records||[]));
 $('basic-count').textContent=list.length+' unverified link'+(list.length===1?'':'s');
 const box=$('basic-catalog-list');
 const panel=$('basic-catalog-panel');
 if(!panel.open){box.textContent='Expand to inspect historical link candidates.';$('basic-more').hidden=true;return;}
 if(!list.length){box.textContent='No historical discovery candidates saved. Scan Inventory reads the current dealer grid directly.';$('basic-more').hidden=true;return;}
 box.innerHTML=list.slice(0,basicVisible).map(r=>{
  const v=r.enrichment,details=v?`<div class="basic-enriched">VIN: ${esc(v.vin||'missing')} · Stock: ${esc(v.stock||'missing')} · ${esc(v.price_label||'Price')}: ${v.price?'$'+esc(Number(v.price).toLocaleString('en-US',{minimumFractionDigits:2})):'missing'} · Miles: ${v.mileage===null?'not recorded':esc(v.mileage)}</div>`:'';
  return `<div class="basic-entry"><div><strong>${esc(r.year)} ${esc(r.make)} ${esc(r.model)}</strong><small>${esc(sourceLabels[r.source]||r.source)} · ${r.discovery_method==='sitemap'?'Historical sitemap possible':'Inventory page link'} · ${v?'Details captured / availability unverified':'Unverified'}</small>${details}</div><div class="basic-actions"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">Dealer ↗</a></div></div>`;
 }).join('');
 $('basic-more').hidden=list.length<=basicVisible;
 $('basic-more').textContent=`Show more links (${Math.min(60,list.length-basicVisible)} of ${list.length-basicVisible} remaining)`;
}
function openEnrichCandidate(url,source){
 const row=(basicCatalog.sources?.[source]?.records||[]).find(x=>x.url===url);
 if(!row){notify('Candidate was not found in this catalog.',true);return;}
 selectedBasic={source,url};$('enrich-subtitle').textContent=`${row.year} ${row.make} ${row.model} · ${sourceLabels[source]||source} · UNVERIFIED`;
 $('enrich-open-url').href=url;
 $('enrich-page-text').value='';$('enrich-result').textContent='';$('enrich-overlay').hidden=false;
 $('enrich-page-text').focus();
}
async function saveEnrichment(){
 if(!selectedBasic)return;
 const text=$('enrich-page-text').value;
 $('enrich-submit').disabled=true;
 try{
  const response=await api('/api/enrich-basic-candidate',{...selectedBasic,text,explicit_capture:true});
  const e=response.enrichment;
  $('enrich-result').textContent=`VIN ${e.vin||'missing'} · Stock ${e.stock||'missing'} · ${e.price_label||'Price'} ${e.price?'$'+e.price:'missing'} · Mileage ${e.mileage===null?'missing':e.mileage} · ${e.details_complete?'All requested fields captured':'Missing: '+e.fields_missing.join(', ')}. Availability UNVERIFIED.`;
  await loadBasicCatalog();notify('Page details saved to the unverified catalog. No listing was published.');
 }catch(e){$('enrich-result').textContent='Could not capture: '+e.message;notify(e.message,true);}
 finally{$('enrich-submit').disabled=false;}
}

async function pairFetch(path,headers={}){
 const controller=new AbortController();
 const timeout=setTimeout(()=>controller.abort(),6000);
 try{return await fetch(path,{headers,cache:'no-store',signal:controller.signal});}
 catch(e){if(e.name==='AbortError')throw Error('Local Marketplace service timed out. Restart the Marketplace terminal and reopen Inventory.');throw Error('Cannot reach local Marketplace server. Reopen Inventory from SalesmanHub.');}
 finally{clearTimeout(timeout);}
}
let readerSetupPending=false;
async function showChromeScanner(){
 $('chrome-bridge-overlay').hidden=false;
 await refreshReaderSetup();
}
async function refreshReaderSetup(){
 if(readerSetupPending||$('chrome-bridge-overlay').hidden)return;
 readerSetupPending=true;
 const keyInput=$('chrome-pair-key'),copy=$('chrome-copy-key'),start=$('chrome-start');
 const status=$('chrome-bridge-status');
 try{
  const live=await api('/api/chrome-bridge/dashboard');
  if($('chrome-bridge-overlay').hidden)return;
  start.disabled=live.dealer_engine!=='headless'&&!live.connected;
  if(live.connected){
   keyInput.value='';copy.disabled=true;$('chrome-pair-controls').hidden=true;
   status.textContent=live.dealer_engine==='headless'?'Dealer scans run headlessly. Chrome is connected for Facebook.':'Chrome Reader connected. Ready for dealer scans.';
   return;
  }
  if(!keyInput.value){
   const obj=await api('/api/chrome-bridge/key');
   if(typeof obj.key!=='string'||!/^[A-Za-z0-9_-]{32,80}$/.test(obj.key))throw Error('LotRadar did not return a valid pairing key.');
   keyInput.value=obj.key;
  }
  if($('chrome-bridge-overlay').hidden){keyInput.value='';return;}
  $('chrome-pair-controls').hidden=false;
  copy.disabled=false;
  status.textContent=live.dealer_engine==='headless'?'Dealer scans run headlessly without Chrome. Pair Chrome below only for Facebook features.':'Reader disconnected. Open LotRadar Browser Reader and reconnect.';
 }catch(e){
  keyInput.value='';copy.disabled=true;start.disabled=true;$('chrome-pair-controls').hidden=true;
  status.textContent='Could not check Chrome Reader: '+e.message;
 }finally{readerSetupPending=false;}
}
async function refreshOneVehicle(vin){
 const vehicle=state.vehicles.find(v=>v.vin===vin&&isUsedVehicle(v));
 if(!vehicle)return notify('Vehicle no longer appears in the loaded used inventory. Refresh the page, then retry.',true);
 const sources=Object.keys(vehicle.sources).filter(k=>usedSources.includes(k)&&validHttps(vehicle.sources[k]?.url));
 if(!sources.length)return notify('This vehicle has no valid used-dealer detail link. Run Chrome Scan again or verify its source URL.',true);
 if(refreshingVin)return notify('A vehicle refresh is already being submitted. Check the scan console.',true);
 refreshingVin=vin;renderGrid();
 try{
  const health=await api('/api/health');
  if(!/CHROME-R1(?:3|4)/.test(String(health.api_revision||'')))
   throw Error('Marketplace server is older than the Refresh feature. Stop the Python server with Ctrl+C, then relaunch Inventory.');
  const response=await api('/api/chrome-refresh-vehicle',{vin,explicit_user_request:true});
  if(!response.chrome?.queued)throw Error('Chrome did not accept a vehicle refresh job.');
  wakeChromeReader();
  if(response.facebook?.state==='queued'||response.facebook?.state==='checking'){
   facebookCompareCache.delete(vin);
   facebookAutoStatus.set(vin,response.facebook);signalFacebookAutoCheck();void watchFacebookAuto(vin);
  }
  // Keep the posting drawer open, so the comparison automatically reflects
  // the updated dealer record and the Facebook capture as each finishes.
  if(selectedVin===vin){
   facebookCompareOpenVin=vehicle?.draft?.published_url?vin:'';
   renderDetail();
  }else{
   openScanConsole();
  }
  const fb=response.facebook||{state:'skipped',detail:'No Facebook status reported.'};
  const fbInfo=fb.state==='queued'||fb.state==='checking'?'Facebook: queued':fb.state==='not_linked'?'Facebook: not linked':`Facebook: ${fb.state} (${fb.detail||'check not started'})`;
  notify(`Dealer: queued for ${sources.length} link(s). ${fbInfo}. Dealer background scan queued.`,fb.state==='skipped');
  if(siteScanTimer)clearInterval(siteScanTimer);
  siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);
  await refreshSiteScanStatus();
 }catch(e){
  const message=String(e?.message||e);
  notify(/unknown_endpoint|HTTP 404/i.test(message)?'Your running Marketplace server does not support single-car Refresh. Stop the old Python process, then relaunch Inventory.':/unknown_used_vehicle|not found/i.test(message)?'This VIN is not in the currently running Marketplace database. Restart the server, reload Inventory, and retry.':/saved_used_dealer_link_missing_or_invalid/i.test(message)?'This VIN has no usable dealership detail link. Refresh discovery links before retrying.':`Refresh not started: ${message}`,true);
 }finally{refreshingVin='';renderGrid();}
}

async function beginChromeScan(){
 try{
  const limit=850;
  const result=await api('/api/start-site-scan',{explicit_user_request:true,mode:'chrome',
    sources:usedSources,
    photos_approved:true,max_vehicles:limit,skip_existing:false,discover_live:true});
  closeOverlay('chrome-bridge');
  openScanConsole();
  notify('Dealer scan queued.'+' '+result.chrome.queued+' queued; '+(result.chrome.skipped_existing||0)+' previously imported URLs skipped.');
  if(siteScanTimer)clearInterval(siteScanTimer);
  siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);
  await refreshSiteScanStatus();
 }catch(e){notify('Chrome scan: '+e.message,true);}
}
async function beginSiteScan(){
 try{
  const res=await api('/api/start-site-scan',{explicit_user_request:true,
   sources:usedSources,
   photos_approved:true,max_vehicles:250,mode:'basic'});
  closeOverlay('site-scan');$('verify-result').hidden=true;openScanConsole();notify('Historical link discovery started. Candidates do not count as verified inventory.');
  if(siteScanTimer)clearInterval(siteScanTimer);
  siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);
  await refreshSiteScanStatus();
 }catch(e){notify(e.message,true)}
}
let externalImportDraft=null;
async function previewExternalFile(ev){
 ev.preventDefault();
 const file=$('external-file').files[0];if(!file){notify('Choose the working scanner export.',true);return;}
 if(file.size>12_000_000){notify('Export exceeds the 12 MB limit.',true);return;}
 const fmt=file.name.toLowerCase().endsWith('.csv')?'csv':'json';
 $('external-confirm-btn').disabled=true;externalImportDraft=null;
 try{
  const text=await file.text();
  const fallback_source=$('external-source').value;
  const res=await api('/api/preview-external-scan',{format:fmt,text,fallback_source});
  const x=res.preview;
  $('external-preview').textContent=`${x.valid} valid / ${x.received} rows · ${x.rejected} rejected · `+
   Object.entries(x.by_source||{}).map(([name,n])=>`${sourceLabels[name]||name}: ${n}`).join(' · ')+
   (x.sample_rejections?.length?` · Rejections: ${x.sample_rejections.slice(0,3).map(y=>y.reason).join(', ')}`:'')+
   ' · Import will be PARTIAL; no sold or removal changes.';
  externalImportDraft={format:fmt,text,fallback_source};
  $('external-confirm-btn').disabled=!x.valid;
 }catch(e){$('external-preview').textContent='Preview failed: '+e.message;notify(e.message,true);}
}
async function commitExternalFile(){
 if(!externalImportDraft)return;
 $('external-confirm-btn').disabled=true;
 try{
  const res=await api('/api/import-external-scan',{...externalImportDraft,explicit_import:true});
  setState(res.state);closeOverlay('external');externalImportDraft=null;
  $('external-form').reset();
  notify(`${res.preview.valid} inventory records transferred; ${res.preview.rejected} quarantined. Run Verify Inventory to inspect gaps.`);
 }catch(e){notify('Transfer failed: '+e.message,true);$('external-confirm-btn').disabled=false;}
}
async function importFile(ev){ev.preventDefault();const file=$('import-file').files[0];if(!file){notify('Choose an inventory export.',true);return;}
 if(file.size>12_000_000){notify('File exceeds the 12 MB import limit.',true);return;}
 try{const text=await file.text(),fmt=file.name.toLowerCase().endsWith('.csv')?'csv':'json';const res=await api('/api/import',{source:$('import-source').value,format:fmt,text,complete:$('import-complete').checked});closeOverlay('import');setState(res.state);notify(`${res.result.accepted} imported, ${res.result.quarantined} quarantined${res.result.complete?'':' • partial snapshot'}.`);$('import-form').reset();}
 catch(e){notify('Import rejected: '+e.message,true);}}
async function refreshFeeds(){try{notify('Refreshing authorized configured feeds…');const res=await api('/api/sync',{});setState(res.state);const outcomes=Object.entries(res.results||{});if(!outcomes.length)return notify('No authorized feed configured. Import a dealership export first.');let good=outcomes.filter(([,x])=>x.ok).length;notify(`${good}/${outcomes.length} authorized feeds refreshed${good<outcomes.length?'; see server logs for failures':''}.`,good<outcomes.length);}catch(e){notify('Refresh failed: '+e.message,true);}}
async function exportData(){try{const data=await api('/api/export');const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='marketplace-audit-'+new Date().toISOString().slice(0,10)+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Audit export saved.')}catch(e){notify(e.message,true);}}
const removalLabel=row=>row.identity?.title||[row.identity?.year,row.identity?.make,row.identity?.model].filter(Boolean).join(' ')||row.vin;
const pendingRemovals=()=>(state.removals||[]).filter(r=>r.status==='PENDING_FB_DELETE');
const isPendingCleanupVin=vin=>pendingRemovals().some(r=>r.vin===vin);
const activeCleanupState=r=>{
 if(!cleanupIssues[r.vin]||isPendingCleanupVin(r.vin))return 'DONE';
 return r.listed?'TRACKED_REVIEW':'UNLISTED_REVIEW';
};
const trackedCleanupCandidates=()=>state.vehicles.filter(r=>isUsedVehicle(r)&&activeCleanupState(r)==='TRACKED_REVIEW');
function updateDeleteListingBadge(){
 const badge=$('delete-listing-badge');if(!badge)return;
 const n=pendingRemovals().length;
 badge.textContent=`${n?'● ':''}Pending (${n})`;badge.classList.toggle('attention',n>0);
}
function removedRecoveryHtml(){
 const rows=(state.removals||[]);
 if(!rows.length)return '';
 return `<details class="removed-recovery"><summary>Removed from inventory (${rows.length}) · restore if removed by mistake</summary>${rows.map(r=>`<div class="removed-row"><span><strong>${esc(removalLabel(r))}</strong> · Stock ${esc(r.identity?.stock||'—')} · ${esc(r.vin)} · ${r.status==='PENDING_FB_DELETE'?'Facebook deletion pending':r.status==='FB_DELETE_CONFIRMED'?'Facebook deletion confirmed':'No Facebook listing'}</span><button type="button" class="btn ghost" data-restore-removed="${esc(r.vin)}">Restore to inventory</button></div>`).join('')}</details>`;
}
function renderDeleteListing(){
 const candidates=trackedCleanupCandidates(),rows=pendingRemovals(),needle=search.trim().toLowerCase();
 const shownCandidates=candidates.filter(r=>`${r.vin} ${name(primary(r))} ${Object.values(r.sources||{}).map(s=>s.stock).join(' ')}`.toLowerCase().includes(needle));
 const shownPending=rows.filter(r=>`${r.vin} ${removalLabel(r)} ${r.identity?.stock||''}`.toLowerCase().includes(needle));
 $('inventory-matches').textContent=`${shownCandidates.length} to verify · ${shownPending.length} pending`;$('vehicle-more-row').hidden=true;
 $('vehicle-grid').classList.add('cleanup-list');
 const candidateHtml=shownCandidates.map(r=>{
  const facebookLink=safeFacebookUrl(r.draft?.published_url||'');
  const stock=Object.values(r.sources||{}).map(s=>s.stock).find(Boolean)||'MISSING';
  return `<article class="vehicle-card delete-listing-card tracked-review-card" data-delete-vin="${esc(r.vin)}"><div class="vehicle-main">
   <div class="card-stock-row"><strong class="stock-number">STOCK ${esc(stock)}</strong><strong class="card-mileage">Needs stock verification</strong></div>
   <div class="vehicle-card-head"><h3>${esc(name(primary(r)))}</h3></div>
   <div class="vehicle-vin-row"><span>VIN</span><strong>${esc(r.vin)}</strong></div>
   <div class="vehicle-dealer-warning"><strong>⚑ Needs stock verification</strong><div>This vehicle is tracked on Facebook. Verify that it is unavailable at the dealership before removal.</div></div>
   <div class="vehicle-card-actions">
    ${facebookLink?`<button type="button" class="btn secondary" data-tracked-listing-open="${esc(r.vin)}" aria-label="Open tracked Facebook listing for ${esc(name(primary(r)))}">Open tracked listing ↗</button>`:'<button type="button" class="btn ghost" disabled>No valid Facebook URL</button>'}
    <button type="button" class="btn primary" data-tracked-confirm="${esc(r.vin)}">Confirm out of stock</button>
   </div></div></article>`;
 }).join('');
 const pendingHtml=shownPending.map(r=>{
  const valid=Boolean(safeFacebookUrl(r.open_url));
  return `<article class="vehicle-card delete-listing-card" data-delete-vin="${esc(r.vin)}"><div class="vehicle-main">
   <div class="card-stock-row"><strong class="stock-number">STOCK ${esc(r.identity?.stock||'MISSING')}</strong><strong class="card-mileage">Removed ${esc(new Date(r.removed_at).toLocaleDateString())}</strong></div>
   <div class="vehicle-card-head"><h3>${esc(removalLabel(r))}</h3></div>
   <div class="vehicle-vin-row"><span>VIN</span><strong>${esc(r.vin)}</strong></div>
   <div class="vehicle-dealer-warning"><strong>⚑ Facebook listing still needs manual deletion</strong>${valid?`<div>${esc(r.open_url)}</div>`:'<div>No valid saved Facebook listing link. The reminder is kept; find and delete this post manually on Facebook Marketplace.</div>'}</div>
   <div class="vehicle-card-actions">
    <button type="button" class="btn secondary" data-delete-open="${esc(r.vin)}">Delete Listing ↗</button>
    <button type="button" class="btn primary" data-delete-confirm="${esc(r.vin)}">I've deleted it on Facebook</button>
    </div></div></article>`;}).join('');
 const candidateSection=candidateHtml?`<div class="delete-listing-section"><h3 class="delete-listing-section-title">Needs stock verification (${shownCandidates.length})</h3><div class="vehicle-grid cleanup-list">${candidateHtml}</div></div>`:'';
 const pendingSection=pendingHtml?`<div class="delete-listing-section"><h3 class="delete-listing-section-title">Pending Facebook deletion (${shownPending.length})</h3><div class="vehicle-grid cleanup-list">${pendingHtml}</div></div>`:'';
 const warning=cleanupError?`<div class="cleanup-status-warning" role="alert"><strong>Availability review status could not be refreshed</strong><div>${esc(cleanupError)}</div><div>Pending Facebook deletion reminders remain visible below. <button type="button" class="btn ghost" data-cleanup-retry>Retry</button></div></div>`:'';
 $('vehicle-grid').innerHTML=warning+(candidateSection+pendingSection||`<div class="empty"><strong>${candidates.length||rows.length?'No matching Delete Listing vehicles':'No vehicles need Delete Listing action'}</strong><p>${candidates.length||rows.length?'Clear or change the search.':'Tracked or pending unavailable vehicles will appear here after availability review.'}</p></div>`);
}
function openFacebookForDeletion(vin){
 const row=(state.removals||[]).find(r=>r.vin===vin&&r.status==='PENDING_FB_DELETE');
 const url=row?safeFacebookUrl(row.open_url):'';
 if(!url)return notify('No valid saved Facebook listing link for this vehicle. The deletion reminder is kept; find the post on Facebook Marketplace manually.',true);
 window.open(url,'_blank','noopener,noreferrer');
}
function openTrackedListing(vin){
 const row=trackedCleanupCandidates().find(r=>r.vin===vin);
 const url=row?safeFacebookUrl(row.draft?.published_url||''):'';
 if(!url)return notify('No valid saved Facebook listing link for this vehicle.',true);
 window.open(url,'_blank','noopener,noreferrer');
}
const removalBusy=new Set();
async function removalAction(vin,body,okMessage){
 if(removalBusy.has(vin))return;
 removalBusy.add(vin);
 try{const result=await api('/api/action',{vin,...body});delete cleanupIssues[vin];setState(result.state);notify(okMessage);}
 catch(e){notify('Not saved: '+e.message,true);void reload();}
 finally{removalBusy.delete(vin);}
}
function removeOutOfStock(vin){
 const car=state.vehicles.find(r=>r.vin===vin);if(!car)return;
 const tracked=car.listed?' A Delete Listing reminder will be created for its Facebook listing; LotRadar will NOT delete the Facebook post.':'';
 if(!window.confirm(`Have you verified that ${name(primary(car))} (VIN ${vin}) is no longer available at the dealership?\n\nThis removes it from active inventory. Nothing is permanently deleted and you can restore it.${tracked}`))return;
 void removalAction(vin,{action:'remove_out_of_stock',explicit_out_of_stock_confirmation:true},'Removed from active inventory.');
}
function confirmFacebookDeleted(vin){
 const row=pendingRemovals().find(r=>r.vin===vin);if(!row)return;
 if(!window.confirm(`Confirm that you manually deleted the Facebook Marketplace listing for ${removalLabel(row)}?\n\nLotRadar will clear the reminder and move its local tracking record to the 30-day Trash.`))return;
 void removalAction(vin,{action:'confirm_facebook_deleted',explicit_manual_facebook_deletion:true,expected_listing_url:row.listing_url},'Reminder cleared. Local tracking archived to Trash for 30 days.');
}
function restoreRemoved(vin){
 const row=(state.removals||[]).find(r=>r.vin===vin);if(!row)return;
 const note=row.status==='PENDING_FB_DELETE'?'\n\nThis also cancels its pending Facebook deletion reminder; its Facebook tracking is unchanged.':row.status==='FB_DELETE_CONFIRMED'?'\n\nIts local Facebook tracking was already archived to Trash; restore it there separately if needed.':'';
 if(!window.confirm(`Restore ${removalLabel(row)} to active inventory?${note}`))return;
 void removalAction(vin,{action:'restore_removed',explicit_confirmation:true},'Restored to active inventory.');
}
function installHandlers(){installDealerScanControls();document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.tab;vehicleVisible=60;renderGrid();if(tab==='outstock'||tab==='deletelisting')void refreshCleanupStatus();}));
 $('search').addEventListener('input',e=>{search=e.target.value;vehicleVisible=60;clearTimeout(searchRenderTimer);searchRenderTimer=setTimeout(()=>{searchRenderTimer=null;renderGrid()},110);});
 $('vehicle-show-more').addEventListener('click',()=>{vehicleVisible+=60;renderGrid();});
 inventoryFilterIds.forEach(id=>$(id).addEventListener('input',()=>{vehicleVisible=60;renderGrid();}));
 ['inventory-sort-up','inventory-sort-down'].forEach((id,index)=>$(id).addEventListener('click',()=>{
  const picker=$('inventory-sort');
  const pair=inventorySortPairs.find(options=>options.includes(picker.value))||inventorySortPairs[0];
  picker.value=pair[index];
  vehicleVisible=60;
  renderGrid();
 }));
 $('inventory-reset').addEventListener('click',()=>{
  inventoryFilterIds.forEach(id=>{$(id).value=id==='inventory-sort'?'priority':'';});
  search='';$('search').value='';vehicleVisible=60;renderGrid();
 });
 $('btn-import').addEventListener('click',()=>{$('import-overlay').hidden=false;});
 $('btn-import-external').addEventListener('click',()=>{$('external-overlay').hidden=false;});
 $('external-form').addEventListener('submit',previewExternalFile);
 $('external-confirm-btn').addEventListener('click',commitExternalFile);
 $('external-file').addEventListener('change',()=>{externalImportDraft=null;$('external-confirm-btn').disabled=true;});
 $('external-source').addEventListener('change',()=>{externalImportDraft=null;$('external-confirm-btn').disabled=true;});
 $('enrich-submit').addEventListener('click',saveEnrichment);
 $('btn-site-scan').addEventListener('click',()=>{$('site-scan-overlay').hidden=false;});
 $('basic-catalog-panel').addEventListener('toggle',renderBasicCatalog);
 $('basic-more').addEventListener('click',()=>{basicVisible+=60;renderBasicCatalog();});
 $('btn-chrome-scan').addEventListener('click',()=>beginInventoryScan(false));
 $('btn-quick-scan').addEventListener('click',()=>beginInventoryScan(true));
 $('btn-full-scan').addEventListener('click',beginFullScan);
 $('btn-reader-setup').addEventListener('click',showChromeScanner);
 $('btn-facebook-scan').addEventListener('click',checkAllFacebook);$('btn-facebook-cancel').addEventListener('click',cancelFacebookBulk);$('btn-facebook-retry').addEventListener('click',retryFailedFacebook);
 $('chrome-start').addEventListener('click',async()=>{closeOverlay('chrome-bridge');await beginInventoryScan();});
 $('chrome-retry').addEventListener('click',showChromeScanner);
 $('chrome-copy-key').addEventListener('click',async()=>{const key=$('chrome-pair-key').value;if(!/^[A-Za-z0-9_-]{32,80}$/.test(key))return notify('No valid key loaded. Select Retry.',true);try{await navigator.clipboard.writeText(key);notify('Pairing key copied for the local Chrome extension.');}catch{notify('Copy blocked: select and copy the key manually.',true);}});
 $('btn-scan-console').addEventListener('click',openScanConsole);
 $('scan-dock').addEventListener('click',openScanConsole);
 $('console-download').addEventListener('click',downloadScanDiagnostics);
 $('btn-verify').addEventListener('click',verifyInventory);
 $('btn-recheck-outstock').addEventListener('click',recheckOutstock);
 $('btn-fetch-missing-photos').addEventListener('click',fetchMissingInventoryPhotos);
 const repairButton=document.createElement('button');repairButton.type='button';repairButton.className='btn secondary';repairButton.dataset.act='refresh-business-cards';repairButton.textContent='Refresh business cards';repairButton.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();$('more-scans').open=false;void onDetailAction('refresh-business-cards');});
 const reportButton=document.createElement('button');reportButton.type='button';reportButton.className='btn secondary';reportButton.dataset.act='business-card-report';reportButton.textContent='Business-card diagnostic report';
 $('btn-fetch-missing-photos').after(repairButton,reportButton);
 const readyButton=document.createElement('button');readyButton.type='button';readyButton.className='btn primary';readyButton.dataset.act='get-trade-ready';readyButton.textContent='Get trade-in priority ready';$('section-title').after(readyButton);

 $('btn-full-stop').addEventListener('click',stopFullScan);
 $('live-verify-pause').addEventListener('click',()=>changeVerification($('live-verify-pause').dataset.paused==='1'?'resume':'pause'));
 $('live-verify-stop').addEventListener('click',()=>changeVerification('stop'));
 $('more-scans').addEventListener('click',e=>{if(e.target.closest('button'))$('more-scans').open=false;});
 $('live-verify-hide').addEventListener('click',()=>closeOverlay('live-verify'));
 $('btn-verify-report').addEventListener('click',()=>{
  $('advanced-tools').open=false;
  $('live-verify-overlay').hidden=false;
  void refreshLiveVerifyStatus();
 });
 $('live-verify-export').addEventListener('click',async()=>{
  try{
   const resp=await fetch('/api/live-verify-status',{headers:{'X-SalesmanHub-Token':csrf}});
   if(!resp.ok)throw Error('Live report unavailable');
   const data=await resp.json(),blob=new Blob([JSON.stringify(data.verification,null,2)],{type:'application/json'});
   const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;
   a.download='marketplace-live-verification-'+new Date().toISOString().slice(0,10)+'.json';
   document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){notify('Report download failed: '+e.message,true)}
 });
 $('site-start-confirm').addEventListener('click',beginSiteScan);
 $('btn-sync').addEventListener('click',refreshFeeds);$('btn-export').addEventListener('click',exportData);
 $('import-form').addEventListener('submit',importFile);
 document.addEventListener('click',e=>{const dismissed=e.target.closest('[data-dismiss]');if(dismissed)return closeOverlay(dismissed.dataset.dismiss);const basic=e.target.closest('[data-basic-url]');if(basic){openEnrichCandidate(basic.dataset.basicUrl,basic.dataset.basicSource);return;}const button=e.target.closest('[data-act]');if(button){const a=button.dataset.act;if(a==='open-import'){$('import-overlay').hidden=false;return;}if(a==='copy-facebook-compare'){void copyFacebookComparison(button);return;}void onDetailAction(a);return;}
 const thumb=e.target.closest('[data-gallery-index]');
 if(thumb&&selectedVin){const idx=Number(thumb.dataset.galleryIndex)||0;
    const priorError=exportPreview.failed.get(idx)||'';
    if(priorError.includes('export_preview_changed')){
      resetExportPreview();void toggleExportPreview();return;
    }
    if(exportPreview.failed.has(idx))exportPreview.failed.delete(idx);
    gallery.index=idx;
    const frame=exportPreview.photos[idx];
    if(!thumb.hasAttribute('data-preview-only')&&frame&&selectionActive())togglePhotoKey(exportFrameKey(frame));else renderDetail();
    if(exportPreview.revision&&!exportPreview.urls.has(idx))void loadExportPreviewFrame(idx);
    return;}
 const photoExport=e.target.closest('[data-photos-vin]');if(photoExport){e.preventDefault();e.stopPropagation();void downloadPhotoZip(photoExport.dataset.photosVin);return;}
 const cleanupRetry=e.target.closest('[data-cleanup-retry]');if(cleanupRetry){e.preventDefault();e.stopPropagation();void refreshCleanupStatus();return;}
 for(const [attr,fn] of [['outstockRemove',removeOutOfStock],['trackedConfirm',removeOutOfStock],['trackedListingOpen',openTrackedListing],['deleteOpen',openFacebookForDeletion],['deleteConfirm',confirmFacebookDeleted],['restoreRemoved',restoreRemoved]]){
  const control=e.target.closest('[data-'+attr.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())+']');
  if(control){e.preventDefault();e.stopPropagation();fn(control.dataset[attr]);return;}}
 const refresh=e.target.closest('[data-refresh-vin]');if(refresh){e.preventDefault();e.stopPropagation();void refreshOneVehicle(refresh.dataset.refreshVin);return;}
 if(e.target.closest('a,input,label,button')&&e.target.closest('[data-cleanup-vin]'))return;
 const facebook=e.target.closest('[data-card-facebook]');if(facebook){e.stopPropagation();return;}
 const card=e.target.closest('[data-vin]');if(card)openDetail(card.dataset.vin);});
 $('drawer-content').addEventListener('click',e=>{if(e.target.matches('.quick-select'))e.target.select();});
 $('drawer-content').addEventListener('input',e=>{
  if(e.target.id==='tracked-facebook-url'){if(facebookUrlEdit?.vin===selectedVin)facebookUrlEdit.url=e.target.value;return;}
  if(e.target.id!=='draft-title'&&e.target.id!=='draft-description')return;
  const record=state.vehicles.find(v=>v.vin===selectedVin);
  if(!record?.draft)return;
  draftEditBuffer={vin:selectedVin,updated_at:record.draft.updated_at,
    snapshot_hash:record.draft.snapshot_hash,
    title:$('draft-title')?.value??record.draft.title,
    description:$('draft-description')?.value??record.draft.description};
 });

 $('drawer-content').addEventListener('keydown',e=>{if(e.target.id!=='tracked-facebook-url'||facebookUrlEdit?.vin!==selectedVin)return;
  if(e.key==='Enter'){e.preventDefault();void toggleFacebookUrl();}
  if(e.key==='Escape'){e.stopPropagation();facebookUrlEdit=null;renderDetail();}
 });

 $('dealer-console-toggle').addEventListener('click',()=>{const body=$('dealer-console-body'),show=body.hidden;body.hidden=!show;$('dealer-console-toggle').textContent=show?'Hide console':'Show console';$('dealer-console-toggle').setAttribute('aria-expanded',String(show));});
 $('vehicle-grid').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-vin]')){e.preventDefault();openDetail(e.target.dataset.vin);}});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(!$('chrome-bridge-overlay').hidden)closeOverlay('chrome-bridge');else if(!$('enrich-overlay').hidden)closeOverlay('enrich');else if(!$('external-overlay').hidden)closeOverlay('external');else if(!$('import-overlay').hidden)closeOverlay('import');else if(!$('site-scan-overlay').hidden)closeOverlay('site-scan');else if(!$('live-verify-overlay').hidden)closeOverlay('live-verify');else if(!$('scan-console-overlay').hidden)closeOverlay('scan-console');else if(!$('detail-overlay').hidden)closeOverlay('detail');}});
 $('theme-toggle').addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=next;try{localStorage.setItem('marketplace-theme',next)}catch{};});}
function installListingTrashButton(){if($('btn-listing-trash')){$('btn-listing-trash').addEventListener('click',openListingTrash);return;}const host=document.querySelector('.sidenav');if(!host)return;const button=document.createElement('button');button.type='button';button.id='btn-listing-trash';button.className='btn secondary';button.textContent='🗑 Trash';button.title='Restore local listing records within 30 days';host.appendChild(button);button.addEventListener('click',openListingTrash);}
async function init(){try{let theme;try{theme=localStorage.getItem('marketplace-theme')}catch{};if(theme==='light'||theme==='dark')document.documentElement.dataset.theme=theme;installHandlers();installPhotoSettings();installScanDockClose();installListingTrashButton();const boot=await api('/api/bootstrap');csrf=boot.csrf;await loadPhotoSettings();await reload();await refreshCleanupStatus();await loadBasicCatalog();await pollDealerScanControls();await refreshSiteScanStatus();await refreshLiveVerifyStatus();await refreshFacebookBulkStatus();await refreshFullScanStatus();await refreshDealerConsole();
 setInterval(()=>{if(!document.hidden&&selectedVin&&(!gallery.cache||gallery.cache.pending))void refreshPhotoStatus()},6500);
 setInterval(()=>{if(!document.hidden){void refreshDealerConsole();void refreshReaderSetup();if(tab==='outstock'||tab==='deletelisting'||lastScanJob?.running)void refreshCleanupStatus();}},3000);
 // Recover scan monitoring after page refresh, even if the console is hidden.
 if(lastScanJob?.running){scanDockEnabled=true;updateScanDock(lastScanJob);siteScanTimer=setInterval(()=>{if(!document.hidden)void refreshSiteScanStatus()},1700);}
 // A server-owned Full Scan remains running if the user reloads Marketplace.
 if($('btn-full-scan').disabled&&!fullScanPollTimer)fullScanPollTimer=setInterval(()=>{if(!document.hidden)void refreshFullScanStatus()},2800);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)return;if(selectedVin)void refreshPhotoStatus();if(liveVerifyTimer)void refreshLiveVerifyStatus();if(siteScanTimer)void refreshSiteScanStatus();});
 }
 catch(e){$('vehicle-grid').innerHTML=`<div class="empty"><strong>Local service unavailable</strong><p>${esc(e.message)}. Start SalesmanHub Marketplace using Launch Marketplace.cmd and reload this page.</p></div>`;notify('Local preview service unavailable.',true);}}
init();


window.addEventListener('load',()=>{
 const match=location.hash.match(/^#vehicle-form=([A-Za-z0-9_-]{32})$/);
 if(!match)return;
 history.replaceState(null,'',location.pathname+location.search);
 window.dispatchEvent(new CustomEvent('lotradar:vehicle-form',{detail:{handoff:match[1]}}));
});
