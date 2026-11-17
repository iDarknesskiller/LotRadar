// Real-Chrome DOM test for the photo picker. Fully self-contained and isolated:
//   * copies the repo into a throwaway temp dir (never the installed app / owner data / production branding),
//   * seeds ONE synthetic vehicle (synthetic images, synthetic business card + dedication),
//   * starts the server on a free port, launches Chrome on a free debugging port with a temp profile,
//   * exits NONZERO if any assertion fails, setup throws, or too few checks ran; always cleans up Chrome/server/temp dir.
// Usage: node tests/browser/picker_dom.mjs        (needs Node 22, python3 + Pillow, google-chrome; CHROME_BIN overrides)
// Test-only fault flag: PICKER_DOM_INJECT_FAIL=1 adds one deliberately failing check (used to prove the exit code).
import {spawn,spawnSync} from 'node:child_process';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';
import {fileURLToPath} from 'node:url';

const REPO=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..','..');
const MIN_CHECKS=50;                       // a run that executes fewer checks than this is a failure
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const results=[];
const check=(name,ok,info='')=>{results.push({name,ok:!!ok});console.log(ok?'PASS':'FAIL',name,info===''?'':String(info).slice(0,300));};
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const freePort=()=>new Promise((res,rej)=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>res(p));});s.on('error',rej);});

let tmp='',server=null,chrome=null,ws=null;
// Last-resort cleanup: runs even on an uncaught exception, signal, or spawn failure, and never hides a failure.
const killChildren=()=>{try{chrome&&chrome.kill('SIGKILL');}catch{}try{server&&server.kill('SIGKILL');}catch{}};
process.on('exit',killChildren);
for(const sig of ['SIGINT','SIGTERM'])process.on(sig,()=>{killChildren();process.exit(130);});
process.on('uncaughtException',e=>{console.log('FAIL uncaught exception: '+(e&&e.message||e));killChildren();process.exit(1);});
process.on('unhandledRejection',e=>{console.log('FAIL unhandled rejection: '+(e&&e.message||e));killChildren();process.exit(1);});
const consoleErr=[],reqs=[];
let evidence='';

