/* R39: explicit active-tab Facebook item/edit capture. NO VIN selectors, scanning, or importing. */
(() => {
  const u=new URL(location.href);
  if(u.protocol!=='https:'||!['www.facebook.com','facebook.com','m.facebook.com'].includes(u.hostname))
    return {error:'open_a_facebook_marketplace_listing_first'};
  const path=u.pathname.replace(/\/$/,'');
  const match=path.match(/^\/marketplace\/item\/(\d{8,24})$/);
  const listingId=match?.[1]||(path==='/marketplace/edit'?u.searchParams.get('listing_id'):'');
  if(!/^\d{8,24}$/.test(listingId||''))return {error:'open_the_item_or_own_edit_link'};
  const isEdit=path==='/marketplace/edit';
  const clean=t=>String(t||'').replace(/[\x00-\x1f\x7f]/g,' ').replace(/[ \t]+/g,' ').trim();
  const isVisible=el=>!!(el?.getClientRects?.().length);
  // Explicit label / field only. No body dump, Facebook messages, VIN or cookies.
  const matches=(text,pattern)=>pattern.test(clean(text));
  const controls=[...document.querySelectorAll('input,textarea,[contenteditable="true"],[role="textbox"]')]
    .filter(isVisible).slice(0,160);
  function label(el){
    const aria=el.getAttribute('aria-label')||el.getAttribute('placeholder')||el.getAttribute('data-testid')||'';
    const group=el.closest('label');
    const title=group?.querySelector('span,strong')?.textContent||'';
    const associated=el.id?document.querySelector('label[for="'+CSS.escape(el.id)+'"]')?.textContent||'':'';
    return clean(aria||associated||title);
  }
  function field(rx,max=4000){
    const el=controls.find(e=>matches(label(e),rx));
    if(!el)return '';
    return clean(('value' in el?el.value:el.innerText)||'').slice(0,max);
  }
  const numeric=(raw,kind)=>{
    if(!raw)return null;
    const s=String(raw).replace(/\s/g,'');
    if(kind==='price'&&!/^\$?[\d,]+(?:\.\d{1,2})?$/.test(s))return null;
    if(kind==='mileage'&&!/^[\d,]+(?:mi|miles|km)?$/i.test(s))return null;
    const n=Number(s.replace(/[^\d.]/g,''));
    return Number.isInteger(n)&&n>=0&&n<=(kind==='price'?5000000:2000000)?n:null;
  };
  // Edit form fields have priority. Metadata/semantic headings are fallback only.
  const fields={
    title:field(/^(?:title|listing title|vehicle title|name)$/i,180),
    description:field(/^(?:description|listing description|details)$/i,5000),
    price:numeric(field(/^(?:price|asking price|listing price)$/i,40),'price'),
    mileage:numeric(field(/^(?:mileage|odometer|miles driven)$/i,40),'mileage')
  };
  const main=document.querySelector('main,[role="main"]')||document;
  // Facebook's public item page often renders the actual vehicle title in H2,
  // role=heading or a short visible span, not H1. H1 may be only "Marketplace".
  // Read only short, title-like fields; never use a whole-page text dump or VIN.
  if(!isEdit&&[...main.querySelectorAll('h1,h2,[role="heading"],span[dir="auto"]')].slice(0,160).some(el=>
    isVisible(el)&&/^(?:this listing is no longer available|this item is no longer available|this listing isn't available)\.?$/i.test(clean(el.textContent))))
    return {url:u.href,error:'facebook_listing_unavailable'};
  const normalizeTitle=t=>clean(t).replace(/^[\s*#🔥⭐★-]+/gu,'').replace(/[\s*#🔥⭐★-]+$/gu,'').trim().slice(0,180);
  const plausibleVehicleTitle=t=>/^(?:19[8-9]\d|20\d{2})\s+[a-z0-9][\w-]*(?:\s+[a-z0-9][\w-]*){1,14}$/i.test(t)&&t.length<=125;
  const titleCandidates=[];
  const consider=(t,weight)=>{
    const candidate=normalizeTitle(t);
    if(plausibleVehicleTitle(candidate))titleCandidates.push({value:candidate,weight});
  };
  consider(fields.title,120);
  const selectors='h1,h2,h3,[role="heading"],[data-testid*="title" i],[aria-label*="title" i]';
  const headingElements=[...main.querySelectorAll(selectors)].slice(0,130);
  for(const el of headingElements){
    if(!isVisible(el))continue;
    const tag=el.tagName.toLowerCase();
    const weight=tag==='h1'?110:tag==='h2'?100:tag==='h3'?95:el.getAttribute('role')==='heading'?95:80;
    consider(el.textContent,weight);
  }
  // React sometimes uses a short <span dir="auto"> instead of a semantic heading.
  // Only inspect short, visible text within the selected listing's main area.
  if(!titleCandidates.length && main!==document){
    for(const el of [...main.querySelectorAll('span[dir="auto"],[data-ad-preview="message"]')].slice(0,110)){
      if(isVisible(el)&&clean(el.textContent).length<=125)consider(el.textContent,60);
    }
  }
  // Some Facebook pages expose the item title outside <main>.
  if(!titleCandidates.length&&main!==document){
    for(const el of [...document.querySelectorAll(selectors)].slice(0,160)){
      if(isVisible(el))consider(el.textContent,75);
    }
  }
  consider(document.querySelector('meta[property="og:title"]')?.content||'',65);
  consider(document.title,55);
  // Seller-authored descriptions commonly start with a short model heading.
  // Only inspect the first line of the already extracted DESCRIPTION field.
  // Do not mistake a long selling paragraph for a listing title.
  if(fields.description){
    const firstLine=fields.description.split(/\n|\r|\u2022/)[0].slice(0,180);
    consider(firstLine,35);
    const firstBold=fields.description.match(/(?:19[8-9]\d|20\d{2})\s+[a-z0-9][\w-]*(?:\s+[a-z0-9][\w-]*){1,10}/i)?.[0];
    if(firstBold&&firstBold.length<=125)consider(firstBold,25);
  }
  if(titleCandidates.length){
    titleCandidates.sort((a,b)=>b.weight-a.weight||a.value.length-b.value.length);
    fields.title=titleCandidates[0].value;
  }else{
    // Do not mislabel "Marketplace" or a generic page heading as a vehicle.
    fields.title='';
  }
  if(fields.price===null){
    const price=[...main.querySelectorAll('[aria-label],[data-testid],h2,h3')].filter(isVisible)
      .slice(0,130).map(el=>[el.getAttribute('aria-label')||'', clean(el.textContent||'')]);
    const value=price.find(([a,t])=>/^(price|asking price|listing price)$/i.test(clean(a)) && t.length<30);
    if(value)fields.price=numeric(value[1],'price');
  }
  if(!fields.description){
    // Only a labeled description, never the entire page or a message thread.
    const description=[...main.querySelectorAll('[aria-label],[data-testid]')].filter(isVisible).find(el=>
      /^(description|listing description)$/i.test(clean(el.getAttribute('aria-label')||'')) &&
      clean(el.textContent||'').length<5000);
    if(description)fields.description=clean(description.textContent).slice(0,5000);
  }
  let status='unknown';
  if([...main.querySelectorAll('[aria-label]')].some(el=>isVisible(el)&&/^(marked sold|sold listing)$/i.test(clean(el.getAttribute('aria-label')))))status='sold';
  const present=Object.entries(fields).filter(([,v])=>v!==''&&v!==null).map(([k])=>k);
  return {url:u.href,title:fields.title,description:fields.description,price:fields.price,mileage:fields.mileage,
          status,fields_found:present,page_type:isEdit?'edit':'item'};
})();
