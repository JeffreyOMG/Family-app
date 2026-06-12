"""
services/mundial_service.py
============================
Servicio de datos del Mundial 2026.

Flujo:
  worldcup26.ir/get/games  →  _fetch_external()  →  _cache  →  endpoints públicos

Características:
  - Caché en memoria con TTL configurable por variable de entorno.
  - Reintentos con backoff exponencial.
  - Timeout configurable.
  - Normalización de la respuesta externa a un esquema canónico.
  - Fallback a datos internos (mundial_bracket.py) si la API externa falla.
  - Logger dedicado (mundial_service).
"""

import logging
import os
import threading
import time
from datetime import datetime, date, timezone, timedelta
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen, Request
import json
import re

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

# ─── Configuración (sobreescribible con variables de entorno) ─────────────────
EXTERNAL_API_URL: str   = os.getenv("MUNDIAL_API_URL", "https://worldcup26.ir/get/games")
CACHE_TTL_SECONDS: int  = int(os.getenv("MUNDIAL_CACHE_TTL",  "120"))   # 2 min por defecto
REQUEST_TIMEOUT:   int  = int(os.getenv("MUNDIAL_TIMEOUT",    "8"))
MAX_RETRIES:       int  = int(os.getenv("MUNDIAL_RETRIES",    "3"))
RETRY_BACKOFF:   float  = float(os.getenv("MUNDIAL_BACKOFF",  "1.5"))   # multiplicador


# ─── Caché en memoria (thread-safe) ──────────────────────────────────────────
class _Cache:
    """Almacén clave-valor con TTL individual por entrada."""

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


_cache = _Cache()
_fetch_lock = threading.Lock()   # Evita thundering herd en caché fría

# ─── Esquema canónico de un partido ──────────────────────────────────────────
# Cada partido normalizado sigue este formato independiente de la fuente:
#
# {
#   "id":             int,
#   "fase":           str,          # "Grupos" | "Dieciseisavos" | …
#   "grupo":          str | None,   # "A" … "L" (solo grupos)
#   "local":          str,
#   "visitante":      str,
#   "codigo_local":   str,          # código bandera ISO 2
#   "codigo_visit":   str,
#   "goles_local":    int | None,
#   "goles_visit":    int | None,
#   "bloqueado":      bool,         # True si el resultado es oficial/cerrado
#   "fecha_texto":    str,          # "Dom. 28 jun, 15:00"
#   "fecha_iso":      str | None,   # "2026-06-28T15:00:00" cuando disponible
#   "sede":           str,
#   "estado":         str,          # "programado" | "en_curso" | "finalizado"
# }


# ─── Normalización de la API externa ─────────────────────────────────────────

