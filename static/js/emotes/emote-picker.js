/**
 * emote-picker.js  — v3 (Parte 3: Production Ready)
 *
 * Mejoras sobre v2:
 *  • Imagen del picker con fade-in (.loaded)
 *  • Prefetch al abrir el modal (warm-up de caché)
 *  • Carga de recientes warm-up en la caché global
 *  • Tab-complete básico: Escape cierra, Enter inserta primer resultado
 *  • Mejor accesibilidad (role, aria)
 */

import { searchEmotes, registerEmoteUsage, prefetchPopularEmotes, globalEmoteCache } from "./emote-api.js";

// ─── Estado ───────────────────────────────────────────────────────────────────
let activeAbort   = null;
let debounceTimer = null;
let currentTarget = null;
let lastResults   = [];   // para Enter-to-insert primer resultado

const RECENTS_KEY = "emote_recents";
const MAX_RECENTS = 20;

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
    console.warn("[EmotePicker] DOM incompleto — verifica los IDs del modal.");
    return;
  }

  currentTarget = textarea;

  openBtn.addEventListener("click", () => { currentTarget = textarea; _open(); });
  closeBtn?.addEventListener("click", _close);
  modal.addEventListener("click", e => { if (e.target === modal) _close(); });

  document.addEventListener("keydown", e => {
    if (!modal.classList.contains("open")) return;
    if (e.key === "Escape") { e.preventDefault(); _close(); }
    // Enter inserta el primer resultado sin cerrar
    if (e.key === "Enter" && e.ctrlKey && lastResults[0]) {
      insertEmoteAtCursor(currentTarget, lastResults[0].name);
      saveRecent(lastResults[0]);
    }
  });

  searchInput.addEventListener("input", e => {
    const q = e.target.value.trim();
    clearTimeout(debounceTimer);
    if (!q) { loadRecents(); return; }

    debounceTimer = setTimeout(async () => {
      if (activeAbort) activeAbort.abort();
      activeAbort = new AbortController();
      _showLoading();
      try {
        const emotes = await searchEmotes(q, activeAbort.signal);
        lastResults = emotes;
        _renderPickerEmotes(emotes);
      } catch {
        _showError();
      }
    }, 300);
  });

  // Warm-up: precarga recientes en la caché global al arrancar
  _warmupRecentCache();
}

export function setEmoteTarget(el) {
  currentTarget = el;
}

// ─── Modal ────────────────────────────────────────────────────────────────────

function _open() {
  modal.classList.add("open");
  searchInput.value = "";
  lastResults = [];
  loadRecents();
  searchInput.focus();
  // Prefetch popular en idle
  if ("requestIdleCallback" in window) {
    requestIdleCallback(() => prefetchPopularEmotes(), { timeout: 2000 });
  }
}

function _close() {
  modal.classList.remove("open");
  if (activeAbort) { activeAbort.abort(); activeAbort = null; }
  clearTimeout(debounceTimer);
}

// ─── Render picker ────────────────────────────────────────────────────────────

function _renderPickerEmotes(emotes) {
  resultsGrid.innerHTML = "";
  if (!emotes.length) {
    resultsGrid.innerHTML = `<div class="emote-empty">Sin resultados para esa búsqueda</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  emotes.forEach(emote => {
    const el = document.createElement("div");
    el.className     = "emote-item";
    el.title         = emote.name;
    el.role          = "button";
    el.tabIndex      = 0;
    el.setAttribute("aria-label", emote.name);

    const img = document.createElement("img");
    img.alt     = emote.name;
    img.loading = "lazy";
    img.width   = 32;
    img.height  = 32;
    // Fade-in
    img.style.opacity = "0";
    img.onload  = () => { img.style.opacity = ""; img.classList.add("loaded"); };
    img.onerror = () => { img.style.opacity = "1"; };
    img.src = emote.url;

    const label = document.createElement("span");
    label.textContent = emote.name;

    el.appendChild(img);
    el.appendChild(label);

    const pick = () => {
      insertEmoteAtCursor(currentTarget, emote.name);
      saveRecent(emote);
      _close();
    };
    el.addEventListener("click", pick);
    el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") pick(); });

    frag.appendChild(el);
  });
  resultsGrid.appendChild(frag);
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
    const s = el.selectionStart ?? el.value.length;
    const e2 = el.selectionEnd ?? el.value.length;
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
  if (!recentRow) return;
  const list = _getRecents();

  if (!list.length) {
    recentRow.innerHTML = `<span class="emote-recent-empty">Aún no usaste emotes</span>`;
    resultsGrid.innerHTML = `<div class="emote-hint">Busca un emote arriba ☝️</div>`;
    return;
  }

  recentRow.innerHTML = "";
  const frag = document.createDocumentFragment();
  list.forEach(emote => {
    const img = document.createElement("img");
    img.alt       = emote.name;
    img.title     = emote.name;
    img.loading   = "lazy";
    img.className = "recent-emote";
    img.style.opacity = "0";
    img.onload  = () => { img.style.opacity = ""; img.classList.add("loaded"); };
    img.onerror = () => { img.style.opacity = "1"; };
    img.src = emote.url;
    img.addEventListener("click", () => {
      insertEmoteAtCursor(currentTarget, emote.name);
      saveRecent(emote);
      _close();
    });
    frag.appendChild(img);
  });
  recentRow.appendChild(frag);
  resultsGrid.innerHTML = `<div class="emote-hint">Busca un emote arriba ☝️</div>`;
}

function _getRecents() {
  try { return JSON.parse(localStorage.getItem(RECENTS_KEY) || "[]"); } catch { return []; }
}

/** Mete las URLs de los recientes en globalEmoteCache para no re-fetchear */
function _warmupRecentCache() {
  _getRecents().forEach(e => {
    if (e.name && e.url) globalEmoteCache.set(e.name.toLowerCase(), e.url);
  });
}

// ─── UI states ────────────────────────────────────────────────────────────────

function _showLoading() {
  resultsGrid.innerHTML = `
    <div class="emote-loading">
      <span class="emote-spinner"></span>
      Buscando emotes...
    </div>`;
}

function _showError() {
  resultsGrid.innerHTML = `<div class="emote-error">⚠️ No se pudo conectar con 7TV</div>`;
}
