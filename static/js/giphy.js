/**
 * giphy.js — Integración GIPHY para publicaciones y comentarios
 * Optimizado para móvil: lazy load, paginación real, sin saturación
 */

// ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────
const GIPHY_KEY    = 'I4PM7lyV4V1MK6qcNcMYLa3RoapteaXE'; // SDK key — APLICACIÓN FAMILIAR
const GIPHY_LIMIT  = 20;   // GIFs por página
const GIPHY_RATING = 'g';  // Safe for all audiences

// ─── ESTADO INTERNO ──────────────────────────────────────────────────────────
let _giphyCallback  = null;   // fn(gifUrl, gifWebp) llamada al elegir GIF
let _giphyQuery     = '';
let _giphyOffset    = 0;
let _giphyTotal     = 0;
let _giphyLoading   = false;
let _giphySearchTO  = null;   // debounce timer
let _giphyMode      = null;   // 'post' | 'comment'

// ─── INICIALIZACIÓN (llamar 1 vez desde inicio.html) ─────────────────────────
export function initGiphy() {
  _buildModal();
  _attachStyles();
}

// ─── ABRIR MODAL ─────────────────────────────────────────────────────────────
/**
 * @param {function} callback  fn(gifUrl) — URL fija de GIPHY para guardar
 * @param {string}   mode      'post' | 'comment'
 */
export function abrirGiphy(callback, mode = 'post') {
  _giphyCallback = callback;
  _giphyMode = mode;
  _giphyQuery  = '';
  _giphyOffset = 0;
  _giphyTotal  = 0;

  const modal = document.getElementById('giphy-modal');
  if (!modal) return;

  // Portal: mover al body para evitar z-index traps
  if (modal.parentElement !== document.body) document.body.appendChild(modal);

  const input = document.getElementById('giphy-search-input');
  if (input) input.value = '';

  const grid = document.getElementById('giphy-grid');
  if (grid) grid.innerHTML = '';

  modal.classList.add('giphy-open');
  document.body.style.overflow = 'hidden';

  setTimeout(() => input?.focus(), 80);
  _fetchGifs(true);
}

export function cerrarGiphy() {
  const modal = document.getElementById('giphy-modal');
  if (!modal) return;
  modal.classList.remove('giphy-open');
  modal.classList.add('giphy-closing');
  setTimeout(() => {
    modal.classList.remove('giphy-closing');
    document.body.style.overflow = '';
  }, 200);
}

// ─── FETCH ───────────────────────────────────────────────────────────────────
async function _fetchGifs(reset = false) {
  if (_giphyLoading) return;
  if (!reset && _giphyOffset >= _giphyTotal && _giphyTotal > 0) return;

  _giphyLoading = true;
  if (reset) { _giphyOffset = 0; _giphyTotal = 0; }

  _showSkeleton(reset);

  try {
    const isSearch = _giphyQuery.trim().length > 0;
    const endpoint = isSearch
      ? `https://api.giphy.com/v1/gifs/search?api_key=${GIPHY_KEY}&q=${encodeURIComponent(_giphyQuery)}&limit=${GIPHY_LIMIT}&offset=${_giphyOffset}&rating=${GIPHY_RATING}&lang=es`
      : `https://api.giphy.com/v1/gifs/trending?api_key=${GIPHY_KEY}&limit=${GIPHY_LIMIT}&offset=${_giphyOffset}&rating=${GIPHY_RATING}`;

    const res  = await fetch(endpoint);
    const data = await res.json();

    _giphyTotal  = data.pagination?.total_count || data.data.length;
    _giphyOffset += data.data.length;

    _renderGifs(data.data, reset);
  } catch (e) {
    _showError();
  }

  _giphyLoading = false;
}

