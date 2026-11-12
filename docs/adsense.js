/* Manual AdSense only. No auto ads, CMP implementation, geo lookup, or ad clicks. */
(() => {
  'use strict';
  if (window.__mushroomManualAds) return;
  const status = window.__mushroomManualAds = { version: '1.0.0', state: 'boot', reason: '' };
  const publisher = 'ca-pub-7212789726507686';
  const allowedSlots = new Set(['4680076950', '7594014909', '6492511219']);
  const root = document.documentElement;
  const params = new URLSearchParams(location.search);
  const printMedia = window.matchMedia('print');
  const narrowMedia = window.matchMedia('(max-width: 680px)');
  let printing = printMedia.matches;
  let observer;
  let libraryPromise;
  let frame = 0;
  let units = [];

  function isJudge() {
    // URL must still be checked when storage is unavailable.
    if (params.get('mode') === 'judge' || document.body?.classList.contains('judge-mode')) return true;
    try { return localStorage.getItem('mushroom-judge-mode') === '1'; }
    catch (_) { return true; } // Fail closed: cannot establish the stored audience mode.
  }
  function blockedReason() {
    if (isJudge()) return 'judge';
    if (printing || printMedia.matches || params.get('mode') === 'print' || params.get('print') === '1') return 'print';
    const host = location.hostname.toLowerCase().replace(/\.$/, '').replace(/^\[|\]$/g, '');
    if (!/^https?:$/.test(location.protocol) || host === 'localhost' || host.endsWith('.localhost') || host === '::1' || /^127\./.test(host) || host === '0.0.0.0' || host === '::' || /^::ffff:7f/.test(host)) return 'local';
    return '';
  }
  function disable(reason) {
    status.state = 'disabled';
    status.reason = reason;
    root.dataset.mushroomAdsDisabled = reason;
  }
  const initialBlock = blockedReason();
  if (initialBlock) { disable(initialBlock); return; }
  // Fail closed rather than eagerly initialize all units on old browsers.
  if (!window.IntersectionObserver) { disable('no-intersection-observer'); return; }

  function eligible(unit) {
    if (blockedReason()) return false;
    if (unit.dataset.mushroomAd === '7594014909' && narrowMedia.matches) return false;
    const rect = unit.getBoundingClientRect();
    const style = getComputedStyle(unit);
    return rect.width >= 250 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }
  function near(unit) {
    const rect = unit.getBoundingClientRect();
    return rect.top <= window.innerHeight + 300 && rect.bottom >= -300;
  }
  function setNPA() {
    const queue = window.adsbygoogle = window.adsbygoogle || [];
    queue.requestNonPersonalizedAds = 1;
    return queue;
  }
  function loadLibrary() {
    if (libraryPromise) return libraryPromise;
    libraryPromise = new Promise((resolve, reject) => {
      if (blockedReason()) { reject(new Error('Advertising disabled')); return; }
      // Existing unmanaged loader may have run before NPA was set: refuse to add requests.
      const existing = [...document.scripts].some(script => {
        try {
          const url = new URL(script.src, location.href);
          return url.hostname === 'pagead2.googlesyndication.com' && url.pathname === '/pagead/js/adsbygoogle.js';
        } catch (_) { return false; }
      });
      if (existing) { reject(new Error('Remove the old AdSense loader before integration')); return; }
      setNPA(); // Must precede both library fetch and every unit push.
      const script = document.createElement('script');
      script.id = 'mushroom-adsense-library';
      script.async = true;
      script.crossOrigin = 'anonymous';
      script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${publisher}`;
      let timeout;
      const cleanup = () => { clearTimeout(timeout); script.onload = null; script.onerror = null; };
      script.onload = () => { cleanup(); resolve(); };
      script.onerror = () => { cleanup(); reject(new Error('AdSense library failed to load')); };
      timeout = setTimeout(() => { cleanup(); reject(new Error('AdSense library load timed out')); }, 15000);
      document.head.appendChild(script);
    });
    return libraryPromise;
  }
  function setupPrivacyChoices() {
    const controls = document.getElementById('privacyControls');
    const button = document.getElementById('privacyChoices');
    const message = document.getElementById('privacyChoicesStatus');
    if (!controls || !button || !message) return;
    window.googlefc = window.googlefc || {};
    window.googlefc.callbackQueue = window.googlefc.callbackQueue || [];
    // Follow Google's official conditional revocation-link example. Keep the
    // entrypoint hidden until the actual CMP API confirms GDPR applies.
    window.googlefc.callbackQueue.push({CONSENT_API_READY: () => {
      if (blockedReason() || typeof window.__tcfapi !== 'function') return;
      window.__tcfapi('addEventListener', 0, (data, success) => {
        controls.hidden = Boolean(blockedReason()) || !success || !data || !data.gdprApplies;
      });
    }});
    button.addEventListener('click', () => {
      if (blockedReason()) { controls.hidden = true; return; }
      // Resolve the live namespace, not the pre-bootstrap object Google may replace.
      window.googlefc.callbackQueue.push({CONSENT_API_READY: () => {
        if (blockedReason()) return;
        try {
          window.googlefc.showRevocationMessage();
          message.textContent = '';
        } catch (_) {
          message.textContent = '目前無法開啟；請稍後再試，或查看隱私權與廣告說明。';
        }
      }});
    });
  }
  async function request(unit) {
    if (unit.dataset.adInit !== 'pending' || !eligible(unit) || !near(unit)) return;
    unit.dataset.adInit = 'waiting'; // Set before await: scroll/resize cannot enqueue again.
    try {
      await loadLibrary();
      // Print, resize, navigation mode, or position may change while the library is in flight.
      if (!eligible(unit) || !near(unit)) { unit.dataset.adInit = 'pending'; return; }
      const template = unit.querySelector('template[data-ad-template]');
      const ad = template?.content.querySelector('ins.adsbygoogle');
      if (!ad || ad.dataset.adClient !== publisher || ad.dataset.adSlot !== unit.dataset.mushroomAd) {
        throw new Error('Invalid manual unit template');
      }
      const body = unit.querySelector('.mushroom-ad__body');
      if (!body || body.querySelector('ins.adsbygoogle')) throw new Error('Duplicate manual unit markup');
      // Keep all unrequested units inert in templates. Otherwise push({}) can select a
      // hidden mobile-middle ins instead of the actual near-viewport unit.
      body.appendChild(ad.cloneNode(true));
      const queue = setNPA();
      unit.dataset.adInit = 'requested'; // Never auto retry push, even if Google throws.
      observer.unobserve(unit);
      queue.push({});
    } catch (error) {
      unit.dataset.adInit = 'error';
      unit.dataset.adError = error.message;
      observer.unobserve(unit);
      console.warn('[mushroom-ads] Manual unit skipped:', error.message);
    }
  }
  function scan() {
    frame = 0;
    for (const unit of units) void request(unit);
  }
  function schedule() {
    if (!frame) frame = window.requestAnimationFrame(scan);
  }
  function onPrintStart() { printing = true; root.dataset.mushroomAdsPrinting = '1'; }
  function onPrintEnd() { printing = false; delete root.dataset.mushroomAdsPrinting; schedule(); }
  function start() {
    const reason = blockedReason();
    if (reason) { disable(reason); return; }
    const seen = new Set();
    units = [...document.querySelectorAll('.mushroom-ad[data-mushroom-ad]')].filter(unit => {
      const slot = unit.dataset.mushroomAd;
      if (!allowedSlots.has(slot) || seen.has(slot)) { unit.hidden = true; return false; }
      seen.add(slot);
      unit.dataset.adInit = 'pending';
      return true;
    });
    if (!units.length) { disable('no-units'); return; }
    setupPrivacyChoices();
    status.state = 'observing';
    observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) void request(entry.target);
    }, {rootMargin:'300px 0px', threshold:0});
    for (const unit of units) observer.observe(unit);
    // Resize handles an unrequested middle unit becoming eligible on desktop.
    window.addEventListener('resize', schedule, {passive:true});
    // Recheck pending entries after print, viewport changes, and library await races.
    window.addEventListener('scroll', schedule, {passive:true});
    window.addEventListener('beforeprint', onPrintStart);
    window.addEventListener('afterprint', onPrintEnd);
    printMedia.addEventListener('change', event => event.matches ? onPrintStart() : onPrintEnd());
    narrowMedia.addEventListener('change', schedule);
    window.addEventListener('storage', event => {
      if (event.key === 'mushroom-judge-mode' && isJudge()) {
        disable('judge');
        observer.disconnect();
        // A previous network request cannot be undone. Page reload is required for
        // a zero-Google judge session; the site's judge toggle already reloads.
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
