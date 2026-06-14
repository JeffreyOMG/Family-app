"""
services/mundial_service.py
============================
Servicio de datos del Mundial 2026.

Flujo:
  api-sports.io/v3/fixtures  →  _fetch_external()  →  _cache  →  endpoints públicos

API: API-Football v3 (api-sports.io)
  - Header: x-apisports-key: TU_API_KEY   (env: 6f0792f3b2f42258107b8d4e2f6fb5a4)
  - Liga Mundial FIFA: id=1, season=2026
  - Timezone: America/Bogota (fecha ya viene en UTC-5)

Esquema canónico de salida (IGUAL que antes — el resto de la app no cambia):
  {
    "id":             int,
    "fase":           str,        "Grupos" | "Dieciseisavos" | "Octavos" | ...
    "grupo":          str | None,
    "local":          str,
    "visitante":      str,
    "codigo_local":   str,        código bandera ISO-2
    "codigo_visit":   str,
    "goles_local":    int | None,
    "goles_visit":    int | None,
    "bloqueado":      bool,
    "fecha_texto":    str,        "Vie. 12 jun, 14:00"
    "fecha_iso":      str | None, "2026-06-12T19:00:00Z"  (UTC)
    "sede":           str,
    "estado":         str,        "programado" | "en_curso" | "finalizado"
    "minuto":         str | None, "34'" | "HT" | "Desc." | None
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
# Poner en Render/Heroku:  APISPORTS_KEY=tu_api_key_aqui

APISPORTS_KEY = os.getenv("APISPORTS_KEY", "")
APISPORTS_BASE:    str   = "https://v3.football.api-sports.io"
LEAGUE_ID:         int   = 1        # FIFA World Cup
SEASON:            int   = 2026
TIMEZONE_COL:      str   = "America/Bogota"

CACHE_TTL_SECONDS: int   = int(os.getenv("MUNDIAL_CACHE_TTL",  "120"))
REQUEST_TIMEOUT:   int   = int(os.getenv("MUNDIAL_TIMEOUT",    "8"))
MAX_RETRIES:       int   = int(os.getenv("MUNDIAL_RETRIES",    "3"))
RETRY_BACKOFF:     float = float(os.getenv("MUNDIAL_BACKOFF",  "1.5"))

_TTL_LIVE   = int(os.getenv("MUNDIAL_TTL_LIVE", "20"))
_TTL_HOY    = int(os.getenv("MUNDIAL_TTL_HOY",  "60"))
_TTL_NORMAL = CACHE_TTL_SECONDS


# ─── Caché en memoria (thread-safe) ──────────────────────────────────────────
class _Cache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock  = threading.Lock()

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


_cache      = _Cache()
_fetch_lock = threading.Lock()


# ─── Mapas de normalización ───────────────────────────────────────────────────

# API-Football status.short → estado canónico
_STATUS_MAP: dict[str, str] = {
    "NS":   "programado",   # Not Started
    "TBD":  "programado",   # Time To Be Defined
    "1H":   "en_curso",     # First Half
    "HT":   "en_curso",     # Half Time
    "2H":   "en_curso",     # Second Half
    "ET":   "en_curso",     # Extra Time
    "BT":   "en_curso",     # Break Time (before ET second half)
    "P":    "en_curso",     # Penalty In Progress
    "INT":  "en_curso",     # Interrupted
    "LIVE": "en_curso",     # Live (generic)
    "SUSP": "programado",   # Suspended
    "PST":  "programado",   # Postponed
    "CANC": "programado",   # Cancelled
    "ABD":  "programado",   # Abandoned
    "FT":   "finalizado",   # Full Time
    "AET":  "finalizado",   # After Extra Time
    "PEN":  "finalizado",   # After Penalties
    "AWD":  "finalizado",   # Technical Loss
    "WO":   "finalizado",   # Walk Over
}

# API-Football status.short → etiqueta del minuto para badge EN VIVO
_MINUTO_LABEL: dict[str, str] = {
    "1H":  None,        # → usar elapsed real
    "HT":  "Desc.",     # Half time
    "2H":  None,        # → usar elapsed real
    "ET":  "Prórroga",
    "BT":  "Desc.",     # Break before ET
    "P":   "Penales",
}

# league.round → fase canónica
_PHASE_MAP: dict[str, str] = {
    "group stage":          "Grupos",
    "round of 32":          "Dieciseisavos",
    "round of 16":          "Octavos",
    "quarter-finals":       "Cuartos",
    "quarter-final":        "Cuartos",
    "semi-finals":          "Semifinal",
    "semi-final":           "Semifinal",
    "3rd place final":      "Tercer puesto",
    "third place":          "Tercer puesto",
    "final":                "Final",
}

# Nombre de equipo (en inglés) → código ISO-2 para banderas locales
_COUNTRY_CODE: dict[str, str] = {
    # América
    "united states":   "us", "usa":            "us", "estados unidos": "us",
    "canada":          "ca", "mexico":         "mx", "méxico":          "mx",
    "brazil":          "br", "brasil":         "br", "argentina":       "ar",
    "colombia":        "co", "uruguay":        "uy", "chile":           "cl",
    "ecuador":         "ec", "peru":           "pe", "perú":            "pe",
    "venezuela":       "ve", "paraguay":       "py", "bolivia":         "bo",
    "costa rica":      "cr", "honduras":       "hn", "panama":          "pa",
    "panamá":          "pa", "jamaica":        "jm", "haiti":           "ht",
    "haití":           "ht",
    # Europa
    "germany":         "de", "alemania":       "de", "france":          "fr",
    "francia":         "fr", "spain":          "es", "españa":          "es",
    "england":         "gb-eng", "portugal":   "pt", "netherlands":     "nl",
    "holanda":         "nl",  "italy":         "it", "italia":          "it",
    "belgium":         "be",  "bélgica":       "be", "croatia":         "hr",
    "croacia":         "hr",  "serbia":        "rs", "denmark":         "dk",
    "dinamarca":       "dk",  "switzerland":   "ch", "suiza":           "ch",
    "poland":          "pl",  "polonia":       "pl", "ukraine":         "ua",
    "ucrania":         "ua",  "austria":       "at", "sweden":          "se",
    "suecia":          "se",  "turkey":        "tr", "turquía":         "tr",
    "scotland":        "gb-sct", "wales":      "gb-wls", "czechia":     "cz",
    "czech republic":  "cz",  "slovakia":     "sk", "hungary":          "hu",
    "romania":         "ro",  "albania":       "al", "greece":          "gr",
    "norway":          "no",  "noruega":       "no",
    "bosnia and herzegovina": "ba", "bosnia":  "ba",
    "cape verde":      "cv",  "cabo verde":    "cv",
    "curacao":         "cw",  "curaçao":       "cw", "curazao":         "cw",
    # África
    "morocco":         "ma",  "marruecos":     "ma", "senegal":         "sn",
    "nigeria":         "ng",  "cameroon":      "cm", "egypt":           "eg",
    "ghana":           "gh",  "ivory coast":   "ci", "cote d'ivoire":   "ci",
    "south africa":    "za",  "tunisia":       "tn", "algeria":         "dz",
    "dr congo":        "cd",  "democratic republic of the congo": "cd",
    "congo dr":        "cd",  "rd congo":      "cd",
    # Asia
    "japan":           "jp",  "japón":         "jp", "south korea":     "kr",
    "korea republic":  "kr",  "iran":          "ir", "iraq":            "iq",
    "saudi arabia":    "sa",  "australia":     "au", "new zealand":     "nz",
    "uzbekistan":      "uz",  "uzbekistán":    "uz", "qatar":           "qa",
    "jordan":          "jo",
}


def _country_code(name: str) -> str:
    return _COUNTRY_CODE.get(name.strip().lower(), "xx")


def _normalize_phase(round_str: str) -> str:
    key = round_str.strip().lower()
    # Match exacto
    if key in _PHASE_MAP:
        return _PHASE_MAP[key]
    # Contiene "group"
    if "group" in key:
        return "Grupos"
    if "32" in key or "round of 32" in key:
        return "Dieciseisavos"
    if "16" in key or "round of 16" in key:
        return "Octavos"
    if "quarter" in key:
        return "Cuartos"
    if "semi" in key:
        return "Semifinal"
    if "3rd" in key or "third" in key:
        return "Tercer puesto"
    if "final" in key:
        return "Final"
    return round_str.strip()


def _to_fecha_texto(iso: Optional[str]) -> str:
    """Convierte ISO UTC a texto español en hora Bogotá: 'Vie. 12 jun, 14:00'."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=-5)))  # Bogotá UTC-5
        days_es   = ["Lun.", "Mar.", "Mié.", "Jue.", "Vie.", "Sáb.", "Dom."]
        months_es = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
        return f"{days_es[dt.weekday()]} {dt.day} {months_es[dt.month-1]}, {dt.strftime('%H:%M')}"
    except Exception:
        return iso or ""