// ─── RENDER ──────────────────────────────────────────────────────────────────
function _renderGifs(gifs, reset) {
  const grid = document.getElementById('giphy-grid');
  if (!grid) return;

  _clearSkeletons(grid);

  if (reset && !gifs.length) {
    grid.innerHTML = `<div class="giphy-empty">
      <span class="material-symbols-outlined">search_off</span>
      <p>Sin resultados para "${_giphyQuery}"</p>
    </div>`;
    return;
  }

  gifs.forEach(gif => {
    const url   = gif.images?.fixed_width?.url || gif.images?.original?.url || '';
    const webp  = gif.images?.fixed_width?.webp || url;
    const title = gif.title || '';
    const w     = gif.images?.fixed_width?.width  || 200;
    const h     = gif.images?.fixed_width?.height || 150;

    const item = document.createElement('div');
    item.className = 'giphy-item';
    item.title = title;
    item.innerHTML = `
      <div class="giphy-item-inner" style="padding-top:${(h/w*100).toFixed(1)}%;">
        <img
          src="${escG(webp || url)}"
          alt="${escG(title)}"
          loading="lazy"
          decoding="async"
          class="giphy-img"
          onload="this.classList.add('giphy-loaded')"
          onerror="this.parentElement.parentElement.style.display='none'"
        >
      </div>`;
    item.addEventListener('click', () => {
      const finalUrl = gif.images?.original?.url || url;
      _elegirGif(finalUrl, title);
    });
    grid.appendChild(item);
  });

  // Infinite scroll trigger
  _attachInfiniteScroll();
}

function _elegirGif(url, title) {
  cerrarGiphy();
  if (_giphyCallback) _giphyCallback(url, title);
}

// ─── SKELETON LOADERS ────────────────────────────────────────────────────────
function _showSkeleton(reset) {
  const grid = document.getElementById('giphy-grid');
  if (!grid) return;
  if (reset) grid.innerHTML = '';
  const count = reset ? 12 : 6;
  for (let i = 0; i < count; i++) {
    const sk = document.createElement('div');
    sk.className = 'giphy-skeleton giphy-skeleton-item';
    grid.appendChild(sk);
  }
}

function _clearSkeletons(grid) {
  grid.querySelectorAll('.giphy-skeleton-item').forEach(s => s.remove());
}

function _showError() {
  const grid = document.getElementById('giphy-grid');
  if (!grid) return;
  _clearSkeletons(grid);
  grid.innerHTML += `<div class="giphy-empty">
    <span class="material-symbols-outlined">wifi_off</span>
    <p>Error al cargar GIFs. Intenta de nuevo.</p>
  </div>`;
}

// ─── INFINITE SCROLL ─────────────────────────────────────────────────────────
let _scrollAttached = false;
function _attachInfiniteScroll() {
  if (_scrollAttached) return;
  _scrollAttached = true;
  const grid = document.getElementById('giphy-grid');
  if (!grid) return;

  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && !_giphyLoading) {
      _fetchGifs(false);
    }
  }, { root: grid.parentElement, rootMargin: '0px 0px 120px 0px', threshold: 0.1 });

  const sentinel = document.createElement('div');
  sentinel.id = 'giphy-sentinel';
  sentinel.style.height = '1px';
  grid.parentElement?.appendChild(sentinel);
  observer.observe(sentinel);
}

