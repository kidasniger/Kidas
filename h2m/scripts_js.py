"""Scripts JavaScript injectés dans la page."""



JS_HELPERS = r"""
window.__raf = () => new Promise(r => { let d = false; const f = () => { if (!d) { d = true; r(); } };
  requestAnimationFrame(f); setTimeout(f, 120); });

window.__prep = async () => {
  const faces = [...document.fonts].filter(f => f.unicodeRange === 'U+0-10FFFF' || /U\+0000/.test(f.unicodeRange));
  await Promise.all(faces.map(f => f.load().catch(() => 0)));
  const au = [...document.querySelectorAll('audio')];
  await Promise.all(au.map(a => a.readyState >= 1 ? 1 :
    new Promise(r => { a.addEventListener('loadedmetadata', r, {once: true}); setTimeout(r, 15000); })));
  return au.map(a => a.duration);
};

window.__finish = async () => {
  await document.fonts.ready;
  const imgs = [...document.images];
  if (imgs.length) await Promise.all(imgs.map(i => i.decode ? i.decode().catch(() => 0) : 0));
  await window.__raf();
};

window.__seek = async (t) => {
  if (window.__profile === 'editpro') {
    if (!window.__ep) {
      window.__manual = true; window.__ep = true;
      run = true; vi = 0; subEnd = 0;
      const ui = document.querySelector('#ui'); if (ui) ui.style.display = 'none';
    }
    render(Math.max(0, t));
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'musicpro') {
    window.__manual = true;
    try { run = 0; } catch (e) {}
    render(Math.max(0, t));
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'voicevideo') {
    window.__manual = true;
    document.querySelectorAll('audio').forEach(a => { try { a.pause(); } catch (e) {} });
    if (window.ReactDOM && ReactDOM.flushSync) ReactDOM.flushSync(() => window.__video.seek(t));
    else { window.__video.seek(t); await window.__raf(); }
    await window.__finish();
    for (const b of document.querySelectorAll('#stage button'))
      if (/Touchez pour lancer|Rejouer/.test(b.textContent) && b.parentElement) b.parentElement.style.display = 'none';
    return 1;
  }
  if (window.__setT && window.ReactDOM && ReactDOM.flushSync) {
    window.__manual = true;
    ReactDOM.flushSync(() => window.__setT(t));
  } else {
    const au = document.querySelectorAll('audio');
    au.forEach(a => { a.currentTime = t; });
    await window.__raf();
    await new Promise(r => setTimeout(r, 40));
    await window.__raf();
  }
  await window.__finish();
  for (const d of document.querySelectorAll('.stage div'))
    if (!d.children.length && d.textContent.startsWith('Touchez pour lancer')) d.style.display = 'none';
  return 1;
};

window.__sfx = async () => {
  if (typeof SFX === 'undefined' || typeof EV === 'undefined') return '';
  const sr = 44100, L = Math.ceil((D + 1.5) * sr);
  const oc = new OfflineAudioContext(1, L, sr);
  let T = 0;
  Object.defineProperty(oc, 'currentTime', { get: () => T });
  const S2 = Object.create(SFX);
  S2.ac = oc; S2.m = oc.createGain(); S2.m.gain.value = .5; S2.m.connect(oc.destination);
  S2.nb = oc.createBuffer(1, sr, sr);
  const nd = S2.nb.getChannelData(0);
  for (let i = 0; i < sr; i++) nd[i] = Math.random() * 2 - 1;
  for (const [et, kind] of EV) { T = Math.max(0, et); S2.play(kind); }
  const buf = await oc.startRendering();
  const x = buf.getChannelData(0), pcm = new Int16Array(x.length);
  for (let i = 0; i < x.length; i++) { const v = Math.max(-1, Math.min(1, x[i])); pcm[i] = v < 0 ? v * 32768 : v * 32767; }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
};

window.__wavOf = async (key) => {
  let buf = null;
  try { buf = await (key === 'voice' ? vP : mP); } catch (e) {}
  if (!buf || !buf.getChannelData) return '';
  const ch = Math.min(2, buf.numberOfChannels), n = buf.length, pcm = new Int16Array(n * ch);
  for (let c = 0; c < ch; c++) {
    const x = buf.getChannelData(c);
    for (let i = 0; i < n; i++) { const v = Math.max(-1, Math.min(1, x[i])); pcm[i * ch + c] = v < 0 ? v * 32768 : v * 32767; }
  }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return buf.sampleRate + ':' + ch + ':' + btoa(bin);
};
0;
"""


