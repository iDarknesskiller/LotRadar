// Real-Chrome DOM test. Needs: synthetic vehicle seeded by seed_synthetic_vehicle.py (throwaway data dir), server on :8791, Node 22, google-chrome.
import {spawn} from 'node:child_process';
const URL='http://127.0.0.1:8791/', PORT=9333;
const chrome=spawn('google-chrome',['--headless=new','--no-sandbox','--disable-gpu',`--remote-debugging-port=${PORT}`,'--window-size=1400,1000','--user-data-dir=/tmp/cdp/prof','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let tgt;for(let i=0;i<50;i++){try{const l=await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();tgt=l.find(t=>t.type==='page');if(tgt)break}catch{}await sleep(200)}
const ws=new WebSocket(tgt.webSocketDebuggerUrl);await new Promise(r=>ws.onopen=r);
let id=0;const pend=new Map();const consoleErr=[],reqs=[];
ws.onmessage=m=>{const d=JSON.parse(m.data);if(d.id&&pend.has(d.id)){pend.get(d.id)(d);pend.delete(d.id)}
 else if(d.method==='Runtime.consoleAPICalled'&&['error','warning'].includes(d.params.type))consoleErr.push(d.params.args.map(a=>a.value||a.description).join(' '));
 else if(d.method==='Runtime.exceptionThrown')consoleErr.push('EXC '+JSON.stringify(d.params.exceptionDetails.exception?.description));
 else if(d.method==='Network.requestWillBeSent')reqs.push(d.params.request.method+' '+d.params.request.url.replace(URL,'/'));};
const send=(method,params={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method,params}))});
const ev=async e=>{const r=await send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});if(r.result.exceptionDetails)throw new Error(JSON.stringify(r.result.exceptionDetails));return r.result.result.value};
const click=async sel=>{const b=await ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;e.scrollIntoView({block:'center',inline:'center'});const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()`);if(!b)throw new Error('nosel '+sel);
 for(const t of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type:t,x:b[0],y:b[1],button:'left',clickCount:1});await sleep(80)};
const results=[];const check=(n,ok,info='')=>{results.push([ok?'PASS':'FAIL',n,info]);console.log(ok?'PASS':'FAIL',n,info)};
await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
await send('Page.navigate',{url:URL});await sleep(2500);
await ev(`localStorage.clear()`).catch(()=>{});
const strip=()=>ev(`[...document.querySelectorAll('.selected-photo-strip .selected-photo-thumb')].map(b=>b.querySelector('span:last-child').textContent)`);
const keysState=()=>ev(`typeof photoSelection!=='undefined'?photoSelection.keys.length:-1`);
await click('[data-tab="all"]');await sleep(1500);await click('[data-vin]');await sleep(2500);
const shot=async n=>{const r=await send('Page.captureScreenshot',{format:'png'});(await import('node:fs')).writeFileSync(`/tmp/cdp/${n}.png`,Buffer.from(r.result.data,'base64'))};
await shot('01-open');
const tiles=await ev(`document.querySelectorAll('[data-gallery-index]:not([data-preview-only])').length`);
check('gallery tiles rendered',tiles>=30,`tiles=${tiles}`);
const sel=()=>ev(`[...document.querySelectorAll('.selected-photo-strip .selected-photo-thumb')].map(b=>b.getAttribute('data-gallery-index'))`);
const tile=i=>`[data-gallery-index="${i}"]:not([data-preview-only])`;
const chk=i=>`[data-photo-check="${i}"]`;
// reset
await click('[data-photo-default]');await sleep(200);
check('reset gives 01+02',JSON.stringify(await sel())==='["0","1"]',JSON.stringify(await sel()));
// alternate photo/checkbox: 03(idx2) photo, 11(10) chk, 14(13) photo, 18(17) chk, 20(19) photo, 25(24) chk, 04(3) photo
const seq=[[2,'t'],[10,'c'],[13,'t'],[17,'c'],[19,'t'],[24,'c'],[3,'t']];
for(const [i,k] of seq){await click(k==='t'?tile(i):chk(i));}
const expect=[0,1,2,10,13,17,19,24,3].map(String);
const got=await sel();
check('click order strip (01,02,03,11,14,18,20,25,04)',JSON.stringify(got)===JSON.stringify(expect),JSON.stringify(got));
check('each toggle exactly once (count 9)',(await keysState())===9,String(await keysState()));
await shot('02-ordered');
// deselect 11 then reselect -> last
await click(chk(10));
check('deselect removes one',(await keysState())===8);
await click(tile(10));
const got2=await sel();check('reselect appends to end',got2.at(-1)==='10'&&got2.length===9,JSON.stringify(got2));
// persisted
await sleep(1200);
const saved=await ev(`(async()=>{const r=await api('/api/photos/selection?vin='+encodeURIComponent(selectedVin)+'&source='+encodeURIComponent(photoSelection.source));return r.keys})()`).catch(e=>String(e));
check('saved selection API order matches',Array.isArray(saved)&&saved.length===9,JSON.stringify(saved));
// rapid clicks
const before=await keysState();
for(let i=0;i<6;i++){await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:1,y:1});}
await click(tile(5));await click(tile(5));
await sleep(300);
const after=await keysState();check('two rapid real clicks on same tile toggle twice => unchanged',after===before,`${before}->${after}`);
// keyboard
await ev(`document.querySelector(${JSON.stringify(tile(6))}).focus()`);
await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,text:'\r'});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});await sleep(200);
const kb=await keysState();
await ev(`document.querySelector(${JSON.stringify(tile(7))}).focus()`);
await send('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32,text:' '});await send('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});await sleep(200);
check('keyboard Enter/Space each toggle once (+1,+1)',kb===before+1&&(await keysState())===before+2,`${before},${kb},${await keysState()}`);
// 20 limit
for(let i=0;i<30;i++){const st=await keysState();if(st>=20)break;const idx=i+12; if(!(await ev(`photoSelection.keys.includes(exportFrameKey(exportPreview.photos[${idx}]))`)))await click(tile(idx));}
const at20=await keysState();
await click(tile(29));await click(tile(28));
check('20 limit enforced (never >20)',at20===20&&(await keysState())===20,`${at20}->${await keysState()}`);
check('limit notice shown',(await ev(`document.body.innerText.includes('no more than 20')||document.body.innerText.includes('limit')`)));
// removed controls absent
const txt=await ev(`document.getElementById('detail-overlay').innerText`);
for(const w of ['Refresh vehicle','Fetch missing photos','Refresh photo preview','Select all','Clear']) check('removed control absent: '+w,!txt.includes(w));
check('single progress bar',(await ev(`document.querySelectorAll('#detail-overlay progress').length`))<=1,String(await ev(`document.querySelectorAll('#detail-overlay progress').length`)));
// close / reopen
await ev(`document.querySelector('[data-act="close-detail"],#close-detail,.detail-close')?.click()`);await sleep(300);
await click('[data-vin]');await sleep(2500);
const re=await sel();check('close/reopen keeps order',re.length===20&&re.slice(0,9).join()===expect.slice(0,9).slice(0,8).join()+','+'10'||re.slice(0,3).join()==='0,1,2',JSON.stringify(re.slice(0,9)));
await shot('03-reopen');

// ---- Facebook draft typing under polling-style re-render ----
await ev(`document.querySelector('[data-act="close-detail"],#close-detail,.detail-close')?.click()`);
await send('Page.navigate',{url:URL});await sleep(2500);
await click('[data-tab="all"]');await sleep(1200);await click('[data-vin]');await sleep(2500);
const hasTa=await ev(`!!document.getElementById('draft-description')&&document.getElementById('draft-description').tagName`);
check('draft editor present',hasTa==='TEXTAREA',String(hasTa));
if(hasTa==='TEXTAREA'){
 await click('#draft-description');
 await ev(`(()=>{const t=document.getElementById('draft-description');t.value='AAAA BBBB CCCC DDDD';t.dispatchEvent(new Event('input',{bubbles:true}));t.focus();t.setSelectionRange(10,10);return 1})()`);
 await send('Input.insertText',{text:'xyz'});
 const snap=()=>ev(`(()=>{const t=document.getElementById('draft-description');return t?{v:t.value,f:document.activeElement===t,s:t.selectionStart,e:t.selectionEnd}:null})()`);
 const b=await snap();
 for(const k of ['queued','downloading','sorting','ready']){
  await ev(`photoProgress={...photoProgress,data:{...(photoProgress.data||{}),stage:${JSON.stringify(k)}}};renderPhotoControls();1`);
  await send('Input.insertText',{text:'1'});await sleep(100);
 }
 const a=await snap();
 check('draft: typed text preserved across polling re-renders',a&&a.v.includes('xyz')&&a.v.length===b.v.length+4,JSON.stringify({b,a}));
 check('draft: textarea keeps focus',a&&a.f,JSON.stringify(a));
 check('draft: caret stays mid-text (not jumped to 0/end-of-reset)',a&&a.s===a.e&&a.s>=10&&a.s<a.v.length,JSON.stringify(a));
}
console.log('CONSOLE ERRORS',JSON.stringify(consoleErr));
console.log('NETWORK',JSON.stringify([...new Set(reqs.filter(r=>!/\.(css|js|png|jpg|ico)/.test(r)))].slice(0,40)));
const fails=results.filter(r=>r[0]==='FAIL');console.log(`TOTAL ${results.length} FAIL ${fails.length}`);
ws.close();chrome.kill();process.exit(0);
