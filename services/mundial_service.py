"""
services/mundial_service.py
============================
Servicio de datos del Mundial 2026 — v3.

Flujo:
  worldcup26.ir/get/teams  →  _teams_cache (iso2 + nombre ES)
  worldcup26.ir/get/games  →  _fetch_external()  →  _cache  →  endpoints públicos

v3 — nuevas funciones públicas:
  get_groups()           → dict {A..L: [equipo, ...]} con tabla FIFA calculada
  get_group_table(letra) → lista de equipos de un grupo ordenados
  get_goals_ranking()    → lista de selecciones ordenadas por GF DESC
  get_qualified()        → 1°/2° de cada grupo
  get_stats()            → estadísticas globales
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
EXTERNAL_API_URL: str = os.getenv("MUNDIAL_API_URL", "https://worldcup26.ir/get/games")
TEAMS_API_URL:    str = "https://worldcup26.ir/get/teams"
CACHE_TTL_SECONDS: int = int(os.getenv("MUNDIAL_CACHE_TTL", "120"))
REQUEST_TIMEOUT:   int = int(os.getenv("MUNDIAL_TIMEOUT",   "10"))
MAX_RETRIES:       int = int(os.getenv("MUNDIAL_RETRIES",   "1"))
RETRY_BACKOFF:   float = float(os.getenv("MUNDIAL_BACKOFF", "1.0"))
_TTL_LIVE   = int(os.getenv("MUNDIAL_TTL_LIVE",  "20"))
_TTL_HOY    = int(os.getenv("MUNDIAL_TTL_HOY",   "60"))
_TTL_NORMAL = CACHE_TTL_SECONDS

# Colombia/Perú: UTC-5 (sin DST todo el año)
_TZ_BOGOTA = timezone(timedelta(hours=-5))

# ─── Caché en memoria ────────────────────────────────────────────────────────
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
_teams_lock = threading.Lock()

# ─── Nombres en español por código ISO-2 (minúsculas) ────────────────────────
_NOMBRE_ES: dict[str, str] = {
    "us": "Estados Unidos", "ca": "Canadá",     "mx": "México",
    "br": "Brasil",         "ar": "Argentina",  "co": "Colombia",
    "uy": "Uruguay",        "cl": "Chile",       "ec": "Ecuador",
    "pe": "Perú",           "ve": "Venezuela",   "py": "Paraguay",
    "bo": "Bolivia",        "cr": "Costa Rica",  "hn": "Honduras",
    "pa": "Panamá",         "jm": "Jamaica",     "ht": "Haití",
    "tt": "Trinidad y Tobago",
    "de": "Alemania",       "fr": "Francia",     "es": "España",
    "gb-eng": "Inglaterra", "pt": "Portugal",    "nl": "Países Bajos",
    "it": "Italia",         "be": "Bélgica",     "hr": "Croacia",
    "rs": "Serbia",         "dk": "Dinamarca",   "ch": "Suiza",
    "pl": "Polonia",        "ua": "Ucrania",     "at": "Austria",
    "se": "Suecia",         "tr": "Turquía",     "gb-sct": "Escocia",
    "gb-wls": "Gales",      "cz": "República Checa", "sk": "Eslovaquia",
    "hu": "Hungría",        "ro": "Rumanía",     "al": "Albania",
    "gr": "Grecia",         "no": "Noruega",     "ba": "Bosnia y Herzegovina",
    "cv": "Cabo Verde",     "cw": "Curazao",
    "ma": "Marruecos",      "sn": "Senegal",     "ng": "Nigeria",
    "cm": "Camerún",        "eg": "Egipto",      "gh": "Ghana",
    "ci": "Costa de Marfil","za": "Sudáfrica",   "tn": "Túnez",
    "dz": "Argelia",        "cd": "RD Congo",    "ml": "Malí",
    "jp": "Japón",          "kr": "Corea del Sur","ir": "Irán",
    "iq": "Irak",           "sa": "Arabia Saudita","au": "Australia",
    "nz": "Nueva Zelanda",  "uz": "Uzbekistán",  "qa": "Catar",
    "jo": "Jordania",       "cn": "China",       "id": "Indonesia",
    "th": "Tailandia",      "in": "India",       "fj": "Fiyi",
}

_EN_ES: dict[str, str] = {
    "united states": "Estados Unidos", "usa": "Estados Unidos",
    "canada": "Canadá",    "mexico": "México",
    "brazil": "Brasil",    "argentina": "Argentina",
    "colombia": "Colombia","uruguay": "Uruguay",
    "chile": "Chile",      "ecuador": "Ecuador",
    "peru": "Perú",        "venezuela": "Venezuela",
    "paraguay": "Paraguay","costa rica": "Costa Rica",
    "honduras": "Honduras","panama": "Panamá",
    "jamaica": "Jamaica",  "haiti": "Haití",
    "germany": "Alemania", "france": "Francia",
    "spain": "España",     "england": "Inglaterra",
    "portugal": "Portugal","netherlands": "Países Bajos",
    "italy": "Italia",     "belgium": "Bélgica",
    "croatia": "Croacia",  "serbia": "Serbia",
    "denmark": "Dinamarca","switzerland": "Suiza",
    "poland": "Polonia",   "ukraine": "Ucrania",
    "austria": "Austria",  "sweden": "Suecia",
    "turkey": "Turquía",   "scotland": "Escocia",
    "wales": "Gales",      "czechia": "República Checa",
    "czech republic": "República Checa",
    "slovakia": "Eslovaquia","hungary": "Hungría",
    "romania": "Rumanía",  "albania": "Albania",
    "greece": "Grecia",    "norway": "Noruega",
    "bosnia and herzegovina": "Bosnia y Herzegovina",
    "cape verde": "Cabo Verde","curacao": "Curazao","curaçao": "Curazao",
    "morocco": "Marruecos","senegal": "Senegal",
    "nigeria": "Nigeria",  "cameroon": "Camerún",
    "egypt": "Egipto",     "ghana": "Ghana",
    "ivory coast": "Costa de Marfil","cote d'ivoire": "Costa de Marfil",
    "south africa": "Sudáfrica","tunisia": "Túnez",
    "algeria": "Argelia",  "dr congo": "RD Congo",
    "democratic republic of the congo": "RD Congo",
    "japan": "Japón",      "south korea": "Corea del Sur",
    "korea republic": "Corea del Sur",
    "iran": "Irán",        "iraq": "Irak",
    "saudi arabia": "Arabia Saudita","australia": "Australia",
    "new zealand": "Nueva Zelanda","uzbekistan": "Uzbekistán",
    "qatar": "Catar",      "jordan": "Jordania",
}

# ─── Mapa offsets UTC de estadios (junio-julio 2026) ─────────────────────────
_STADIUM_UTC_OFFSET: dict[str, int] = {
    "MetLife Stadium": -4, "AT&T Stadium": -5, "SoFi Stadium": -7,
    "Hard Rock Stadium": -4, "Mercedes-Benz Stadium": -4, "NRG Stadium": -5,
    "Lincoln Financial Field": -4, "Levi's Stadium": -7, "Lumen Field": -7,
    "Gillette Stadium": -4, "GEHA Field at Arrowhead Stadium": -5,
    "Estadio Azteca": -6, "Estadio Akron": -6, "Estadio BBVA": -6,
    "BC Place": -7, "BMO Field": -4,
}
_STADIUM_ID_NAME: dict[str, str] = {
    "1": "Estadio Azteca",   "2": "Estadio Akron",
    "3": "Estadio BBVA",     "4": "AT&T Stadium",
    "5": "NRG Stadium",      "6": "GEHA Field at Arrowhead Stadium",
    "7": "Mercedes-Benz Stadium", "8": "Hard Rock Stadium",
    "9": "Gillette Stadium", "10": "Lincoln Financial Field",
    "11": "MetLife Stadium", "12": "BMO Field",
    "13": "BC Place",        "14": "Lumen Field",
    "15": "Levi's Stadium",  "16": "SoFi Stadium",
}

# ─── Mapas de estado y fase ───────────────────────────────────────────────────
_STATUS_MAP: dict[str, str] = {
    "scheduled": "programado", "upcoming": "programado",
    "not started": "programado", "notstarted": "programado",
    "live": "en_curso", "in progress": "en_curso", "halftime": "en_curso",
    "finished": "finalizado", "full-time": "finalizado",
    "fulltime": "finalizado", "ft": "finalizado",
    "aet": "finalizado", "penalties": "finalizado", "completed": "finalizado",
}
_TYPE_MAP: dict[str, str] = {
    "group": "Grupos",   "r32": "Dieciseisavos", "r16": "Octavos",
    "qf": "Cuartos",     "sf": "Semifinal",
    "third": "Tercer puesto", "3rd": "Tercer puesto",
    "final": "Final",    "knockout": "Eliminatoria",
}
_ELAPSED_LABEL: dict[str, Optional[str]] = {
    "halftime": "Desc.", "half time": "Desc.",
    "first half": "1T",  "second half": "2T",
    "extra time": "Prórroga", "penalty": "Penales",
    "penalties": "Penales",   "in progress": None,
}

# Grupos A-L del Mundial 2026
_GRUPOS_LETRAS = list("ABCDEFGHIJKL")

# ─── Caché de equipos (iso2 + nombre ES) ─────────────────────────────────────
_teams_data: dict[str, dict] = {}
_teams_loaded = False

def _hacer_request(url: str) -> Any:
    """HTTP GET autenticado a worldcup26.ir con reintentos."""
    last_exc: Exception = RuntimeError("never tried")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            jwt = os.getenv("WC26_JWT_TOKEN", "").strip()
            headers = {
                "User-Agent": "FamiliaApp/1.0 Mundial2026",
                "Accept":     "application/json",
            }
            if jwt:
                headers["Authorization"] = f"Bearer {jwt}"
            req = Request(url, headers=headers)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (URLError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF ** (attempt - 1)
            if attempt < MAX_RETRIES:
                logger.warning(f"Request intento {attempt} falló ({exc}); reintentando en {wait:.1f}s")
                time.sleep(wait)
    raise RuntimeError(f"Request fallida tras {MAX_RETRIES} intentos: {last_exc}")


def _cargar_equipos() -> None:
    """Carga /get/teams una vez y puebla _teams_data con iso2 + nombre ES."""
    global _teams_data, _teams_loaded
    cached = _cache.get("teams_data")
    if cached:
        _teams_data = cached
        _teams_loaded = True
        return
    try:
        raw = _hacer_request(TEAMS_API_URL)
        teams_list = raw if isinstance(raw, list) else raw.get("teams", [])
        data: dict[str, dict] = {}
        for t in teams_list:
            tid = str(t.get("id") or t.get("_id") or "")
            if not tid:
                continue
            iso2_raw = (t.get("iso2") or "").lower().strip()
            nombre_en = t.get("name_en") or ""
            nombre_es = (
                _NOMBRE_ES.get(iso2_raw)
                or _EN_ES.get(nombre_en.lower())
                or nombre_en
            )
            data[tid] = {
                "iso2":      iso2_raw,
                "nombre_es": nombre_es,
                "nombre_en": nombre_en,
            }
        _teams_data = data
        _teams_loaded = True
        _cache.set("teams_data", data, ttl=3600)
        logger.info(f"Equipos cargados: {len(data)} equipos con iso2 y nombre ES")
    except Exception as exc:
        logger.warning(f"No se pudo cargar /get/teams: {exc} — se usará fallback por nombre")
        _teams_loaded = True


def _get_team_info(team_id: str, name_en: str) -> tuple[str, str]:
    """Devuelve (nombre_es, iso2) para un equipo."""
    global _teams_loaded
    if not _teams_loaded:
        with _teams_lock:
            if not _teams_loaded:
                _cargar_equipos()

    info = _teams_data.get(str(team_id))
    if info:
        return info["nombre_es"], info["iso2"]

    iso2 = ""
    nombre_es = _EN_ES.get(name_en.lower(), name_en)
    for _iso, _en in {
        "us":"United States","ca":"Canada","mx":"Mexico","br":"Brazil",
        "ar":"Argentina","co":"Colombia","uy":"Uruguay","cl":"Chile",
        "ec":"Ecuador","pe":"Peru","ve":"Venezuela","py":"Paraguay",
        "cr":"Costa Rica","hn":"Honduras","pa":"Panama","jm":"Jamaica",
        "ht":"Haiti","de":"Germany","fr":"France","es":"Spain",
        "gb-eng":"England","pt":"Portugal","nl":"Netherlands","it":"Italy",
        "be":"Belgium","hr":"Croatia","rs":"Serbia","dk":"Denmark",
        "ch":"Switzerland","pl":"Poland","ua":"Ukraine","at":"Austria",
        "se":"Sweden","tr":"Turkey","gb-sct":"Scotland","gb-wls":"Wales",
        "cz":"Czechia","sk":"Slovakia","hu":"Hungary","ro":"Romania",
        "al":"Albania","gr":"Greece","no":"Norway","ba":"Bosnia and Herzegovina",
        "cv":"Cape Verde","cw":"Curacao","ma":"Morocco","sn":"Senegal",
        "ng":"Nigeria","cm":"Cameroon","eg":"Egypt","gh":"Ghana",
        "ci":"Ivory Coast","za":"South Africa","tn":"Tunisia","dz":"Algeria",
        "cd":"DR Congo","jp":"Japan","kr":"South Korea","ir":"Iran",
        "iq":"Iraq","sa":"Saudi Arabia","au":"Australia","nz":"New Zealand",
        "uz":"Uzbekistan","qa":"Qatar","jo":"Jordan",
    }.items():
        if _en.lower() == name_en.lower():
            iso2 = _iso
            break
    return nombre_es, iso2


# ─── Conversión de fecha local del estadio → UTC → Colombia ──────────────────

def _local_date_to_col_iso(local_date: str, stadium_id: str) -> Optional[str]:
    try:
        parts = local_date.strip().split(" ")
        dp = parts[0].split("/")
        tp = parts[1] if len(parts) > 1 else "00:00"
        naive = datetime(int(dp[2]), int(dp[0]), int(dp[1]),
                         int(tp[:2]), int(tp[3:]))
        stadium_name = _STADIUM_ID_NAME.get(str(stadium_id))
        offset_h = _STADIUM_UTC_OFFSET.get(stadium_name, -6)
        utc_dt = naive - timedelta(hours=offset_h)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _iso_to_col_texto(iso: str) -> str:
    dias_es   = ["Lun.", "Mar.", "Mié.", "Jue.", "Vie.", "Sáb.", "Dom."]
    meses_es  = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"]
    try:
        dt_utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_col = dt_utc.astimezone(_TZ_BOGOTA)
        dia    = dias_es[dt_col.weekday()]
        mes    = meses_es[dt_col.month - 1]
        return f"{dia} {dt_col.day} {mes}, {dt_col.strftime('%H:%M')}"
    except Exception:
        return iso[:16] if iso else ""


def _today_col() -> str:
    return datetime.now(_TZ_BOGOTA).date().isoformat()


def _iso_to_col_date(iso: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(_TZ_BOGOTA).date().isoformat()
    except Exception:
        return None


# ─── Normalización de un partido ─────────────────────────────────────────────

def _normalize_game(raw: dict, idx: int = 0) -> dict:
    home_id   = str(raw.get("home_team_id") or "")
    away_id   = str(raw.get("away_team_id") or "")
    home_en   = raw.get("home_team_name_en") or raw.get("home_team") or "TBD"
    away_en   = raw.get("away_team_name_en") or raw.get("away_team") or "TBD"

    nombre_local,    cod_local = _get_team_info(home_id, home_en)
    nombre_visitante, cod_visit = _get_team_info(away_id, away_en)

    score = raw.get("score") or raw.get("scores")
    if isinstance(score, dict) and score:
        gl = score.get("home")
        gv = score.get("away")
    else:
        gl = raw.get("home_score")
        gv = raw.get("away_score")
    try: gl = int(gl) if gl is not None else None
    except (TypeError, ValueError): gl = None
    try: gv = int(gv) if gv is not None else None
    except (TypeError, ValueError): gv = None

    time_elapsed  = str(raw.get("time_elapsed") or "").lower().strip()
    finished_raw  = str(raw.get("finished")     or "").upper().strip()

    if finished_raw == "TRUE":
        estado = "finalizado"
    elif time_elapsed in ("fulltime", "full time", "full-time", "completed", "ft"):
        estado = "finalizado"
    elif time_elapsed in ("halftime", "first half", "second half",
                          "extra time", "penalty", "in progress"):
        estado = "en_curso"
    elif time_elapsed and time_elapsed not in ("notstarted", "not started", ""):
        estado = "en_curso"
    else:
        estado = _STATUS_MAP.get(str(raw.get("status") or "scheduled").lower(), "programado")

    bloqueado = estado == "finalizado"

    type_raw  = str(raw.get("type")  or "").lower()
    phase_raw = str(raw.get("round") or raw.get("phase") or raw.get("stage") or "")
    fase = _TYPE_MAP.get(type_raw) or _TYPE_MAP.get(phase_raw.lower(), phase_raw.strip() or "Grupos")

    grupo = None
    if fase == "Grupos":
        grupo_raw = str(raw.get("group") or "")
        m = re.search(r"[A-L]", grupo_raw.upper())
        grupo = m.group(0) if m else None

    local_date = str(raw.get("local_date") or "")
    stadium_id = str(raw.get("stadium_id") or "")

    if local_date and "/" in local_date:
        fecha_iso = _local_date_to_col_iso(local_date, stadium_id)
    else:
        fecha_iso = local_date or None

    fecha_texto = _iso_to_col_texto(fecha_iso) if fecha_iso else ""
    sede = _STADIUM_ID_NAME.get(stadium_id, "")
    if not sede:
        venue = raw.get("venue") or raw.get("stadium") or raw.get("city") or ""
        sede  = str(venue) if not isinstance(venue, dict) else venue.get("name", "")

    def _minuto_reloj(iso: Optional[str]) -> Optional[str]:
        if not iso:
            return "En vivo"
        try:
            kickoff = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            elapsed = int((datetime.now(timezone.utc) - kickoff).total_seconds() / 60)
            if elapsed < 0:   return None
            elif elapsed <= 47:  return f"{min(elapsed, 45)}'"
            elif elapsed <= 60:  return "Desc."
            elif elapsed <= 107: return f"{min(elapsed - 15, 90)}'"
            elif elapsed <= 122: return "Desc."
            elif elapsed <= 152: return f"PT {min(elapsed - 122, 30)}'"
            else:                return "Penales"
        except Exception:
            return "En vivo"

    minuto: Optional[str] = None
    if estado == "en_curso":
        if time_elapsed and re.match(r"^\d+", time_elapsed):
            minuto = time_elapsed if "+" in time_elapsed else f"{time_elapsed}'"
        elif time_elapsed in _ELAPSED_LABEL:
            lbl = _ELAPSED_LABEL[time_elapsed]
            minuto = lbl if lbl is not None else _minuto_reloj(fecha_iso)
        else:
            minuto = _minuto_reloj(fecha_iso)

    _id_raw = raw.get("id") if raw.get("id") is not None else raw.get("match_id")
    return {
        "id":           int(_id_raw if _id_raw is not None else (1000 + idx)),
        "fase":         fase,
        "grupo":        grupo,
        "local":        nombre_local,
        "visitante":    nombre_visitante,
        "codigo_local": cod_local,
        "codigo_visit": cod_visit,
        "goles_local":  gl,
        "goles_visit":  gv,
        "bloqueado":    bloqueado,
        "fecha_texto":  fecha_texto,
        "fecha_iso":    fecha_iso,
        "sede":         sede,
        "estado":       estado,
        "minuto":       minuto,
    }


# ─── Seed fallback (104 partidos) ────────────────────────────────────────────
import json as _json_mod

_SEED_GAMES_RAW: list[dict] = _json_mod.loads(
    '[{"id":"1","local_date":"06/11/2026 13:00","stadium_id":"1","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Mexico","away_team_name_en":"South Africa","home_team_id":"1","away_team_id":"2"},{"id":"2","local_date":"06/11/2026 20:00","stadium_id":"2","group":"B","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Korea","away_team_name_en":"Czech Republic","home_team_id":"3","away_team_id":"4"},{"id":"3","local_date":"06/12/2026 15:00","stadium_id":"12","group":"C","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Canada","away_team_name_en":"Bosnia and Herzegovina","home_team_id":"5","away_team_id":"6"},{"id":"4","local_date":"06/12/2026 18:00","stadium_id":"16","group":"D","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"United States","away_team_name_en":"Paraguay","home_team_id":"7","away_team_id":"8"},{"id":"5","local_date":"06/13/2026 13:00","stadium_id":"3","group":"E","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Qatar","away_team_name_en":"Switzerland","home_team_id":"9","away_team_id":"10"},{"id":"6","local_date":"06/13/2026 16:00","stadium_id":"4","group":"F","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Brazil","away_team_name_en":"Morocco","home_team_id":"11","away_team_id":"12"},{"id":"7","local_date":"06/13/2026 21:00","stadium_id":"5","group":"G","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Haiti","away_team_name_en":"Scotland","home_team_id":"13","away_team_id":"14"},{"id":"8","local_date":"06/14/2026 14:00","stadium_id":"6","group":"H","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"United States","away_team_name_en":"Paraguay","home_team_id":"7","away_team_id":"8"},{"id":"9","local_date":"06/14/2026 17:00","stadium_id":"7","group":"I","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Australia","away_team_name_en":"Turkey","home_team_id":"15","away_team_id":"16"},{"id":"10","local_date":"06/14/2026 21:00","stadium_id":"8","group":"J","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Germany","away_team_name_en":"Curacao","home_team_id":"17","away_team_id":"18"},{"id":"11","local_date":"06/15/2026 12:00","stadium_id":"9","group":"K","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ivory Coast","away_team_name_en":"Ecuador","home_team_id":"19","away_team_id":"20"},{"id":"12","local_date":"06/15/2026 15:00","stadium_id":"10","group":"L","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Netherlands","away_team_name_en":"Japan","home_team_id":"21","away_team_id":"22"},{"id":"13","local_date":"06/15/2026 19:00","stadium_id":"11","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Sweden","away_team_name_en":"Tunisia","home_team_id":"23","away_team_id":"24"},{"id":"14","local_date":"06/16/2026 12:00","stadium_id":"13","group":"B","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Belgium","away_team_name_en":"Egypt","home_team_id":"25","away_team_id":"26"},{"id":"15","local_date":"06/16/2026 16:00","stadium_id":"14","group":"C","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iran","away_team_name_en":"New Zealand","home_team_id":"27","away_team_id":"28"},{"id":"16","local_date":"06/16/2026 20:00","stadium_id":"15","group":"D","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Spain","away_team_name_en":"Cape Verde","home_team_id":"29","away_team_id":"30"},{"id":"17","local_date":"06/17/2026 12:00","stadium_id":"16","group":"E","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Saudi Arabia","away_team_name_en":"Uruguay","home_team_id":"31","away_team_id":"32"},{"id":"18","local_date":"06/17/2026 16:00","stadium_id":"1","group":"F","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"France","away_team_name_en":"Senegal","home_team_id":"33","away_team_id":"34"},{"id":"19","local_date":"06/17/2026 20:00","stadium_id":"2","group":"G","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iraq","away_team_name_en":"Norway","home_team_id":"35","away_team_id":"36"},{"id":"20","local_date":"06/18/2026 12:00","stadium_id":"3","group":"H","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"21","local_date":"06/18/2026 16:00","stadium_id":"4","group":"I","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Austria","away_team_name_en":"Jordan","home_team_id":"39","away_team_id":"40"},{"id":"22","local_date":"06/18/2026 20:00","stadium_id":"5","group":"J","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Portugal","away_team_name_en":"Democratic Republic of the Congo","home_team_id":"41","away_team_id":"42"},{"id":"23","local_date":"06/19/2026 12:00","stadium_id":"6","group":"K","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Uzbekistan","away_team_name_en":"Colombia","home_team_id":"43","away_team_id":"44"},{"id":"24","local_date":"06/19/2026 16:00","stadium_id":"7","group":"L","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"England","away_team_name_en":"Croatia","home_team_id":"45","away_team_id":"46"},{"id":"25","local_date":"06/19/2026 20:00","stadium_id":"8","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ghana","away_team_name_en":"Panama","home_team_id":"47","away_team_id":"48"},{"id":"26","local_date":"06/20/2026 12:00","stadium_id":"9","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Czech Republic","away_team_name_en":"Belgium","home_team_id":"4","away_team_id":"25"},{"id":"27","local_date":"06/20/2026 16:00","stadium_id":"10","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Bosnia and Herzegovina","away_team_name_en":"Iran","home_team_id":"6","away_team_id":"27"},{"id":"28","local_date":"06/20/2026 20:00","stadium_id":"11","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Paraguay","away_team_name_en":"Spain","home_team_id":"8","away_team_id":"29"},{"id":"29","local_date":"06/21/2026 12:00","stadium_id":"12","group":"E","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Switzerland","away_team_name_en":"Saudi Arabia","home_team_id":"10","away_team_id":"31"},{"id":"30","local_date":"06/21/2026 16:00","stadium_id":"13","group":"F","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Morocco","away_team_name_en":"Uzbekistan","home_team_id":"12","away_team_id":"43"},{"id":"31","local_date":"06/21/2026 20:00","stadium_id":"14","group":"G","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Scotland","away_team_name_en":"Iraq","home_team_id":"14","away_team_id":"35"},{"id":"32","local_date":"06/22/2026 12:00","stadium_id":"15","group":"H","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Algeria","away_team_name_en":"Austria","home_team_id":"38","away_team_id":"39"},{"id":"33","local_date":"06/22/2026 16:00","stadium_id":"16","group":"I","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Jordan","away_team_name_en":"Australia","home_team_id":"40","away_team_id":"15"},{"id":"34","local_date":"06/22/2026 20:00","stadium_id":"1","group":"J","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Curacao","away_team_name_en":"Portugal","home_team_id":"18","away_team_id":"41"},{"id":"35","local_date":"06/23/2026 12:00","stadium_id":"2","group":"K","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Colombia","away_team_name_en":"Ivory Coast","home_team_id":"44","away_team_id":"19"},{"id":"36","local_date":"06/23/2026 16:00","stadium_id":"3","group":"L","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Croatia","away_team_name_en":"Netherlands","home_team_id":"46","away_team_id":"21"},{"id":"37","local_date":"06/23/2026 20:00","stadium_id":"4","group":"A","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Africa","away_team_name_en":"Sweden","home_team_id":"2","away_team_id":"23"},{"id":"38","local_date":"06/24/2026 12:00","stadium_id":"5","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Egypt","away_team_name_en":"South Korea","home_team_id":"26","away_team_id":"3"},{"id":"39","local_date":"06/24/2026 16:00","stadium_id":"6","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"New Zealand","away_team_name_en":"Canada","home_team_id":"28","away_team_id":"5"},{"id":"40","local_date":"06/24/2026 20:00","stadium_id":"7","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Cape Verde","away_team_name_en":"United States","home_team_id":"30","away_team_id":"7"},{"id":"41","local_date":"06/25/2026 12:00","stadium_id":"8","group":"E","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Uruguay","away_team_name_en":"Qatar","home_team_id":"32","away_team_id":"9"},{"id":"42","local_date":"06/25/2026 16:00","stadium_id":"9","group":"F","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Senegal","away_team_name_en":"Brazil","home_team_id":"34","away_team_id":"11"},{"id":"43","local_date":"06/25/2026 20:00","stadium_id":"10","group":"G","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Norway","away_team_name_en":"Haiti","home_team_id":"36","away_team_id":"13"},{"id":"44","local_date":"06/26/2026 12:00","stadium_id":"11","group":"H","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"45","local_date":"06/26/2026 16:00","stadium_id":"12","group":"I","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Turkey","away_team_name_en":"Jordan","home_team_id":"16","away_team_id":"40"},{"id":"46","local_date":"06/26/2026 20:00","stadium_id":"13","group":"J","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Democratic Republic of the Congo","away_team_name_en":"Germany","home_team_id":"42","away_team_id":"17"},{"id":"47","local_date":"06/27/2026 12:00","stadium_id":"14","group":"K","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ecuador","away_team_name_en":"Colombia","home_team_id":"20","away_team_id":"44"},{"id":"48","local_date":"06/27/2026 16:00","stadium_id":"15","group":"L","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Japan","away_team_name_en":"England","home_team_id":"22","away_team_id":"45"},{"id":"49","local_date":"06/27/2026 20:00","stadium_id":"16","group":"A","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Panama","away_team_name_en":"Mexico","home_team_id":"48","away_team_id":"1"},{"id":"50","local_date":"06/28/2026 12:00","stadium_id":"1","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Tunisia","away_team_name_en":"Czech Republic","home_team_id":"24","away_team_id":"4"},{"id":"51","local_date":"06/28/2026 16:00","stadium_id":"2","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iran","away_team_name_en":"New Zealand","home_team_id":"27","away_team_id":"28"},{"id":"52","local_date":"06/28/2026 20:00","stadium_id":"3","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Spain","away_team_name_en":"Paraguay","home_team_id":"29","away_team_id":"8"},{"id":"53","local_date":"06/29/2026 12:00","stadium_id":"4","group":"E","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Qatar","away_team_name_en":"Saudi Arabia","home_team_id":"9","away_team_id":"31"},{"id":"54","local_date":"06/29/2026 12:00","stadium_id":"5","group":"E","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Switzerland","away_team_name_en":"Uruguay","home_team_id":"10","away_team_id":"32"},{"id":"55","local_date":"06/29/2026 20:00","stadium_id":"6","group":"F","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Brazil","away_team_name_en":"Senegal","home_team_id":"11","away_team_id":"34"},{"id":"56","local_date":"06/29/2026 20:00","stadium_id":"7","group":"F","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Morocco","away_team_name_en":"Uzbekistan","home_team_id":"12","away_team_id":"43"},{"id":"57","local_date":"06/30/2026 12:00","stadium_id":"8","group":"G","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Scotland","away_team_name_en":"Haiti","home_team_id":"14","away_team_id":"13"},{"id":"58","local_date":"06/30/2026 12:00","stadium_id":"9","group":"G","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Norway","away_team_name_en":"Iraq","home_team_id":"36","away_team_id":"35"},{"id":"59","local_date":"06/30/2026 20:00","stadium_id":"10","group":"H","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"60","local_date":"06/30/2026 20:00","stadium_id":"11","group":"H","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Austria","away_team_name_en":"Algeria","home_team_id":"39","away_team_id":"38"},{"id":"61","local_date":"07/01/2026 12:00","stadium_id":"12","group":"I","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Australia","away_team_name_en":"Jordan","home_team_id":"15","away_team_id":"40"},{"id":"62","local_date":"07/01/2026 12:00","stadium_id":"13","group":"I","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Turkey","away_team_name_en":"Austria","home_team_id":"16","away_team_id":"39"},{"id":"63","local_date":"07/01/2026 20:00","stadium_id":"14","group":"J","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Germany","away_team_name_en":"Portugal","home_team_id":"17","away_team_id":"41"},{"id":"64","local_date":"07/01/2026 20:00","stadium_id":"15","group":"J","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Curacao","away_team_name_en":"Democratic Republic of the Congo","home_team_id":"18","away_team_id":"42"},{"id":"65","local_date":"07/02/2026 12:00","stadium_id":"16","group":"K","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ivory Coast","away_team_name_en":"Colombia","home_team_id":"19","away_team_id":"44"},{"id":"66","local_date":"07/02/2026 12:00","stadium_id":"1","group":"K","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ecuador","away_team_name_en":"Uzbekistan","home_team_id":"20","away_team_id":"43"},{"id":"67","local_date":"07/02/2026 20:00","stadium_id":"2","group":"L","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Netherlands","away_team_name_en":"England","home_team_id":"21","away_team_id":"45"},{"id":"68","local_date":"07/02/2026 20:00","stadium_id":"3","group":"L","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Japan","away_team_name_en":"Croatia","home_team_id":"22","away_team_id":"46"},{"id":"69","local_date":"07/03/2026 12:00","stadium_id":"4","group":"A","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Mexico","away_team_name_en":"Ghana","home_team_id":"1","away_team_id":"47"},{"id":"70","local_date":"07/03/2026 12:00","stadium_id":"5","group":"A","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Panama","away_team_name_en":"South Africa","home_team_id":"48","away_team_id":"2"},{"id":"71","local_date":"07/03/2026 20:00","stadium_id":"6","group":"B","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Korea","away_team_name_en":"Tunisia","home_team_id":"3","away_team_id":"24"},{"id":"72","local_date":"07/03/2026 20:00","stadium_id":"7","group":"B","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Belgium","away_team_name_en":"Egypt","home_team_id":"25","away_team_id":"26"},{"id":"73","local_date":"07/04/2026 15:00","stadium_id":"16","group":"","type":"r32","matchday":"4","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"2A","away_team_name_en":"2B","home_team_id":"0","away_team_id":"0"},{"id":"104","local_date":"08/02/2026 15:00","stadium_id":"11","group":"","type":"final","matchday":"9","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W101","away_team_name_en":"W102","home_team_id":"0","away_team_id":"0"}]'
)


def _fallback_games() -> list[dict]:
    normalized = []
    for i, g in enumerate(_SEED_GAMES_RAW):
        try:
            normalized.append(_normalize_game(g, i))
        except Exception as exc:
            logger.warning(f"Fallback: error id={g.get('id')}: {exc}")
    logger.info(f"Fallback seed: {len(normalized)} partidos")
    return normalized


# ─── Fetch externo ────────────────────────────────────────────────────────────

def _fetch_external() -> list[dict]:
    raw_json = _hacer_request(EXTERNAL_API_URL)
    if isinstance(raw_json, list):
        games_raw = raw_json
    elif isinstance(raw_json, dict):
        games_raw = (raw_json.get("games") or raw_json.get("data")
                     or raw_json.get("matches") or raw_json.get("results") or [])
    else:
        games_raw = []

    normalized, skipped = [], 0
    for i, g in enumerate(games_raw):
        try:
            normalized.append(_normalize_game(g, i))
        except Exception as exc:
            skipped += 1
            logger.warning(f"_normalize_game skipped id={g.get('id','?')}: {exc}")
    if skipped:
        logger.warning(f"Fetch: {skipped} partidos descartados")
    logger.info(f"Fetch exitosa — {len(normalized)} partidos")
    return normalized


# ─── Helpers de filtrado ──────────────────────────────────────────────────────

def _game_is_live(g: dict) -> bool:
    return g.get("estado") == "en_curso"

def _game_is_today(g: dict) -> bool:
    iso = g.get("fecha_iso")
    if iso:
        d = _iso_to_col_date(iso)
        if d:
            return d == _today_col()
    return False

def _game_is_upcoming(g: dict) -> bool:
    iso = g.get("fecha_iso")
    if iso:
        d = _iso_to_col_date(iso)
        if d:
            return d > _today_col()
    return g.get("estado") == "programado" and not _game_is_today(g)

def _dynamic_ttl(games: list[dict]) -> int:
    if any(_game_is_live(g) for g in games):
        return _TTL_LIVE
    if any(_game_is_today(g) for g in games):
        return _TTL_HOY
    return _TTL_NORMAL


# ─── get_all_games ────────────────────────────────────────────────────────────

def get_all_games(force_refresh: bool = False) -> tuple[list[dict], str]:
    if not force_refresh:
        cached = _cache.get("all_games")
        if cached is not None:
            return cached, "cache"

    with _fetch_lock:
        cached = _cache.get("all_games")
        if cached is not None and not force_refresh:
            return cached, "cache"

        if not _teams_loaded:
            _cargar_equipos()

        try:
            games = _fetch_external()
            ttl   = _dynamic_ttl(games)
            _cache.set("all_games", games, ttl=ttl)
            logger.info(f"Caché actualizado — TTL={ttl}s, partidos={len(games)}")
            return games, "external"
        except Exception as exc:
            # worldcup26.ir no es accesible desde Render (IP bloqueada).
            # El front obtiene datos frescos directamente desde el navegador.
            # TTL largo para no spamear logs con el mismo error cada 30s.
            logger.warning(f"worldcup26.ir inaccesible desde servidor: {exc}. "
                           f"Usando seed (el front obtiene datos en vivo directamente).")
            games = _fallback_games()
            _cache.set("all_games", games, ttl=3600)
            return games, "fallback"


# ─── API pública — partidos ───────────────────────────────────────────────────

def get_partidos_hoy() -> tuple[list[dict], str]:
    games, source = get_all_games()
    hoy = [g for g in games if _game_is_today(g)]
    def _prio(g):
        e = g.get("estado", "")
        return (0 if e == "en_curso" else 1 if e == "programado" else 2,
                g.get("fecha_iso") or "")
    hoy.sort(key=_prio)
    return hoy, source


def get_en_vivo() -> tuple[list[dict], str]:
    games, source = get_all_games()
    live = [g for g in games if _game_is_live(g)]
    if live and source == "cache":
        games, source = get_all_games(force_refresh=True)
        live = [g for g in games if _game_is_live(g)]
    return live, source


def get_proximos(limit: int = 10) -> tuple[list[dict], str]:
    games, source = get_all_games()
    upcoming = sorted(
        [g for g in games if _game_is_upcoming(g)],
        key=lambda g: g.get("fecha_iso") or ""
    )
    return upcoming[:limit], source


def get_partido(partido_id: int) -> tuple[Optional[dict], str]:
    games, source = get_all_games()
    match = next((g for g in games if g["id"] == partido_id), None)
    return match, source


def get_live_ttl() -> int:
    cached = _cache.get("all_games")
    if cached is None:
        return _TTL_NORMAL
    return _dynamic_ttl(cached)


def hay_partidos_en_vivo() -> bool:
    cached = _cache.get("all_games")
    if cached is None:
        return False
    return any(_game_is_live(g) for g in cached)


# ─── API pública — grupos y tabla FIFA ───────────────────────────────────────

def _calcular_tabla_grupo(letra: str, games: list[dict]) -> list[dict]:
    """
    Calcula la tabla FIFA para un grupo a partir de los partidos finalizados.
    Retorna lista de equipos ordenados por: PTS → DG → GF → nombre.
    """
    partidos_grupo = [
        g for g in games
        if g.get("grupo") == letra and g.get("fase") == "Grupos"
    ]

    # Recopilar equipos únicos en el grupo
    equipos: dict[str, dict] = {}
    for g in partidos_grupo:
        for nombre, codigo in [
            (g["local"], g["codigo_local"]),
            (g["visitante"], g["codigo_visit"])
        ]:
            if nombre and nombre != "TBD" and nombre not in equipos:
                equipos[nombre] = {
                    "nombre":  nombre,
                    "codigo":  codigo,
                    "pj": 0, "pg": 0, "pe": 0, "pp": 0,
                    "gf": 0, "gc": 0, "dg": 0, "pts": 0,
                }

    # Computar estadísticas con partidos finalizados
    for g in partidos_grupo:
        if not g.get("bloqueado"):
            continue
        gl = g.get("goles_local")
        gv = g.get("goles_visit")
        if gl is None or gv is None:
            continue
        loc = g["local"]
        vis = g["visitante"]
        if loc not in equipos or vis not in equipos:
            continue

        gl, gv = int(gl), int(gv)

        equipos[loc]["pj"] += 1
        equipos[loc]["gf"] += gl
        equipos[loc]["gc"] += gv
        equipos[vis]["pj"] += 1
        equipos[vis]["gf"] += gv
        equipos[vis]["gc"] += gl

        if gl > gv:
            equipos[loc]["pg"] += 1; equipos[loc]["pts"] += 3
            equipos[vis]["pp"] += 1
        elif gl < gv:
            equipos[vis]["pg"] += 1; equipos[vis]["pts"] += 3
            equipos[loc]["pp"] += 1
        else:
            equipos[loc]["pe"] += 1; equipos[loc]["pts"] += 1
            equipos[vis]["pe"] += 1; equipos[vis]["pts"] += 1

    for e in equipos.values():
        e["dg"] = e["gf"] - e["gc"]

    # Ordenar: pts → dg → gf → nombre
    rows = sorted(equipos.values(), key=lambda x: (
        -x["pts"], -x["dg"], -x["gf"], x["nombre"]
    ))

    # Añadir posición
    for i, r in enumerate(rows):
        r["pos"] = i + 1

    return rows


def get_groups() -> tuple[dict[str, list[dict]], str]:
    """
    Retorna {letra: [equipo_con_stats, ...]} para los 12 grupos.
    Calcula posiciones con reglas FIFA desde partidos reales.
    """
    cached = _cache.get("groups_table")
    if cached is not None:
        return cached, "cache"

    games, source = get_all_games()

    result: dict[str, list[dict]] = {}
    for letra in _GRUPOS_LETRAS:
        result[letra] = _calcular_tabla_grupo(letra, games)

    _cache.set("groups_table", result, ttl=_dynamic_ttl(games))
    return result, source


def get_group_table(letra: str) -> tuple[list[dict], str]:
    """Retorna la tabla de un solo grupo."""
    letra = letra.upper()
    if letra not in _GRUPOS_LETRAS:
        return [], "error"
    grupos, source = get_groups()
    return grupos.get(letra, []), source


def get_goals_ranking() -> tuple[list[dict], str]:
    """
    Retorna selecciones ordenadas por goles a favor (GF DESC).
    Si worldcup26.ir no tiene goleadores individuales, se usa GF por selección.
    """
    cached = _cache.get("goals_ranking")
    if cached is not None:
        return cached, "cache"

    games, source = get_all_games()

    # Acumular GF por equipo desde partidos finalizados (todas las fases)
    goles: dict[str, dict] = {}
    for g in games:
        if not g.get("bloqueado"):
            continue
        gl = g.get("goles_local")
        gv = g.get("goles_visit")
        if gl is None or gv is None:
            continue
        gl, gv = int(gl), int(gv)

        for nombre, codigo, golesf in [
            (g["local"],     g["codigo_local"], gl),
            (g["visitante"], g["codigo_visit"], gv),
        ]:
            if not nombre or nombre == "TBD":
                continue
            if nombre not in goles:
                goles[nombre] = {"nombre": nombre, "codigo": codigo, "gf": 0}
            goles[nombre]["gf"] += golesf

    ranking = sorted(goles.values(), key=lambda x: -x["gf"])
    for i, r in enumerate(ranking):
        r["pos"] = i + 1

    _cache.set("goals_ranking", ranking, ttl=_dynamic_ttl(games))
    return ranking, source


def get_qualified() -> tuple[list[dict], str]:
    """
    Detecta automáticamente 1° y 2° clasificado de cada grupo.
    Solo muestra equipos cuando el grupo tiene partidos finalizados.
    """
    cached = _cache.get("qualified")
    if cached is not None:
        return cached, "cache"

    grupos, source = get_groups()
    result = []

    for letra, equipos in grupos.items():
        if not equipos:
            continue
        # Solo incluir si hay algún partido jugado
        if all(e["pj"] == 0 for e in equipos):
            continue
        for eq in equipos[:2]:  # 1° y 2° lugar
            result.append({
                "grupo":    letra,
                "pos":      eq["pos"],
                "nombre":   eq["nombre"],
                "codigo":   eq["codigo"],
                "pts":      eq["pts"],
                "pj":       eq["pj"],
            })

    games, _ = get_all_games()
    _cache.set("qualified", result, ttl=_dynamic_ttl(games))
    return result, source


def get_stats() -> tuple[dict, str]:
    """
    Estadísticas globales del torneo calculadas desde partidos oficiales.
    """
    cached = _cache.get("stats")
    if cached is not None:
        return cached, "cache"

    games, source = get_all_games()

    equipos: dict[str, dict] = {}
    total_goles = 0
    partidos_jugados = 0

    for g in games:
        if not g.get("bloqueado"):
            continue
        gl = g.get("goles_local")
        gv = g.get("goles_visit")
        if gl is None or gv is None:
            continue
        gl, gv = int(gl), int(gv)
        total_goles += gl + gv
        partidos_jugados += 1

        for nombre, codigo, gf, gc in [
            (g["local"],     g["codigo_local"], gl, gv),
            (g["visitante"], g["codigo_visit"], gv, gl),
        ]:
            if not nombre or nombre == "TBD":
                continue
            if nombre not in equipos:
                equipos[nombre] = {
                    "nombre": nombre, "codigo": codigo,
                    "gf": 0, "gc": 0, "dg": 0,
                    "pg": 0, "pe": 0, "pp": 0, "pj": 0
                }
            e = equipos[nombre]
            e["gf"] += gf; e["gc"] += gc; e["pj"] += 1
            if gf > gc:   e["pg"] += 1
            elif gf == gc: e["pe"] += 1
            else:          e["pp"] += 1

    for e in equipos.values():
        e["dg"] = e["gf"] - e["gc"]

    if not equipos:
        stats = {
            "total_goles": 0, "partidos_jugados": 0,
            "mas_goleador": None, "menos_goleado": None,
            "mayor_diferencia": None, "mas_victorias": None,
            "mas_empates": None, "mas_derrotas": None,
        }
    else:
        lst = list(equipos.values())
        stats = {
            "total_goles":        total_goles,
            "partidos_jugados":   partidos_jugados,
            "mas_goleador":       max(lst, key=lambda x: x["gf"]),
            "menos_goleado":      min((e for e in lst if e["pj"] > 0), key=lambda x: x["gc"], default=None),
            "mayor_diferencia":   max(lst, key=lambda x: x["dg"]),
            "mas_victorias":      max(lst, key=lambda x: x["pg"]),
            "mas_empates":        max(lst, key=lambda x: x["pe"]),
            "mas_derrotas":       max(lst, key=lambda x: x["pp"]),
        }

    _cache.set("stats", stats, ttl=_dynamic_ttl(games))
    return stats, source


def invalidate_cache() -> None:
    _cache.clear()
    global _teams_loaded
    _teams_loaded = False
    logger.info("Caché invalidada manualmente")


def inject_games_from_client(games_raw: list, teams_raw: list | None = None) -> int:
    """
    Recibe datos crudos de worldcup26.ir enviados por el navegador del usuario
    (que sí puede llegar a la API externa) y los normaliza + guarda en caché.
    Esto soluciona que Render bloquee la IP del servidor hacia worldcup26.ir.
    """
    global _teams_data, _teams_loaded

    # Cargar equipos si vinieron
    if teams_raw and isinstance(teams_raw, list):
        data: dict[str, dict] = {}
        for t in teams_raw:
            tid = str(t.get("id") or t.get("_id") or "")
            if not tid:
                continue
            iso2_raw = (t.get("iso2") or "").lower().strip()
            nombre_en = t.get("name_en") or ""
            nombre_es = _NOMBRE_ES.get(iso2_raw) or _EN_ES.get(nombre_en.lower()) or nombre_en
            data[tid] = {"iso2": iso2_raw, "nombre_es": nombre_es, "nombre_en": nombre_en}
        if data:
            _teams_data = data
            _teams_loaded = True
            _cache.set("teams_data", data, ttl=3600)

    if not _teams_loaded:
        _cargar_equipos()

    normalized, skipped = [], 0
    for i, g in enumerate(games_raw):
        try:
            normalized.append(_normalize_game(g, i))
        except Exception as exc:
            skipped += 1
            logger.debug(f"inject: skipped id={g.get('id','?')}: {exc}")

    if normalized:
        ttl = _dynamic_ttl(normalized)
        _cache.set("all_games", normalized, ttl=ttl)
        # Invalida derivados para que se recalculen con datos frescos
        for key in ("groups_table", "goals_ranking", "qualified", "stats"):
            _cache.delete(key)
        logger.info(f"Caché inyectada desde cliente — {len(normalized)} partidos, TTL={ttl}s")

    return len(normalized)


# ─── Acceso a datos crudos (para integraciones externas) ─────────────────────

def get_raw_games() -> tuple[list[dict], str]:
    """
    Devuelve los partidos normalizados (mismo formato que get_all_games).
    Alias público para compatibilidad con módulos que lo importan por este nombre.
    """
    return get_all_games()


def get_raw_teams() -> tuple[dict[str, dict], str]:
    """
    Devuelve el mapa de equipos {team_id: {iso2, nombre_es, nombre_en}}.
    Carga /get/teams si no está en caché.
    """
    global _teams_loaded
    if not _teams_loaded:
        with _teams_lock:
            if not _teams_loaded:
                _cargar_equipos()
    return dict(_teams_data), "cache" if _teams_loaded else "fallback"
