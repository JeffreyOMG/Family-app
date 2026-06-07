/**
 * emote-api.js — v5 (Paginación + GQL estable + Cache TTL)
 *
 * NUEVO en v5:
 *  • fetchRaw(query, limit) → devuelve TODO el array desde la API (hasta 100)
 *  • searchEmotes solo trae 20 por defecto; el picker maneja páginas
 *  • Paginación vive en el estado del picker (no en la API)
 *  • Cache TTL 10 min sin cambios
 */

const GQL_URL       = "https://7tv.io/v3/gql";
const CDN_BASE      = "https://cdn.7tv.app/emote";
const EMOTE_QUALITY = "2x";
const CACHE_TTL_MS  = 10 * 60 * 1000;

// ─── Cache con TTL ────────────────────────────────────────────────────────────

const _searchCache = new Map();

function _cacheGet(key) {
  const entry = _searchCache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.time > CACHE_TTL_MS) { _searchCache.delete(key); return null; }
  return entry.data;
}
function _cacheSet(key, data) {
  _searchCache.set(key, { data, time: Date.now() });
}

// ─── Cache global de URLs (compartido con renderer) ───────────────────────────

export const globalEmoteCache = new Map();

const popularEmotes = new Set();

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function emoteUrl(id) {
  return `${CDN_BASE}/${id}/${EMOTE_QUALITY}.webp`;
}

export function sanitizeEmoteName(name) {
  return String(name).replace(/[^a-zA-Z0-9_\-]/g, "").slice(0, 40);
}

// ─── GQL fetch ───────────────────────────────────────────────────────────────

async function _gqlSearch(query, limit, signal) {
  const res = await fetch(GQL_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: `
        query SearchEmotes($query: String!, $limit: Int!) {
          emotes(query: $query, limit: $limit) {
            items { id name animated }
          }
        }`,
      variables: { query, limit },
    }),
    signal: signal ?? AbortSignal.timeout(7000),
  });
  if (!res.ok) throw new Error(`GQL HTTP ${res.status}`);
  const json = await res.json();
  return json?.data?.emotes?.items ?? [];
}

function _toEmote(e) {
  return { id: e.id, name: e.name, url: emoteUrl(e.id), animated: e.animated ?? false };
}

// ─── fetchAllEmotes — trae el lote completo (para paginación en picker) ───────

/**
 * Trae hasta `limit` emotes para una query y los devuelve todos.
 * El picker decide cuántos mostrar por página.
 * Usa cache con TTL.
 * NUNCA lanza.
 */
export async function fetchAllEmotes(query, signal, limit = 80) {
  if (!query || query.trim().length < 2) return [];

  const key = query.toLowerCase().trim();
  const cached = _cacheGet(key);
  if (cached) return cached;

  try {
    const items  = await _gqlSearch(key, limit, signal);
    const emotes = items.map(_toEmote);

    _cacheSet(key, emotes);
    emotes.forEach(e => globalEmoteCache.set(e.name.toLowerCase(), e.url));

    return emotes;
  } catch (err) {
    if (err?.name === "AbortError") return [];
    console.warn("[7TV] fetchAllEmotes fallback silencioso:", err.message);
    const stale = _searchCache.get(query.toLowerCase().trim());
    return stale ? stale.data : [];
  }
}

// ─── searchEmotes — compatibilidad hacia atrás (devuelve primeros 20) ─────────

export async function searchEmotes(query, signal) {
  const all = await fetchAllEmotes(query, signal, 20);
  return all;
}

// ─── resolveEmoteUrl — para el renderer ──────────────────────────────────────

export async function resolveEmoteUrl(rawName) {
  const name = sanitizeEmoteName(rawName);
  const key  = name.toLowerCase();

  if (globalEmoteCache.has(key)) return globalEmoteCache.get(key);

  try {
    const items = await _gqlSearch(name, 5, AbortSignal.timeout(5000));
    const exact = items.find(e => e.name.toLowerCase() === key);
    const hit   = exact || items[0];
    const url   = hit ? emoteUrl(hit.id) : null;
    globalEmoteCache.set(key, url);
    if (url) popularEmotes.add(name);
    return url;
  } catch {
    globalEmoteCache.set(key, null);
    return null;
  }
}

// ─── Registro + prefetch ──────────────────────────────────────────────────────

export function registerEmoteUsage(name, url) {
  const key = sanitizeEmoteName(name).toLowerCase();
  if (url) globalEmoteCache.set(key, url);
  popularEmotes.add(name);
}

export async function prefetchPopularEmotes() {
  const list = Array.from(popularEmotes).slice(0, 20);
  for (const name of list) {
    const key = name.toLowerCase();
    if (globalEmoteCache.has(key)) continue;
    resolveEmoteUrl(name).catch(() => {});
    await new Promise(r => setTimeout(r, 100));
  }
}

export function clearAllCaches() {
  _searchCache.clear();
  globalEmoteCache.clear();
  popularEmotes.clear();
}
