"""
services/mundial_service.py
============================

Servicio de datos del Mundial 2026.

Flujo:
    API-Football (api-sports.io)
        ↓
    _fetch_external()
        ↓
    caché en memoria
        ↓
    endpoints públicos

API:
    - Proveedor: API-Football v3 (api-sports.io)
    - Variable de entorno: APISPORTS_KEY
    - Liga Mundial FIFA: id=1
    - Temporada: 2026
    - Timezone solicitada: America/Bogota

Esquema canónico de salida
(el resto de la aplicación no necesita cambios):

{
    "id":             int,
    "fase":           str,
    "grupo":          str | None,
    "local":          str,
    "visitante":      str,
    "codigo_local":   str,
    "codigo_visit":   str,
    "goles_local":    int | None,
    "goles_visit":    int | None,
    "bloqueado":      bool,
    "fecha_texto":    str,
    "fecha_iso":      str | None,
    "sede":           str,
    "estado":         str,
    "minuto":         str | None
}
"""
import logging
import os
import threading
import time
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# ─── Logger ──────────────────────────────────────────────────────────────────
logger = logging.getLogger("mundial_service")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s  mundial_service  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ─── Configuración ────────────────────────────────────────────────────────────
APISPORTS_KEY = os.getenv("APISPORTS_KEY", "").strip()

APISPORTS_BASE: str = "https://v3.football.api-sports.io"

# FIFA World Cup 2026
LEAGUE_ID: int = 1
SEASON: int = 2026
TIMEZONE_COL: str = "America/Bogota"

CACHE_TTL_SECONDS: int = int(os.getenv("MUNDIAL_CACHE_TTL", "120"))
REQUEST_TIMEOUT: int = int(os.getenv("MUNDIAL_TIMEOUT", "8"))
MAX_RETRIES: int = int(os.getenv("MUNDIAL_RETRIES", "3"))
RETRY_BACKOFF: float = float(os.getenv("MUNDIAL_BACKOFF", "1.5"))

# TTL dinámico
_TTL_LIVE   = int(os.getenv("MUNDIAL_TTL_LIVE",   "20"))
_TTL_HOY    = int(os.getenv("MUNDIAL_TTL_HOY",    "60"))
_TTL_NORMAL = CACHE_TTL_SECONDS

# ─── Caché en memoria ────────────────────────────────────────────────────────

class _Cache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_cache = _Cache()
_fetch_lock = threading.Lock()

# ─── Mapas de normalización ──────────────────────────────────────────────────

# API-Football status.short → estado canónico
_STATUS_MAP: dict[str, str] = {
    # Programados
    "NS":   "programado",
    "TBD":  "programado",
    "PST":  "programado",
    "CANC": "programado",
    "ABD":  "programado",
    "SUSP": "programado",

    # En vivo
    "1H":    "en_curso",
    "H1":    "en_curso",
    "HT":    "en_curso",
    "2H":    "en_curso",
    "H2":    "en_curso",
    "ET":    "en_curso",
    "BT":    "en_curso",
    "BREAK": "en_curso",
    "P":     "en_curso",
    "LIVE":  "en_curso",
    "INT":   "en_curso",

    # Finalizados
    "FT":  "finalizado",
    "AET": "finalizado",
    "PEN": "finalizado",
    "AWD": "finalizado",
    "WO":  "finalizado",
}

# API-Football status.short → etiqueta del minuto para badge EN VIVO
_MINUTO_LABEL: dict[str, Optional[str]] = {
    "1H":    None,
    "H1":    None,
    "HT":    "Desc.",
    "2H":    None,
    "H2":    None,
    "ET":    "Prórroga",
    "BT":    "Desc.",
    "BREAK": "Desc.",
    "P":     "Penales",
}

# league.round → fase canónica
_PHASE_MAP: dict[str, str] = {
    "group stage":     "Grupos",
    "round of 32":     "Dieciseisavos",
    "round of 16":     "Octavos",
    "quarter-finals":  "Cuartos",
    "quarter-final":   "Cuartos",
    "semi-finals":     "Semifinal",
    "semi-final":      "Semifinal",
    "3rd place final": "Tercer puesto",
    "third place":     "Tercer puesto",
    "final":           "Final",
}