async function main(){
 tmp=fs.mkdtempSync(path.join(os.tmpdir(),'lotradar-dom-'));
 evidence=process.env.EVIDENCE_DIR||path.join(tmp,'evidence');fs.mkdirSync(evidence,{recursive:true});
 const app=path.join(tmp,'app'),data=path.join(tmp,'data');
 fs.cpSync(REPO,app,{recursive:true,filter:s=>!/[\\/](\.git|node_modules|__pycache__|docs|tests)([\\/]|$)/.test(s)});
 const seed=spawnSync('python3',[path.join(REPO,'tests/browser/seed_synthetic_vehicle.py'),app,data,'40','32'],{encoding:'utf8'});
 check('seed synthetic vehicle',seed.status===0,(seed.stdout+seed.stderr).trim().split('\n').pop());
 if(seed.status!==0)return;
 const port=await freePort(),dbg=await freePort();
 const URL=`http://127.0.0.1:${port}/`;
 server=spawn('python3',['server.py','--data-dir',data,'--port',String(port),'--no-browser'],{cwd:app,stdio:'ignore'});server.on('error',e=>console.log('server spawn error: '+e.message));
 let up=false;for(let i=0;i<60&&!up;i++){try{up=(await fetch(URL)).ok;}catch{}if(!up)await sleep(250);}
 check('server started',up);if(!up)return;
 chrome=spawn(process.env.CHROME_BIN||'google-chrome',['--headless=new','--no-sandbox','--disable-gpu',`--remote-debugging-port=${dbg}`,'--window-size=1400,1000',`--user-data-dir=${path.join(tmp,'profile')}`,'about:blank'],{stdio:'ignore'});chrome.on('error',e=>console.log('chrome spawn error: '+e.message));
 let tgt;for(let i=0;i<60&&!tgt;i++){try{tgt=(await (await fetch(`http://127.0.0.1:${dbg}/json`)).json()).find(t=>t.type==='page');}catch{}if(!tgt)await sleep(250);}
 check('chrome devtools reachable',!!tgt);if(!tgt)return;
 ws=new WebSocket(tgt.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=()=>j(new Error('ws error'));});
 let id=0;const pend=new Map();
 ws.onmessage=m=>{const d=JSON.parse(m.data);
  if(d.id&&pend.has(d.id)){pend.get(d.id)(d);pend.delete(d.id);}
  else if(d.method==='Runtime.consoleAPICalled'&&['error','warning'].includes(d.params.type))consoleErr.push(d.params.args.map(a=>a.value||a.description).join(' '));
  else if(d.method==='Runtime.exceptionThrown')consoleErr.push('EXC '+(d.params.exceptionDetails.exception?.description||d.params.exceptionDetails.text));
  else if(d.method==='Network.requestWillBeSent')reqs.push(d.params.request.method+' '+d.params.request.url.replace(URL,'/'));};
 const send=(method,params={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method,params}));});
 const ev=async e=>{const r=await send('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});if(r.result.exceptionDetails)throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0,300));return r.result.result.value;};
 const click=async sel=>{const b=await ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;e.scrollIntoView({block:'center',inline:'center'});const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()`);
  if(!b)throw new Error('selector not found: '+sel);
  for(const t of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type:t,x:b[0],y:b[1],button:'left',clickCount:1});await sleep(90);};
 const shot=async n=>{const r=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(evidence,n+'.png'),Buffer.from(r.result.data,'base64'));};
 const key=async(k,code,vk,text)=>{await send('Input.dispatchKeyEvent',{type:'keyDown',key:k,code,windowsVirtualKeyCode:vk,...(text?{text}:{})});await send('Input.dispatchKeyEvent',{type:'keyUp',key:k,code,windowsVirtualKeyCode:vk});await sleep(200);};
 await send('Runtime.enable');await send('Network.enable');await send('Page.enable');

 const open=async()=>{await send('Page.navigate',{url:URL});await sleep(2500);await click('[data-tab="all"]');await sleep(1200);await click('[data-vin]');await sleep(3500);};
 const tile=i=>`[data-gallery-index="${i}"]:not([data-preview-only])`,chk=i=>`[data-photo-check="${i}"]`;
 // Page-side truth, all as exact arrays of stable photo keys (dedication has key "dedication").
 const keyOf=i=>ev(`exportFrameKey(exportPreview.photos[${i}])`);
 const stateKeys=()=>ev(`[...photoSelection.keys]`);
 const stripKeys=()=>ev(`[...document.querySelectorAll('.selected-photo-strip .selected-photo-thumb')].map(b=>exportFrameKey(exportPreview.photos[+b.getAttribute('data-gallery-index')]))`);
 const apiKeys=()=>ev(`(async()=>{const r=await api('/api/photos/selection?vin='+encodeURIComponent(selectedVin)+'&source='+encodeURIComponent(photoSelection.source));return r.keys})()`);
 const settle=()=>sleep(1300);   // > 400 ms save debounce

 await open();
 const tiles=await ev(`document.querySelectorAll('[data-gallery-index]:not([data-preview-only])').length`);
 check('gallery tiles rendered (32 cached + business card + dedication)',tiles>=33,`tiles=${tiles}`);
 await shot('01-open');

 // ---- exact click order, photo vs checkbox, verified after EVERY transition ----
 await click('[data-photo-default]');await settle();
 let expected=[await keyOf(0),await keyOf(1)];
 check('reset = first two keys (state)',same(await stateKeys(),expected));
 check('reset = first two keys (strip)',same(await stripKeys(),expected));
 check('reset = first two keys (API)',same(await apiKeys(),expected));
 const seq=[[2,'t'],[10,'c'],[13,'t'],[17,'c'],[19,'t'],[24,'c'],[3,'t']];
 for(const [i,k] of seq){
  await click(k==='t'?tile(i):chk(i));expected=[...expected,await keyOf(i)];
  check(`after ${k==='t'?'photo':'checkbox'} click ${i+1}: state keys exact`,same(await stateKeys(),expected),`n=${expected.length}`);
  check(`after ${k==='t'?'photo':'checkbox'} click ${i+1}: strip keys exact`,same(await stripKeys(),expected));
 }
 check('9 selected, order 01,02,03,11,14,18,20,25,04',expected.length===9&&same(await ev(`photoSelection.keys.map(k=>exportPreview.photos.findIndex(p=>exportFrameKey(p)===k)+1)`),[1,2,3,11,14,18,20,25,4]));
 await settle();
 check('API saved keys exactly equal click order',same(await apiKeys(),expected),JSON.stringify((await apiKeys()).length));
 await shot('02-ordered');

 // deselect 11 (checkbox) then reselect via photo -> goes to end
 const k11=await keyOf(10);
 await click(chk(10));expected=expected.filter(x=>x!==k11);
 check('deselect 11: state exact',same(await stateKeys(),expected));
 await click(tile(10));expected=[...expected,k11];
 check('reselect 11: appended to end (state)',same(await stateKeys(),expected)&&expected.at(-1)===k11);
 check('reselect 11: strip exact',same(await stripKeys(),expected));
 await settle();
 check('reselect 11: API exact',same(await apiKeys(),expected));

 // double-trigger / rapid / keyboard
 const before=[...expected];
 await click(tile(5));await click(tile(5));
 check('two rapid real clicks on one tile cancel out (no double trigger)',same(await stateKeys(),before));
 await ev(`document.querySelector(${JSON.stringify(tile(6))}).focus()`);await key('Enter','Enter',13,'\r');
 const afterEnter=[...before,await keyOf(6)];
 check('keyboard Enter toggles exactly once',same(await stateKeys(),afterEnter));
 await ev(`document.querySelector(${JSON.stringify(tile(7))}).focus()`);await key(' ','Space',32,' ');
 const afterSpace=[...afterEnter,await keyOf(7)];
 check('keyboard Space toggles exactly once',same(await stateKeys(),afterSpace));
 expected=afterSpace;

 // 20 limit
 for(let i=12;i<31&&(await stateKeys()).length<20;i++){const k=await keyOf(i);if(!expected.includes(k)){await click(tile(i));expected=[...expected,k];}}
 check('reached exactly 20',(await stateKeys()).length===20&&same(await stateKeys(),expected));
 await click(tile(29));await click(tile(28));
 check('21st/22nd selection refused; array unchanged',same(await stateKeys(),expected));
 check('limit notice shown',await ev(`/no more than 20/i.test(document.body.innerText)`));
 await settle();check('API at limit exact',same(await apiKeys(),expected));
 // drop back to a clean 9-photo sequence for later checks
 await click('[data-photo-default]');expected=[await keyOf(0),await keyOf(1)];
 for(const i of [2,10,13,17,19,24,3]){await click(tile(i));expected=[...expected,await keyOf(i)];}
 await click(tile(10));expected=expected.filter(x=>x!==k11);      // deselect 11 (it was picked in the loop above)
 await click(tile(10));expected=[...expected,k11];                 // reselect 11 -> goes to the end
 check('rebuilt sequence exact (state)',same(await stateKeys(),expected)&&expected.length===9);
 await settle();check('rebuilt sequence exact (API)',same(await apiKeys(),expected));

 // removed controls / single bar
 const txt=await ev(`document.getElementById('detail-overlay').innerText`);
 for(const w of ['Refresh vehicle','Fetch missing photos','Refresh photo preview','Select all','Clear'])check('removed control absent: '+w,!txt.includes(w));
 check('exactly one progress bar',(await ev(`document.querySelectorAll('#detail-overlay progress').length`))===1);

 // ---- close / reopen: whole array ----
 await ev(`document.querySelector('[data-dismiss="detail"],[data-act="close-detail"],#close-detail,.detail-close')?.click()`);await sleep(400);
 await click('[data-vin]');await sleep(3500);
 check('close/reopen (same page): full state array identical',same(await stateKeys(),expected));
 check('close/reopen (same page): full strip identical',same(await stripKeys(),expected));
 // full page reload
 await open();
 check('page reload+reopen: full state array identical',same(await stateKeys(),expected));
 check('page reload+reopen: full strip identical',same(await stripKeys(),expected));
 check('page reload+reopen: full API array identical',same(await apiKeys(),expected));
 await shot('03-reopen');
 // quick close right after a change must still persist the whole new array
 await click(chk(12));const k13=await keyOf(12);expected=[...expected,k13];
 await ev(`document.querySelector('[data-dismiss="detail"],[data-act="close-detail"],#close-detail,.detail-close')?.click()`);
 await sleep(1800);
 await open();
 check('change then immediate close then reload: full array incl. new photo',same(await stateKeys(),expected)&&same(await stripKeys(),expected));

 // ---- genuine background polling with the Facebook draft textarea active ----
 // The seeded vehicle has 8 uncached photos; opening it enqueued a real job, so /api/photos/progress is polled by watchPhotoProgress.
 await ev(`window.__calls={update:0,render:0,progress:0};
  (function(){const u=window.updatePhotoProgressInPlace;window.updatePhotoProgressInPlace=function(){window.__calls.update++;return u.apply(this,arguments)};
   const r=window.renderDetail;window.renderDetail=function(){window.__calls.render++;return r.apply(this,arguments)};})();1`);
 const vinBefore=await ev(`selectedVin`);
 const hasTa=await ev(`document.getElementById('draft-description')?.tagName`);
 check('draft description editor present',hasTa==='TEXTAREA',hasTa);
 if(hasTa==='TEXTAREA'){
  await ev(`(()=>{const t=document.getElementById('draft-description');t.value=Array.from({length:70},(_,i)=>'LINE '+String(i).padStart(2,'0')+' alpha beta gamma').join('\\n');t.dispatchEvent(new Event('input',{bubbles:true}));t.scrollTop=200;t.focus();const p=t.value.indexOf('LINE 20 alpha')+8;t.setSelectionRange(p,p);window.__base=t.value;window.__pos=p;return 1})()`);
  const startStage=await ev(`photoProgress.data&&photoProgress.data.stage`);
  const pollsBefore=reqs.filter(r=>r.startsWith('GET /api/photos/progress')).length;
  let typed='',sawStages=new Set(),baseTop=-1;
  const t0=Date.now();
  while(Date.now()-t0<45000){
   const polls=reqs.filter(r=>r.startsWith('GET /api/photos/progress')).length-pollsBefore;
   const st=await ev(`photoProgress.data&&photoProgress.data.stage`);if(st)sawStages.add(st);
   if(polls>=3&&typed.length>=8)break;
   await send('Input.insertText',{text:'x'});typed+='x';await sleep(600);
   if(typed.length===1)baseTop=await ev(`document.getElementById('draft-description').scrollTop`);
  }
  const polls=reqs.filter(r=>r.startsWith('GET /api/photos/progress')).length-pollsBefore;
  const snap=await ev(`(()=>{const t=document.getElementById('draft-description');return t?{v:t.value,f:document.activeElement===t,s:t.selectionStart,e:t.selectionEnd,top:t.scrollTop,vin:selectedVin,calls:window.__calls}:null})()`);
  const exp=await ev(`window.__base.slice(0,window.__pos)+${JSON.stringify(typed)}+window.__base.slice(window.__pos)`);
  const pos=await ev(`window.__pos`);
  check('real background polling occurred (>=3 GET /api/photos/progress while typing)',polls>=3,`polls=${polls} stages=${[...sawStages]} start=${startStage}`);
  check('progress panel was actually updated by the poll callback',snap&&snap.calls.update+snap.calls.render>=1,JSON.stringify(snap&&snap.calls));
  check('draft text exactly preserved (typed chars at the caret, nothing lost/overwritten)',snap&&snap.v===exp,`typed=${typed.length}`);
  check('draft textarea still focused',snap&&snap.f);
  check('draft caret exactly after typed text, mid-text',snap&&snap.s===snap.e&&snap.s===pos+typed.length&&snap.s<snap.v.length,JSON.stringify(snap&&{s:snap.s,e:snap.e,expected:pos+typed.length}));
  check('draft textarea scroll position retained',snap&&Math.abs(snap.top-baseTop)<=20,`scrollTop=${snap&&snap.top} baseline=${baseTop}`);
  check('still the same vehicle (no VIN switch)',snap&&snap.vin===vinBefore);
  await shot('04-draft-polling');
  // composition is not exercised: headless CDP IME composition is not reliable across Chrome versions
  console.log('NOTE composition/IME input not exercised in headless Chrome');
 }
 const cons=consoleErr.filter(e=>!/favicon|Failed to load resource.*(403|404|net::)/i.test(e));
 check('no console errors/exceptions',cons.length===0,cons.slice(0,3).join(' | '));
 const unexpected=[...new Set(reqs.filter(r=>/^(GET|POST) (https?:\/\/)(?!127\.0\.0\.1)/.test(r)))];
 check('no requests to hosts other than the local server',unexpected.length===0,unexpected.slice(0,3).join(' | '));
 const opens=reqs.filter(r=>r==='POST /api/photos/open').length;
 console.log('REQUEST SUMMARY',JSON.stringify({photosOpen:opens,progressGets:reqs.filter(r=>r.startsWith('GET /api/photos/progress')).length,selectionPosts:reqs.filter(r=>r.startsWith('POST /api/photos/selection')).length,total:reqs.length}));
 if(process.env.PICKER_DOM_INJECT_FAIL==='1')check('INJECTED FAILURE (self-check of exit status)',false);
}

try{await main();}
catch(e){check('harness error: '+(e&&e.message||e),false);}
finally{
 try{ws&&ws.close();}catch{}
 try{chrome&&chrome.kill('SIGKILL');}catch{}
 try{server&&server.kill('SIGKILL');}catch{}
 await sleep(300);
 const fails=results.filter(r=>!r.ok);
 if(results.length<MIN_CHECKS){console.log(`FAIL too few checks executed: ${results.length} < ${MIN_CHECKS}`);fails.push({name:'check-count'});}
 console.log(`TOTAL ${results.length} PASS ${results.length-fails.length} FAIL ${fails.length}  evidence=${evidence}`);
 process.exitCode=fails.length?1:0;
 if(!process.env.KEEP_TMP&&!process.env.EVIDENCE_DIR){try{fs.rmSync(path.join(tmp,'app'),{recursive:true,force:true});fs.rmSync(path.join(tmp,'data'),{recursive:true,force:true});fs.rmSync(path.join(tmp,'profile'),{recursive:true,force:true});}catch{}}
}