# Mapa de variantes de nombre a código ISO-3166-1 alpha-2
_COUNTRY_CODE: dict[str, str] = {
    # América
    "united states":   "us", "usa":           "us", "estados unidos": "us",
    "canada":          "ca", "mexico":        "mx", "méxico":         "mx",
    "brazil":          "br", "brasil":        "br", "argentina":      "ar",
    "colombia":        "co", "uruguay":       "uy", "chile":          "cl",
    "ecuador":         "ec", "peru":          "pe", "perú":           "pe",
    "venezuela":       "ve", "paraguay":      "py", "bolivia":        "bo",
    "costa rica":      "cr", "honduras":      "hn", "panama":         "pa",
    "panamá":          "pa", "jamaica":       "jm", "trinidad":       "tt",
    "haiti":           "ht", "haití":         "ht",
    # Europa
    "germany":         "de", "alemania":      "de", "france":         "fr",
    "francia":         "fr", "spain":         "es", "españa":         "es",
    "england":         "gb-eng", "portugal": "pt", "netherlands":    "nl",
    "holanda":         "nl", "italy":         "it", "italia":         "it",
    "belgium":         "be", "bélgica":       "be", "croatia":        "hr",
    "croacia":         "hr", "serbia":        "rs", "denmark":        "dk",
    "dinamarca":       "dk", "switzerland":   "ch", "suiza":          "ch",
    "poland":          "pl", "polonia":       "pl", "ukraine":        "ua",
    "ucrania":         "ua", "austria":       "at", "sweden":         "se",
    "suecia":          "se", "turkey":        "tr", "turquía":        "tr",
    "scotland":        "gb-sct", "wales":     "gb-wls", "czechia":    "cz",
    "czech republic":  "cz", "slovakia":     "sk", "hungary":        "hu",
    "hungría":         "hu", "romania":      "ro", "rumanía":        "ro",
    "albania":         "al", "greece":       "gr", "grecia":         "gr",
    "norway":          "no", "noruega":      "no",
    "bosnia and herzegovina": "ba", "bosnia":  "ba", "bosnia y herzegovina": "ba",
    "cape verde": "cv", "cabo verde": "cv", "curacao": "cw", "curaçao": "cw", "curazao": "cw",
    # África
    "morocco":         "ma", "marruecos":     "ma", "senegal":        "sn",
    "nigeria":         "ng", "cameroon":      "cm", "camerún":        "cm",
    "egypt":           "eg", "egipto":        "eg", "ghana":          "gh",
    "ivory coast":     "ci", "cote d'ivoire": "ci", "mali":          "ml",
    "south africa":    "za", "tunisia":       "tn", "túnez":          "tn",
    "algeria":         "dz", "argelia":       "dz", "dr congo":       "cd",
    # Asia
    "japan":           "jp", "japón":         "jp", "south korea":    "kr",
    "corea del sur":   "kr", "iran":          "ir", "iraq":           "iq",
    "saudi arabia":    "sa", "arabia saudita": "sa", "australia":     "au",
    "australia/nz":    "au", "new zealand":   "nz", "china":          "cn",
    "china pr":        "cn", "indonesia":     "id", "vietnam":        "vn",
    "uzbekistan":      "uz", "uzbekistán":    "uz", "thailand":       "th",
    "india":           "in", "qatar":         "qa", "bahrain":        "bh",
    "jordan":          "jo", "kuwait":        "kw", "oman":           "om",
    "yemen":           "ye",
    # Oceanía
    "fiji":            "fj",
}

_MONTH_ES = {
    "jan": "ene", "feb": "feb", "mar": "mar", "apr": "abr",
    "may": "may", "jun": "jun", "jul": "jul", "aug": "ago",
    "sep": "sep", "oct": "oct", "nov": "nov", "dec": "dic",
    "january":   "ene", "february": "feb", "march":    "mar",
    "april":     "abr", "june":     "jun", "july":     "jul",
    "august":    "ago", "september":"sep", "october":  "oct",
    "november":  "nov", "december": "dic",
}

_DAY_ES = {
    "monday": "Lun.", "tuesday": "Mar.", "wednesday": "Mié.",
    "thursday": "Jue.", "friday": "Vie.", "saturday": "Sáb.", "sunday": "Dom.",
    "mon": "Lun.", "tue": "Mar.", "wed": "Mié.", "thu": "Jue.",
    "fri": "Vie.", "sat": "Sáb.", "sun": "Dom.",
}

_STATUS_MAP = {
    "scheduled":    "programado",
    "upcoming":     "programado",
    "not started":  "programado",
    "live":         "en_curso",
    "in progress":  "en_curso",
    "halftime":     "en_curso",
    "finished":     "finalizado",
    "full-time":    "finalizado",
    "ft":           "finalizado",
    "aet":          "finalizado",
    "penalties":    "finalizado",
}

_PHASE_MAP = {
    "group stage":       "Grupos",
    "group":             "Grupos",
    "round of 32":       "Dieciseisavos",
    "round of 16":       "Octavos",
    "quarter-final":     "Cuartos",
    "quarterfinal":      "Cuartos",
    "semi-final":        "Semifinal",
    "semifinal":         "Semifinal",
    "third place":       "Tercer puesto",
    "third-place play-off": "Tercer puesto",
    "final":             "Final",
}