# ─── Normalización de la respuesta de API-Football ───────────────────────────

def _normalize_fixture(raw: dict, idx: int = 0) -> dict:
    """
    Transforma un objeto de api-sports.io al esquema canónico.

    Estructura de entrada:
      raw["fixture"]  → id, date, status, venue
      raw["league"]   → id, round
      raw["teams"]    → home.name, away.name, home.logo, away.logo
      raw["goals"]    → home, away
    """
    fixture = raw.get("fixture") or {}
    league  = raw.get("league")  or {}
    teams   = raw.get("teams")   or {}
    goals   = raw.get("goals")   or {}

    home_team = teams.get("home") or {}
    away_team = teams.get("away") or {}

    # ── ID ────────────────────────────────────────────────────────────────────
    fixture_id = fixture.get("id") or (1000 + idx)

    # ── Equipos ───────────────────────────────────────────────────────────────
    local     = str(home_team.get("name") or "TBD").strip()
    visitante = str(away_team.get("name") or "TBD").strip()

    # Preferir logo de la API (URL directa) para bandera;
    # si no, usar código ISO local
    # Nota: el frontend usa /static/banderas/XX.png → usar codigo_local/visit
    cod_l = _country_code(local)
    cod_v = _country_code(visitante)

    # ── Marcador ──────────────────────────────────────────────────────────────
    gl = goals.get("home")
    gv = goals.get("away")
    try:
        gl = int(gl) if gl is not None else None
    except (TypeError, ValueError):
        gl = None
    try:
        gv = int(gv) if gv is not None else None
    except (TypeError, ValueError):
        gv = None

    # ── Estado ────────────────────────────────────────────────────────────────
    status     = fixture.get("status") or {}
    status_short = str(status.get("short") or "NS").upper().strip()
    elapsed      = status.get("elapsed")  # int o None (minuto real del árbitro)

    estado    = _STATUS_MAP.get(status_short, "programado")
    bloqueado = estado == "finalizado"

    # ── Minuto para badge EN VIVO ─────────────────────────────────────────────
    minuto: Optional[str] = None
    if estado == "en_curso":
        if status_short in _MINUTO_LABEL:
            minuto = _MINUTO_LABEL[status_short]   # "Desc.", "Prórroga", "Penales", o None
        # Si es None (1H o 2H) → usar elapsed real del árbitro
        if minuto is None and elapsed is not None:
            try:
                minuto = f"{int(elapsed)}'"
            except (TypeError, ValueError):
                pass
        # Último recurso si elapsed también es None
        if minuto is None:
            minuto = "En vivo"

    # ── Fase / grupo ──────────────────────────────────────────────────────────
    round_str = str(league.get("round") or "")
    fase      = _normalize_phase(round_str)

    grupo: Optional[str] = None
    if fase == "Grupos":
        # "Group Stage - 1" → buscar letra del grupo si existe
        # api-sports no incluye letra de grupo en /fixtures, solo en /standings
        m = re.search(r"Group\s+([A-L])", round_str, re.IGNORECASE)
        grupo = m.group(1).upper() if m else None

    # ── Fecha → UTC para fecha_iso ────────────────────────────────────────────
    # api-sports devuelve date ya en timezone solicitada (America/Bogota = UTC-5)
    # cuando se usa &timezone=America/Bogota.
    # Ejemplo: "2026-06-20T15:00:00-05:00"
    # Convertimos a UTC para fecha_iso (coherente con el resto del sistema).
    date_raw  = str(fixture.get("date") or "")
    fecha_iso: Optional[str] = None
    if date_raw:
        try:
            dt = datetime.fromisoformat(date_raw)
            if dt.tzinfo is None:
                # Sin zona → asumir Bogotá (UTC-5) porque usamos timezone param
                dt = dt.replace(tzinfo=timezone(timedelta(hours=-5)))
            utc_dt    = dt.astimezone(timezone.utc)
            fecha_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            fecha_iso = None

    fecha_texto = _to_fecha_texto(fecha_iso)

    # ── Sede ──────────────────────────────────────────────────────────────────
    venue = fixture.get("venue") or {}
    if isinstance(venue, dict):
        sede = str(venue.get("name") or venue.get("city") or "").strip()
    else:
        sede = str(venue).strip()

    return {
        "id":           int(fixture_id),
        "fase":         fase,
        "grupo":        grupo,
        "local":        local,
        "visitante":    visitante,
        "codigo_local": cod_l,
        "codigo_visit": cod_v,
        "goles_local":  gl,
        "goles_visit":  gv,
        "bloqueado":    bloqueado,
        "fecha_texto":  fecha_texto,
        "fecha_iso":    fecha_iso,
        "sede":         sede,
        "estado":       estado,
        "minuto":       minuto,
        # Extras de api-sports (útiles para el admin y el fixture)
        "status_short": status_short,   # "1H", "HT", "FT", "NS"…
        "logo_local":   home_team.get("logo") or "",
        "logo_visit":   away_team.get("logo") or "",
    }


