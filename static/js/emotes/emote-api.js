/**
 * emote-api.js — v4 (7TV GraphQL + Fallback inteligente + Cache pro)
 *
 * CAMBIOS v4:
 *  • Usa 7TV GraphQL (https://7tv.io/v3/gql) — API estable, sin CORS
 *  • Cache de 10 min con TTL real
 *  • Fallback silencioso: nunca lanza errores al caller
 *  • AbortSignal.timeout() para timeouts automáticos
 *  • resolveEmoteUrl también usa GQL
 *  • searchEmotesGQL exportada para uso interno
 */

const GQL_URL       = "https://7tv.io/v3/gql";
const CDN_BASE      = "https://cdn.7tv.app/emote";
const EMOTE_QUALITY = "2x";
const CACHE_TTL_MS  = 10 * 60 * 1000; // 10 minutos

// ─── Cache con TTL ────────────────────────────────────────────────────────────

const _searchCache = new Map(); // query → { data, time }

function _cacheGet(key) {
  const entry = _searchCache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.time > CACHE_TTL_MS) {
    _searchCache.delete(key);
    return null;
  }
  return entry.data;
}

function _cacheSet(key, data) {
  _searchCache.set(key, { data, time: Date.now() });
}

// ─── Cache global de URLs por nombre (compartido con picker y renderer) ───────

export const globalEmoteCache = new Map(); // name_lower → url | null

// ─── Set de nombres populares (para prefetch) ─────────────────────────────────

const popularEmotes = new Set();

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function emoteUrl(id) {
  return `${CDN_BASE}/${id}/${EMOTE_QUALITY}.webp`;
}

export function sanitizeEmoteName(name) {
  return String(name).replace(/[^a-zA-Z0-9_\-]/g, "").slice(0, 40);
}

// ─── GQL query ───────────────────────────────────────────────────────────────

async function _gqlSearch(query, limit = 20, signal) {
  const body = JSON.stringify({
    query: `
      query SearchEmotes($query: String!, $limit: Int!) {
        emotes(query: $query, limit: $limit) {
          items {
            id
            name
            animated
          }
        }
      }
    `,
    variables: { query, limit },
  });

  const res = await fetch(GQL_URL, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: signal ?? AbortSignal.timeout(6000),
  });

  if (!res.ok) throw new Error(`GQL HTTP ${res.status}`);

  const json = await res.json();
  return json?.data?.emotes?.items ?? [];
}

// ─── searchEmotes — principal export ─────────────────────────────────────────

/**
 * Busca emotes en 7TV.
 * NUNCA lanza error: si falla la API devuelve [] silenciosamente.
 *
 * @param {string} query
 * @param {AbortSignal} [signal]
 * @returns {Promise<Array<{id, name, url, animated}>>}
 */
export async function searchEmotes(query, signal) {
  if (!query || query.trim().length < 2) return [];

  const key = query.toLowerCase().trim();

  // 1. Cache hit
  const cached = _cacheGet(key);
  if (cached) return cached;

  try {
    const items = await _gqlSearch(key, 30, signal);

    const emotes = items.map(e => ({
      id:       e.id,
      name:     e.name,
      url:      emoteUrl(e.id),
      animated: e.animated ?? false,
    }));

    // Guardar en cache
    _cacheSet(key, emotes);

    // Warm-up globalEmoteCache
    emotes.forEach(e => globalEmoteCache.set(e.name.toLowerCase(), e.url));

    return emotes;

  } catch (err) {
    if (err?.name === "AbortError") return [];

    // API caída: devolver cache expirado si existe, o []
    console.warn("[7TV] searchEmotes falló, modo fallback silencioso:", err.message);
    const stale = _searchCache.get(key);
    return stale ? stale.data : [];
  }
}

// ─── resolveEmoteUrl — para el renderer ──────────────────────────────────────

/**
 * Resuelve la URL de un emote por nombre exacto.
 * Usa globalEmoteCache primero, luego GQL.
 * Nunca lanza error.
 *
 * @param {string} rawName
 * @returns {Promise<string|null>}
 */
export async function resolveEmoteUrl(rawName) {
  const name = sanitizeEmoteName(rawName);
  const key  = name.toLowerCase();

  // Cache hit
  if (globalEmoteCache.has(key)) return globalEmoteCache.get(key);

  try {
    const items = await _gqlSearch(name, 5, AbortSignal.timeout(5000));

    // Coincidencia exacta primero
    const exact = items.find(e => e.name.toLowerCase() === key);
    const hit   = exact || items[0];

    const url = hit ? emoteUrl(hit.id) : null;
    globalEmoteCache.set(key, url);

    if (url) popularEmotes.add(name);
    return url;
  } catch {
    globalEmoteCache.set(key, null);
    return null;
  }
}

// ─── Registro de uso ─────────────────────────────────────────────────────────

export function registerEmoteUsage(name, url) {
  const key = sanitizeEmoteName(name).toLowerCase();
  if (url) globalEmoteCache.set(key, url);
  popularEmotes.add(name);
}

// ─── Prefetch de populares ────────────────────────────────────────────────────

export async function prefetchPopularEmotes() {
  const list = Array.from(popularEmotes).slice(0, 20);
  for (const name of list) {
    const key = name.toLowerCase();
    if (globalEmoteCache.has(key)) continue;
    resolveEmoteUrl(name).catch(() => {});
    await new Promise(r => setTimeout(r, 100));
  }
}

// ─── Limpieza ─────────────────────────────────────────────────────────────────

export function clearAllCaches() {
  _searchCache.clear();
  globalEmoteCache.clear();
  popularEmotes.clear();
}