# Nombre de equipo → código ISO-2
_COUNTRY_CODE: dict[str, str] = {
    # América
    "united states": "us",
    "usa": "us",
    "estados unidos": "us",
    "canada": "ca",
    "mexico": "mx",
    "méxico": "mx",
    "brazil": "br",
    "brasil": "br",
    "argentina": "ar",
    "colombia": "co",
    "uruguay": "uy",
    "chile": "cl",
    "ecuador": "ec",
    "peru": "pe",
    "perú": "pe",
    "venezuela": "ve",
    "paraguay": "py",
    "bolivia": "bo",
    "costa rica": "cr",
    "honduras": "hn",
    "panama": "pa",
    "panamá": "pa",
    "jamaica": "jm",
    "haiti": "ht",
    "haití": "ht",

    # Europa
    "germany": "de",
    "alemania": "de",
    "france": "fr",
    "francia": "fr",
    "spain": "es",
    "españa": "es",
    "england": "gb-eng",
    "portugal": "pt",
    "netherlands": "nl",
    "holanda": "nl",
    "italy": "it",
    "italia": "it",
    "belgium": "be",
    "bélgica": "be",
    "croatia": "hr",
    "croacia": "hr",
    "serbia": "rs",
    "denmark": "dk",
    "dinamarca": "dk",
    "switzerland": "ch",
    "suiza": "ch",
    "poland": "pl",
    "polonia": "pl",
    "ukraine": "ua",
    "ucrania": "ua",
    "austria": "at",
    "sweden": "se",
    "suecia": "se",
    "turkey": "tr",
    "turquía": "tr",
    "scotland": "gb-sct",
    "wales": "gb-wls",
    "czechia": "cz",
    "czech republic": "cz",
    "slovakia": "sk",
    "hungary": "hu",
    "romania": "ro",
    "albania": "al",
    "greece": "gr",
    "norway": "no",
    "noruega": "no",
    "bosnia and herzegovina": "ba",
    "bosnia": "ba",
    "cape verde": "cv",
    "cabo verde": "cv",
    "curacao": "cw",
    "curaçao": "cw",
    "curazao": "cw",

    # África
    "morocco": "ma",
    "marruecos": "ma",
    "senegal": "sn",
    "nigeria": "ng",
    "cameroon": "cm",
    "egypt": "eg",
    "ghana": "gh",
    "ivory coast": "ci",
    "cote d'ivoire": "ci",
    "south africa": "za",
    "tunisia": "tn",
    "algeria": "dz",
    "dr congo": "cd",
    "democratic republic of the congo": "cd",
    "congo dr": "cd",
    "rd congo": "cd",

    # Asia/Oceanía
    "japan": "jp",
    "japón": "jp",
    "south korea": "kr",
    "korea republic": "kr",
    "iran": "ir",
    "iraq": "iq",
    "saudi arabia": "sa",
    "australia": "au",
    "new zealand": "nz",
    "uzbekistan": "uz",
    "uzbekistán": "uz",
    "qatar": "qa",
    "jordan": "jo",
}

# ─── Helpers internos ────────────────────────────────────────────────────────

def _fixture_cache_key(fixture_id: int, suffix: str) -> str:
    return f"fixture:{fixture_id}:{suffix}"


def _api_get(endpoint: str, params: dict) -> list:
    """Llama a API-Football con reintentos y devuelve response[].
    Lanza RuntimeError si la clave no está configurada o la llamada falla."""
    if not APISPORTS_KEY:
        raise RuntimeError("APISPORTS_KEY no configurada")

    qs = urlencode(params)
    url = f"{APISPORTS_BASE}/{endpoint}?{qs}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"x-apisports-key": APISPORTS_KEY})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read()
            data = json.loads(raw)
            if data.get("errors"):
                raise RuntimeError(f"API error: {data['errors']}")
            return data.get("response", [])
        except (URLError, OSError) as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF ** attempt
            logger.warning(f"_api_get intento {attempt} falló ({exc}); reintentando en {wait:.1f}s")
            time.sleep(wait)
    return []


