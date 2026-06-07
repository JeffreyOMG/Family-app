/**
 * emote-picker.js — v5 (Paginación Load More + rendimiento pro)
 *
 * NUEVO en v5:
 *  • Paginación client-side: 20 iniciales, botón "Cargar más"
 *  • allEmotes[] guarda el lote completo de la API
 *  • Append incremental al DOM (no re-render completo)
 *  • Botón load-more se auto-oculta cuando no quedan más
 *  • Scroll infinito opcional (IntersectionObserver en sentinel)
 *  • emotes-post más grandes: clase .inline-emote gestionada desde CSS
 *  • Sin mensajes de error técnicos: todo silencioso
 */

import {
  fetchAllEmotes,
  registerEmoteUsage,
  prefetchPopularEmotes,
  globalEmoteCache,
} from "./emote-api.js";

// ─── Paginación ───────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;
let allEmotes   = [];   // lote completo de la búsqueda actual
let currentPage = 0;    // página que ya se mostró (0-based)
let currentQuery = "";

function _getPage(page) {
  const start = page * PAGE_SIZE;
  return allEmotes.slice(start, start + PAGE_SIZE);
}

function _hasMore() {
  return (currentPage + 1) * PAGE_SIZE < allEmotes.length;
}

// ─── Estado general ───────────────────────────────────────────────────────────

let activeAbort   = null;
let debounceTimer = null;
let currentTarget = null;
let lastFirstEmote = null; // primer emote del lote (para Enter)
let focusedIdx    = -1;

const RECENTS_KEY = "emote_recents";
const HISTORY_KEY = "emote_search_history";
const MAX_RECENTS = 20;
const MAX_HISTORY = 10;

// Trending fallback cuando no hay recientes ni búsqueda
const TRENDING = [
  { id: "60ae4b5b36a2c8addef48b3e", name: "PogChamp",    animated: false },
  { id: "6268a27f5e3ede527d74ce74", name: "GIGACHAD",    animated: false },
  { id: "6042089e0f012f43dae27d35", name: "monkaS",      animated: false },
  { id: "60ae4b5b36a2c8addef48c1b", name: "OMEGALUL",    animated: false },
  { id: "60ae4b5b36a2c8addef48b87", name: "PauseChamp",  animated: false },
  { id: "61b6f1793cbbc72a0e9d9611", name: "BASED",       animated: false },
  { id: "60ae4b5b36a2c8addef48b5f", name: "Pog",         animated: false },
  { id: "60ae4b5b36a2c8addef48b69", name: "FeelsGoodMan",animated: false },
  { id: "60ae4b5b36a2c8addef48c35", name: "Sadge",       animated: false },
  { id: "60ae4b5b36a2c8addef48b9f", name: "peepoHappy",  animated: false },
].map(e => ({ ...e, url: `https://cdn.7tv.app/emote/${e.id}/2x.webp` }));

let modal, searchInput, resultsGrid, recentRow, closeBtn, loadMoreBtn;

// ─── Init ─────────────────────────────────────────────────────────────────────

export function initEmotePicker(textarea, triggerBtnId = "btnEmotes") {
  modal       = document.getElementById("emoteModal");
  searchInput = document.getElementById("emoteSearch");
  resultsGrid = document.getElementById("emoteResults");
  recentRow   = document.getElementById("emoteRecent");
  closeBtn    = document.getElementById("closeEmote");
  loadMoreBtn = document.getElementById("emoteLoadMore");
  const openBtn = document.getElementById(triggerBtnId);

  if (!modal || !searchInput || !resultsGrid || !openBtn) {
    console.warn("[EmotePicker] DOM incompleto.");
    return;
  }

  currentTarget = textarea;

  openBtn.addEventListener("click", () => { currentTarget = textarea; _open(); });
  closeBtn?.addEventListener("click", _close);
  modal.addEventListener("click", e => { if (e.target === modal) _close(); });

  // Botón load more
  loadMoreBtn?.addEventListener("click", _loadMore);

  // Teclado
  document.addEventListener("keydown", _handleGlobalKey);

  // Input debounce 250ms
  searchInput.addEventListener("input", e => {
    const q = e.target.value.trim();
    clearTimeout(debounceTimer);
    focusedIdx = -1;
    if (!q) { _cancelSearch(); loadRecents(); return; }
    debounceTimer = setTimeout(() => _doSearch(q), 250);
  });

  _warmupRecentCache();

  // Scroll infinito en el grid (sentinel al fondo del grid)
  _setupScrollSentinel();
}

export function setEmoteTarget(el) { currentTarget = el; }

// ─── Búsqueda con paginación ──────────────────────────────────────────────────

