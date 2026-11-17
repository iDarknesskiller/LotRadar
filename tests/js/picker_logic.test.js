// Runs the REAL functions from app.js inside a vm with minimal stubs (no jsdom available offline).
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(__dirname+'/../../app.js','utf8');
function grab(name){const m=src.match(new RegExp('(?:async )?function '+name+'\\('));assert(m,'missing '+name);let i=m.index,depth=0,j=src.indexOf('{',i);for(let k=j;k<src.length;k++){const c=src[k];if(c==='{')depth++;else if(c==='}'){depth--;if(!depth){return src.slice(i,k+1);}}}}
const efk=src.match(/const exportFrameKey=[^\n]*;/)[0];
const names=['orderedPhotoKeys','selectionActive','togglePhotoKey','selectPhotoPreset','photoProgressPanel'];
const notices=[];let changes=0;
const ctx={notify:m=>notices.push(m),renderPhotoControls(){},selectionChanged(){changes++;},esc:s=>String(s),selectedVin:'V',
 PHOTO_STAGE_LABEL:{queued:'Queued',downloading:'Downloading',sorting:'Sorting',ready:'Ready',partial:'Partial',unavailable:'Unavailable'},PHOTO_FAIL_LABEL:{},
 photoProgress:{vin:'V',data:null},
 exportPreview:{vin:'V',actualSource:'toyota_used',photos:Array.from({length:30},(_,i)=>({kind:i===1?'dedication':'vehicle',url:i===1?null:'u'+(i+1)}))},
 photoSelection:{vin:'V',source:'toyota_used',ready:true,keys:[],limit:20}};
vm.createContext(ctx);vm.runInContext(efk+'\n'+names.map(grab).join('\n'),ctx);
const key=n=>n===2?'dedication':'u'+n;
const run=code=>vm.runInContext(code,ctx);
const t=(label,fn)=>{try{fn();console.log('PASS',label)}catch(e){console.log('FAIL',label,e.message);process.exitCode=1}};
const click=n=>run(`togglePhotoKey(${JSON.stringify(key(n))})`);
const keys=()=>JSON.parse(run('JSON.stringify(orderedPhotoKeys())'));
t('reset gives 01 + 02',()=>{run('selectPhotoPreset()');assert.deepStrictEqual(keys(),[key(1),key(2)]);});
t('exact click-order sequence',()=>{run('selectPhotoPreset()');[3,11,14,18,20,25,4].forEach(click);assert.deepStrictEqual(keys(),[1,2,3,11,14,18,20,25,4].map(key));});
t('deselect then reselect appends to end',()=>{click(11);assert(!keys().includes(key(11)));click(11);assert.strictEqual(keys().at(-1),key(11));});
t('one toggle per call (no double toggle)',()=>{const before=changes;click(30);assert.strictEqual(changes,before+1);click(30);});
t('limit enforced with feedback',()=>{run('selectPhotoPreset()');for(let n=3;n<=20;n++)click(n);assert.strictEqual(keys().length,20);const r=click(21);assert.strictEqual(r,false);assert.strictEqual(keys().length,20);assert(notices.some(m=>/Limit reached/.test(m)));});
t('missing keys never remapped',()=>{run('photoSelection.keys=["gone",'+JSON.stringify(key(5))+']');assert.deepStrictEqual(keys(),[key(5)]);});
t('progress panel: exactly one bar, funnel line, failures disclosure',()=>{
  run('photoProgress.data={stage:"downloading",found:78,unique:65,downloaded:40,usable:38,failed:3,failure_reasons:{timeout:3},sorting:{}}');
  const html=run('photoProgressPanel()');
  assert.strictEqual((html.match(/<progress/g)||[]).length,1);
  assert(html.includes('Found 78 → Unique 65 → Downloaded 40 → Usable 38'));
  assert(html.includes('Failures (3)')&&html.includes('Retry failed'));
  run('photoProgress.data={stage:"ready",found:5,unique:5,downloaded:5,usable:5,failed:0,failure_reasons:{},sorting:{}}');
  assert(!run('photoProgressPanel()').includes('Failures'));});
t('old controls removed from source',()=>{for(const s of ['Select all shown','Unselect all shown','data-photo-filter','data-photo-group','Fetch missing photos','Refresh photo preview','Refresh vehicle</button>','data-photo-autosort','photo-auto-tag','Sort automatically'])assert(!src.includes(s),'still present: '+s);});
t('kept controls present',()=>{for(const s of ['data-photo-default','download-photo-zip','open-photo-folder','toggle-photo-grid','dealerLinks'])assert(src.includes(s),'missing '+s);});