def _normalizar_fixture(f: dict) -> dict:
    """Convierte un fixture de API-Football al esquema canónico."""
    fixture   = f.get("fixture", {})
    league    = f.get("league", {})
    teams     = f.get("teams", {})
    goals     = f.get("goals", {})
    status    = fixture.get("status", {})

    status_short = status.get("short", "NS")
    estado       = _STATUS_MAP.get(status_short, "programado")

    # Minuto
    elapsed = status.get("elapsed")
    minuto: Optional[str] = None
    if estado == "en_curso":
        label = _MINUTO_LABEL.get(status_short)
        if label:
            minuto = label
        elif elapsed is not None:
            minuto = str(elapsed)

    # Fase y grupo
    round_str = (league.get("round") or "").lower()
    fase = _PHASE_MAP.get(round_str, league.get("round", ""))
    grupo: Optional[str] = None
    if "group" in round_str:
        m = re.search(r"group\s+(\w+)", round_str)
        if m:
            grupo = f"Grupo {m.group(1).upper()}"

    # Equipos
    home_name = teams.get("home", {}).get("name", "")
    away_name = teams.get("away", {}).get("name", "")

    codigo_local = _COUNTRY_CODE.get(home_name.lower(), "")
    codigo_visit = _COUNTRY_CODE.get(away_name.lower(), "")

    # Fecha
    fecha_iso  = fixture.get("date")           # ya en hora Colombia si se pidió con timezone
    fecha_texto = ""
    if fecha_iso:
        try:
            dt = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
            fecha_texto = dt.strftime("%-d %b %H:%M")
        except Exception:
            fecha_texto = fecha_iso[:16]

    # Sede
    venue = fixture.get("venue", {})
    sede  = venue.get("name") or venue.get("city") or ""

    return {
        "id":           fixture.get("id"),
        "fase":         fase,
        "grupo":        grupo,
        "local":        home_name,
        "visitante":    away_name,
        "codigo_local": codigo_local,
        "codigo_visit": codigo_visit,
        "goles_local":  goals.get("home"),
        "goles_visit":  goals.get("away"),
        "bloqueado":    False,
        "fecha_texto":  fecha_texto,
        "fecha_iso":    fecha_iso,
        "sede":         sede,
        "estado":       estado,
        "minuto":       minuto,
    }

# ─── API pública ─────────────────────────────────────────────────────────────

def get_live_ttl() -> int:
    """TTL recomendado según si hay partidos en vivo en caché."""
    cached = _cache.get("worldcup_en_vivo")
    if cached and cached[0]:         # (lista, fuente) — lista no vacía
        return _TTL_LIVE
    cached_hoy = _cache.get("worldcup_partidos_hoy")
    if cached_hoy and cached_hoy[0]:
        return _TTL_HOY
    return _TTL_NORMAL


def invalidate_cache() -> None:
    """Elimina todas las entradas del caché del mundial."""
    _cache.clear()
    logger.info("Caché del mundial invalidado")


def get_partidos_hoy() -> tuple[list, str]:
    """Partidos del día en zona América/Bogotá (UTC-5)."""
    cache_key = "worldcup_partidos_hoy"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    with _fetch_lock:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        col_now = datetime.now(timezone(timedelta(hours=-5)))
        date_str = col_now.strftime("%Y-%m-%d")

        try:
            raw = _api_get("fixtures", {
                "league":   LEAGUE_ID,
                "season":   SEASON,
                "date":     date_str,
                "timezone": TIMEZONE_COL,
            })
            partidos = [_normalizar_fixture(f) for f in raw]
            fuente   = "api"

            # TTL dinámico: más corto si hay partidos en vivo
            hay_vivo = any(p["estado"] == "en_curso" for p in partidos)
            ttl = _TTL_LIVE if hay_vivo else (_TTL_HOY if partidos else _TTL_NORMAL)
        except Exception as exc:
            logger.warning(f"get_partidos_hoy falló: {exc}")
            partidos = []
            fuente   = "fallback"
            ttl      = _TTL_NORMAL

        result = (partidos, fuente)
        _cache.set(cache_key, result, ttl=ttl)
        return result


def get_en_vivo() -> tuple[list, str]:
    """Solo los partidos con estado 'en_curso' en este momento."""
    cache_key = "worldcup_en_vivo"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    with _fetch_lock:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            raw = _api_get("fixtures", {
                "live":   str(LEAGUE_ID),
                "league": LEAGUE_ID,
            })
            partidos = [_normalizar_fixture(f) for f in raw]
            fuente   = "api"
            ttl      = _TTL_LIVE if partidos else _TTL_HOY
        except Exception as exc:
            logger.warning(f"get_en_vivo falló: {exc}")
            partidos = []
            fuente   = "fallback"
            ttl      = _TTL_HOY

        result = (partidos, fuente)
        _cache.set(cache_key, result, ttl=ttl)
        return result