async function _doSearch(q) {
  if (q === currentQuery && allEmotes.length) {
    // misma query y ya tenemos datos: sólo re-renderizar
    currentPage = 0;
    _renderPage(0, false);
    _updateLoadMore();
    return;
  }

  _cancelSearch();
  activeAbort  = new AbortController();
  currentQuery = q;
  currentPage  = 0;
  allEmotes    = [];

  _showLoading();
  _saveHistory(q);

  // Trae hasta 80 emotes de una vez; el picker pagina client-side
  allEmotes = await fetchAllEmotes(q, activeAbort.signal, 80);
  lastFirstEmote = allEmotes[0] ?? null;

  if (!allEmotes.length) {
    _showEmpty();
    _hideLoadMore();
    return;
  }

  _renderPage(0, false);
  _updateLoadMore();
}

function _loadMore() {
  if (!_hasMore()) return;
  currentPage++;
  _renderPage(currentPage, true); // append = true
  _updateLoadMore();
  // Scroll suave al nuevo bloque
  loadMoreBtn?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function _cancelSearch() {
  if (activeAbort) { activeAbort.abort(); activeAbort = null; }
  clearTimeout(debounceTimer);
}

// ─── Modal ────────────────────────────────────────────────────────────────────

function _open() {
  modal.classList.add("open");
  searchInput.value = "";
  allEmotes    = [];
  currentPage  = 0;
  currentQuery = "";
  focusedIdx   = -1;
  loadRecents();
  requestAnimationFrame(() => searchInput.focus());
  if ("requestIdleCallback" in window) {
    requestIdleCallback(() => prefetchPopularEmotes(), { timeout: 2000 });
  }
}

function _close() {
  modal.classList.remove("open");
  _cancelSearch();
}

// ─── Teclado ──────────────────────────────────────────────────────────────────

function _handleGlobalKey(e) {
  if (!modal?.classList.contains("open")) return;
  if (e.key === "Escape") { e.preventDefault(); _close(); return; }

  const items = resultsGrid?.querySelectorAll(".emote-item");
  if (!items?.length) return;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    focusedIdx = Math.min(focusedIdx + 1, items.length - 1);
    items[focusedIdx]?.focus();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    focusedIdx = Math.max(focusedIdx - 1, 0);
    items[focusedIdx]?.focus();
  } else if (e.key === "Enter" && lastFirstEmote && document.activeElement === searchInput) {
    _pickEmote(lastFirstEmote);
  }
}

// ─── Render ───────────────────────────────────────────────────────────────────

/**
 * Renderiza una página al grid.
 * @param {number} page  - página a renderizar
 * @param {boolean} append - si true, añade al final; si false, limpia primero
 */
function _renderPage(page, append) {
  const emotes = _getPage(page);
  if (!emotes.length) return;

  if (!append) {
    // Limpiar sólo los emote-items anteriores, dejar el sentinel
    const existing = resultsGrid.querySelectorAll(".emote-item");
    existing.forEach(el => el.remove());
  }

  const frag = document.createDocumentFragment();
  emotes.forEach((emote, i) => frag.appendChild(_makeEmoteItem(emote, page * PAGE_SIZE + i)));
  resultsGrid.appendChild(frag);
}

function _makeEmoteItem(emote, idx) {
  const el = document.createElement("div");
  el.className = "emote-item";
  el.title     = emote.name;
  el.role      = "button";
  el.tabIndex  = 0;
  el.setAttribute("aria-label", `Emote ${emote.name}`);
  el.dataset.idx = idx;

  const img   = document.createElement("img");
  img.alt     = emote.name;
  img.loading = "lazy";
  img.width   = 40;   // más grande: era 32px
  img.height  = 40;
  img.style.opacity = "0";
  img.onload  = () => { img.style.transition = "opacity .15s ease"; img.style.opacity = "1"; img.classList.add("loaded"); };
  img.onerror = () => { img.style.opacity = "0.35"; };
  img.src     = emote.url;

  const label = document.createElement("span");
  label.textContent = emote.name;

  el.appendChild(img);
  el.appendChild(label);

  const pick = () => _pickEmote(emote);
  el.addEventListener("click", pick);
  el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
  el.addEventListener("mouseenter", () => {
    globalEmoteCache.set(emote.name.toLowerCase(), emote.url);
  }, { once: true });

  return el;
}

function _pickEmote(emote) {
  insertEmoteAtCursor(currentTarget, emote.name);
  saveRecent(emote);
  _close();
}

// ─── Load More button ─────────────────────────────────────────────────────────

function _updateLoadMore() {
  if (!loadMoreBtn) return;
  if (_hasMore()) {
    const remaining = allEmotes.length - (currentPage + 1) * PAGE_SIZE;
    loadMoreBtn.textContent = `Cargar ${Math.min(remaining, PAGE_SIZE)} más`;
    loadMoreBtn.style.display = "flex";
  } else {
    _hideLoadMore();
  }
}

function _hideLoadMore() {
  if (loadMoreBtn) loadMoreBtn.style.display = "none";
}

// ─── Scroll infinito (sentinel) ───────────────────────────────────────────────

