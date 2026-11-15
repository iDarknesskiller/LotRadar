// Bridge only a SalesmanHub page event to the paired Chrome Reader.
// Never trust a VIN, Facebook URL, or login token from DOM events.
(() => {
  if (location.origin !== 'http://127.0.0.1:8765') return;
  const report = (status, error = '') => {
    window.dispatchEvent(new CustomEvent('salesmanhub:facebook-auto-result', {
      detail: {status: String(status || ''), error: String(error || '')}
    }));
  };
  window.addEventListener('lotradar:vehicle-form', async event => {
    const handoff=event.detail?.handoff;
    if(typeof handoff!=='string'||!/^[A-Za-z0-9_-]{32}$/.test(handoff))return;
    let error='';
    try {
      const reply=await chrome.runtime.sendMessage({action:'open-vehicle-form',handoff});
      if(!reply?.ok)error=reply?.error||'Chrome Reader could not open the Facebook form.';
    } catch {
      error='Reload LotRadar Reader, then refresh the LotRadar page and try again.';
    }
    window.dispatchEvent(new CustomEvent('lotradar:vehicle-form-result',{detail:{handoff,error}}));
  });
  window.addEventListener('salesmanhub:scan-control', event => {
    // Only a local, confirmed action name. Never consume URLs/VINs from page events.
    const action=event?.detail?.action;
    if(!['stop','resume','start'].includes(action))return;
    try {
      if(typeof chrome==='undefined'||!chrome.runtime||typeof chrome.runtime.sendMessage!=='function')return;
      Promise.resolve(chrome.runtime.sendMessage({action:action==='stop'?'scan-stop':'run'})).catch(()=>{});
    } catch {}
  });
  window.addEventListener('salesmanhub:facebook-auto-check', () => {
    // After an extension update, the old page may keep a stale content script.
    // Chrome can remove runtime access until Marketplace is reloaded.
    try {
      if (typeof chrome === 'undefined' || !chrome.runtime || typeof chrome.runtime.sendMessage !== 'function') {
        report('unavailable', 'Reader context unavailable. Reload the extension and Marketplace tab.');
        return;
      }
      Promise.resolve(chrome.runtime.sendMessage({action: 'facebook-auto-check'}))
        .then(reply => report(reply?.status || 'unknown', reply?.error || ''))
        .catch(() => report('unavailable', 'Reader disconnected. Reload the extension and Marketplace tab.'));
    } catch (_error) {
      report('unavailable', 'Reader context expired. Reload the extension and Marketplace tab.');
    }
  });
})();