# ─── Offsets horarios de los 16 estadios del Mundial 2026 (UTC, junio/julio) ──
# IMPORTANTE: "local_date" de worldcup26.ir es la HORA LOCAL DEL ESTADIO,
# SIN indicador de zona — NO es UTC. Para convertir correctamente a
# Colombia/Perú (UTC-5) hay que restar el offset real de cada estadio.
# En junio-julio 2026: EE.UU./Canadá están en horario de verano (DST);
# México NO observa DST.
#   ET (Nueva York, Filadelfia, Atlanta, Miami, Boston)        → UTC-4
#   CT (Dallas, Houston, Kansas City, Monterrey*, Guadalajara*) → UTC-5
#       (*México: CT real es UTC-6, pero México no aplica DST,
#        así que en verano EE.UU.-CT(-5) ≠ México-CT(-6))
#   MT (Arizona/Denver — no aplica aquí)                        → UTC-6
#   PT (Los Ángeles, Seattle, San Francisco, Vancouver)         → UTC-7
#   México Central (CDMX, Guadalajara, Monterrey)               → UTC-6 (todo el año)
_STADIUM_UTC_OFFSET: dict[str, int] = {
    # ── Estados Unidos ──
    "MetLife Stadium":            -4,  # East Rutherford, NJ (ET, DST)
    "AT&T Stadium":                -5,  # Dallas, TX (CT, DST)
    "SoFi Stadium":                -7,  # Los Angeles, CA (PT, DST)
    "Hard Rock Stadium":           -4,  # Miami, FL (ET, DST)
    "Mercedes-Benz Stadium":       -4,  # Atlanta, GA (ET, DST)
    "NRG Stadium":                 -5,  # Houston, TX (CT, DST)
    "Lincoln Financial Field":     -4,  # Philadelphia, PA (ET, DST)
    "Levi's Stadium":              -7,  # San Francisco/Santa Clara, CA (PT, DST)
    "Lumen Field":                 -7,  # Seattle, WA (PT, DST)
    "Gillette Stadium":            -4,  # Boston/Foxborough, MA (ET, DST)
    "Arrowhead Stadium":           -5,  # Kansas City, MO (CT, DST)
    # ── México (sin DST) ──
    "Estadio Azteca":              -6,  # Ciudad de México
    "Estadio Akron":               -6,  # Guadalajara
    "Estadio BBVA":                -6,  # Monterrey
    # ── Canadá ──
    "BC Place":                    -7,  # Vancouver, BC (PT, DST)
    "BMO Field":                   -4,  # Toronto, ON (ET, DST)
}

# Mapa stadium_id (worldcup26.ir) → nombre de estadio. Orden documentado en
# el README del proyecto (11 EE.UU. + 3 México + 2 Canadá = 16 sedes).
_STADIUM_ID_NAME: dict[str, str] = {
    "1":  "Estadio Azteca",
    "2":  "Estadio Akron",
    "3":  "Estadio BBVA",
    "4":  "BC Place",
    "5":  "BMO Field",
    "6":  "MetLife Stadium",
    "7":  "AT&T Stadium",
    "8":  "SoFi Stadium",
    "9":  "Hard Rock Stadium",
    "10": "Mercedes-Benz Stadium",
    "11": "NRG Stadium",
    "12": "Lincoln Financial Field",
    "13": "Levi's Stadium",
    "14": "Lumen Field",
    "15": "Gillette Stadium",
    "16": "Arrowhead Stadium",
}



def _country_code(name: str) -> str:
    return _COUNTRY_CODE.get(name.strip().lower(), "xx")


def _normalize_status(raw: str) -> str:
    return _STATUS_MAP.get(raw.strip().lower(), "programado")


def _normalize_phase(raw: str) -> str:
    return _PHASE_MAP.get(raw.strip().lower(), raw.strip())


def _parse_iso(raw: str) -> Optional[str]:
    """Devuelve ISO-8601 si el string tiene formato reconocible, else None.
    Preserva el sufijo Z (UTC) si está presente."""
    raw = raw.strip()
    has_z = raw.endswith("Z")
    clean = raw.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            result = datetime.strptime(clean, fmt).isoformat()
            return result + "Z" if has_z else result
        except ValueError:
            continue
    return None