// ─── CONSTRUIR MODAL ─────────────────────────────────────────────────────────
function _buildModal() {
  if (document.getElementById('giphy-modal')) return;

  const modal = document.createElement('div');
  modal.id = 'giphy-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Selector de GIFs');
  modal.innerHTML = `
    <div id="giphy-box" onclick="event.stopPropagation()">
      <div id="giphy-header">
        <div id="giphy-search-wrap">
          <span class="material-symbols-outlined" id="giphy-search-icon">search</span>
          <input
            type="search"
            id="giphy-search-input"
            placeholder="Buscar GIF…"
            autocomplete="off"
            autocorrect="off"
            spellcheck="false"
          >
          <button id="giphy-close" aria-label="Cerrar selector de GIFs">
            <span class="material-symbols-outlined">close</span>
          </button>
        </div>
        <div id="giphy-label">
          <span id="giphy-label-txt">GIFs en tendencia</span>
          <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/5/5a/GIPHY-logo.png/220px-GIPHY-logo.png"
               alt="GIPHY" id="giphy-logo">
        </div>
      </div>
      <div id="giphy-grid-wrap">
        <div id="giphy-grid"></div>
      </div>
    </div>`;

  document.body.appendChild(modal);

  // Cerrar al pulsar fuera del box
  modal.addEventListener('click', cerrarGiphy);

  // Cerrar con ESC
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('giphy-open')) cerrarGiphy();
  });

  // Botón cerrar
  document.getElementById('giphy-close').addEventListener('click', cerrarGiphy);

  // Búsqueda con debounce
  const input = document.getElementById('giphy-search-input');
  input.addEventListener('input', () => {
    clearTimeout(_giphySearchTO);
    _giphyQuery = input.value.trim();
    const label = document.getElementById('giphy-label-txt');
    if (label) label.textContent = _giphyQuery ? `Resultados para "${_giphyQuery}"` : 'GIFs en tendencia';
    _giphySearchTO = setTimeout(() => {
      _scrollAttached = false;
      const sentinel = document.getElementById('giphy-sentinel');
      sentinel?.remove();
      _fetchGifs(true);
    }, 350);
  });
}

