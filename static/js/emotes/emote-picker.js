/**
 * emote-picker.js — v4 (UX Pro: nunca muestra errores técnicos)
 *
 * CAMBIOS v4:
 *  • _showError() eliminada — ahora va a showEmpty() silencioso
 *  • Debounce de 250ms (era 300ms)
 *  • Solo 2 estados UI: "resultados" o "sin resultados"
 *  • Trending emotes al abrir (si no hay recientes)
 *  • Navegación por teclado: ↑↓ entre emotes, Enter inserta
 *  • Historial de búsquedas en localStorage
 *  • Sin throw al exterior: todos los errores son silenciosos
 */

import {
  searchEmotes,
  registerEmoteUsage,
  prefetchPopularEmotes,
  globalEmoteCache,
} from "./emote-api.js";

// ─── Estado ───────────────────────────────────────────────────────────────────

let activeAbort   = null;
let debounceTimer = null;
let currentTarget = null;
let lastResults   = [];
let focusedIdx    = -1;

const RECENTS_KEY  = "emote_recents";
const HISTORY_KEY  = "emote_search_history";
const MAX_RECENTS  = 20;
const MAX_HISTORY  = 10;

// Trending por defecto si la API cae o no hay recientes
const TRENDING_FALLBACK = [
  { id: "60ae4b5b36a2c8add ef48b3", name: "PogChamp"  },
  { id: "6268a27f5e3ede527d74ce74", name: "GIGACHAD"  },
  { id: "6042089e0f012f43dae27d35", name: "monkaS"    },
  { id: "60ae4b5b36a2c8addef48c1b", name: "OMEGALUL"  },
  { id: "60ae4b5b36a2c8addef48b87", name: "PauseChamp"},
  { id: "61b6f1793cbbc72a0e9d9611", name: "BASED"     },
  { id: "60ae4b5b36a2c8addef48b5f", name: "Pog"       },
  { id: "60ae4b5b36a2c8addef48b69", name: "FeelsGoodMan"},
].map(e => ({
  ...e,
  id:  e.id.replace(/\s/g, ""), // limpiar IDs con espacios
  url: `https://cdn.7tv.app/emote/${e.id.replace(/\s/g, "")}/2x.webp`,
  animated: false,
}));

let modal, searchInput, resultsGrid, recentRow, closeBtn;

// ─── Init ─────────────────────────────────────────────────────────────────────

export function initEmotePicker(textarea, triggerBtnId = "btnEmotes") {
  modal       = document.getElementById("emoteModal");
  searchInput = document.getElementById("emoteSearch");
  resultsGrid = document.getElementById("emoteResults");
  recentRow   = document.getElementById("emoteRecent");
  closeBtn    = document.getElementById("closeEmote");
  const openBtn = document.getElementById(triggerBtnId);

  if (!modal || !searchInput || !resultsGrid || !openBtn) {
    console.warn("[EmotePicker] DOM incompleto — verifica IDs del modal.");
    return;
  }

  currentTarget = textarea;

  openBtn.addEventListener("click", () => { currentTarget = textarea; _open(); });
  closeBtn?.addEventListener("click", _close);
  modal.addEventListener("click", e => { if (e.target === modal) _close(); });

  // Teclado global
  document.addEventListener("keydown", _handleGlobalKey);

  // Input con debounce
  searchInput.addEventListener("input", e => {
    const q = e.target.value.trim();
    clearTimeout(debounceTimer);
    focusedIdx = -1;

    if (!q) {
      _cancelSearch();
      loadRecents();
      return;
    }

    debounceTimer = setTimeout(() => _doSearch(q), 250);
  });

  // Warm-up al arrancar
  _warmupRecentCache();
}

export function setEmoteTarget(el) {
  currentTarget = el;
}

// ─── Búsqueda ─────────────────────────────────────────────────────────────────

async function _doSearch(q) {
  _cancelSearch();
  activeAbort = new AbortController();
  _showLoading();

  // Guardar en historial
  _saveHistory(q);

  // searchEmotes NUNCA lanza: devuelve [] en caso de error
  const emotes = await searchEmotes(q, activeAbort.signal);
  lastResults = emotes;
  _renderPickerEmotes(emotes);
}

function _cancelSearch() {
  if (activeAbort) {
    activeAbort.abort();
    activeAbort = null;
  }
  clearTimeout(debounceTimer);
}

// ─── Modal ────────────────────────────────────────────────────────────────────

function _open() {
  modal.classList.add("open");
  searchInput.value = "";
  lastResults = [];
  focusedIdx  = -1;
  loadRecents();
  requestAnimationFrame(() => searchInput.focus());

  // Prefetch de populares en idle
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

  if (e.key === "Escape") {
    e.preventDefault();
    _close();
    return;
  }

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
  } else if (e.key === "Enter" && lastResults[0] && document.activeElement === searchInput) {
    // Enter en el input = insertar primer resultado
    _pickEmote(lastResults[0]);
  }
}

// ─── Render resultados ────────────────────────────────────────────────────────

function _renderPickerEmotes(emotes) {
  if (!resultsGrid) return;
  resultsGrid.innerHTML = "";

  if (!emotes || !emotes.length) {
    _showEmpty();
    return;
  }

  const frag = document.createDocumentFragment();
  emotes.forEach((emote, idx) => {
    const el = _makeEmoteItem(emote, idx);
    frag.appendChild(el);
  });
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

  const img = document.createElement("img");
  img.alt     = emote.name;
  img.loading = "lazy";
  img.width   = 32;
  img.height  = 32;
  img.style.opacity = "0";
  img.onload  = () => { img.style.opacity = "1"; img.classList.add("loaded"); };
  img.onerror = () => { img.style.opacity = "0.4"; }; // fallo silencioso
  img.src     = emote.url;

  const label = document.createElement("span");
  label.textContent = emote.name;

  el.appendChild(img);
  el.appendChild(label);

  const pick = () => _pickEmote(emote);
  el.addEventListener("click", pick);
  el.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
  });

  // Hover prefetch
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

// ─── Estados UI (solo 2 visibles al usuario) ──────────────────────────────────

function _showLoading() {
  if (!resultsGrid) return;
  resultsGrid.innerHTML = `
    <div class="emote-loading">
      <span class="emote-spinner"></span>
    </div>`;
}

function _showEmpty() {
  if (!resultsGrid) return;
  resultsGrid.innerHTML = `<div class="emote-empty">Sin resultados</div>`;
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
    // Mostrar trending como placeholder
    _renderPickerEmotes(TRENDING_FALLBACK);
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
    img.onerror = () => { img.style.opacity = "0.4"; };
    img.src     = emote.url;
    img.addEventListener("click", () => _pickEmote(emote));
    frag.appendChild(img);
  });
  recentRow.appendChild(frag);
  resultsGrid.innerHTML = `<div class="emote-hint">Busca un emote arriba ☝️</div>`;
}

function _getRecents() {
  try { return JSON.parse(localStorage.getItem(RECENTS_KEY) || "[]"); } catch { return []; }
}

function _warmupRecentCache() {
  _getRecents().forEach(e => {
    if (e.name && e.url) globalEmoteCache.set(e.name.toLowerCase(), e.url);
  });
}

// ─── Historial de búsquedas ───────────────────────────────────────────────────

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
