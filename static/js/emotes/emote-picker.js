/**
 * emote-picker.js — v5.1 (FIX: sin duplicación de hint/spinner)
 *
 * BUGS corregidos:
 *  • _clearGrid() centralizado — limpia TODO el contenido del grid de una vez
 *  • Sentinel vive en el BOX (fuera del grid), no dentro
 *  • loadRecents ya no puede duplicar el hint al llamarse varias veces
 *  • _renderPage limpia correctamente antes de pintar la primera página
 *  • _showLoading y _showEmpty usan _clearGrid()
 */

import {
  fetchAllEmotes,
  registerEmoteUsage,
  prefetchPopularEmotes,
  globalEmoteCache,
} from "./emote-api.js";

// ─── Paginación ───────────────────────────────────────────────────────────────

const PAGE_SIZE  = 20;
let   allEmotes  = [];
let   currentPage = 0;
let   currentQuery = "";

function _getPage(page) {
  const start = page * PAGE_SIZE;
  return allEmotes.slice(start, start + PAGE_SIZE);
}
function _hasMore() {
  return (currentPage + 1) * PAGE_SIZE < allEmotes.length;
}

// ─── Estado ───────────────────────────────────────────────────────────────────

let activeAbort    = null;
let debounceTimer  = null;
let currentTarget  = null;
let lastFirstEmote = null;
let focusedIdx     = -1;

const RECENTS_KEY = "emote_recents";
const HISTORY_KEY = "emote_search_history";
const MAX_RECENTS = 20;
const MAX_HISTORY = 10;

const TRENDING = [
  { id: "60ae4b5b36a2c8addef48b3e", name: "PogChamp"    },
  { id: "6268a27f5e3ede527d74ce74", name: "GIGACHAD"    },
  { id: "6042089e0f012f43dae27d35", name: "monkaS"      },
  { id: "60ae4b5b36a2c8addef48c1b", name: "OMEGALUL"    },
  { id: "60ae4b5b36a2c8addef48b87", name: "PauseChamp"  },
  { id: "61b6f1793cbbc72a0e9d9611", name: "BASED"       },
  { id: "60ae4b5b36a2c8addef48b5f", name: "Pog"         },
  { id: "60ae4b5b36a2c8addef48b69", name: "FeelsGoodMan"},
  { id: "60ae4b5b36a2c8addef48c35", name: "Sadge"       },
  { id: "60ae4b5b36a2c8addef48b9f", name: "peepoHappy"  },
].map(e => ({ ...e, url: `https://cdn.7tv.app/emote/${e.id}/2x.webp`, animated: false }));

let modal, searchInput, resultsGrid, recentRow, closeBtn, loadMoreBtn;
let _sentinelIO = null;   // IntersectionObserver del scroll infinito

// ─── HELPER CENTRAL: limpiar el grid ─────────────────────────────────────────
// Borra TODO el contenido del grid. Punto único de verdad.

function _clearGrid() {
  if (resultsGrid) resultsGrid.innerHTML = "";
}

// ─── Poner contenido en el grid ───────────────────────────────────────────────

function _gridAppend(el) {
  resultsGrid?.appendChild(el);
}

function _gridPrepend(node) {
  if (!resultsGrid) return;
  resultsGrid.insertBefore(node, resultsGrid.firstChild);
}

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
  loadMoreBtn?.addEventListener("click", _loadMore);
  document.addEventListener("keydown", _handleGlobalKey);

  searchInput.addEventListener("input", e => {
    const q = e.target.value.trim();
    clearTimeout(debounceTimer);
    focusedIdx = -1;
    if (!q) { _cancelSearch(); loadRecents(); return; }
    debounceTimer = setTimeout(() => _doSearch(q), 250);
  });

  _warmupRecentCache();
  _setupScrollSentinel();
}

export function setEmoteTarget(el) { currentTarget = el; }

// ─── Búsqueda ─────────────────────────────────────────────────────────────────

