/**
 * FAMILIA APP — Custom Video Player
 * Reemplaza <video controls class="post-media">
 *
 * USO: familiaVideoPlayer.init(videoEl)
 * O auto-inicializa todos los .fvp-video al cargar.
 */

(function () {
  'use strict';

  /* ── íconos SVG inline (sin dependencias externas) ── */
  const ICONS = {
    play: `<svg viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21" fill="white"/></svg>`,
    pause: `<svg viewBox="0 0 24 24"><rect x="5" y="3" width="4" height="18" fill="white"/><rect x="15" y="3" width="4" height="18" fill="white"/></svg>`,
    mute: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>`,
    vol: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><path d="M15.54 8.46a5 5 0 010 7.07"/><path d="M19.07 4.93a10 10 0 010 14.14"/></svg>`,
    volLow: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>`,
    fullscreen: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3"/></svg>`,
    exitFs: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3"/></svg>`,
    pip: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><rect x="12" y="12" width="8" height="6" rx="1"/></svg>`,
    settings: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>`,
    captions: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"/><path d="M7 12h4m-4 3h8M15 12h2"/></svg>`,
    share: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>`,
    skipBack: `<svg viewBox="0 0 24 24" fill="white"><path d="M11 19l-7-7 7-7v4c4.97 0 9 4.03 9 9 0 .84-.12 1.65-.33 2.43A8.94 8.94 0 0011 15v4z"/></svg>`,
    skipFwd: `<svg viewBox="0 0 24 24" fill="white"><path d="M13 5l7 7-7 7v-4c-4.97 0-9-4.03-9-9 0-.84.12-1.65.33-2.43A8.94 8.94 0 0113 9V5z"/></svg>`,
    reel: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="14" height="18" rx="2"/><path d="M20 7l2-2v14l-2-2"/></svg>`,
    horiz: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>`,
  };

  /* ── helpers ── */
  function fmtTime(s) {
    if (isNaN(s)) return '0:00';
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60).toString().padStart(2, '0');
    if (m >= 60) {
      const h = Math.floor(m / 60);
      return `${h}:${(m % 60).toString().padStart(2, '0')}:${sec}`;
    }
    return `${m}:${sec}`;
  }

  function pct(current, total) {
    return total ? (current / total * 100).toFixed(2) + '%' : '0%';
  }

  /* ── builder de HTML del player ── */
  function buildPlayerHTML() {
    return `
      <div class="fvp-badge fvp-badge-el"></div>
      <div class="fvp-big-play fvp-big-play-el">
        <div class="fvp-big-play-btn">${ICONS.play}</div>
      </div>
      <div class="fvp-seek-flash left fvp-fl-left">
        <div class="fvp-seek-flash-inner">
          ${ICONS.skipBack}<span>-10s</span>
        </div>
      </div>
      <div class="fvp-seek-flash right fvp-fl-right">
        <div class="fvp-seek-flash-inner">
          ${ICONS.skipFwd}<span>+10s</span>
        </div>
      </div>
      <div class="fvp-spinner"><div class="fvp-spinner-ring"></div></div>
      <div class="fvp-subtitle-display"><span class="fvp-subtitle-text" style="display:none"></span></div>
      <div class="fvp-pip-indicator">▶ Reproduciendo en segundo plano</div>
      <div class="fvp-action-toast fvp-action-toast-el"></div>
      <div class="fvp-menu fvp-menu-el" id="fvp-menu-PLACEHOLDER">
        <div class="fvp-menu-title">Velocidad</div>
        ${[0.5,0.75,1,1.25,1.5,2].map(s=>`
          <div class="fvp-menu-item fvp-speed-item ${s===1?'active':''}" data-speed="${s}">
            <span class="fvp-check"></span>${s === 1 ? 'Normal' : s + 'x'}
          </div>`).join('')}
        <div class="fvp-divider"></div>
        <div class="fvp-menu-title">Calidad</div>
        <div class="fvp-menu-item fvp-quality-auto active"><span class="fvp-check"></span>Auto</div>
        <div class="fvp-menu-item fvp-quality-1080"><span class="fvp-check"></span>1080p</div>
        <div class="fvp-menu-item fvp-quality-720"><span class="fvp-check"></span>720p</div>
        <div class="fvp-menu-item fvp-quality-480"><span class="fvp-check"></span>480p</div>
        <div class="fvp-menu-item fvp-quality-360"><span class="fvp-check"></span>360p</div>
      </div>
      <div class="fvp-controls">
        <div class="fvp-progress-wrap fvp-prog-wrap">
          <div class="fvp-progress-buf fvp-prog-buf"></div>
          <div class="fvp-progress-fill fvp-prog-fill"></div>
          <div class="fvp-progress-thumb fvp-prog-thumb"></div>
          <div class="fvp-time-tooltip fvp-tt"></div>
        </div>
        <div class="fvp-row">
          <button class="fvp-btn fvp-play-btn" aria-label="Reproducir/Pausar">${ICONS.play}</button>
          <div class="fvp-vol-wrap">
            <button class="fvp-btn fvp-mute-btn" aria-label="Silenciar">${ICONS.vol}</button>
            <div class="fvp-vol-slider"><input type="range" min="0" max="1" step="0.05" value="1" class="fvp-vol-input" aria-label="Volumen"></div>
          </div>
          <span class="fvp-time fvp-time-el">0:00 / 0:00</span>
          <div class="fvp-row-end">
            <button class="fvp-btn fvp-cc-btn" aria-label="Subtítulos" title="Subtítulos" style="display:none">${ICONS.captions}</button>
            <button class="fvp-btn fvp-pip-btn" aria-label="Segundo plano" title="Reproducir en segundo plano">${ICONS.pip}</button>
            <button class="fvp-btn fvp-share-btn" aria-label="Compartir" title="Compartir">${ICONS.share}</button>
            <button class="fvp-btn fvp-settings-btn" aria-label="Configuración" title="Calidad / Velocidad">${ICONS.settings}</button>
            <button class="fvp-btn fvp-fs-btn" aria-label="Pantalla completa" title="Pantalla completa">${ICONS.fullscreen}</button>
          </div>
        </div>
      </div>
    `;
  }

  /* ── inicializar un video element ── */
  function initPlayer(videoEl) {
    if (videoEl.dataset.fvpInit) return;
    videoEl.dataset.fvpInit = '1';

    const wrap = document.createElement('div');
    wrap.className = 'fvp-wrap fvp-paused';

    // detectar aspecto antes de insertar
    function setAspect() {
      const w = videoEl.videoWidth;
      const h = videoEl.videoHeight;
      if (!w || !h) return;
      const ratio = w / h;
      if (ratio < 0.75) wrap.dataset.aspect = 'vertical';
      else if (ratio > 1.4) wrap.dataset.aspect = 'horizontal';
      else wrap.dataset.aspect = 'square';
      updateBadge();
    }

    // ID único para el menú
    const uid = Math.random().toString(36).slice(2, 8);

    wrap.innerHTML = buildPlayerHTML();
    // poner video dentro del wrap
    videoEl.className = 'fvp-video';
    videoEl.removeAttribute('controls');
    videoEl.playsInline = true;

    wrap.insertBefore(videoEl, wrap.firstChild);
    // si el video estaba en un <source>, ya está bien

    // ── referencias ──
    const bigPlay = wrap.querySelector('.fvp-big-play-el');
    const playBtn = wrap.querySelector('.fvp-play-btn');
    const muteBtn = wrap.querySelector('.fvp-mute-btn');
    const volInput = wrap.querySelector('.fvp-vol-input');
    const timeEl = wrap.querySelector('.fvp-time-el');
    const progWrap = wrap.querySelector('.fvp-prog-wrap');
    const progFill = wrap.querySelector('.fvp-prog-fill');
    const progBuf = wrap.querySelector('.fvp-prog-buf');
    const progThumb = wrap.querySelector('.fvp-prog-thumb');
    const tt = wrap.querySelector('.fvp-tt');
    const fsBtn = wrap.querySelector('.fvp-fs-btn');
    const pipBtn = wrap.querySelector('.fvp-pip-btn');
    const shareBtn = wrap.querySelector('.fvp-share-btn');
    const settingsBtn = wrap.querySelector('.fvp-settings-btn');
    const menuEl = wrap.querySelector('.fvp-menu-el');
    const ccBtn = wrap.querySelector('.fvp-cc-btn');
    const subtitleDisplay = wrap.querySelector('.fvp-subtitle-text');
    const spinner = wrap.querySelector('.fvp-spinner');
    const badge = wrap.querySelector('.fvp-badge-el');
    const flLeft = wrap.querySelector('.fvp-fl-left');
    const flRight = wrap.querySelector('.fvp-fl-right');
    const actionToast = wrap.querySelector('.fvp-action-toast-el');

    let toastTimer = null;
    let hideCtrlTimer = null;
    let isFs = false;
    let isDragging = false;

    function showToast(msg) {
      actionToast.textContent = msg;
      actionToast.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => actionToast.classList.remove('show'), 1500);
    }

    function updateBadge() {
      const asp = wrap.dataset.aspect;
      if (asp === 'vertical') {
        badge.innerHTML = ICONS.reel + ' Reel';
        badge.style.display = 'flex';
      } else if (asp === 'horizontal') {
        badge.innerHTML = ICONS.horiz + ' Video';
        badge.style.display = 'flex';
      } else {
        badge.style.display = 'none';
      }
    }

    function updatePlayBtn() {
      const paused = videoEl.paused;
      playBtn.innerHTML = paused ? ICONS.play : ICONS.pause;
      bigPlay.classList.toggle('hidden', !paused);
      wrap.classList.toggle('fvp-paused', paused);
    }

    function updateTime() {
      const c = videoEl.currentTime;
      const d = videoEl.duration || 0;
      timeEl.textContent = fmtTime(c) + ' / ' + fmtTime(d);
      progFill.style.width = pct(c, d);
      progThumb.style.left = pct(c, d);
      // buffer
      if (videoEl.buffered.length) {
        const buf = videoEl.buffered.end(videoEl.buffered.length - 1);
        progBuf.style.width = pct(buf, d);
      }
    }

    function updateVol() {
      const v = videoEl.volume;
      const m = videoEl.muted;
      muteBtn.innerHTML = (m || v === 0) ? ICONS.mute : (v < 0.5 ? ICONS.volLow : ICONS.vol);
      volInput.value = m ? 0 : v;
    }

    function togglePlay() {
      if (videoEl.paused) {
        videoEl.play().catch(() => {});
      } else {
        videoEl.pause();
      }
    }

    function seekRelative(delta) {
      videoEl.currentTime = Math.max(0, Math.min(videoEl.duration || 0, videoEl.currentTime + delta));
      showToast(delta > 0 ? `+${delta}s` : `${delta}s`);
      if (delta < 0) { flLeft.classList.add('active'); setTimeout(() => flLeft.classList.remove('active'), 400); }
      else { flRight.classList.add('active'); setTimeout(() => flRight.classList.remove('active'), 400); }
    }

    // clic en zona central → play/pause; bordes → seek
    let tapTimer = null;
    let tapCount = 0;
    let tapSide = null;

    wrap.addEventListener('click', function (e) {
      // no propagar si click en controles
      if (e.target.closest('.fvp-controls') || e.target.closest('.fvp-menu') || e.target.closest('.fvp-big-play')) return;

      const rect = wrap.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const side = x < rect.width * 0.3 ? 'left' : (x > rect.width * 0.7 ? 'right' : 'center');

      tapCount++;
      if (tapSide !== side) tapCount = 1;
      tapSide = side;

      clearTimeout(tapTimer);
      tapTimer = setTimeout(() => {
        if (tapCount >= 2 && side !== 'center') {
          seekRelative(side === 'right' ? 10 : -10);
        } else {
          togglePlay();
          showCtrlTemp();
        }
        tapCount = 0;
      }, 220);
    });

    bigPlay.addEventListener('click', (e) => { e.stopPropagation(); togglePlay(); });
    playBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePlay(); });

    // mute
    muteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      videoEl.muted = !videoEl.muted;
      showToast(videoEl.muted ? '🔇 Silenciado' : '🔊 Con sonido');
      updateVol();
    });

    volInput.addEventListener('input', () => {
      videoEl.volume = parseFloat(volInput.value);
      videoEl.muted = videoEl.volume === 0;
      updateVol();
    });

    // progreso
    function seekFromEvent(e) {
      const rect = progWrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
      const t = (x / rect.width) * (videoEl.duration || 0);
      videoEl.currentTime = t;
      updateTime();
    }

    progWrap.addEventListener('click', (e) => { e.stopPropagation(); seekFromEvent(e); });

    progWrap.addEventListener('mousemove', (e) => {
      const rect = progWrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
      const t = (x / rect.width) * (videoEl.duration || 0);
      tt.textContent = fmtTime(t);
      tt.style.left = x + 'px';
    });

    // arrastrar barra
    progWrap.addEventListener('mousedown', (e) => {
      isDragging = true;
      seekFromEvent(e);
    });
    document.addEventListener('mousemove', (e) => { if (isDragging) seekFromEvent(e); });
    document.addEventListener('mouseup', () => { isDragging = false; });

    // touch scrub
    progWrap.addEventListener('touchstart', (e) => { isDragging = true; seekFromEvent(e.touches[0]); }, { passive: true });
    progWrap.addEventListener('touchmove', (e) => { if (isDragging) { seekFromEvent(e.touches[0]); } }, { passive: true });
    progWrap.addEventListener('touchend', () => { isDragging = false; });

    // pantalla completa
    fsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!document.fullscreenElement) {
        wrap.requestFullscreen?.() || wrap.webkitRequestFullscreen?.();
      } else {
        document.exitFullscreen?.() || document.webkitExitFullscreen?.();
      }
    });

    document.addEventListener('fullscreenchange', () => {
      isFs = !!document.fullscreenElement;
      fsBtn.innerHTML = isFs ? ICONS.exitFs : ICONS.fullscreen;
    });

    // PiP (segundo plano)
    if ('pictureInPictureEnabled' in document) {
      pipBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
          if (document.pictureInPictureElement) {
            await document.exitPictureInPicture();
            wrap.classList.remove('fvp-in-pip');
          } else {
            await videoEl.requestPictureInPicture();
            wrap.classList.add('fvp-in-pip');
            showToast('▶ Segundo plano activado');
          }
        } catch (err) { showToast('PiP no disponible'); }
      });
      videoEl.addEventListener('leavepictureinpicture', () => wrap.classList.remove('fvp-in-pip'));
    } else {
      pipBtn.style.display = 'none';
    }

    // compartir
    shareBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const url = videoEl.src || videoEl.querySelector?.('source')?.src || window.location.href;
      if (navigator.share) {
        try {
          await navigator.share({ title: document.title, url });
        } catch (_) {}
      } else {
        try {
          await navigator.clipboard.writeText(url);
          showToast('🔗 Enlace copiado');
        } catch (_) {
          showToast('🔗 ' + url);
        }
      }
    });

    // menú de settings
    settingsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      menuEl.classList.toggle('open');
    });

    wrap.addEventListener('click', (e) => {
      if (!e.target.closest('.fvp-menu') && !e.target.closest('.fvp-settings-btn')) {
        menuEl.classList.remove('open');
      }
    });

    // velocidad
    wrap.querySelectorAll('.fvp-speed-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const speed = parseFloat(item.dataset.speed);
        videoEl.playbackRate = speed;
        wrap.querySelectorAll('.fvp-speed-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        showToast('⚡ ' + (speed === 1 ? 'Normal' : speed + 'x'));
        menuEl.classList.remove('open');
      });
    });

    // calidad (informativo — solo muestra; sin adaptive streaming real)
    wrap.querySelectorAll('[class*="fvp-quality"]').forEach(item => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        wrap.querySelectorAll('[class*="fvp-quality"]').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        const q = item.textContent.trim();
        showToast('📺 Calidad: ' + q);
        menuEl.classList.remove('open');
      });
    });

    // subtítulos / tracks de texto
    function setupCaptions() {
      const tracks = videoEl.textTracks;
      if (!tracks || tracks.length === 0) return;
      ccBtn.style.display = 'flex';
      let ccOn = false;

      // activar primer track disponible
      function applyCCState() {
        for (let i = 0; i < tracks.length; i++) {
          tracks[i].mode = ccOn ? 'showing' : 'hidden';
        }
      }

      // renderizar cues custom
      for (let i = 0; i < tracks.length; i++) {
        tracks[i].mode = 'hidden'; // empezamos ocultos
        tracks[i].addEventListener('cuechange', () => {
          if (!ccOn) { subtitleDisplay.style.display = 'none'; return; }
          const track = tracks[i];
          const cue = track.activeCues[0];
          if (cue) {
            subtitleDisplay.style.display = 'inline-block';
            subtitleDisplay.textContent = cue.text.replace(/<[^>]+>/g, '');
          } else {
            subtitleDisplay.style.display = 'none';
          }
        });
      }

      ccBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        ccOn = !ccOn;
        applyCCState();
        ccBtn.style.opacity = ccOn ? '1' : '0.5';
        if (!ccOn) subtitleDisplay.style.display = 'none';
        showToast(ccOn ? '💬 Subtítulos activados' : '💬 Subtítulos desactivados');
      });
    }

    videoEl.addEventListener('loadedmetadata', () => {
      setAspect();
      updateTime();
      updateVol();
      setupCaptions();
    });

    videoEl.addEventListener('play', updatePlayBtn);
    videoEl.addEventListener('pause', updatePlayBtn);
    videoEl.addEventListener('timeupdate', updateTime);
    videoEl.addEventListener('volumechange', updateVol);
    videoEl.addEventListener('durationchange', updateTime);

    // spinner de buffering
    videoEl.addEventListener('waiting', () => spinner.classList.add('visible'));
    videoEl.addEventListener('playing', () => spinner.classList.remove('visible'));
    videoEl.addEventListener('canplay', () => spinner.classList.remove('visible'));

    // mostrar controles temporalmente al mover el ratón
    function showCtrlTemp() {
      wrap.classList.add('fvp-show-controls');
      clearTimeout(hideCtrlTimer);
      hideCtrlTimer = setTimeout(() => {
        if (!videoEl.paused) wrap.classList.remove('fvp-show-controls');
      }, 3000);
    }

    wrap.addEventListener('mousemove', showCtrlTemp);
    wrap.addEventListener('touchstart', showCtrlTemp, { passive: true });

    // teclado cuando el player tiene foco
    wrap.setAttribute('tabindex', '0');
    wrap.addEventListener('keydown', (e) => {
      switch (e.key) {
        case ' ': case 'k': e.preventDefault(); togglePlay(); break;
        case 'ArrowRight': e.preventDefault(); seekRelative(5); break;
        case 'ArrowLeft': e.preventDefault(); seekRelative(-5); break;
        case 'ArrowUp': e.preventDefault(); videoEl.volume = Math.min(1, videoEl.volume + 0.1); updateVol(); break;
        case 'ArrowDown': e.preventDefault(); videoEl.volume = Math.max(0, videoEl.volume - 0.1); updateVol(); break;
        case 'm': videoEl.muted = !videoEl.muted; updateVol(); break;
        case 'f': fsBtn.click(); break;
        case 'p': pipBtn.click(); break;
      }
    });

    // ocultar badge después de 2s
    setTimeout(() => { badge.style.opacity = '0.6'; }, 2000);

    updatePlayBtn();
    updateVol();
  }

  /* ── reemplazar todos los <video> existentes ── */
  function initAll() {
    document.querySelectorAll('video.post-media:not([data-fvp-init])').forEach(v => {
      const parent = v.parentNode;
      const wrap = document.createElement('div');
      // insertar wrap antes del video
      parent.insertBefore(wrap, v);
      wrap.appendChild(v);
      // mover wrap al lugar correcto
      parent.insertBefore(wrap, wrap.nextSibling); // ya está bien
      // quitar clases viejas
      v.classList.remove('post-media');
      initPlayer(v);
    });
  }

  /* ── API pública ── */
  window.familiaVideoPlayer = { init: initPlayer, initAll };

  /* ── auto-init en DOMContentLoaded y en mutaciones ── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }

  // observer para posts que se agregan dinámicamente (HTMX / fetch)
  const mo = new MutationObserver(() => initAll());
  mo.observe(document.body, { childList: true, subtree: true });

})();