// ─── ESTILOS ─────────────────────────────────────────────────────────────────
function _attachStyles() {
  if (document.getElementById('giphy-styles')) return;
  const style = document.createElement('style');
  style.id = 'giphy-styles';
  style.textContent = `
/* ═══════════════════════════════════════
   GIPHY MODAL — mobile-first
═══════════════════════════════════════ */
#giphy-modal {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 1100000;
  background: rgba(0,0,0,.65);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  align-items: flex-end;
  justify-content: center;
}
#giphy-modal.giphy-open { display: flex; }
#giphy-modal.giphy-closing #giphy-box {
  animation: giphySlideDown .2s ease forwards;
}

#giphy-box {
  background: var(--card, #fff);
  border-radius: 22px 22px 0 0;
  width: 100%;
  max-width: 600px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-height: 86vh;
  max-height: 86dvh;
  animation: giphySlideUp .22s cubic-bezier(.34,1.1,.64,1);
  box-shadow: 0 -8px 40px rgba(0,0,0,.22);
}

@keyframes giphySlideUp {
  from { opacity:.5; transform: translateY(40px); }
  to   { opacity:1;  transform: translateY(0); }
}
@keyframes giphySlideDown {
  from { opacity:1; transform: translateY(0); }
  to   { opacity:0; transform: translateY(40px); }
}

#giphy-header {
  flex-shrink: 0;
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border, #eee);
  background: var(--card, #fff);
}

#giphy-search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg2, rgba(0,0,0,.06));
  border: 1.5px solid var(--border, #e0e0e0);
  border-radius: 14px;
  padding: 0 12px;
  transition: border-color .15s;
}
#giphy-search-wrap:focus-within {
  border-color: var(--ac, #ff4d8d);
  box-shadow: 0 0 0 3px rgba(255,77,141,.1);
}

#giphy-search-icon { font-size: 18px; color: var(--text3, #aaa); flex-shrink:0; }

#giphy-search-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  padding: 10px 0;
  font-size: 14px;
  color: var(--text, #111);
  font-family: inherit;
  min-width: 0;
}
#giphy-search-input::placeholder { color: var(--text3, #aaa); }
#giphy-search-input::-webkit-search-cancel-button { display: none; }

#giphy-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text3, #aaa);
  display: flex;
  align-items: center;
  padding: 4px;
  border-radius: 50%;
  transition: color .15s, background .15s;
  flex-shrink: 0;
}
#giphy-close:hover { background: var(--bg2); color: var(--text, #111); }
#giphy-close .material-symbols-outlined { font-size: 20px; }

#giphy-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 2px 2px;
}
#giphy-label-txt {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text3, #aaa);
  text-transform: uppercase;
  letter-spacing: .05em;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
#giphy-logo {
  height: 14px;
  width: auto;
  opacity: .5;
  flex-shrink: 0;
}

#giphy-grid-wrap {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-y: contain;
  padding: 8px;
}
#giphy-grid-wrap::-webkit-scrollbar { width: 3px; }
#giphy-grid-wrap::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ── Grid masonry-like (2 cols en móvil, 3 en desktop) ── */
#giphy-grid {
  columns: 2;
  column-gap: 6px;
  width: 100%;
}
@media (min-width: 480px) { #giphy-grid { columns: 3; } }

.giphy-item {
  break-inside: avoid;
  margin-bottom: 6px;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  background: var(--bg2, #f0f0f0);
  transition: transform .15s, opacity .15s;
}
.giphy-item:hover { transform: scale(1.02); }
.giphy-item:active { transform: scale(.97); opacity: .85; }

/* Aspect-ratio padding trick para reservar espacio antes de cargar */
.giphy-item-inner {
  position: relative;
  width: 100%;
  overflow: hidden;
}
.giphy-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transition: opacity .25s;
}
.giphy-img.giphy-loaded { opacity: 1; }

/* ── Skeletons ── */
.giphy-skeleton-item {
  break-inside: avoid;
  margin-bottom: 6px;
  height: 120px;
  border-radius: 10px;
  background: linear-gradient(90deg, var(--bg2,#e8e8e8) 25%, var(--border,#d8d8d8) 50%, var(--bg2,#e8e8e8) 75%);
  background-size: 400px 100%;
  animation: giphySk 1.3s ease-in-out infinite;
}
@keyframes giphySk {
  0%   { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}

/* ── Empty/error states ── */
.giphy-empty {
  column-span: all;
  grid-column: 1/-1;
  text-align: center;
  padding: 36px 16px;
  color: var(--text3, #aaa);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.giphy-empty .material-symbols-outlined { font-size: 36px; opacity: .4; }
.giphy-empty p { font-size: 13px; }

/* ── Desktop: centrado con max-width ── */
@media (min-width: 600px) {
  #giphy-modal { align-items: center; }
  #giphy-box {
    border-radius: 18px;
    max-height: 80vh;
    animation: giphyFadeIn .18s ease;
    box-shadow: 0 16px 60px rgba(0,0,0,.28);
  }
  @keyframes giphyFadeIn {
    from { opacity:0; transform: scale(.96) translateY(-8px); }
    to   { opacity:1; transform: scale(1) translateY(0); }
  }
}

/* ── Preview de GIF seleccionado en el composer ── */
.composer-gif-preview {
  position: relative;
  display: inline-block;
  border-radius: 12px;
  overflow: hidden;
  margin-top: 8px;
  max-width: 100%;
}
.composer-gif-preview img {
  display: block;
  max-width: 100%;
  max-height: 220px;
  border-radius: 12px;
  object-fit: cover;
}
.composer-gif-remove {
  position: absolute;
  top: 6px;
  right: 6px;
  background: rgba(0,0,0,.65);
  border: none;
  border-radius: 50%;
  width: 26px;
  height: 26px;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background .15s;
}
.composer-gif-remove:hover { background: rgba(200,30,30,.85); }
.composer-gif-remove .material-symbols-outlined { font-size: 15px; }

/* ── GIF en post y comentario ── */
.post-gif-img, .comment-gif-img {
  display: block;
  width: 100%;
  max-width: 420px;
  border-radius: 12px;
  object-fit: cover;
  margin: 8px 0 4px;
  background: var(--bg2);
  cursor: pointer;
}
.comment-gif-img {
  max-width: 280px;
  border-radius: 10px;
  margin-top: 6px;
}
@media (max-width: 480px) {
  .post-gif-img { max-width: 100%; }
  .comment-gif-img { max-width: 100%; }
}

/* ── Botón GIF en la barra del composer/comentarios — estado activo ── */
#btn-gif-toggle.giphy-active,
.mc-act-btn.giphy-active {
  color: var(--ac, #ff4d8d) !important;
  background: var(--ac-soft, rgba(255,77,141,.1)) !important;
}
  `;
  document.head.appendChild(style);
}

// ─── HELPERS ─────────────────────────────────────────────────────────────────
function escG(s) {
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
