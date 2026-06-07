/**
 * emote-renderer.js — v4 (Production Ready + Silent Errors)
 *
 * CAMBIOS v4:
 *  • resolveEmoteUrl nunca lanza → no puede romper el feed
 *  • render queue con CPU yield (anti-freeze)
 *  • Fade-in suave con clase .loaded
 *  • IntersectionObserver rootMargin: 400px (más anticipación)
 *  • WeakSet de procesados (sin doble-render)
 *  • onerror silencioso: reemplaza img por texto plano :emoteName:
 *  • MutationObserver para feeds dinámicos (SPA-compatible)
 */

import {
  resolveEmoteUrl,
  sanitizeEmoteName,
  registerEmoteUsage,
  prefetchPopularEmotes,
} from "./emote-api.js";

// ─── Constantes ───────────────────────────────────────────────────────────────

const EMOTE_RE = /:([A-Za-z0-9_\-]{2,40}):/g;

const TEXT_SELECTORS = [
  ".post-text",
  ".comment-text",
  ".pv-texto",
  ".pv-comment-text",
];

const processed = new WeakSet();

// ─── Render Queue (anti-freeze) ───────────────────────────────────────────────

const renderQueue = [];
let   queueRunning = false;

function queueRender(node) {
  if (processed.has(node)) return;
  renderQueue.push(node);
  _drainQueue();
}

async function _drainQueue() {
  if (queueRunning) return;
  queueRunning = true;

  while (renderQueue.length) {
    const node = renderQueue.shift();
    await _renderNode(node);
    // Yield al browser: evita congelar UI en feeds largos
    await new Promise(r => setTimeout(r, 8));
  }

  queueRunning = false;

  // Prefetch de populares una vez vaciada la cola
  if ("requestIdleCallback" in window) {
    requestIdleCallback(() => prefetchPopularEmotes(), { timeout: 3000 });
  } else {
    setTimeout(prefetchPopularEmotes, 2000);
  }
}

// ─── Core renderer ────────────────────────────────────────────────────────────

async function _renderNode(el) {
  if (!el || processed.has(el)) return;
  processed.add(el);

  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      EMOTE_RE.lastIndex = 0;
      return EMOTE_RE.test(node.nodeValue)
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_SKIP;
    },
  });

  const textNodes = [];
  let n;
  while ((n = walker.nextNode())) textNodes.push(n);
  if (!textNodes.length) return;

  for (const tn of textNodes) {
    await _replaceTokens(tn);
  }
}

async function _replaceTokens(textNode) {
  if (!textNode.parentNode) return;
  const raw = textNode.nodeValue;
  EMOTE_RE.lastIndex = 0;

  const parts = [];
  let lastIdx = 0, m;

  while ((m = EMOTE_RE.exec(raw)) !== null) {
    if (m.index > lastIdx) parts.push({ text: raw.slice(lastIdx, m.index) });
    parts.push({ emote: sanitizeEmoteName(m[1]) });
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < raw.length) parts.push({ text: raw.slice(lastIdx) });

  // Resolver todas las URLs en paralelo — resolveEmoteUrl nunca lanza
  const urls = await Promise.all(
    parts.map(p => p.emote ? resolveEmoteUrl(p.emote) : Promise.resolve(null))
  );

  // Si ningún emote resolvió, dejar el texto como está
  if (!urls.some(Boolean)) return;

  const frag = document.createDocumentFragment();
  parts.forEach((p, i) => {
    if (p.text) {
      frag.appendChild(document.createTextNode(p.text));
    } else if (urls[i]) {
      frag.appendChild(_makeImg(p.emote, urls[i]));
      registerEmoteUsage(p.emote, urls[i]);
    } else {
      // Emote no encontrado → texto plano, sin ruido visual
      frag.appendChild(document.createTextNode(`:${p.emote}:`));
    }
  });

  textNode.parentNode.replaceChild(frag, textNode);
}

function _makeImg(name, url) {
  const img     = document.createElement("img");
  img.alt       = `:${name}:`;
  img.title     = name;
  img.loading   = "lazy";
  img.className = "inline-emote";
  img.width     = 28;
  img.height    = 28;
  img.style.opacity = "0";
  // Fade-in suave
  img.onload  = () => {
    img.style.transition = "opacity 0.15s ease";
    img.style.opacity    = "1";
    img.classList.add("loaded");
  };
  // onerror silencioso: reemplaza img por texto
  img.onerror = () => {
    img.replaceWith(document.createTextNode(`:${name}:`));
  };
  img.src = url; // src al final para que los handlers estén listos
  return img;
}

// ─── IntersectionObserver ─────────────────────────────────────────────────────

let _io = null;

function _getIO() {
  if (_io) return _io;
  _io = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        _io.unobserve(e.target);
        queueRender(e.target);
      }
    });
  }, { rootMargin: "400px" }); // 400px de anticipación
  return _io;
}

export function observeEmoteNode(el) {
  if (!el || processed.has(el)) return;
  _getIO().observe(el);
}

/** Render inmediato (para elementos ya visibles). */
export function renderEmoteNode(el) {
  if (!el) return;
  queueRender(el);
}

// ─── MutationObserver (feeds dinámicos / SPA) ─────────────────────────────────

let _mo = null;

export function watchContainer(container) {
  if (_mo || !container) return;
  _mo = new MutationObserver(mutations => {
    for (const mut of mutations) {
      for (const node of mut.addedNodes) {
        if (node.nodeType !== 1) continue;
        if (TEXT_SELECTORS.some(s => node.matches?.(s))) {
          observeEmoteNode(node);
        }
        TEXT_SELECTORS.forEach(s => {
          node.querySelectorAll?.(s).forEach(observeEmoteNode);
        });
      }
    }
  });
  _mo.observe(container, { childList: true, subtree: true });
}

// ─── Init ─────────────────────────────────────────────────────────────────────

export function initEmoteRenderer() {
  const io = _getIO();
  document.querySelectorAll(TEXT_SELECTORS.join(", ")).forEach(el => io.observe(el));

  const feed =
    document.getElementById("posts-feed") ||
    document.getElementById("feed")       ||
    document.querySelector(".posts-list") ||
    document.querySelector("main")        ||
    document.body;

  watchContainer(feed);
}

// ─── Helper modal ─────────────────────────────────────────────────────────────

export function renderEmotesInModal() {
  const modal = document.getElementById("pv-content");
  if (!modal) return;
  TEXT_SELECTORS.forEach(s => {
    modal.querySelectorAll(s).forEach(renderEmoteNode);
  });
}
