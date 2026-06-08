/**
 * emote-api.js — v6 (Exact match + localStorage persistence)
 *
 * CAMBIOS v6:
 *  • resolveEmoteUrl solo usa exact match (nunca items[0]) → el emote siempre es el correcto
 *  • globalEmoteCache se persiste en localStorage (clave "emote_url_cache")
 *    para que las URLs sobrevivan recargas y no cambien entre sesiones
 *  • fetchAllEmotes registra todas las URLs en el cache persistente
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

// ─── Cache global de URLs — persistente en localStorage ───────────────────────
// Clave: nombre en minúsculas  Valor: URL del emote (string)
// Se carga al arrancar y se sincroniza en cada escritura.

const _STORAGE_KEY = "emote_url_cache";
const _MAX_STORED  = 500;   // máximo de entradas guardadas

function _loadStoredCache() {
  try {
    const raw = localStorage.getItem(_STORAGE_KEY);
    return raw ? new Map(Object.entries(JSON.parse(raw))) : new Map();
  } catch { return new Map(); }
}

function _persistCache(map) {
  try {
    // Guardar solo las primeras _MAX_STORED entradas
    const obj = {};
    let n = 0;
    for (const [k, v] of map) {
      if (v && n < _MAX_STORED) { obj[k] = v; n++; }
    }
    localStorage.setItem(_STORAGE_KEY, JSON.stringify(obj));
  } catch {}
}

export const globalEmoteCache = _loadStoredCache();

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
    emotes.forEach(e => {
      globalEmoteCache.set(e.name.toLowerCase(), e.url);
    });
    _persistCache(globalEmoteCache);

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

  // 1. Cache en memoria (ya tiene lo persistido desde localStorage al arrancar)
  if (globalEmoteCache.has(key)) return globalEmoteCache.get(key);

  try {
    const items = await _gqlSearch(name, 25, AbortSignal.timeout(5000));
    // Solo aceptar coincidencia EXACTA (case-insensitive) para no mezclar emotes
    const exact = items.find(e => e.name.toLowerCase() === key);
    const url   = exact ? emoteUrl(exact.id) : null;
    globalEmoteCache.set(key, url);
    if (url) {
      popularEmotes.add(name);
      _persistCache(globalEmoteCache);
    }
    return url;
  } catch {
    globalEmoteCache.set(key, null);
    return null;
  }
}

// ─── Registro + prefetch ──────────────────────────────────────────────────────

export function registerEmoteUsage(name, url) {
  const key = sanitizeEmoteName(name).toLowerCase();
  if (url) {
    globalEmoteCache.set(key, url);
    _persistCache(globalEmoteCache);
  }
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
  try { localStorage.removeItem(_STORAGE_KEY); } catch {}
}