def _to_fecha_texto(iso: Optional[str]) -> str:
    """Convierte ISO a texto español estilo 'Dom. 28 jun, 15:00'."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        days_es = ["Lun.", "Mar.", "Mié.", "Jue.", "Vie.", "Sáb.", "Dom."]
        months_es = ["ene", "feb", "mar", "abr", "may", "jun",
                     "jul", "ago", "sep", "oct", "nov", "dic"]
        # weekday(): 0=Lun … 6=Dom — coincide exactamente con days_es
        day_name = days_es[dt.weekday()]
        month = months_es[dt.month - 1]
        return f"{day_name} {dt.day} {month}, {dt.strftime('%H:%M')}"
    except Exception:
        return iso


def _normalize_game(raw: dict, idx: int = 0) -> dict:
    """Transforma un objeto de la API externa al esquema canónico.

    Compatible con worldcup26.ir que usa:
      - home_team_name_en / away_team_name_en  para nombres
      - home_team_id / away_team_id            para IDs de equipo
      - home_score / away_score                para marcador (string "0")
      - local_date = "06/11/2026 13:00"        para fecha
      - time_elapsed = "notstarted"/"halftime"/"fulltime"
      - finished = "TRUE"/"FALSE"              para estado
      - group = "A" … "L"                      para grupo
      - type = "group"/"r32"/"r16"/"qf"/"sf"/"final"
    """

    # ── Equipos ──────────────────────────────────────────────────────────────
    home = (raw.get("home_team") or raw.get("home") or {})
    away = (raw.get("away_team") or raw.get("away") or {})

    if isinstance(home, str):
        home = {"name": home}
    if isinstance(away, str):
        away = {"name": away}

    # worldcup26.ir usa home_team_name_en / away_team_name_en directamente
    local     = (raw.get("home_team_name_en") or home.get("name") or home.get("team") or "TBD").strip()
    visitante = (raw.get("away_team_name_en") or away.get("name") or away.get("team") or "TBD").strip()
    cod_l     = home.get("code") or home.get("flag") or _country_code(local)
    cod_v     = away.get("code") or away.get("flag") or _country_code(visitante)

    # ── Marcador ─────────────────────────────────────────────────────────────
    score = raw.get("score") or raw.get("scores") or {}
    if isinstance(score, dict):
        gl = score.get("home") if score.get("home") is not None else score.get("home_score")
        gv = score.get("away") if score.get("away") is not None else score.get("away_score")
    else:
        # worldcup26.ir: home_score / away_score como strings ("0")
        # IMPORTANTE: usar 'is not None' — no 'or' — porque "0" es falsy
        hs = raw.get("home_score")
        ga = raw.get("away_score")
        gl = hs if hs is not None else raw.get("goals_home")
        gv = ga if ga is not None else raw.get("goals_away")

    try:
        gl = int(gl) if gl is not None else None
    except (TypeError, ValueError):
        gl = None
    try:
        gv = int(gv) if gv is not None else None
    except (TypeError, ValueError):
        gv = None

    # ── Estado — worldcup26.ir usa time_elapsed + finished ───────────────────
    time_elapsed = str(raw.get("time_elapsed") or "").lower().strip()
    finished_raw = str(raw.get("finished") or "").upper().strip()

    if finished_raw == "TRUE":
        estado = "finalizado"
    elif time_elapsed in ("halftime", "first half", "second half", "extra time",
                          "penalty", "in progress"):
        estado = "en_curso"
    elif time_elapsed and time_elapsed not in ("notstarted", "not started", ""):
        # Cualquier otro valor no vacío y no "notstarted" → en curso
        estado = "en_curso"
    else:
        # Fallback: campo status estándar
        status_raw = str(raw.get("status") or raw.get("state") or "scheduled")
        estado = _normalize_status(status_raw)

    bloqueado = estado == "finalizado"

    # ── Fase / tipo ───────────────────────────────────────────────────────────
    # worldcup26.ir usa "type": "group" | "r32" | "r16" | "qf" | "sf" | "third" | "final"
    type_raw  = str(raw.get("type") or "").lower()
    phase_raw = str(raw.get("round") or raw.get("phase") or raw.get("stage") or "")

    _TYPE_MAP = {
        "group":  "Grupos",
        "r32":    "Dieciseisavos",
        "r16":    "Octavos",
        "qf":     "Cuartos",
        "sf":     "Semifinal",
        "third":  "Tercer puesto",
        "3rd":    "Tercer puesto",
        "final":  "Final",
    }
    fase = _TYPE_MAP.get(type_raw) or _normalize_phase(phase_raw) or "Grupos"

    grupo = None
    # worldcup26.ir: grupo viene en campo "group" = "A"…"L" o "R32", "R16", etc.
    grupo_raw = str(raw.get("group") or raw.get("group_name") or "")
    if fase == "Grupos":
        m = re.search(r"[A-L]", grupo_raw.upper())
        grupo = m.group(0) if m else None

    # ── Fecha — worldcup26.ir usa local_date = "MM/DD/YYYY HH:MM" ────────────
    # NOTA: worldcup26.ir devuelve local_date en hora local del estadio (ET/CT).
    # Para que el frontend pueda convertir a zona horaria del usuario,
    # guardamos la ISO tal cual (sin indicador de zona) y el frontend la trata como UTC
    # sumándole 'Z' para que toLocaleTimeString pueda aplicar timeZone: 'America/Bogota'.
    # Esto funciona porque la app fuerza zona Bogotá en el frontend.
    date_raw = str(
        raw.get("local_date") or          # worldcup26.ir: "06/11/2026 13:00"
        raw.get("date") or
        raw.get("datetime") or
        raw.get("kickoff") or
        ""
    )
    time_raw = str(raw.get("time") or raw.get("kickoff_time") or "")

    # Normalizar "MM/DD/YYYY HH:MM" → fecha/hora local del estadio (sin TZ aún)
    stadium_local_dt: Optional[datetime] = None
    if date_raw and "/" in date_raw and "T" not in date_raw:
        try:
            parts = date_raw.strip().split(" ")
            date_part = parts[0]   # "06/11/2026"
            time_part = parts[1] if len(parts) > 1 else (time_raw or "00:00")
            md = date_part.split("/")
            if len(md) == 3:
                # MM/DD/YYYY HH:MM → hora LOCAL del estadio (NO es UTC todavía)
                naive_str = f"{md[2]}-{md[0].zfill(2)}-{md[1].zfill(2)}T{time_part}:00"
                stadium_local_dt = datetime.strptime(naive_str, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            stadium_local_dt = None

    if stadium_local_dt is not None:
        # ── Convertir hora local del estadio → UTC real usando el offset
        #    del estadio (ver _STADIUM_UTC_OFFSET). Esto es lo que estaba
        #    fallando: antes se le pegaba 'Z' directamente a la hora del
        #    estadio, tratándola como si ya fuera UTC.
        stadium_id  = str(raw.get("stadium_id") or "")
        stadium_nom = _STADIUM_ID_NAME.get(stadium_id)
        offset_h    = _STADIUM_UTC_OFFSET.get(stadium_nom, -6)  # fallback: México Central
        utc_dt = stadium_local_dt - timedelta(hours=offset_h)
        fecha_iso = utc_dt.isoformat() + "Z"
    else:
        if date_raw and time_raw and "T" not in date_raw and "/" not in date_raw:
            date_raw = f"{date_raw}T{time_raw}"
        # Si ya tiene Z o indicador de zona, _parse_iso lo maneja tal cual.
        # Si no tiene zona y no pudimos determinar el estadio, se asume UTC
        # (mejor esfuerzo; puede no coincidir exactamente con Colombia/Perú).
        if date_raw and not date_raw.endswith("Z") and "+" not in date_raw:
            date_raw = date_raw + "Z"
        fecha_iso = _parse_iso(date_raw)


    # Texto legible en español (si hay)
    fecha_texto_raw = str(raw.get("fecha_texto") or raw.get("date_text") or "")
    fecha_texto     = fecha_texto_raw if fecha_texto_raw else _to_fecha_texto(fecha_iso)

    # ── Sede — worldcup26.ir no tiene nombre de estadio en /get/games ────────
    venue = raw.get("venue") or raw.get("stadium") or raw.get("city") or ""
    if isinstance(venue, dict):
        venue = venue.get("name") or venue.get("stadium") or ""
    sede = str(venue).strip()

    # is not None guard: id=0 is falsy but valid; must not fall through to match_id
    _id_raw = raw.get("id") if raw.get("id") is not None else raw.get("match_id")
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
        "bloqueado":    bloqueado,
        "fecha_texto":  fecha_texto,
        "fecha_iso":    fecha_iso,
        "sede":         sede,
        "estado":       estado,
    }


# ─── Fuente de fallback: mundial_bracket.py ──────────────────────────────────

def _fallback_games() -> list[dict]:
    """
    Genera una lista canónica a partir de los datos hardcodeados locales.
    Solo contiene partidos de eliminación (sin equipos reales aún, solo slots).
    Se usa cuando la API externa no está disponible.
    """
    try:
        # mundial_bracket.py debe estar en el root del proyecto (mismo nivel que app.py).
        # Flask añade el CWD al sys.path, por lo que funciona en runtime.
        # En tests unitarios aislados puede fallar; ese caso retorna lista vacía.
        from mundial_bracket import (
            DIECISEISAVOS, OCTAVOS, CUARTOS, SEMIFINALES, TERCER_PUESTO, FINAL
        )
    except ImportError as exc:
        logger.error(
            "mundial_bracket.py no importable — fallback retorna lista vacía. "
            f"Asegúrate de que existe en el root del proyecto. Detalle: {exc}"
        )
        return []

    games: list[dict] = []

    phase_data = [
        (DIECISEISAVOS,  "Dieciseisavos"),
        (OCTAVOS,        "Octavos"),
        (CUARTOS,        "Cuartos"),
        (SEMIFINALES,    "Semifinal"),
        ([TERCER_PUESTO], "Tercer puesto"),
        ([FINAL],         "Final"),
    ]

    for partidos, fase in phase_data:
        for p in partidos:
            games.append({
                "id":           p["id"],
                "fase":         fase,
                "grupo":        None,
                "local":        p.get("slot_l") or p.get("dep1") or "TBD",
                "visitante":    p.get("slot_v") or p.get("dep2") or "TBD",
                "codigo_local": "xx",
                "codigo_visit": "xx",
                "goles_local":  None,
                "goles_visit":  None,
                "bloqueado":    False,
                "fecha_texto":  p.get("fecha", ""),
                "fecha_iso":    None,
                "sede":         p.get("sede", ""),
                "estado":       "programado",
            })

    return games


# ─── Obtención y caché de datos externos ─────────────────────────────────────

def _fetch_external() -> list[dict]:
    """
    Llama a EXTERNAL_API_URL con reintentos y timeout.
    Devuelve lista normalizada al esquema canónico.
    Lanza RuntimeError si todos los intentos fallan.
    """
    last_exc: Exception = RuntimeError("never tried")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Fetch externa intento {attempt}/{MAX_RETRIES} → {EXTERNAL_API_URL}")
            req = Request(
                EXTERNAL_API_URL,
                headers={
                    "User-Agent":  "FamiliaApp/1.0 Mundial2026",
                    "Accept":      "application/json",
                    "Accept-Language": "es,en;q=0.8",
                },
            )
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw_bytes = resp.read()

            raw_json = json.loads(raw_bytes.decode("utf-8", errors="replace"))

            # La API puede devolver lista directa o wrapper {"games": [...], "data": [...]}
            if isinstance(raw_json, list):
                games_raw = raw_json
            elif isinstance(raw_json, dict):
                games_raw = (
                    raw_json.get("games")
                    or raw_json.get("data")
                    or raw_json.get("matches")
                    or raw_json.get("results")
                    or []
                )
            else:
                games_raw = []

            normalized = [_normalize_game(g, i) for i, g in enumerate(games_raw)]
            logger.info(f"Fetch exitosa — {len(normalized)} partidos obtenidos")
            return normalized

        except (URLError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF ** (attempt - 1)
            logger.warning(
                f"Intento {attempt} fallido ({type(exc).__name__}: {exc}). "
                f"{'Reintentando en %.1fs…' % wait if attempt < MAX_RETRIES else 'Sin más reintentos.'}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(wait)

    raise RuntimeError(f"API externa no disponible tras {MAX_RETRIES} intentos: {last_exc}")


def get_all_games(force_refresh: bool = False) -> tuple[list[dict], str]:
    """
    Devuelve (lista_partidos, fuente).
    fuente ∈ {"cache", "external", "fallback"}

    Estrategia:
      1. Caché en memoria con TTL.
      2. API externa con reintentos (protegida por _fetch_lock para evitar
         thundering herd: si N requests llegan con caché fría, solo uno
         hace el fetch externo; los demás esperan y usan el resultado).
      3. Fallback a datos locales (mundial_bracket.py).
    """
    if not force_refresh:
        cached = _cache.get("all_games")
        if cached is not None:
            logger.debug("Cache hit — all_games")
            return cached, "cache"

    with _fetch_lock:
        # Segunda verificación dentro del lock: otro hilo puede haber
        # completado el fetch mientras esperábamos.
        cached = _cache.get("all_games")
        if cached is not None and not force_refresh:
            logger.debug("Cache hit (post-lock) — all_games")
            return cached, "cache"

        try:
            games = _fetch_external()
            _cache.set("all_games", games, ttl=CACHE_TTL_SECONDS)
            return games, "external"
        except RuntimeError as exc:
            logger.error(f"Usando fallback local. Razón: {exc}")
            games = _fallback_games()
            # Caché más corta para que se reintente pronto
            _cache.set("all_games", games, ttl=30)
            return games, "fallback"


# ─── Helpers de filtrado ──────────────────────────────────────────────────────

_TZ_BOGOTA = timezone(timedelta(hours=-5))  # Colombia / Perú (sin DST)


def _today_str() -> str:
    """Fecha actual en zona Colombia/Perú (UTC-5), no la fecha local del servidor."""
    return datetime.now(_TZ_BOGOTA).date().isoformat()


def _fecha_iso_to_bogota_date(iso: str) -> Optional[str]:
    """Convierte un fecha_iso (en UTC) a la fecha (YYYY-MM-DD) en zona Bogotá/Lima."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ_BOGOTA).date().isoformat()
    except Exception:
        return None