# ─── Fetch a API-Football ─────────────────────────────────────────────────────

def _api_get(endpoint: str, params: dict) -> list[dict]:
    """
    Llama a api-sports.io y devuelve response[].
    Lanza RuntimeError si falla o no hay API key.
    """
    if not APISPORTS_KEY:
        raise RuntimeError(
            "APISPORTS_KEY no configurada. "
            "Añade la variable de entorno en Render/Heroku."
        )

    qs    = "&".join(f"{k}={v}" for k, v in params.items())
    url   = f"{APISPORTS_BASE}/{endpoint}?{qs}"
    last_exc: Exception = RuntimeError("never tried")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"API-Football intento {attempt}/{MAX_RETRIES} → {url}")
            req = Request(
                url,
                headers={
                    "x-apisports-key": APISPORTS_KEY,
                    # IMPORTANTE: NO agregar headers extra — rompe la API
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = json.loads(resp.read().decode("utf-8", errors="replace"))

            # Validar estructura
            if isinstance(raw, dict):
                errors = raw.get("errors") or {}
                if errors:
                    raise RuntimeError(f"API error: {errors}")
                results = raw.get("results", 0)
                if results == 0:
                    logger.info("API-Football: results=0 (sin datos para esta query)")
                    return []
                response = raw.get("response") or []
                logger.info(f"API-Football OK — {len(response)} fixtures")
                return response
            return []

        except (URLError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF ** (attempt - 1)
            logger.warning(
                f"Intento {attempt} fallido ({type(exc).__name__}: {exc}). "
                f"{'Reintentando en %.1fs…' % wait if attempt < MAX_RETRIES else 'Sin más reintentos.'}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(wait)

    raise RuntimeError(f"API-Football no disponible tras {MAX_RETRIES} intentos: {last_exc}")


def _fetch_external() -> list[dict]:
    """
    Obtiene TODOS los partidos del Mundial 2026 desde api-sports.io.
    Estrategia: combinar jugados recientes + próximos para tener el fixture completo.
    Devuelve lista normalizada al esquema canónico.
    """
    all_fixtures: dict[int, dict] = {}  # keyed by fixture_id para deduplicar

    common = {
        "league":   LEAGUE_ID,
        "season":   SEASON,
        "timezone": TIMEZONE_COL,
    }

    # 1. Partidos en vivo (si los hay)
    try:
        live = _api_get("fixtures", {"live": f"all"})
        # Filtrar solo liga 1 (Mundial)
        live = [f for f in live if (f.get("league") or {}).get("id") == LEAGUE_ID]
        for f in live:
            all_fixtures[f["fixture"]["id"]] = f
        if live:
            logger.info(f"En vivo: {len(live)} partidos")
    except RuntimeError as e:
        logger.warning(f"Live fetch falló (no crítico): {e}")

    # 2. Últimos 50 resultados
    try:
        last = _api_get("fixtures", {**common, "last": 50})
        for f in last:
            all_fixtures[f["fixture"]["id"]] = f
        logger.info(f"Últimos: {len(last)} partidos")
    except RuntimeError as e:
        logger.warning(f"Last fetch falló: {e}")

    # 3. Próximos 60 partidos
    try:
        nxt = _api_get("fixtures", {**common, "next": 60})
        for f in nxt:
            all_fixtures[f["fixture"]["id"]] = f
        logger.info(f"Próximos: {len(nxt)} partidos")
    except RuntimeError as e:
        logger.warning(f"Next fetch falló: {e}")

    if not all_fixtures:
        raise RuntimeError("API-Football no devolvió ningún partido")

    # Normalizar
    normalized = []
    skipped    = 0
    for i, raw in enumerate(all_fixtures.values()):
        try:
            normalized.append(_normalize_fixture(raw, i))
        except Exception as exc:
            skipped += 1
            logger.warning(f"_normalize_fixture skipped id={raw.get('fixture',{}).get('id','?')}: {exc}")

    if skipped:
        logger.warning(f"Fetch: {skipped} partidos descartados por error de normalización")

    # Ordenar cronológicamente
    normalized.sort(key=lambda g: g.get("fecha_iso") or "")
    logger.info(f"Fetch exitosa — {len(normalized)} partidos obtenidos")
    return normalized


# ─── Fallback seed (igual que antes) ─────────────────────────────────────────
# Si la API está caída o sin quota, usamos los 104 partidos del seed local.
# Scores en 0-0 hasta que la API vuelva.

_SEED_GAMES_RAW: list[dict] = json.loads(
    '[{"id":"1","local_date":"06/11/2026 13:00","stadium_id":"1","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Mexico","away_team_name_en":"South Africa","home_team_id":"1","away_team_id":"2"},{"id":"2","local_date":"06/11/2026 20:00","stadium_id":"2","group":"B","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Korea","away_team_name_en":"Czech Republic","home_team_id":"3","away_team_id":"4"},{"id":"3","local_date":"06/12/2026 15:00","stadium_id":"12","group":"C","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Canada","away_team_name_en":"Bosnia and Herzegovina","home_team_id":"5","away_team_id":"6"},{"id":"4","local_date":"06/12/2026 18:00","stadium_id":"16","group":"D","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"United States","away_team_name_en":"Paraguay","home_team_id":"7","away_team_id":"8"},{"id":"5","local_date":"06/13/2026 13:00","stadium_id":"3","group":"E","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Qatar","away_team_name_en":"Switzerland","home_team_id":"9","away_team_id":"10"},{"id":"6","local_date":"06/13/2026 16:00","stadium_id":"4","group":"F","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Brazil","away_team_name_en":"Morocco","home_team_id":"11","away_team_id":"12"},{"id":"7","local_date":"06/13/2026 21:00","stadium_id":"5","group":"G","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Haiti","away_team_name_en":"Scotland","home_team_id":"13","away_team_id":"14"},{"id":"8","local_date":"06/14/2026 14:00","stadium_id":"6","group":"H","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"United States","away_team_name_en":"Paraguay","home_team_id":"7","away_team_id":"8"},{"id":"9","local_date":"06/14/2026 17:00","stadium_id":"7","group":"I","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Australia","away_team_name_en":"Turkey","home_team_id":"15","away_team_id":"16"},{"id":"10","local_date":"06/14/2026 21:00","stadium_id":"8","group":"J","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Germany","away_team_name_en":"Curacao","home_team_id":"17","away_team_id":"18"},{"id":"11","local_date":"06/15/2026 12:00","stadium_id":"9","group":"K","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ivory Coast","away_team_name_en":"Ecuador","home_team_id":"19","away_team_id":"20"},{"id":"12","local_date":"06/15/2026 15:00","stadium_id":"10","group":"L","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Netherlands","away_team_name_en":"Japan","home_team_id":"21","away_team_id":"22"},{"id":"13","local_date":"06/15/2026 19:00","stadium_id":"11","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Sweden","away_team_name_en":"Tunisia","home_team_id":"23","away_team_id":"24"},{"id":"14","local_date":"06/16/2026 12:00","stadium_id":"13","group":"B","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Belgium","away_team_name_en":"Egypt","home_team_id":"25","away_team_id":"26"},{"id":"15","local_date":"06/16/2026 16:00","stadium_id":"14","group":"C","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iran","away_team_name_en":"New Zealand","home_team_id":"27","away_team_id":"28"},{"id":"16","local_date":"06/16/2026 20:00","stadium_id":"15","group":"D","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Spain","away_team_name_en":"Cape Verde","home_team_id":"29","away_team_id":"30"},{"id":"17","local_date":"06/17/2026 12:00","stadium_id":"16","group":"E","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Saudi Arabia","away_team_name_en":"Uruguay","home_team_id":"31","away_team_id":"32"},{"id":"18","local_date":"06/17/2026 16:00","stadium_id":"1","group":"F","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"France","away_team_name_en":"Senegal","home_team_id":"33","away_team_id":"34"},{"id":"19","local_date":"06/17/2026 20:00","stadium_id":"2","group":"G","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iraq","away_team_name_en":"Norway","home_team_id":"35","away_team_id":"36"},{"id":"20","local_date":"06/18/2026 12:00","stadium_id":"3","group":"H","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"21","local_date":"06/18/2026 16:00","stadium_id":"4","group":"I","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Austria","away_team_name_en":"Jordan","home_team_id":"39","away_team_id":"40"},{"id":"22","local_date":"06/18/2026 20:00","stadium_id":"5","group":"J","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Portugal","away_team_name_en":"Democratic Republic of the Congo","home_team_id":"41","away_team_id":"42"},{"id":"23","local_date":"06/19/2026 12:00","stadium_id":"6","group":"K","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Uzbekistan","away_team_name_en":"Colombia","home_team_id":"43","away_team_id":"44"},{"id":"24","local_date":"06/19/2026 16:00","stadium_id":"7","group":"L","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"England","away_team_name_en":"Croatia","home_team_id":"45","away_team_id":"46"},{"id":"25","local_date":"06/19/2026 20:00","stadium_id":"8","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ghana","away_team_name_en":"Panama","home_team_id":"47","away_team_id":"48"},{"id":"26","local_date":"06/20/2026 12:00","stadium_id":"9","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Czech Republic","away_team_name_en":"Belgium","home_team_id":"4","away_team_id":"25"},{"id":"27","local_date":"06/20/2026 16:00","stadium_id":"10","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Bosnia and Herzegovina","away_team_name_en":"Iran","home_team_id":"6","away_team_id":"27"},{"id":"28","local_date":"06/20/2026 20:00","stadium_id":"11","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Paraguay","away_team_name_en":"Spain","home_team_id":"8","away_team_id":"29"},{"id":"29","local_date":"06/21/2026 12:00","stadium_id":"12","group":"E","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Switzerland","away_team_name_en":"Saudi Arabia","home_team_id":"10","away_team_id":"31"},{"id":"30","local_date":"06/21/2026 16:00","stadium_id":"13","group":"F","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Morocco","away_team_name_en":"Uzbekistan","home_team_id":"12","away_team_id":"43"},{"id":"31","local_date":"06/21/2026 20:00","stadium_id":"14","group":"G","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Scotland","away_team_name_en":"Iraq","home_team_id":"14","away_team_id":"35"},{"id":"32","local_date":"06/22/2026 12:00","stadium_id":"15","group":"H","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Algeria","away_team_name_en":"Austria","home_team_id":"38","away_team_id":"39"},{"id":"33","local_date":"06/22/2026 16:00","stadium_id":"16","group":"I","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Jordan","away_team_name_en":"Australia","home_team_id":"40","away_team_id":"15"},{"id":"34","local_date":"06/22/2026 20:00","stadium_id":"1","group":"J","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Curacao","away_team_name_en":"Portugal","home_team_id":"18","away_team_id":"41"},{"id":"35","local_date":"06/23/2026 12:00","stadium_id":"2","group":"K","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Colombia","away_team_name_en":"Ivory Coast","home_team_id":"44","away_team_id":"19"},{"id":"36","local_date":"06/23/2026 16:00","stadium_id":"3","group":"L","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Croatia","away_team_name_en":"Netherlands","home_team_id":"46","away_team_id":"21"},{"id":"37","local_date":"06/23/2026 20:00","stadium_id":"4","group":"A","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Africa","away_team_name_en":"Sweden","home_team_id":"2","away_team_id":"23"},{"id":"38","local_date":"06/24/2026 12:00","stadium_id":"5","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Egypt","away_team_name_en":"South Korea","home_team_id":"26","away_team_id":"3"},{"id":"39","local_date":"06/24/2026 16:00","stadium_id":"6","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"New Zealand","away_team_name_en":"Canada","home_team_id":"28","away_team_id":"5"},{"id":"40","local_date":"06/24/2026 20:00","stadium_id":"7","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Cape Verde","away_team_name_en":"United States","home_team_id":"30","away_team_id":"7"},{"id":"41","local_date":"06/25/2026 12:00","stadium_id":"8","group":"E","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Uruguay","away_team_name_en":"Qatar","home_team_id":"32","away_team_id":"9"},{"id":"42","local_date":"06/25/2026 16:00","stadium_id":"9","group":"F","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Senegal","away_team_name_en":"Brazil","home_team_id":"34","away_team_id":"11"},{"id":"43","local_date":"06/25/2026 20:00","stadium_id":"10","group":"G","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Norway","away_team_name_en":"Haiti","home_team_id":"36","away_team_id":"13"},{"id":"44","local_date":"06/26/2026 12:00","stadium_id":"11","group":"H","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"45","local_date":"06/26/2026 16:00","stadium_id":"12","group":"I","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Turkey","away_team_name_en":"Jordan","home_team_id":"16","away_team_id":"40"},{"id":"46","local_date":"06/26/2026 20:00","stadium_id":"13","group":"J","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Democratic Republic of the Congo","away_team_name_en":"Germany","home_team_id":"42","away_team_id":"17"},{"id":"47","local_date":"06/27/2026 12:00","stadium_id":"14","group":"K","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ecuador","away_team_name_en":"Colombia","home_team_id":"20","away_team_id":"44"},{"id":"48","local_date":"06/27/2026 16:00","stadium_id":"15","group":"L","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Japan","away_team_name_en":"England","home_team_id":"22","away_team_id":"45"},{"id":"49","local_date":"06/27/2026 20:00","stadium_id":"16","group":"A","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Panama","away_team_name_en":"Mexico","home_team_id":"48","away_team_id":"1"},{"id":"50","local_date":"06/28/2026 12:00","stadium_id":"1","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Tunisia","away_team_name_en":"Czech Republic","home_team_id":"24","away_team_id":"4"},{"id":"51","local_date":"06/28/2026 16:00","stadium_id":"2","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iran","away_team_name_en":"New Zealand","home_team_id":"27","away_team_id":"28"},{"id":"52","local_date":"06/28/2026 20:00","stadium_id":"3","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Spain","away_team_name_en":"Paraguay","home_team_id":"29","away_team_id":"8"},{"id":"53","local_date":"06/29/2026 12:00","stadium_id":"4","group":"E","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Qatar","away_team_name_en":"Saudi Arabia","home_team_id":"9","away_team_id":"31"},{"id":"54","local_date":"06/29/2026 12:00","stadium_id":"5","group":"E","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Switzerland","away_team_name_en":"Uruguay","home_team_id":"10","away_team_id":"32"},{"id":"55","local_date":"06/29/2026 20:00","stadium_id":"6","group":"F","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Brazil","away_team_name_en":"Senegal","home_team_id":"11","away_team_id":"34"},{"id":"56","local_date":"06/29/2026 20:00","stadium_id":"7","group":"F","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Morocco","away_team_name_en":"Uzbekistan","home_team_id":"12","away_team_id":"43"},{"id":"57","local_date":"06/30/2026 12:00","stadium_id":"8","group":"G","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Scotland","away_team_name_en":"Haiti","home_team_id":"14","away_team_id":"13"},{"id":"58","local_date":"06/30/2026 12:00","stadium_id":"9","group":"G","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Norway","away_team_name_en":"Iraq","home_team_id":"36","away_team_id":"35"},{"id":"59","local_date":"06/30/2026 20:00","stadium_id":"10","group":"H","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"60","local_date":"06/30/2026 20:00","stadium_id":"11","group":"H","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Austria","away_team_name_en":"Algeria","home_team_id":"39","away_team_id":"38"},{"id":"61","local_date":"07/01/2026 12:00","stadium_id":"12","group":"I","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Australia","away_team_name_en":"Jordan","home_team_id":"15","away_team_id":"40"},{"id":"62","local_date":"07/01/2026 12:00","stadium_id":"13","group":"I","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Turkey","away_team_name_en":"Austria","home_team_id":"16","away_team_id":"39"},{"id":"63","local_date":"07/01/2026 20:00","stadium_id":"14","group":"J","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Germany","away_team_name_en":"Portugal","home_team_id":"17","away_team_id":"41"},{"id":"64","local_date":"07/01/2026 20:00","stadium_id":"15","group":"J","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Curacao","away_team_name_en":"Democratic Republic of the Congo","home_team_id":"18","away_team_id":"42"},{"id":"65","local_date":"07/02/2026 12:00","stadium_id":"16","group":"K","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ivory Coast","away_team_name_en":"Colombia","home_team_id":"19","away_team_id":"44"},{"id":"66","local_date":"07/02/2026 12:00","stadium_id":"1","group":"K","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ecuador","away_team_name_en":"Uzbekistan","home_team_id":"20","away_team_id":"43"},{"id":"67","local_date":"07/02/2026 20:00","stadium_id":"2","group":"L","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Netherlands","away_team_name_en":"England","home_team_id":"21","away_team_id":"45"},{"id":"68","local_date":"07/02/2026 20:00","stadium_id":"3","group":"L","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Japan","away_team_name_en":"Croatia","home_team_id":"22","away_team_id":"46"},{"id":"69","local_date":"07/03/2026 12:00","stadium_id":"4","group":"A","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Mexico","away_team_name_en":"Ghana","home_team_id":"1","away_team_id":"47"},{"id":"70","local_date":"07/03/2026 12:00","stadium_id":"5","group":"A","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Panama","away_team_name_en":"South Africa","home_team_id":"48","away_team_id":"2"},{"id":"71","local_date":"07/03/2026 20:00","stadium_id":"6","group":"B","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Korea","away_team_name_en":"Tunisia","home_team_id":"3","away_team_id":"24"},{"id":"72","local_date":"07/03/2026 20:00","stadium_id":"7","group":"B","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Belgium","away_team_name_en":"Egypt","home_team_id":"25","away_team_id":"26"}]'
)

_STADIUM_UTC_OFFSET: dict[str, int] = {
    "MetLife Stadium": -4, "AT&T Stadium": -5, "SoFi Stadium": -7,
    "Hard Rock Stadium": -4, "Mercedes-Benz Stadium": -4, "NRG Stadium": -5,
    "Lincoln Financial Field": -4, "Levi's Stadium": -7, "Lumen Field": -7,
    "Gillette Stadium": -4, "GEHA Field at Arrowhead Stadium": -5,
    "Estadio Azteca": -6, "Estadio Akron": -6, "Estadio BBVA": -6,
    "BC Place": -7, "BMO Field": -4,
}
_STADIUM_ID_NAME: dict[str, str] = {
    "1": "Estadio Azteca", "2": "Estadio Akron", "3": "Estadio BBVA",
    "4": "AT&T Stadium", "5": "NRG Stadium",
    "6": "GEHA Field at Arrowhead Stadium", "7": "Mercedes-Benz Stadium",
    "8": "Hard Rock Stadium", "9": "Gillette Stadium",
    "10": "Lincoln Financial Field", "11": "MetLife Stadium",
    "12": "BMO Field", "13": "BC Place", "14": "Lumen Field",
    "15": "Levi's Stadium", "16": "SoFi Stadium",
}
_TYPE_MAP = {
    "group": "Grupos", "r32": "Dieciseisavos", "r16": "Octavos",
    "qf": "Cuartos", "sf": "Semifinal", "third": "Tercer puesto",
    "3rd": "Tercer puesto", "final": "Final", "knockout": "Eliminatoria",
}
_STATUS_MAP_OLD = {
    "scheduled": "programado", "upcoming": "programado",
    "not started": "programado", "live": "en_curso",
    "in progress": "en_curso", "halftime": "en_curso",
    "finished": "finalizado", "full-time": "finalizado",
    "ft": "finalizado",
}


def _normalize_game_seed(raw: dict, idx: int = 0) -> dict:
    """Normaliza un partido del seed local (formato de fallback)."""
    local     = str(raw.get("home_team_name_en") or "TBD").strip()
    visitante = str(raw.get("away_team_name_en") or "TBD").strip()
    cod_l = _country_code(local)
    cod_v = _country_code(visitante)

    hs = raw.get("home_score"); ga = raw.get("away_score")
    try:   gl = int(hs) if hs is not None else None
    except: gl = None
    try:   gv = int(ga) if ga is not None else None
    except: gv = None

    time_elapsed = str(raw.get("time_elapsed") or "").lower().strip()
    finished_raw = str(raw.get("finished") or "").upper().strip()
    if finished_raw == "TRUE":  estado = "finalizado"
    elif time_elapsed not in ("notstarted", "not started", "", "ns"): estado = "en_curso"
    else: estado = "programado"

    type_raw = str(raw.get("type") or "").lower()
    fase  = _TYPE_MAP.get(type_raw, "Grupos")
    grupo_raw = str(raw.get("group") or "")
    grupo = None
    if fase == "Grupos":
        m = re.search(r"[A-L]", grupo_raw.upper())
        grupo = m.group(0) if m else None

    date_raw = str(raw.get("local_date") or "")
    stadium_id = str(raw.get("stadium_id") or "")
    fecha_iso: Optional[str] = None
    if date_raw and "/" in date_raw:
        try:
            parts = date_raw.strip().split(" ")
            md = parts[0].split("/")
            naive_str = f"{md[2]}-{md[0].zfill(2)}-{md[1].zfill(2)}T{parts[1]}:00"
            local_dt = datetime.strptime(naive_str, "%Y-%m-%dT%H:%M:%S")
            stadium_nom = _STADIUM_ID_NAME.get(stadium_id, "")
            offset_h = _STADIUM_UTC_OFFSET.get(stadium_nom, -6)
            utc_dt = local_dt - timedelta(hours=offset_h)
            fecha_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass

    _id_raw = raw.get("id")
    return {
        "id":           int(_id_raw if _id_raw is not None else (1000 + idx)),
        "fase":         fase,
        "grupo":        grupo,
        "local":        local,
        "visitante":    visitante,
        "codigo_local": cod_l,
        "codigo_visit": cod_v,
        "goles_local":  gl,
        "goles_visit":  gv,
        "bloqueado":    estado == "finalizado",
        "fecha_texto":  _to_fecha_texto(fecha_iso),
        "fecha_iso":    fecha_iso,
        "sede":         "",
        "estado":       estado,
        "minuto":       None,
        "status_short": "",
        "logo_local":   "",
        "logo_visit":   "",
    }


def _fallback_games() -> list[dict]:
    """Fallback: 72 partidos de grupos con fechas reales (seed local)."""
    normalized = []
    for i, g in enumerate(_SEED_GAMES_RAW):
        try:
            normalized.append(_normalize_game_seed(g, i))
        except Exception as exc:
            logger.warning(f"Fallback seed error id={g.get('id')}: {exc}")
    logger.info(f"Fallback seed: {len(normalized)} partidos cargados")
    return normalized


# ─── Cache y TTL dinámico ────────────────────────────────────────────────────

_TZ_BOGOTA = timezone(timedelta(hours=-5))


def _today_str() -> str:
    return datetime.now(_TZ_BOGOTA).date().isoformat()


def _fecha_iso_to_bogota_date(iso: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ_BOGOTA).date().isoformat()
    except Exception:
        return None


def _game_is_live(game: dict) -> bool:
    return game.get("estado") == "en_curso"


def _game_is_today(game: dict) -> bool:
    iso = game.get("fecha_iso")
    if iso:
        bog = _fecha_iso_to_bogota_date(iso)
        if bog:
            return bog == _today_str()
    return False


def _game_is_upcoming(game: dict) -> bool:
    iso = game.get("fecha_iso")
    if iso:
        bog = _fecha_iso_to_bogota_date(iso)
        if bog:
            return bog > _today_str()
    return game.get("estado") == "programado" and not _game_is_today(game)


def _dynamic_ttl(games: list[dict]) -> int:
    if any(_game_is_live(g) for g in games):
        return _TTL_LIVE
    if any(_game_is_today(g) for g in games):
        return _TTL_HOY
    return _TTL_NORMAL


# ─── API pública del servicio (MISMO contrato que antes) ──────────────────────

def get_all_games(force_refresh: bool = False) -> tuple[list[dict], str]:
    """Devuelve (lista_partidos, fuente). TTL dinámico según estado del torneo."""
    if not force_refresh:
        cached = _cache.get("all_games")
        if cached is not None:
            return cached, "cache"

    with _fetch_lock:
        cached = _cache.get("all_games")
        if cached is not None and not force_refresh:
            return cached, "cache"

        try:
            games = _fetch_external()
            ttl   = _dynamic_ttl(games)
            _cache.set("all_games", games, ttl=ttl)
            logger.info(f"Cache actualizado — {len(games)} partidos, TTL={ttl}s")
            return games, "external"
        except RuntimeError as exc:
            logger.error(f"Usando fallback local. Razón: {exc}")
            games = _fallback_games()
            _cache.set("all_games", games, ttl=30)
            return games, "fallback"


def get_partidos_hoy() -> tuple[list[dict], str]:
    """Partidos de hoy en Bogotá/Lima (UTC-5), ordenados: en_curso → programado → finalizado."""
    games, source = get_all_games()
    hoy = [g for g in games if _game_is_today(g)]

    def _prio(g: dict) -> tuple:
        e = g.get("estado", "")
        p = 0 if e == "en_curso" else (1 if e == "programado" else 2)
        return (p, g.get("fecha_iso") or "")

    hoy.sort(key=_prio)
    return hoy, source


def get_en_vivo() -> tuple[list[dict], str]:
    """Solo partidos en curso. Fuerza refresh si venían de caché."""
    games, source = get_all_games()
    live = [g for g in games if _game_is_live(g)]
    if live and source == "cache":
        games, source = get_all_games(force_refresh=True)
        live = [g for g in games if _game_is_live(g)]
    return live, source


def get_proximos(limit: int = 10) -> tuple[list[dict], str]:
    """Próximos partidos sin disputar, ordenados por fecha."""
    games, source = get_all_games()
    upcoming = sorted(
        [g for g in games if _game_is_upcoming(g)],
        key=lambda g: g.get("fecha_iso") or ""
    )
    return upcoming[:limit], source


def get_partido(partido_id: int) -> tuple[Optional[dict], str]:
    """Partido por ID; None si no existe."""
    games, source = get_all_games()
    return next((g for g in games if g["id"] == partido_id), None), source


def get_live_ttl() -> int:
    cached = _cache.get("all_games")
    return _dynamic_ttl(cached) if cached else _TTL_NORMAL


def hay_partidos_en_vivo() -> bool:
    cached = _cache.get("all_games")
    return any(_game_is_live(g) for g in cached) if cached else False


def invalidate_cache() -> None:
    _cache.delete("all_games")
    logger.info("Caché invalidada manualmente")