async function _doSearch(q) {
  if (q === currentQuery && allEmotes.length) {
    currentPage = 0;
    _clearGrid();
    _renderPage(0);
    _updateLoadMore();
    return;
  }

  _cancelSearch();
  activeAbort   = new AbortController();
  currentQuery  = q;
  currentPage   = 0;
  allEmotes     = [];
  lastFirstEmote = null;

  _showLoading();
  _saveHistory(q);

  allEmotes      = await fetchAllEmotes(q, activeAbort.signal, 80);
  lastFirstEmote = allEmotes[0] ?? null;

  _clearGrid();

  if (!allEmotes.length) {
    _showEmpty();
    _hideLoadMore();
    return;
  }

  _renderPage(0);
  _updateLoadMore();
}

function _loadMore() {
  if (!_hasMore()) return;
  currentPage++;
  _renderPage(currentPage, true);
  _updateLoadMore();
}

function _cancelSearch() {
  if (activeAbort) { activeAbort.abort(); activeAbort = null; }
  clearTimeout(debounceTimer);
}

// ─── Modal ────────────────────────────────────────────────────────────────────

function _open() {
  modal.classList.add("open");
  searchInput.value = "";
  allEmotes     = [];
  currentPage   = 0;
  currentQuery  = "";
  focusedIdx    = -1;
  lastFirstEmote = null;
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

// ─── Render página ────────────────────────────────────────────────────────────

/**
 * @param {number}  page   - índice de página (0-based)
 * @param {boolean} append - si true, añade al final; si false, REEMPLAZA todo
 */
function _renderPage(page, append = false) {
  const emotes = _getPage(page);
  if (!emotes.length) return;

  if (!append) _clearGrid();

  const frag = document.createDocumentFragment();
  emotes.forEach((emote, i) => frag.appendChild(_makeEmoteItem(emote, page * PAGE_SIZE + i)));
  _gridAppend(frag);
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
  img.width   = 40;
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

// ─── Load More ────────────────────────────────────────────────────────────────

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

// ─── Scroll infinito ──────────────────────────────────────────────────────────
// El sentinel NO vive dentro del grid (evita conflictos con innerHTML).
// Vive como hermano del grid dentro del .emote-box.

function _setupScrollSentinel() {
  if (!resultsGrid) return;

  // Usar el scroll del propio grid
  resultsGrid.addEventListener("scroll", () => {
    if (!_hasMore() || !searchInput?.value.trim()) return;
    const { scrollTop, scrollHeight, clientHeight } = resultsGrid;
    if (scrollHeight - scrollTop - clientHeight < 80) {
      currentPage++;
      _renderPage(currentPage, true);
      _updateLoadMore();
    }
  }, { passive: true });
}

// ─── Estados UI ───────────────────────────────────────────────────────────────

function _showLoading() {
  _clearGrid();
  const el = document.createElement("div");
  el.className = "emote-loading";
  el.innerHTML = `<span class="emote-spinner"></span>`;
  _gridAppend(el);
  _hideLoadMore();
}

function _showEmpty() {
  _clearGrid();
  const el = document.createElement("div");
  el.className = "emote-empty";
  el.textContent = "Sin resultados";
  _gridAppend(el);
}

function _showHint() {
  _clearGrid();
  const el = document.createElement("div");
  el.className = "emote-hint";
  el.textContent = "Busca un emote arriba ☝️";
  _gridAppend(el);
  _hideLoadMore();
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
  // NO llamar loadRecents() aquí — sólo actualizar la fila de recientes
  _refreshRecentRow();
}

export function loadRecents() {
  _refreshRecentRow();

  // Grid: si no hay búsqueda activa, mostrar hint o trending
  if (!searchInput?.value.trim()) {
    const list = _getRecents();
    if (!list.length) {
      // Sin recientes → trending
      allEmotes   = TRENDING;
      currentPage = 0;
      _renderPage(0);
      _hideLoadMore();
    } else {
      _showHint();
    }
  }
}

/** Sólo refresca la fila de recientes (sin tocar el grid). */
function _refreshRecentRow() {
  if (!recentRow) return;
  const list = _getRecents();

  if (!list.length) {
    recentRow.innerHTML = `<span class="emote-recent-empty">Sin recientes</span>`;
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