GENERIC_AUDIO_CAPTURE = r"""<script>
(() => {
  if (window.__h2mCaptureInstalled) return;
  window.__h2mCaptureInstalled = true;
  const Native = window.AudioContext || window.webkitAudioContext;
  const contexts = [];
  let active = false;
  const originalConnect = window.AudioNode && AudioNode.prototype.connect;
  if (originalConnect) {
    AudioNode.prototype.connect = function(destination, ...args) {
      const result = originalConnect.call(this, destination, ...args);
      try {
        const ctx = this.context;
        if (ctx && destination === ctx.destination && ctx.__h2mDest && !ctx.__h2mDup) {
          ctx.__h2mDup = true;
          originalConnect.call(this, ctx.__h2mDest);
          ctx.__h2mDup = false;
        }
      } catch (_) {}
      return result;
    };
  }
  function install(ctx) {
    if (!ctx || ctx.__h2mDest) return;
    try {
      ctx.__h2mDest = ctx.createMediaStreamDestination();
      ctx.__h2mChunks = [];
      ctx.__h2mRec = null;
      contexts.push(ctx);
      start(ctx);
    } catch (_) {}
  }
  if (Native) {
    function WrappedAudioContext(...args) {
      const ctx = new Native(...args);
      install(ctx);
      return ctx;
    }
    WrappedAudioContext.prototype = Native.prototype;
    try { Object.setPrototypeOf(WrappedAudioContext, Native); } catch (_) {}
    window.AudioContext = WrappedAudioContext;
    if (window.webkitAudioContext) window.webkitAudioContext = WrappedAudioContext;
  }
  function start(ctx) {
    if (!ctx || !ctx.__h2mDest || ctx.__h2mRec || !window.MediaRecorder) return;
    try {
      const type = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';
      const rec = new MediaRecorder(ctx.__h2mDest.stream, { mimeType: type });
      ctx.__h2mRec = rec;
      rec.ondataavailable = e => { if (e.data && e.data.size) ctx.__h2mChunks.push(e.data); };
      rec.start(250);
      ctx.__h2mRecStartPerf = performance.now();
      ctx.__h2mRecCt = ctx.currentTime;
    } catch (_) {}
  }
  window.__h2mStart = async () => {
    if (active) return contexts.length;
    active = true;
    if (Native) {
      for (const el of document.querySelectorAll('audio,video')) {
        try {
          if (!el.__h2mSource) {
            const ctx = new Native();
            install(ctx);
            const source = ctx.createMediaElementSource(el);
            el.__h2mSource = source;
            source.connect(ctx.destination);
          }
        } catch (_) {}
      }
    }
    for (const ctx of contexts) {
      try { await ctx.resume(); } catch (_) {}
      start(ctx);
    }
    for (const el of document.querySelectorAll('audio,video')) {
      try { el.muted = false; el.currentTime = 0; const p = el.play(); if (p) await p.catch(() => {}); } catch (_) {}
    }
    return contexts.length;
  };
  // L'horloge de l'AudioContext n'avance que lorsqu'il tourne, comme le flux enregistré :
  // elle donne un décalage fiable même si le contexte a démarré suspendu.
  window.__h2mMark = () => {
    window.__h2mVideoStartPerf = performance.now();
    for (const ctx of contexts) { try { ctx.__h2mMarkCt = ctx.currentTime; } catch (_) {} }
  };
  window.__h2mStop = async () => {
    const records = contexts.filter(c => c.__h2mRec);
    await Promise.all(records.map(c => new Promise(resolve => {
      const rec = c.__h2mRec;
      if (rec.state === 'inactive') return resolve();
      rec.addEventListener('stop', resolve, { once: true });
      try { rec.stop(); } catch (_) { resolve(); }
    })));
    const result = [];
    for (const ctx of records) {
      try {
        const blob = new Blob(ctx.__h2mChunks, { type: 'audio/webm' });
        if (blob.size < 500) continue;
        const data = await new Promise(resolve => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',').pop());
          reader.onerror = () => resolve('');
          reader.readAsDataURL(blob);
        });
        if (data) result.push({
          mime: blob.type || 'audio/webm',
          data,
          offset: (ctx.__h2mMarkCt != null && ctx.__h2mRecCt != null) ? ctx.__h2mMarkCt - ctx.__h2mRecCt :
            window.__h2mVideoStartPerf == null ? 0 :
            (window.__h2mVideoStartPerf - (ctx.__h2mRecStartPerf || window.__h2mVideoStartPerf)) / 1000
        });
      } catch (_) {}
    }
    return result;
  };
  window.addEventListener('load', () => { try { window.__h2mStart(); } catch (_) {} }, { once: true });
})();
</script>"""
