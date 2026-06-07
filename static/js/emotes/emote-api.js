/**
 * emote-api.js  — v3 (Parte 3: Production Ready)
 * Búsqueda 7TV con caché, sanitización y control de calidad.
 */

const API_BASE      = "https://7tv.io/v3/emotes";
const EMOTE_QUALITY = "2x";               // 1x=móvil lento | 2x=✅ PROD | 3x=desktop premium

/** Caché de búsquedas (query → array de emotes) */
const searchCache = new Map();

/** Caché global de URLs resueltas (nombre_lower → url | null) */
export const globalEmoteCache = new Map();

/** Set de nombres usados recientemente para prefetch */
const popularEmotes = new Set();

/** Construye la URL CDN de un emote dado su id */
export function emoteUrl(id) {
  return `https://cdn.7tv.app/emote/${id}/${EMOTE_QUALITY}.webp`;
}

/**
 * Sanitiza el nombre de un emote: sólo alfanumérico + _ (sin XSS posible).
 */
export function sanitizeEmoteName(name) {
  return name.replace(/[^a-zA-Z0-9_\-]/g, "");
}

/**
 * Busca emotes en la API de 7TV con caché.
 * @param {string} query
 * @param {AbortSignal} signal
 * @returns {Promise<Array<{id,name,url,animated}>>}
 */
export async function searchEmotes(query, signal) {
  if (!query || query.length < 2) return [];

  const key = query.toLowerCase().trim();
  if (searchCache.has(key)) return searchCache.get(key);

  try {
    const res = await fetch(
      `${API_BASE}?query=${encodeURIComponent(key)}&limit=50`,
      { signal }
    );
    if (!res.ok) throw new Error(`7TV API ${res.status}`);

    const data = await res.json();
    const raw  = Array.isArray(data) ? data : (data.items || []);

    const emotes = raw.slice(0, 50).map(e => ({
      id:       e.id,
      name:     e.name,
      url:      emoteUrl(e.id),
      animated: e.animated || false,
    }));

    searchCache.set(key, emotes);

    // Registrar en caché global para que el renderer los encuentre sin re-fetch
    emotes.forEach(e => globalEmoteCache.set(e.name.toLowerCase(), e.url));

    return emotes;
  } catch (err) {
    if (err.name === "AbortError") return [];
    console.warn("[7TV] searchEmotes error:", err.message);
    throw err;
  }
}

/**
 * Resuelve la URL de un emote por nombre exacto.
 * Primero revisa globalEmoteCache, luego consulta la API.
 * @returns {Promise<string|null>}
 */
export async function resolveEmoteUrl(rawName) {
  const name = sanitizeEmoteName(rawName);
  const key  = name.toLowerCase();

  if (globalEmoteCache.has(key)) return globalEmoteCache.get(key);

  try {
    const res = await fetch(
      `${API_BASE}?query=${encodeURIComponent(name)}&limit=5`,
      { signal: AbortSignal.timeout(5000) }
    );
    if (!res.ok) { globalEmoteCache.set(key, null); return null; }

    const data = await res.json();
    const raw  = Array.isArray(data) ? data : (data.items || []);

    // Coincidencia exacta primero
    const exact = raw.find(e => e.name.toLowerCase() === key);
    const hit   = exact || raw[0];

    const url = hit ? emoteUrl(hit.id) : null;
    globalEmoteCache.set(key, url);

    if (url) popularEmotes.add(name);
    return url;
  } catch {
    globalEmoteCache.set(key, null);
    return null;
  }
}

/**
 * Registra que un emote fue usado (para prefetch futuro).
 */
export function registerEmoteUsage(name, url) {
  const key = sanitizeEmoteName(name).toLowerCase();
  if (url) globalEmoteCache.set(key, url);
  popularEmotes.add(name);
}

/**
 * Prefetch de los emotes más populares (warm-up de caché).
 * Llamar al cargar la página o cuando el usuario abre el picker.
 */
export async function prefetchPopularEmotes() {
  const list = Array.from(popularEmotes).slice(0, 30);
  for (const name of list) {
    const key = name.toLowerCase();
    if (globalEmoteCache.has(key)) continue;
    // Fire-and-forget, no bloquear
    resolveEmoteUrl(name).catch(() => {});
    // Pequeño yield para no saturar el browser
    await new Promise(r => setTimeout(r, 80));
  }
}

/** Limpia ambas cachés (útil en tests o refresh manual). */
export function clearAllCaches() {
  searchCache.clear();
  globalEmoteCache.clear();
  popularEmotes.clear();
}