def _game_is_today(game: dict) -> bool:
    iso = game.get("fecha_iso")
    if iso:
        bog_date = _fecha_iso_to_bogota_date(iso)
        if bog_date is not None:
            return bog_date == _today_str()
    # Heurística sobre fecha_texto en español ("Dom. 28 jun, 15:00")
    texto = game.get("fecha_texto", "")
    today = datetime.now(_TZ_BOGOTA).date()
    months_es = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"]
    m = re.search(r"(\d{1,2})\s+([a-záéíóú]+)", texto.lower())
    if m:
        try:
            day   = int(m.group(1))
            month = months_es.index(m.group(2)) + 1
            return day == today.day and month == today.month
        except (ValueError, IndexError):
            pass
    return False


def _game_is_upcoming(game: dict) -> bool:
    iso = game.get("fecha_iso")
    if iso:
        bog_date = _fecha_iso_to_bogota_date(iso)
        if bog_date is not None:
            return bog_date > _today_str()
    return game.get("estado") == "programado" and not _game_is_today(game)


# ─── API pública del servicio ─────────────────────────────────────────────────

def get_partidos_hoy() -> tuple[list[dict], str]:
    """Partidos que se juegan hoy (fecha ISO o heurística de texto)."""
    games, source = get_all_games()
    return [g for g in games if _game_is_today(g)], source


def get_proximos(limit: int = 10) -> tuple[list[dict], str]:
    """Próximos partidos no disputados aún, ordenados por fecha."""
    games, source = get_all_games()
    upcoming = [g for g in games if _game_is_upcoming(g)]
    upcoming.sort(key=lambda g: g.get("fecha_iso") or g.get("fecha_texto") or "")
    return upcoming[:limit], source


def get_partido(partido_id: int) -> tuple[Optional[dict], str]:
    """Partido por ID; None si no existe."""
    games, source = get_all_games()
    match = next((g for g in games if g["id"] == partido_id), None)
    return match, source


def invalidate_cache() -> None:
    """Fuerza recarga en la próxima solicitud."""
    _cache.delete("all_games")
    logger.info("Caché invalidada manualmente")