function _setupScrollSentinel() {
  if (!resultsGrid) return;
  const sentinel = document.createElement("div");
  sentinel.id = "emote-sentinel";
  sentinel.style.height = "1px";
  resultsGrid.appendChild(sentinel);

  const io = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting && _hasMore() && searchInput?.value.trim()) {
        currentPage++;
        _renderPage(currentPage, true);
        _updateLoadMore();
      }
    });
  }, { root: resultsGrid, rootMargin: "60px" });

  io.observe(sentinel);
}

// ─── Estados UI ───────────────────────────────────────────────────────────────

function _showLoading() {
  if (!resultsGrid) return;
  resultsGrid.querySelectorAll(".emote-item").forEach(el => el.remove());
  // Conservar sentinel; añadir spinner al principio
  const spinner = document.createElement("div");
  spinner.className = "emote-loading";
  spinner.innerHTML = `<span class="emote-spinner"></span>`;
  spinner.id = "__emote-spinner";
  resultsGrid.insertBefore(spinner, resultsGrid.firstChild);
  _hideLoadMore();
}

function _showEmpty() {
  if (!resultsGrid) return;
  const old = resultsGrid.querySelectorAll(".emote-item, .emote-loading, .emote-hint, #__emote-spinner");
  old.forEach(el => el.remove());
  const empty = document.createElement("div");
  empty.className = "emote-empty";
  empty.textContent = "Sin resultados";
  resultsGrid.insertBefore(empty, resultsGrid.firstChild);
}

// ─── Inserción en cursor ──────────────────────────────────────────────────────

export function insertEmoteAtCursor(el, emoteName) {
  if (!el) return;
  const tag = `:${emoteName}: `;

  if (el.isContentEditable) {
    el.focus();
    const sel = window.getSelection();
    if (!sel?.rangeCount) return;
    const range = sel.getRangeAt(0);
    range.deleteContents();
    const tn = document.createTextNode(tag);
    range.insertNode(tn);
    range.setStartAfter(tn);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  } else {
    const s  = el.selectionStart ?? el.value.length;
    const e2 = el.selectionEnd   ?? el.value.length;
    el.value = el.value.substring(0, s) + tag + el.value.substring(e2);
    el.focus();
    el.selectionStart = el.selectionEnd = s + tag.length;
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

// ─── Recientes ────────────────────────────────────────────────────────────────

export function saveRecent(emote) {
  let list = _getRecents();
  list = list.filter(e => e.id !== emote.id);
  list.unshift(emote);
  list = list.slice(0, MAX_RECENTS);
  try { localStorage.setItem(RECENTS_KEY, JSON.stringify(list)); } catch {}
  registerEmoteUsage(emote.name, emote.url);
  loadRecents();
}

export function loadRecents() {
  if (!recentRow || !resultsGrid) return;
  const list = _getRecents();

  if (!list.length) {
    recentRow.innerHTML = `<span class="emote-recent-empty">Sin recientes</span>`;
    // Mostrar trending en el grid
    resultsGrid.querySelectorAll(".emote-item, .emote-hint, #__emote-spinner").forEach(el => el.remove());
    allEmotes   = TRENDING;
    currentPage = 0;
    _renderPage(0, false);
    _hideLoadMore();
    return;
  }

  recentRow.innerHTML = "";
  const frag = document.createDocumentFragment();
  list.forEach(emote => {
    const img     = document.createElement("img");
    img.alt       = emote.name;
    img.title     = emote.name;
    img.loading   = "lazy";
    img.className = "recent-emote";
    img.style.opacity = "0";
    img.onload  = () => { img.style.opacity = "1"; img.classList.add("loaded"); };
    img.onerror = () => { img.style.opacity = "0.35"; };
    img.src     = emote.url;
    img.addEventListener("click", () => _pickEmote(emote));
    frag.appendChild(img);
  });
  recentRow.appendChild(frag);

  // Grid → hint si no hay búsqueda activa
  if (!searchInput?.value.trim()) {
    resultsGrid.querySelectorAll(".emote-item, #__emote-spinner").forEach(el => el.remove());
    const hint = document.createElement("div");
    hint.className = "emote-hint";
    hint.textContent = "Busca un emote arriba ☝️";
    resultsGrid.insertBefore(hint, resultsGrid.firstChild);
    _hideLoadMore();
  }
}

function _getRecents() {
  try { return JSON.parse(localStorage.getItem(RECENTS_KEY) || "[]"); } catch { return []; }
}

function _warmupRecentCache() {
  _getRecents().forEach(e => {
    if (e.name && e.url) globalEmoteCache.set(e.name.toLowerCase(), e.url);
  });
}

// ─── Historial ────────────────────────────────────────────────────────────────

function _saveHistory(q) {
  try {
    let hist = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    hist = hist.filter(h => h !== q);
    hist.unshift(q);
    hist = hist.slice(0, MAX_HISTORY);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(hist));
  } catch {}
}

export function getSearchHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { return []; }
}
