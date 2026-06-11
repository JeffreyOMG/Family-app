/**
 * FAMILIA APP — Premium Video Player v3.0
 * Inspirado en X (Twitter), YouTube, Instagram Reels, TikTok
 *
 * CARACTERÍSTICAS:
 *  - Auto-pause global (un video a la vez)
 *  - Autoplay por visibilidad (IntersectionObserver acotado al feed)
 *  - Guardar posición entre secciones y modales
 *  - Mini player flotante
 *  - Doble tap para like (con animación de corazón)
 *  - Preview en timeline
 *  - Gestos móviles (volumen, brillo, seek)
 *  - Controles completos: play/pause, progreso, volumen, velocidad, PiP, compartir, CC
 *  - Detección de aspecto: vertical (reel), horizontal, cuadrado
 *  - Fullscreen inteligente
 *  - Atajos de teclado (escritorio)
 *  - Indicador de buffering
 *  - Toast de acciones
 *  - Sin MutationObserver global (rendimiento)
 *  - Sin fugas de memoria (AbortController por instancia)
 */

(function () {
  'use strict';

  /* ══════════════════════════════════════
     ICONS
  ══════════════════════════════════════ */
  const IC = {
    play:     `<svg viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21" fill="white"/></svg>`,
    pause:    `<svg viewBox="0 0 24 24"><rect x="5" y="3" width="4" height="18" fill="white"/><rect x="15" y="3" width="4" height="18" fill="white"/></svg>`,
    mute:     `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>`,
    vol:      `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><path d="M15.54 8.46a5 5 0 010 7.07"/><path d="M19.07 4.93a10 10 0 010 14.14"/></svg>`,
    volLow:   `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>`,
    fullscreen:`<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3"/></svg>`,
    exitFs:   `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3"/></svg>`,
    pip:      `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><rect x="12" y="12" width="8" height="6" rx="1"/></svg>`,
    settings: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>`,
    captions: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"/><path d="M7 12h4m-4 3h8M15 12h2"/></svg>`,
    share:    `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>`,
    skipBack: `<svg viewBox="0 0 24 24" fill="white"><path d="M11 19l-7-7 7-7v4c4.97 0 9 4.03 9 9 0 .84-.12 1.65-.33 2.43A8.94 8.94 0 0011 15v4z"/></svg>`,
    skipFwd:  `<svg viewBox="0 0 24 24" fill="white"><path d="M13 5l7 7-7 7v-4c-4.97 0-9-4.03-9-9 0-.84.12 1.65.33 2.43A8.94 8.94 0 0113 9V5z"/></svg>`,
    reel:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="14" height="18" rx="2"/><path d="M20 7l2-2v14l-2-2"/></svg>`,
    horiz:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>`,
    heart:    `<svg viewBox="0 0 24 24"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" fill="#ff4d8d" stroke="#ff4d8d" stroke-width="1"/></svg>`,
    close:    `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    expand:   `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`,
  };

  /* ══════════════════════════════════════
     ESTADO GLOBAL — mínimo y limpio
  ══════════════════════════════════════ */
  // Registro de todos los players activos: Map<videoEl, PlayerInstance>
  const _players = new Map();

  // Mini player flotante (singleton)
  let _miniPlayer = null;

  // Posiciones guardadas por src: Map<src, currentTime>
  const _savedPositions = new Map();

  /* ══════════════════════════════════════
     HELPERS
  ══════════════════════════════════════ */
  function fmtTime(s) {
    if (!s || isNaN(s)) return '0:00';
    const m = Math.floor(s / 60), sec = Math.floor(s % 60).toString().padStart(2, '0');
    if (m >= 60) return `${Math.floor(m / 60)}:${(m % 60).toString().padStart(2, '0')}:${sec}`;
    return `${m}:${sec}`;
  }

  function pct(cur, total) { return total ? `${(cur / total * 100).toFixed(2)}%` : '0%'; }

  // Pausar todos los videos excepto uno
  function pauseAllExcept(exceptEl) {
    _players.forEach((inst, vidEl) => {
      if (vidEl !== exceptEl && !vidEl.paused) {
        vidEl.pause();
        // Si tenía mini player activo, cerrarlo
        if (_miniPlayer && _miniPlayer.videoEl === vidEl) {
          _miniPlayer.destroy();
        }
      }
    });
  }

  // Recuperar el like button del post que contiene el video
  function findLikeBtn(videoEl) {
    const card = videoEl.closest('.post-card');
    if (card) return card.querySelector('.like-btn');
    // En post viewer modal
    const pvPost = videoEl.closest('#pv-content');
    if (pvPost) return document.getElementById('pv-like-btn');
    return null;
  }

  // Recuperar el post-id del post que contiene el video
  function findPostId(videoEl) {
    const card = videoEl.closest('.post-card');
    if (card) {
      const id = card.id.replace('post-', '');
      if (id && !isNaN(id)) return parseInt(id, 10);
    }
    return null;
  }

  /* ══════════════════════════════════════
     HTML DEL PLAYER
  ══════════════════════════════════════ */
  function buildHTML() {
    return `
      <div class="fvp-badge fvp-badge-el"></div>

      <div class="fvp-big-play fvp-big-play-el">
        <div class="fvp-big-play-btn">${IC.play}</div>
      </div>

      <div class="fvp-seek-flash left fvp-fl-left">
        <div class="fvp-seek-flash-inner">${IC.skipBack}<span>10s</span></div>
      </div>
      <div class="fvp-seek-flash right fvp-fl-right">
        <div class="fvp-seek-flash-inner">${IC.skipFwd}<span>10s</span></div>
      </div>

      <div class="fvp-spinner"><div class="fvp-spinner-ring"></div></div>

      <div class="fvp-heart-anim fvp-heart-el" style="display:none">
        <div class="fvp-heart-icon">${IC.heart}</div>
      </div>

      <div class="fvp-subtitle-display"><span class="fvp-subtitle-text" style="display:none"></span></div>
      <div class="fvp-pip-indicator">▶ Reproduciendo en segundo plano</div>
      <div class="fvp-action-toast fvp-action-toast-el"></div>
      <div class="fvp-brightness-overlay fvp-bright-el" style="display:none"></div>

      <div class="fvp-menu fvp-menu-el">
        <div class="fvp-menu-section fvp-quality-section" style="display:none">
          <div class="fvp-menu-title">Calidad</div>
          <div class="fvp-menu-item fvp-quality-item active" data-quality="auto"><span class="fvp-check"></span>Auto</div>
        </div>
        <div class="fvp-divider fvp-quality-divider" style="display:none"></div>
        <div class="fvp-menu-title">Velocidad</div>
        ${[0.5,0.75,1,1.25,1.5,2].map(s=>`
          <div class="fvp-menu-item fvp-speed-item ${s===1?'active':''}" data-speed="${s}">
            <span class="fvp-check"></span>${s===1?'Normal':s+'x'}
          </div>`).join('')}
      </div>

      <div class="fvp-controls">
        <div class="fvp-progress-wrap fvp-prog-wrap">
          <div class="fvp-progress-buf fvp-prog-buf"></div>
          <div class="fvp-progress-fill fvp-prog-fill"></div>
          <div class="fvp-progress-thumb fvp-prog-thumb"></div>
          <div class="fvp-time-tooltip fvp-tt"></div>
        </div>
        <div class="fvp-row">
          <button class="fvp-btn fvp-play-btn" aria-label="Reproducir/Pausar">${IC.play}</button>
          <div class="fvp-vol-wrap">
            <button class="fvp-btn fvp-mute-btn" aria-label="Silenciar">${IC.vol}</button>
            <div class="fvp-vol-slider"><input type="range" min="0" max="1" step="0.05" value="1" class="fvp-vol-input" aria-label="Volumen"></div>
          </div>
          <span class="fvp-time fvp-time-el">0:00 / 0:00</span>
          <div class="fvp-row-end">
            <button class="fvp-btn fvp-cc-btn" aria-label="Subtítulos" style="display:none">${IC.captions}</button>
            <button class="fvp-btn fvp-pip-btn" aria-label="Segundo plano" title="Segundo plano">${IC.pip}</button>
            <button class="fvp-btn fvp-share-btn" aria-label="Compartir" title="Compartir">${IC.share}</button>
            <button class="fvp-btn fvp-settings-btn" aria-label="Velocidad" title="Velocidad">${IC.settings}</button>
            <button class="fvp-btn fvp-fs-btn" aria-label="Pantalla completa">${IC.fullscreen}</button>
          </div>
        </div>
      </div>
    `;
  }

  /* ══════════════════════════════════════
     MINI PLAYER FLOTANTE
  ══════════════════════════════════════ */
  class MiniPlayer {
    constructor(videoEl, postId) {
      this.videoEl = videoEl;
      this.postId  = postId;
      this.el      = null;
      this._build();
    }

    _build() {
      if (document.getElementById('fvp-mini-player')) {
        document.getElementById('fvp-mini-player').remove();
      }

      const el = document.createElement('div');
      el.id = 'fvp-mini-player';
      el.className = 'fvp-mini';
      el.innerHTML = `
        <video class="fvp-mini-video" playsinline></video>
        <div class="fvp-mini-controls">
          <button class="fvp-mini-btn fvp-mini-play" aria-label="Play/Pause">${IC.play}</button>
          <div class="fvp-mini-progress">
            <div class="fvp-mini-fill"></div>
          </div>
          <button class="fvp-mini-btn fvp-mini-expand" aria-label="Volver al post" title="Ir al post">${IC.expand}</button>
          <button class="fvp-mini-btn fvp-mini-close" aria-label="Cerrar">${IC.close}</button>
        </div>
      `;
      document.body.appendChild(el);
      this.el = el;

      const miniVideo = el.querySelector('.fvp-mini-video');

      // Transferir stream del video original al mini
      // Usamos el mismo srcObject si hay uno, sino copiamos src
      const origSrc = this.videoEl.src ||
        (this.videoEl.querySelector('source') ? this.videoEl.querySelector('source').src : '');
      if (origSrc) {
        miniVideo.src = origSrc;
        miniVideo.currentTime = this.videoEl.currentTime;
        if (!this.videoEl.paused) miniVideo.play().catch(()=>{});
      }
      this._miniVideo = miniVideo;

      // Sync play state
      miniVideo.addEventListener('play', () => {
        el.querySelector('.fvp-mini-play').innerHTML = IC.pause;
      });
      miniVideo.addEventListener('pause', () => {
        el.querySelector('.fvp-mini-play').innerHTML = IC.play;
      });
      miniVideo.addEventListener('timeupdate', () => {
        const pct = miniVideo.duration ? (miniVideo.currentTime / miniVideo.duration) * 100 : 0;
        el.querySelector('.fvp-mini-fill').style.width = pct + '%';
        // Sync position back to original video
        _savedPositions.set(origSrc, miniVideo.currentTime);
      });

      // Controls
      el.querySelector('.fvp-mini-play').addEventListener('click', (e) => {
        e.stopPropagation();
        miniVideo.paused ? miniVideo.play().catch(()=>{}) : miniVideo.pause();
      });

      el.querySelector('.fvp-mini-expand').addEventListener('click', (e) => {
        e.stopPropagation();
        // Volver al post original
        if (this.postId && window.abrirPost) {
          window.abrirPost(this.postId);
        } else {
          // Scroll al elemento original
          const card = document.getElementById('post-' + this.postId);
          if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        this.destroy();
      });

      el.querySelector('.fvp-mini-close').addEventListener('click', (e) => {
        e.stopPropagation();
        miniVideo.pause();
        this.destroy();
      });

      // Arrastrar mini player
      this._makeDraggable(el);

      _miniPlayer = this;
    }

    _makeDraggable(el) {
      let startX, startY, startLeft, startTop, dragging = false;
      el.addEventListener('mousedown', (e) => {
        if (e.target.closest('button') || e.target.closest('.fvp-mini-progress')) return;
        dragging = true;
        startX = e.clientX; startY = e.clientY;
        const rect = el.getBoundingClientRect();
        startLeft = rect.left; startTop = rect.top;
        e.preventDefault();
      });
      document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const dx = e.clientX - startX, dy = e.clientY - startY;
        el.style.right = 'auto';
        el.style.bottom = 'auto';
        el.style.left = Math.max(0, startLeft + dx) + 'px';
        el.style.top  = Math.max(0, startTop  + dy) + 'px';
      });
      document.addEventListener('mouseup', () => { dragging = false; });
    }

    destroy() {
      if (this._miniVideo) {
        this._miniVideo.pause();
        this._miniVideo.src = '';
      }
      if (this.el) this.el.remove();
      if (_miniPlayer === this) _miniPlayer = null;
    }
  }

  /* ══════════════════════════════════════
     INITPLAYER — core
  ══════════════════════════════════════ */
  function initPlayer(videoEl) {
    if (videoEl.dataset.fvpInit) return;
    videoEl.dataset.fvpInit = '1';

    // Restaurar posición guardada
    const videoSrc = videoEl.src || (videoEl.querySelector('source') ? videoEl.querySelector('source').src : '');
    if (videoSrc && _savedPositions.has(videoSrc)) {
      videoEl.addEventListener('loadedmetadata', () => {
        const saved = _savedPositions.get(videoSrc);
        if (saved && saved < videoEl.duration - 1) {
          videoEl.currentTime = saved;
        }
      }, { once: true });
    }

    /* ─── wrap: reemplaza el video en el DOM ─── */
    const wrap = document.createElement('div');
    wrap.className = 'fvp-wrap fvp-paused';

    // Insertar wrap donde estaba el video, luego mover el video dentro
    if (videoEl.parentNode) {
      videoEl.parentNode.insertBefore(wrap, videoEl);
    }

    wrap.innerHTML = buildHTML();

    videoEl.className = 'fvp-video';
    videoEl.removeAttribute('controls');
    videoEl.playsInline = true;
    // Mover el video como primer hijo del wrap (antes de los controles)
    wrap.insertBefore(videoEl, wrap.firstChild);

    /* ─── references ─── */
    const bigPlay    = wrap.querySelector('.fvp-big-play-el');
    const playBtn    = wrap.querySelector('.fvp-play-btn');
    const muteBtn    = wrap.querySelector('.fvp-mute-btn');
    const volInput   = wrap.querySelector('.fvp-vol-input');
    const timeEl     = wrap.querySelector('.fvp-time-el');
    const progWrap   = wrap.querySelector('.fvp-prog-wrap');
    const progFill   = wrap.querySelector('.fvp-prog-fill');
    const progBuf    = wrap.querySelector('.fvp-prog-buf');
    const progThumb  = wrap.querySelector('.fvp-prog-thumb');
    const tt         = wrap.querySelector('.fvp-tt');
    const fsBtn      = wrap.querySelector('.fvp-fs-btn');
    const pipBtn     = wrap.querySelector('.fvp-pip-btn');
    const shareBtn   = wrap.querySelector('.fvp-share-btn');
    const settingsBtn= wrap.querySelector('.fvp-settings-btn');
    const menuEl     = wrap.querySelector('.fvp-menu-el');
    const ccBtn      = wrap.querySelector('.fvp-cc-btn');
    const subText    = wrap.querySelector('.fvp-subtitle-text');
    const spinner    = wrap.querySelector('.fvp-spinner');
    const badge      = wrap.querySelector('.fvp-badge-el');
    const flLeft     = wrap.querySelector('.fvp-fl-left');
    const flRight    = wrap.querySelector('.fvp-fl-right');
    const toast      = wrap.querySelector('.fvp-action-toast-el');
    const heartEl    = wrap.querySelector('.fvp-heart-el');
    const brightEl   = wrap.querySelector('.fvp-bright-el');

    let toastTimer = null, hideCtrlTimer = null, isFs = false, isDragging = false;

    /* ─── AbortController para cleanup ─── */
    const ac = new AbortController();
    const sig = { signal: ac.signal };

    /* ─── estado de la instancia ─── */
    const inst = {
      wrap, videoEl, ac,
      destroy() {
        ac.abort();
        observer && observer.disconnect();
        _players.delete(videoEl);
        if (_miniPlayer && _miniPlayer.videoEl === videoEl) {
          _miniPlayer.destroy();
        }
      }
    };
    _players.set(videoEl, inst);

    /* ─── ASPECT DETECTION ─── */
    function setAspect() {
      const w = videoEl.videoWidth, h = videoEl.videoHeight;
      if (!w || !h) return;
      const r = w / h;
      if      (r < 0.75) wrap.dataset.aspect = 'vertical';
      else if (r > 1.4)  wrap.dataset.aspect = 'horizontal';
      else               wrap.dataset.aspect = 'square';
      updateBadge();
    }

    function updateBadge() {
      const asp = wrap.dataset.aspect;
      if (asp === 'vertical') {
        badge.innerHTML = IC.reel + ' Reel'; badge.style.display = 'flex';
      } else if (asp === 'horizontal') {
        badge.innerHTML = IC.horiz + ' Video'; badge.style.display = 'flex';
      } else {
        badge.style.display = 'none';
      }
    }

    /* ─── TOAST ─── */
    function showToast(msg, duration = 1500) {
      toast.textContent = msg;
      toast.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove('show'), duration);
    }

    /* ─── PLAY/PAUSE ─── */
    function updatePlayBtn() {
      const paused = videoEl.paused;
      playBtn.innerHTML = paused ? IC.play : IC.pause;
      bigPlay.classList.toggle('hidden', !paused);
      wrap.classList.toggle('fvp-paused', paused);
    }

    function togglePlay() {
      if (videoEl.paused) {
        pauseAllExcept(videoEl);
        videoEl.play().catch(() => {});
      } else {
        videoEl.pause();
      }
    }

    /* ─── TIEMPO Y PROGRESO ─── */
    function updateTime() {
      const c = videoEl.currentTime, d = videoEl.duration || 0;
      timeEl.textContent = fmtTime(c) + ' / ' + fmtTime(d);
      progFill.style.width = pct(c, d);
      progThumb.style.left = pct(c, d);
      if (videoEl.buffered.length) {
        progBuf.style.width = pct(videoEl.buffered.end(videoEl.buffered.length - 1), d);
      }
      // Guardar posición
      const src = videoEl.src || (videoEl.querySelector('source') ? videoEl.querySelector('source').src : '');
      if (src && d > 0) _savedPositions.set(src, c);
    }

    function seekFromEvent(e) {
      const rect = progWrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
      videoEl.currentTime = (x / rect.width) * (videoEl.duration || 0);
      updateTime();
    }

    /* ─── VOLUMEN ─── */
    function updateVol() {
      const v = videoEl.volume, m = videoEl.muted;
      muteBtn.innerHTML = (m || v === 0) ? IC.mute : (v < 0.5 ? IC.volLow : IC.vol);
      volInput.value = m ? 0 : v;
    }

    /* ─── SEEK RELATIVO ─── */
    function seekRelative(delta) {
      videoEl.currentTime = Math.max(0, Math.min(videoEl.duration || 0, videoEl.currentTime + delta));
      showToast(delta > 0 ? `+${delta}s` : `${delta}s`);
      if (delta < 0) { flLeft.classList.add('active'); setTimeout(() => flLeft.classList.remove('active'), 450); }
      else           { flRight.classList.add('active'); setTimeout(() => flRight.classList.remove('active'), 450); }
      updateTime();
    }

    /* ─── CONTROLES VISIBILIDAD ─── */
    function showCtrlTemp() {
      wrap.classList.add('fvp-show-controls');
      clearTimeout(hideCtrlTimer);
      hideCtrlTimer = setTimeout(() => {
        if (!videoEl.paused) wrap.classList.remove('fvp-show-controls');
      }, 3000);
    }

    /* ─── DOBLE TAP: SEEK + LIKE ─── */
    let tapTimer = null, tapCount = 0, tapSide = null;

    wrap.addEventListener('click', (e) => {
      if (e.target.closest('.fvp-controls') || e.target.closest('.fvp-menu') || e.target.closest('.fvp-big-play')) return;

      const rect = wrap.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const zone = x < rect.width * 0.3 ? 'left' : (x > rect.width * 0.7 ? 'right' : 'center');

      tapCount++;
      if (tapSide !== zone) tapCount = 1;
      tapSide = zone;
      clearTimeout(tapTimer);

      tapTimer = setTimeout(() => {
        if (tapCount >= 2) {
          if (zone === 'left')   { seekRelative(-10); }
          else if (zone === 'right') { seekRelative(10); }
          else {
            // doble tap centro → like
            _triggerLike();
          }
        } else {
          togglePlay();
          showCtrlTemp();
        }
        tapCount = 0; tapSide = null;
      }, 220);
    }, sig);

    /* ─── LIKE POR DOBLE TAP ─── */
    function _triggerLike() {
      const likeBtn = findLikeBtn(videoEl);
      if (likeBtn && window.darLike) {
        const postId = findPostId(videoEl);
        if (postId) window.darLike(postId, likeBtn);
      }
      // Animación corazón grande
      heartEl.style.display = 'flex';
      heartEl.classList.add('fvp-heart-pop');
      setTimeout(() => {
        heartEl.classList.remove('fvp-heart-pop');
        heartEl.style.display = 'none';
      }, 900);
    }

    bigPlay.addEventListener('click', (e)  => { e.stopPropagation(); togglePlay(); }, sig);
    playBtn.addEventListener('click', (e)  => { e.stopPropagation(); togglePlay(); }, sig);

    /* ─── MUTE ─── */
    muteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      videoEl.muted = !videoEl.muted;
      showToast(videoEl.muted ? '🔇 Silenciado' : '🔊 Con sonido');
      updateVol();
    }, sig);

    volInput.addEventListener('input', () => {
      videoEl.volume = parseFloat(volInput.value);
      videoEl.muted = videoEl.volume === 0;
      updateVol();
    }, sig);

    /* ─── PROGRESS BAR ─── */
    progWrap.addEventListener('click', (e) => { e.stopPropagation(); seekFromEvent(e); }, sig);

    progWrap.addEventListener('mousemove', (e) => {
      const rect = progWrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
      const t = (x / rect.width) * (videoEl.duration || 0);
      tt.textContent = fmtTime(t);
      tt.style.left = x + 'px';
    }, sig);

    progWrap.addEventListener('mousedown', (e)  => { isDragging = true; seekFromEvent(e); }, sig);
    document.addEventListener('mousemove',  (e)  => { if (isDragging) seekFromEvent(e); }, sig);
    document.addEventListener('mouseup',    ()   => { isDragging = false; }, sig);

    progWrap.addEventListener('touchstart', (e) => { isDragging = true; seekFromEvent(e.touches[0]); }, { passive: true });
    progWrap.addEventListener('touchmove',  (e) => { if (isDragging) seekFromEvent(e.touches[0]); }, { passive: true });
    progWrap.addEventListener('touchend',   ()  => { isDragging = false; });

    /* ─── FULLSCREEN ─── */
    // Detectar iOS: no soporta requestFullscreen en div, usa webkitEnterFullscreen en <video>
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
                  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    function enterFullscreen() {
      if (isIOS) {
        // iOS Safari: fullscreen nativo directo en el elemento video
        if (videoEl.webkitEnterFullscreen) {
          videoEl.webkitEnterFullscreen();
        }
      } else {
        const req = wrap.requestFullscreen || wrap.webkitRequestFullscreen;
        if (req) req.call(wrap);
      }
    }

    function exitFullscreen() {
      if (isIOS) {
        if (videoEl.webkitExitFullscreen) videoEl.webkitExitFullscreen();
      } else {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) exit.call(document);
      }
    }

    function isInFullscreen() {
      return !!(document.fullscreenElement || document.webkitFullscreenElement ||
                videoEl.webkitDisplayingFullscreen);
    }

    fsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      isInFullscreen() ? exitFullscreen() : enterFullscreen();
    }, sig);

    function onFsChange() {
      isFs = isInFullscreen();
      fsBtn.innerHTML = isFs ? IC.exitFs : IC.fullscreen;
      videoEl.style.objectFit = isFs ? 'contain' : '';
      videoEl.style.maxHeight = isFs ? '100vh' : '';
    }

    document.addEventListener('fullscreenchange',       onFsChange, sig);
    document.addEventListener('webkitfullscreenchange', onFsChange, sig);
    // iOS: el video emite estos eventos cuando entra/sale de su fullscreen nativo
    videoEl.addEventListener('webkitbeginfullscreen',   onFsChange, sig);
    videoEl.addEventListener('webkitendfullscreen',     onFsChange, sig);

    /* ─── PICTURE IN PICTURE ─── */
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
        } catch (_) { showToast('PiP no disponible en este navegador'); }
      }, sig);
      videoEl.addEventListener('leavepictureinpicture', () => wrap.classList.remove('fvp-in-pip'), sig);
    } else {
      pipBtn.style.display = 'none';
    }

    /* ─── COMPARTIR ─── */
    shareBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const src = videoEl.src || (videoEl.querySelector('source') ? videoEl.querySelector('source').src : '') || window.location.href;
      if (navigator.share) {
        try { await navigator.share({ title: document.title, url: src }); } catch (_) {}
      } else {
        try {
          await navigator.clipboard.writeText(src);
          showToast('🔗 Enlace copiado');
        } catch (_) { showToast('🔗 ' + src.slice(0, 60)); }
      }
    }, sig);

    /* ─── SETTINGS / VELOCIDAD ─── */
    settingsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      menuEl.classList.toggle('open');
    }, sig);

    wrap.addEventListener('click', (e) => {
      if (!e.target.closest('.fvp-menu') && !e.target.closest('.fvp-settings-btn')) {
        menuEl.classList.remove('open');
      }
    }, sig);

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

    /* ─── SUBTÍTULOS ─── */
    function setupCaptions() {
      const tracks = videoEl.textTracks;
      if (!tracks || !tracks.length) return;
      ccBtn.style.display = 'flex';
      let ccOn = false;

      for (let i = 0; i < tracks.length; i++) {
        tracks[i].mode = 'hidden';
        tracks[i].addEventListener('cuechange', () => {
          if (!ccOn) { subText.style.display = 'none'; return; }
          const cue = tracks[i].activeCues[0];
          if (cue) { subText.style.display = 'inline-block'; subText.textContent = cue.text.replace(/<[^>]+>/g, ''); }
          else      { subText.style.display = 'none'; }
        });
      }

      ccBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        ccOn = !ccOn;
        for (let i = 0; i < tracks.length; i++) tracks[i].mode = ccOn ? 'showing' : 'hidden';
        ccBtn.style.opacity = ccOn ? '1' : '0.5';
        if (!ccOn) subText.style.display = 'none';
        showToast(ccOn ? '💬 Subtítulos activados' : '💬 Subtítulos desactivados');
      }, sig);
    }

    /* ─── CALIDAD ─── */
    function setupQuality() {
      const qualSection  = wrap.querySelector('.fvp-quality-section');
      const qualDivider  = wrap.querySelector('.fvp-quality-divider');

      // Buscar <source> elements con data-quality o type distintos
      const sources = Array.from(videoEl.querySelectorAll('source[data-quality]'));
      if (sources.length < 2) return; // Sin múltiples calidades, no mostrar

      qualSection.style.display = 'block';
      qualDivider.style.display = 'block';

      // Construir items de calidad desde los data-quality de los <source>
      const autoItem = qualSection.querySelector('.fvp-quality-item');
      sources.forEach(s => {
        const label = s.dataset.quality;
        const item  = document.createElement('div');
        item.className = 'fvp-menu-item fvp-quality-item';
        item.dataset.qualitySrc = s.src;
        item.innerHTML = `<span class="fvp-check"></span>${label}`;
        qualSection.appendChild(item);
      });

      let currentQuality = 'auto';

      qualSection.querySelectorAll('.fvp-quality-item').forEach(item => {
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const src   = item.dataset.qualitySrc;
          const label = item.textContent.trim();

          qualSection.querySelectorAll('.fvp-quality-item').forEach(i => i.classList.remove('active'));
          item.classList.add('active');
          menuEl.classList.remove('open');

          if (!src) {
            // Auto → restaurar src original (primer source)
            currentQuality = 'auto';
            showToast('📺 Auto');
            return;
          }

          // Cambiar calidad manteniendo posición
          const savedTime = videoEl.currentTime;
          const wasPaused = videoEl.paused;
          currentQuality  = label;

          videoEl.src = src;
          videoEl.load();
          videoEl.addEventListener('loadedmetadata', () => {
            videoEl.currentTime = savedTime;
            if (!wasPaused) videoEl.play().catch(() => {});
          }, { once: true });

          showToast('📺 ' + label);
        });
      });
    }

    /* ─── GESTOS MÓVILES ─── */
    let touchStartX = 0, touchStartY = 0, touchStartTime = 0;
    let touchStartVol = 1, isTouchSeeking = false;
    let brightnessVal = 1;

    wrap.addEventListener('touchstart', (e) => {
      if (e.target.closest('.fvp-controls') || e.target.closest('.fvp-prog-wrap')) return;
      const t = e.touches[0];
      touchStartX = t.clientX; touchStartY = t.clientY; touchStartTime = Date.now();
      touchStartVol = videoEl.volume;
      isTouchSeeking = false;
      showCtrlTemp();
    }, { passive: true });

    wrap.addEventListener('touchmove', (e) => {
      if (e.target.closest('.fvp-controls') || e.target.closest('.fvp-prog-wrap')) return;
      const t = e.touches[0];
      const dx = t.clientX - touchStartX, dy = t.clientY - touchStartY;
      const rect = wrap.getBoundingClientRect();
      const isRightSide = touchStartX > rect.left + rect.width * 0.5;

      if (Math.abs(dx) > Math.abs(dy) * 1.5 && Math.abs(dx) > 15) {
        // Seek horizontal
        isTouchSeeking = true;
        const seekDelta = (dx / rect.width) * (videoEl.duration || 60);
        showToast(seekDelta > 0 ? `+${Math.abs(seekDelta).toFixed(0)}s` : `-${Math.abs(seekDelta).toFixed(0)}s`);
      } else if (Math.abs(dy) > 15 && !isTouchSeeking) {
        if (isRightSide) {
          // Volumen (lado derecho)
          const newVol = Math.max(0, Math.min(1, touchStartVol - dy / rect.height));
          videoEl.volume = newVol;
          videoEl.muted = newVol === 0;
          updateVol();
          showToast(newVol === 0 ? '🔇 Silenciado' : `🔊 ${Math.round(newVol * 100)}%`);
        } else {
          // Brillo visual (lado izquierdo)
          brightnessVal = Math.max(0.3, Math.min(1, 1 - dy / (rect.height * 2)));
          brightEl.style.display = 'block';
          brightEl.style.opacity = (1 - brightnessVal).toString();
          showToast(`☀️ ${Math.round(brightnessVal * 100)}%`);
        }
      }
    }, { passive: true });

    wrap.addEventListener('touchend', (e) => {
      if (isTouchSeeking) {
        const dx = e.changedTouches[0].clientX - touchStartX;
        const rect = wrap.getBoundingClientRect();
        const seekDelta = (dx / rect.width) * (videoEl.duration || 60);
        seekRelative(Math.round(seekDelta));
      }
      // Desvanecer brillo en 1s
      if (brightEl.style.display === 'block') {
        setTimeout(() => { brightEl.style.display = 'none'; }, 1000);
      }
    }, { passive: true });

    /* ─── MOUSE MOVE / CTRL VISIBILITY ─── */
    wrap.addEventListener('mousemove', showCtrlTemp, sig);
    wrap.addEventListener('touchstart', showCtrlTemp, { passive: true });

    /* ─── TECLADO ─── */
    wrap.setAttribute('tabindex', '0');
    wrap.addEventListener('keydown', (e) => {
      switch (e.key) {
        case ' ':
        case 'k':  e.preventDefault(); togglePlay(); break;
        case 'ArrowRight': e.preventDefault(); seekRelative(5); break;
        case 'ArrowLeft':  e.preventDefault(); seekRelative(-5); break;
        case 'ArrowUp':    e.preventDefault(); videoEl.volume = Math.min(1, videoEl.volume + 0.1); updateVol(); break;
        case 'ArrowDown':  e.preventDefault(); videoEl.volume = Math.max(0, videoEl.volume - 0.1); updateVol(); break;
        case 'm': videoEl.muted = !videoEl.muted; updateVol(); break;
        case 'f': fsBtn.click(); break;
        case 'p': pipBtn.click(); break;
        case '0': case '1': case '2': case '3': case '4':
        case '5': case '6': case '7': case '8': case '9':
          if (videoEl.duration) videoEl.currentTime = (parseInt(e.key) / 10) * videoEl.duration;
          break;
      }
    }, sig);

    /* ─── VIDEO EVENTS ─── */
    videoEl.addEventListener('loadedmetadata', () => { setAspect(); updateTime(); updateVol(); setupCaptions(); setupQuality(); }, sig);
    videoEl.addEventListener('play',           () => { updatePlayBtn(); }, sig);
    videoEl.addEventListener('pause',          () => { updatePlayBtn(); }, sig);
    videoEl.addEventListener('timeupdate',     updateTime, sig);
    videoEl.addEventListener('volumechange',   updateVol, sig);
    videoEl.addEventListener('durationchange', updateTime, sig);
    videoEl.addEventListener('waiting',  () => spinner.classList.add('visible'), sig);
    videoEl.addEventListener('playing',  () => spinner.classList.remove('visible'), sig);
    videoEl.addEventListener('canplay',  () => spinner.classList.remove('visible'), sig);

    // Guardar posición al pausar / cuando sale de pantalla
    videoEl.addEventListener('pause', () => {
      const src = videoEl.src || (videoEl.querySelector('source') ? videoEl.querySelector('source').src : '');
      if (src && videoEl.duration > 0) _savedPositions.set(src, videoEl.currentTime);
    }, sig);

    // Mini player cuando el video sale del viewport Y está reproduciendo
    videoEl.addEventListener('play', () => {
      pauseAllExcept(videoEl);
    }, sig);

    /* ─── INTERSECTION OBSERVER (autoplay / mini player) ─── */
    let wasPlaying = false;

    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && entry.intersectionRatio >= 0.8) {
          // Video visible → reproducir si estaba reproduciendo
          if (wasPlaying && videoEl.paused) {
            pauseAllExcept(videoEl);
            videoEl.play().catch(() => {});
          }
          // Cerrar mini player si existe para este video
          if (_miniPlayer && _miniPlayer.videoEl === videoEl) {
            _miniPlayer.destroy();
          }
        } else if (!entry.isIntersecting) {
          wasPlaying = !videoEl.paused;
          if (!videoEl.paused) {
            // Guardar posición
            const src = videoEl.src || (videoEl.querySelector('source') ? videoEl.querySelector('source').src : '');
            if (src) _savedPositions.set(src, videoEl.currentTime);

            videoEl.pause();

            // Mostrar mini player si la visibilidad es completa (0%)
            if (entry.intersectionRatio < 0.1) {
              const postId = findPostId(videoEl);
              new MiniPlayer(videoEl, postId);
            }
          }
        }
      });
    }, { threshold: [0, 0.1, 0.8] });

    observer.observe(wrap);

    /* ─── badge fadee ─── */
    setTimeout(() => { badge.style.opacity = '0.6'; }, 2500);

    updatePlayBtn();
    updateVol();
  }

  /* ══════════════════════════════════════
     INIT ALL — escanea videos sin inicializar
  ══════════════════════════════════════ */
  function initAll(root) {
    const container = root || document;
    container.querySelectorAll('video.post-media:not([data-fvp-init])').forEach(v => {
      v.classList.remove('post-media');
      initPlayer(v);
    });
  }

  /* ══════════════════════════════════════
     MUTATION OBSERVER — SOLO sobre el feed,
     NO sobre document.body completo
  ══════════════════════════════════════ */
  function setupFeedObserver() {
    // Targets conocidos del feed
    const feedIds = ['feed-posts', 'feed-guardados', 'feed-tendencias', 'pv-content'];
    const observed = new Set();

    function observeFeedContainer(container) {
      if (!container || observed.has(container)) return;
      observed.add(container);
      const mo = new MutationObserver((mutations) => {
        let hasNewNodes = false;
        mutations.forEach(m => {
          m.addedNodes.forEach(n => {
            if (n.nodeType === 1) hasNewNodes = true;
          });
        });
        if (hasNewNodes) initAll(container);
      });
      mo.observe(container, { childList: true, subtree: true });
    }

    feedIds.forEach(id => {
      const el = document.getElementById(id);
      if (el) observeFeedContainer(el);
    });

    // Observer para cuando los contenedores del feed se creen dinámicamente
    const rootObs = new MutationObserver(() => {
      feedIds.forEach(id => {
        const el = document.getElementById(id);
        if (el && !observed.has(el)) observeFeedContainer(el);
      });
    });
    rootObs.observe(document.body, { childList: true });
  }

  /* ══════════════════════════════════════
     ESCUCHAR SECCIÓN CHANGE para mini player
  ══════════════════════════════════════ */
  document.addEventListener('click', (e) => {
    const navItem = e.target.closest('.nav-item[data-sec]');
    if (!navItem) return;
    // El usuario cambia de sección → los videos se pausan por IntersectionObserver
    // Si había mini player activo, puede seguir si quiere
  });

  /* ══════════════════════════════════════
     API PÚBLICA
  ══════════════════════════════════════ */
  window.familiaVideoPlayer = {
    init: initPlayer,
    initAll,
    pauseAll: () => pauseAllExcept(null),
    getPlayers: () => _players,
  };

  /* ══════════════════════════════════════
     BOOTSTRAP
  ══════════════════════════════════════ */
  function bootstrap() {
    initAll();
    setupFeedObserver();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }

  // No se necesita listener global de click - el MutationObserver del feed
  // y los patches en _renderPostModal/abrirMediaModal cubren todos los casos.

})();
