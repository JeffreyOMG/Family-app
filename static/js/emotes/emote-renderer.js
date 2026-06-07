/**
 * emote-renderer.js  — v3 (Parte 3: Production Ready)
 *
 * MEJORAS sobre v2:
 *  • Render queue con CPU yield (anti-freeze en feeds largos)
 *  • Imagen con fade-in suave (clase .loaded)
 *  • Prefetch automático de emotes usados
 *  • globalEmoteCache compartido con emote-api.js
 *  • Sanitización hardened
 *  • IntersectionObserver rootMargin: 300px (pre-carga anticipada)
 *  • WeakSet de procesados (sin double-render)
 *  • Fallback gracioso si CDN falla
 */

import { resolveEmoteUrl, sanitizeEmoteName, registerEmoteUsage, prefetchPopularEmotes } from "./emote-api.js";

// ─── Constantes ───────────────────────────────────────────────────────────────

const EMOTE_RE = /:([A-Za-z0-9_\-]{2,40}):/g;

const TEXT_SELECTORS = [
  '.post-text',
  '.comment-text',
  '.pv-texto',
  '.pv-comment-text',
];

/** Nodos ya procesados — evita doble-render */
const processed = new WeakSet();

// ─── Render Queue (anti-freeze) ───────────────────────────────────────────────

const renderQueue = [];
let queueRunning  = false;

function queueRender(node) {
  if (processed.has(node)) return;
  renderQueue.push(node);
  _drainQueue();
}

async function _drainQueue() {
  if (queueRunning) return;
  queueRunning = true;

  while (renderQueue.length > 0) {
    const node = renderQueue.shift();
    await _renderNode(node);
    // Yield al browser entre cada nodo para no congelar el hilo principal
    await new Promise(r => setTimeout(r, 8));
  }

  queueRunning = false;

  // Una vez vaciada la cola, prefetch de emotes populares en idle
  if ("requestIdleCallback" in window) {
    requestIdleCallback(() => prefetchPopularEmotes(), { timeout: 3000 });
  } else {
    setTimeout(() => prefetchPopularEmotes(), 2000);
  }
}

// ─── Core renderer ────────────────────────────────────────────────────────────

async function _renderNode(el) {
  if (!el || processed.has(el)) return;
  processed.add(el);

  // TreeWalker sólo sobre text nodes con tokens :x:
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
  while ((n = walker.nextNode())) {
    EMOTE_RE.lastIndex = 0;
    textNodes.push(n);
  }
  if (!textNodes.length) return;

  for (const tn of textNodes) {
    await _replaceTokens(tn);
  }
}

async function _replaceTokens(textNode) {
  if (!textNode.parentNode) return;   // nodo ya eliminado del DOM
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

  // Resolver todas las URLs en paralelo
  const urls = await Promise.all(
    parts.map(p => p.emote ? resolveEmoteUrl(p.emote) : Promise.resolve(null))
  );

  if (!urls.some(Boolean)) return;   // ningún emote válido → no tocar DOM

  const frag = document.createDocumentFragment();
  parts.forEach((p, i) => {
    if (p.text) {
      frag.appendChild(document.createTextNode(p.text));
    } else if (urls[i]) {
      frag.appendChild(_makeImg(p.emote, urls[i]));
      registerEmoteUsage(p.emote, urls[i]);
    } else {
      frag.appendChild(document.createTextNode(`:${p.emote}:`));
    }
  });

  textNode.parentNode.replaceChild(frag, textNode);
}

function _makeImg(name, url) {
  const img       = document.createElement("img");
  img.alt         = `:${name}:`;
  img.title       = name;
  img.loading     = "lazy";
  img.className   = "inline-emote";
  img.width       = 28;
  img.height      = 28;
  // Fade-in: empieza invisible, .loaded la hace visible
  img.style.opacity = "0";
  img.onload  = () => { img.style.opacity = ""; img.classList.add("loaded"); };
  img.onerror = () => { img.replaceWith(document.createTextNode(`:${name}:`)); };
  img.src = url;   // src al final para que onload/onerror estén registrados
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
  }, { rootMargin: "300px" });   // 300px de anticipación
  return _io;
}

export function observeEmoteNode(el) {
  if (!el || processed.has(el)) return;
  _getIO().observe(el);
}

/** Render inmediato (para elementos nuevos ya visibles). */
export function renderEmoteNode(el) {
  if (!el) return;
  queueRender(el);
}

// ─── MutationObserver ─────────────────────────────────────────────────────────

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
    document.getElementById("feed") ||
    document.querySelector(".posts-list") ||
    document.querySelector("main") ||
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