def get_proximos(limit: int = 10) -> tuple[list, str]:
    """Próximos N partidos sin disputar ordenados por fecha."""
    cache_key = "worldcup_proximos"
    cached = _cache.get(cache_key)
    if cached is None:
        with _fetch_lock:
            cached = _cache.get(cache_key)
            if cached is None:
                try:
                    raw = _api_get("fixtures", {
                        "league":   LEAGUE_ID,
                        "season":   SEASON,
                        "next":     50,
                        "timezone": TIMEZONE_COL,
                    })
                    partidos = [_normalizar_fixture(f) for f in raw]
                    fuente   = "api"
                except Exception as exc:
                    logger.warning(f"get_proximos falló: {exc}")
                    partidos = []
                    fuente   = "fallback"
                cached = (partidos, fuente)
                _cache.set(cache_key, cached, ttl=_TTL_NORMAL)

    partidos, fuente = cached
    return partidos[:limit], fuente


def get_partido(partido_id: int) -> tuple[Optional[dict], str]:
    """Detalle de un partido por ID. Devuelve (None, fuente) si no existe."""
    cache_key = _fixture_cache_key(partido_id, "detail")
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        raw = _api_get("fixtures", {
            "id":       partido_id,
            "timezone": TIMEZONE_COL,
        })
        if not raw:
            return None, "api"
        partido = _normalizar_fixture(raw[0])
        fuente  = "api"
    except Exception as exc:
        logger.warning(f"get_partido({partido_id}) falló: {exc}")
        return None, "fallback"

    result = (partido, fuente)
    _cache.set(cache_key, result, ttl=_TTL_HOY)
    return result

# ─── Funciones de detalle de fixture ─────────────────────────────────────────

def get_fixture_events(fixture_id: int) -> list:
    cache_key = _fixture_cache_key(fixture_id, "events")
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _api_get("fixtures/events", {"fixture": fixture_id})
    except Exception as exc:
        logger.warning(f"Error obteniendo eventos fixture {fixture_id}: {exc}")
        return []

    events = []
    for ev in response:
        time_obj = ev.get("time", {})
        elapsed  = time_obj.get("elapsed")
        extra    = time_obj.get("extra")
        minute   = str(elapsed or "")
        if extra:
            minute += f"+{extra}"
        minute += "'"
        events.append({
            "minute": minute,
            "type":   ev.get("type"),
            "detail": ev.get("detail"),
            "player": (ev.get("player") or {}).get("name"),
            "assist": (ev.get("assist") or {}).get("name"),
            "team":   (ev.get("team")   or {}).get("name"),
        })

    _cache.set(cache_key, events, ttl=15)
    return events


def get_fixture_statistics(fixture_id: int) -> list:
    cache_key = _fixture_cache_key(fixture_id, "stats")
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _api_get("fixtures/statistics", {"fixture": fixture_id})
    except Exception as exc:
        logger.warning(f"Error obteniendo estadísticas fixture {fixture_id}: {exc}")
        return []

    stats = []
    for team_data in response:
        team = team_data.get("team", {})
        item = {
            "team":       team.get("name"),
            "logo":       team.get("logo"),
            "statistics": {},
        }
        for stat in team_data.get("statistics", []):
            item["statistics"][stat["type"]] = stat["value"]
        stats.append(item)

    _cache.set(cache_key, stats, ttl=15)
    return stats


def get_fixture_lineups(fixture_id: int) -> list:
    cache_key = _fixture_cache_key(fixture_id, "lineups")
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _api_get("fixtures/lineups", {"fixture": fixture_id})
    except Exception as exc:
        logger.warning(f"Error obteniendo alineaciones fixture {fixture_id}: {exc}")
        return []

    lineups = []
    for lineup in response:
        coach = lineup.get("coach") or {}
        lineups.append({
            "team":        lineup.get("team", {}),
            "formation":   lineup.get("formation"),
            "coach":       coach.get("name"),
            "startXI":     lineup.get("startXI", []),
            "substitutes": lineup.get("substitutes", []),
        })

    _cache.set(cache_key, lineups, ttl=300)
    return lineups


def get_standings() -> list:
    cache_key = "worldcup_standings"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = _api_get("standings", {"league": LEAGUE_ID, "season": SEASON})
    except Exception as exc:
        logger.warning(f"Error obteniendo standings: {exc}")
        return []

    groups = []
    for group in response:
        league = group.get("league", {})
        for standings_group in league.get("standings", []):
            if not standings_group:
                continue
            group_name = standings_group[0].get("group", "Grupo")
            groups.append({
                "group": group_name,
                "table": standings_group,
            })

    _cache.set(cache_key, groups, ttl=300)
    return groups
