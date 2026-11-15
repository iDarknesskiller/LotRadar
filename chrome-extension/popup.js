const $=id=>document.getElementById(id);
const connection=$('connection'), detail=$('connection-detail'), pairing=$('pairing'), key=$('key');
const message=$('message'), change=$('change'), actions=$('actions'), retry=$('retry');
const auto=$('enable-facebook-auto');
let checking=false, editing=false, autoEnabled=false;
$('version').textContent=chrome.runtime.getManifest().version;

async function send(action, fields={}){
  let timer;
  try{
    const reply=await Promise.race([
      chrome.runtime.sendMessage({action,...fields}),
      new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Chrome Reader did not respond. Reload it in chrome://extensions.')),action==='fill-vehicle-form'?25000:12000);})
    ]);
    if(!reply)throw Error('Chrome Reader did not respond. Reload it in chrome://extensions.');
    return reply;
  }finally{clearTimeout(timer);}
}
function render(result){
  const connected=result.state==='connected';
  connection.dataset.state=result.state;
  connection.textContent=connected?'Connected':result.state==='unpaired'?'Pair Reader':'Disconnected';
  detail.textContent=connected?(result.paused?'Dealer scan paused.':result.running?
    `${result.inflight||0} active · ${result.queued||0} queued`:'Ready for dealer scans. Reconnects automatically when LotRadar opens.'):
    result.error||'Copy the key from LotRadar Settings → Chrome Reader pairing.';
  actions.hidden=!connected;
  pairing.hidden=connected?!editing:!editing&&(result.paired!==false&&result.state!=='unpaired');
  change.hidden=!pairing.hidden||(!connected&&result.paired===false);
  if(pairing.hidden)key.value='';
}
async function check(candidate){
  if(checking)return;
  checking=true;
  retry.disabled=true;
  try{
    const result=await send(candidate?'pair':'check',candidate?{key:candidate}:{});
    if(candidate&&result.state==='connected')editing=false;
    render(result);
  }catch(e){
    const {bridgeKey}=await chrome.storage.local.get('bridgeKey').catch(()=>({}));
    render({state:'offline',paired:Boolean(bridgeKey),error:/No SW|Receiving end|message port/i.test(e.message)?
      'Chrome Reader worker unavailable. Reload it in chrome://extensions.':e.message});
  }finally{checking=false;retry.disabled=false;}
}
retry.addEventListener('click',()=>void check());
change.addEventListener('click',()=>{editing=true;pairing.hidden=false;change.hidden=true;key.focus();});
pairing.addEventListener('submit',async e=>{
  e.preventDefault();
  const candidate=key.value.trim();
  if(!/^[A-Za-z0-9_-]{32,80}$/.test(candidate)){message.textContent='Paste the complete pairing key.';return;}
  $('save').disabled=true;
  message.textContent='';
  try{await check(candidate);}finally{$('save').disabled=false;}
});
async function run(button,action){
  button.disabled=true;
  try{
    const reply=await send(action);
    message.textContent=reply.error||reply.status||'Done.';
  }catch(e){message.textContent=e.message;}
  finally{button.disabled=false;}
}
chrome.tabs.query({active:true,currentWindow:true}).then(([tab])=>{
  try{
    const url=new URL(tab?.url);
    $('fill-vehicle-form').hidden=url.origin!=='https://www.facebook.com'||!/^\/marketplace\/create\/vehicle\/?$/.test(url.pathname);
  }catch{}
}).catch(()=>{});
$('fill-vehicle-form').addEventListener('click',e=>void run(e.currentTarget,'fill-vehicle-form'));
$('run').addEventListener('click',e=>void run(e.currentTarget,'run'));
$('capture-facebook').addEventListener('click',e=>void run(e.currentTarget,'capture-facebook'));
function updateAuto(){auto.textContent=autoEnabled?'Disable automatic Facebook checks':'Enable automatic Facebook checks';}
auto.addEventListener('click',async()=>{
  auto.disabled=true;
  try{
    if(!autoEnabled&&!await chrome.permissions.request({origins:['https://www.facebook.com/*']})){
      message.textContent='Facebook access declined. Manual capture is still available.';
      return;
    }
    await chrome.storage.local.set({facebookAutoEnabled:!autoEnabled});
    autoEnabled=!autoEnabled;
    updateAuto();
    message.textContent=autoEnabled?'Automatic checks enabled.':'Automatic checks disabled.';
    if(autoEnabled)await run(auto,'facebook-auto-check');
  }catch(e){message.textContent=e.message;}
  finally{auto.disabled=false;}
});
chrome.storage.local.get('facebookAutoEnabled').then(async({facebookAutoEnabled})=>{
  autoEnabled=Boolean(facebookAutoEnabled&&await chrome.permissions.contains({origins:['https://www.facebook.com/*']}));
  updateAuto();
}).catch(()=>{});
void check();
setInterval(()=>{if(!editing&&document.activeElement!==key)void check();},4000);
