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
    "democratic republic of the congo": "cd", "congo dr": "cd",
    "rd congo":        "cd", "congo":         "cd",
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
    "fulltime":     "finalizado",   # worldcup26.ir: time_elapsed="fulltime"
    "ft":           "finalizado",
    "aet":          "finalizado",
    "penalties":    "finalizado",
    "completed":    "finalizado",
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
    # ── Estados Unidos (horario de verano jun-jul 2026) ──
    "MetLife Stadium":                  -4,  # East Rutherford, NJ  (ET/DST)
    "AT&T Stadium":                     -5,  # Dallas/Arlington, TX (CT/DST)
    "SoFi Stadium":                     -7,  # Los Angeles, CA      (PT/DST)
    "Hard Rock Stadium":                -4,  # Miami Gardens, FL    (ET/DST)
    "Mercedes-Benz Stadium":            -4,  # Atlanta, GA          (ET/DST)
    "NRG Stadium":                      -5,  # Houston, TX          (CT/DST)
    "Lincoln Financial Field":          -4,  # Philadelphia, PA     (ET/DST)
    "Levi's Stadium":                   -7,  # Santa Clara, CA      (PT/DST)
    "Lumen Field":                      -7,  # Seattle, WA          (PT/DST)
    "Gillette Stadium":                 -4,  # Foxborough/Boston, MA (ET/DST)
    "GEHA Field at Arrowhead Stadium":  -5,  # Kansas City, MO      (CT/DST)
    # ── México (sin DST, UTC-6 permanente) ──
    "Estadio Azteca":                   -6,  # Ciudad de México
    "Estadio Akron":                    -6,  # Guadalajara (Zapopan)
    "Estadio BBVA":                     -6,  # Monterrey (Guadalupe)
    # ── Canadá ──
    "BC Place":                         -7,  # Vancouver, BC        (PT/DST)
    "BMO Field":                        -4,  # Toronto, ON          (ET/DST)
}

# Mapa stadium_id (worldcup26.ir) → nombre de estadio.
# FUENTE: football.stadiums.json auditado el 11/06/2026.
_STADIUM_ID_NAME: dict[str, str] = {
    "1":  "Estadio Azteca",
    "2":  "Estadio Akron",
    "3":  "Estadio BBVA",
    "4":  "AT&T Stadium",                    # Dallas/Arlington, TX  ← corregido
    "5":  "NRG Stadium",                     # Houston, TX           ← corregido
    "6":  "GEHA Field at Arrowhead Stadium", # Kansas City, MO       ← corregido
    "7":  "Mercedes-Benz Stadium",           # Atlanta, GA           ← corregido
    "8":  "Hard Rock Stadium",               # Miami Gardens, FL     ← corregido
    "9":  "Gillette Stadium",                # Foxborough/Boston, MA ← corregido
    "10": "Lincoln Financial Field",         # Philadelphia, PA      ← corregido
    "11": "MetLife Stadium",                 # East Rutherford, NJ   ← corregido
    "12": "BMO Field",                       # Toronto, ON           ← corregido
    "13": "BC Place",                        # Vancouver, BC         ← corregido
    "14": "Lumen Field",                     # Seattle, WA           (ya era correcto)
    "15": "Levi's Stadium",                  # Santa Clara, CA       ← corregido
    "16": "SoFi Stadium",                    # Los Angeles, CA       ← corregido
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
    # worldcup26.ir NO envía "score"/"scores"; usa home_score/away_score en la
    # raíz del objeto. Si "score"/"scores" no existen, raw.get(...) devuelve
    # None y "score = {} " (dict vacío) — antes esto entraba al branch dict
    # y nunca llegaba a leer home_score/away_score de la raíz. Corregido:
    # solo usar el branch dict si score/scores REALMENTE vino como dict no vacío.
    score = raw.get("score") or raw.get("scores")
    if isinstance(score, dict) and score:
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
    elif time_elapsed in ("fulltime", "full time", "full-time", "completed"):
        estado = "finalizado"
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

    # ── Minuto / tiempo transcurrido (para badge EN VIVO) ────────────────────
    # Prioridad:
    #   1. Si time_elapsed es un número ("45", "67", "90+2") → úsalo directo
    #   2. Si es texto descriptivo ("halftime", "first half") → etiqueta legible
    #   3. Si la API manda "in progress" o vacío → calcular desde fecha_iso (reloj)
    _ELAPSED_LABEL: dict[str, str] = {
        "halftime":    "Desc.",    # Entre tiempos
        "half time":   "Desc.",
        "first half":  "1T",
        "second half": "2T",
        "extra time":  "Prórroga",
        "penalty":     "Penales",
        "penalties":   "Penales",
        "in progress": None,       # → fallback al reloj
    }

    def _minuto_por_reloj(iso: Optional[str]) -> Optional[str]:
        """Estima el minuto usando el tiempo transcurrido desde el kick-off."""
        if not iso:
            return "En vivo"
        try:
            from datetime import timezone as _tz
            kickoff = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            elapsed = int((datetime.now(_tz.utc) - kickoff).total_seconds() / 60)
            if elapsed < 0:
                return None
            elif elapsed <= 47:        # Primer tiempo
                return f"{min(elapsed, 45)}'"
            elif elapsed <= 60:        # Descanso (~13-15 min)
                return "Desc."
            elif elapsed <= 107:       # Segundo tiempo
                return f"{min(elapsed - 15, 90)}'"
            elif elapsed <= 122:       # Descanso prórroga
                return "Desc."
            elif elapsed <= 152:       # Prórroga
                return f"PT {min(elapsed - 122, 30)}'"
            else:
                return "Penales"
        except Exception:
            return "En vivo"

    minuto: Optional[str] = None
    if estado == "en_curso":
        if time_elapsed and re.match(r"^\d+", time_elapsed):
            # Número real enviado por la API ("45", "67", "90+3")
            minuto = time_elapsed if "+" in time_elapsed else f"{time_elapsed}'"
        elif time_elapsed in _ELAPSED_LABEL:
            label = _ELAPSED_LABEL[time_elapsed]
            minuto = label if label is not None else _minuto_por_reloj(fecha_iso)
        else:
            # time_elapsed vacío, "notstarted" actualizado, o valor desconocido
            minuto = _minuto_por_reloj(fecha_iso)

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
        "minuto":       minuto,     # "45'", "ET", "2T", None si no aplica
    }


# ─── Fuente de fallback: datos semilla (72 grupos + 32 eliminación) ───────────
#
# Si la API externa está caída o devuelve 403, usamos estos datos locales.
# Contienen los 104 partidos del Mundial 2026 con fechas y equipos reales.
# Los scores/estados son los del seed original (todos 0-0 / notstarted).
# El admin actualiza los scores reales via PUT /data/game/:id en worldcup26.ir.
#
# FORMATO: igual al que devuelve worldcup26.ir/get/games, listo para _normalize_game.

import json as _json_mod

_SEED_GAMES_RAW: list[dict] = _json_mod.loads(
    '[{"id":"1","local_date":"06/11/2026 13:00","stadium_id":"1","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Mexico","away_team_name_en":"South Africa","home_team_id":"1","away_team_id":"2"},{"id":"2","local_date":"06/11/2026 20:00","stadium_id":"2","group":"B","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Korea","away_team_name_en":"Czech Republic","home_team_id":"3","away_team_id":"4"},{"id":"3","local_date":"06/12/2026 15:00","stadium_id":"12","group":"C","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Canada","away_team_name_en":"Bosnia and Herzegovina","home_team_id":"5","away_team_id":"6"},{"id":"4","local_date":"06/12/2026 18:00","stadium_id":"16","group":"D","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"United States","away_team_name_en":"Paraguay","home_team_id":"7","away_team_id":"8"},{"id":"5","local_date":"06/13/2026 13:00","stadium_id":"3","group":"E","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Qatar","away_team_name_en":"Switzerland","home_team_id":"9","away_team_id":"10"},{"id":"6","local_date":"06/13/2026 16:00","stadium_id":"4","group":"F","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Brazil","away_team_name_en":"Morocco","home_team_id":"11","away_team_id":"12"},{"id":"7","local_date":"06/13/2026 21:00","stadium_id":"5","group":"G","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Haiti","away_team_name_en":"Scotland","home_team_id":"13","away_team_id":"14"},{"id":"8","local_date":"06/14/2026 14:00","stadium_id":"6","group":"H","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"United States","away_team_name_en":"Paraguay","home_team_id":"7","away_team_id":"8"},{"id":"9","local_date":"06/14/2026 17:00","stadium_id":"7","group":"I","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Australia","away_team_name_en":"Turkey","home_team_id":"15","away_team_id":"16"},{"id":"10","local_date":"06/14/2026 21:00","stadium_id":"8","group":"J","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Germany","away_team_name_en":"Curacao","home_team_id":"17","away_team_id":"18"},{"id":"11","local_date":"06/15/2026 12:00","stadium_id":"9","group":"K","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ivory Coast","away_team_name_en":"Ecuador","home_team_id":"19","away_team_id":"20"},{"id":"12","local_date":"06/15/2026 15:00","stadium_id":"10","group":"L","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Netherlands","away_team_name_en":"Japan","home_team_id":"21","away_team_id":"22"},{"id":"13","local_date":"06/15/2026 19:00","stadium_id":"11","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Sweden","away_team_name_en":"Tunisia","home_team_id":"23","away_team_id":"24"},{"id":"14","local_date":"06/16/2026 12:00","stadium_id":"13","group":"B","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Belgium","away_team_name_en":"Egypt","home_team_id":"25","away_team_id":"26"},{"id":"15","local_date":"06/16/2026 16:00","stadium_id":"14","group":"C","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iran","away_team_name_en":"New Zealand","home_team_id":"27","away_team_id":"28"},{"id":"16","local_date":"06/16/2026 20:00","stadium_id":"15","group":"D","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Spain","away_team_name_en":"Cape Verde","home_team_id":"29","away_team_id":"30"},{"id":"17","local_date":"06/17/2026 12:00","stadium_id":"16","group":"E","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Saudi Arabia","away_team_name_en":"Uruguay","home_team_id":"31","away_team_id":"32"},{"id":"18","local_date":"06/17/2026 16:00","stadium_id":"1","group":"F","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"France","away_team_name_en":"Senegal","home_team_id":"33","away_team_id":"34"},{"id":"19","local_date":"06/17/2026 20:00","stadium_id":"2","group":"G","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iraq","away_team_name_en":"Norway","home_team_id":"35","away_team_id":"36"},{"id":"20","local_date":"06/18/2026 12:00","stadium_id":"3","group":"H","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"21","local_date":"06/18/2026 16:00","stadium_id":"4","group":"I","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Austria","away_team_name_en":"Jordan","home_team_id":"39","away_team_id":"40"},{"id":"22","local_date":"06/18/2026 20:00","stadium_id":"5","group":"J","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Portugal","away_team_name_en":"Democratic Republic of the Congo","home_team_id":"41","away_team_id":"42"},{"id":"23","local_date":"06/19/2026 12:00","stadium_id":"6","group":"K","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Uzbekistan","away_team_name_en":"Colombia","home_team_id":"43","away_team_id":"44"},{"id":"24","local_date":"06/19/2026 16:00","stadium_id":"7","group":"L","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"England","away_team_name_en":"Croatia","home_team_id":"45","away_team_id":"46"},{"id":"25","local_date":"06/19/2026 20:00","stadium_id":"8","group":"A","type":"group","matchday":"1","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ghana","away_team_name_en":"Panama","home_team_id":"47","away_team_id":"48"},{"id":"26","local_date":"06/20/2026 12:00","stadium_id":"9","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Czech Republic","away_team_name_en":"Belgium","home_team_id":"4","away_team_id":"25"},{"id":"27","local_date":"06/20/2026 16:00","stadium_id":"10","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Bosnia and Herzegovina","away_team_name_en":"Iran","home_team_id":"6","away_team_id":"27"},{"id":"28","local_date":"06/20/2026 20:00","stadium_id":"11","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Paraguay","away_team_name_en":"Spain","home_team_id":"8","away_team_id":"29"},{"id":"29","local_date":"06/21/2026 12:00","stadium_id":"12","group":"E","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Switzerland","away_team_name_en":"Saudi Arabia","home_team_id":"10","away_team_id":"31"},{"id":"30","local_date":"06/21/2026 16:00","stadium_id":"13","group":"F","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Morocco","away_team_name_en":"Uzbekistan","home_team_id":"12","away_team_id":"43"},{"id":"31","local_date":"06/21/2026 20:00","stadium_id":"14","group":"G","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Scotland","away_team_name_en":"Iraq","home_team_id":"14","away_team_id":"35"},{"id":"32","local_date":"06/22/2026 12:00","stadium_id":"15","group":"H","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Algeria","away_team_name_en":"Austria","home_team_id":"38","away_team_id":"39"},{"id":"33","local_date":"06/22/2026 16:00","stadium_id":"16","group":"I","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Jordan","away_team_name_en":"Australia","home_team_id":"40","away_team_id":"15"},{"id":"34","local_date":"06/22/2026 20:00","stadium_id":"1","group":"J","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Curacao","away_team_name_en":"Portugal","home_team_id":"18","away_team_id":"41"},{"id":"35","local_date":"06/23/2026 12:00","stadium_id":"2","group":"K","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Colombia","away_team_name_en":"Ivory Coast","home_team_id":"44","away_team_id":"19"},{"id":"36","local_date":"06/23/2026 16:00","stadium_id":"3","group":"L","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Croatia","away_team_name_en":"Netherlands","home_team_id":"46","away_team_id":"21"},{"id":"37","local_date":"06/23/2026 20:00","stadium_id":"4","group":"A","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Africa","away_team_name_en":"Sweden","home_team_id":"2","away_team_id":"23"},{"id":"38","local_date":"06/24/2026 12:00","stadium_id":"5","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Egypt","away_team_name_en":"South Korea","home_team_id":"26","away_team_id":"3"},{"id":"39","local_date":"06/24/2026 16:00","stadium_id":"6","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"New Zealand","away_team_name_en":"Canada","home_team_id":"28","away_team_id":"5"},{"id":"40","local_date":"06/24/2026 20:00","stadium_id":"7","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Cape Verde","away_team_name_en":"United States","home_team_id":"30","away_team_id":"7"},{"id":"41","local_date":"06/25/2026 12:00","stadium_id":"8","group":"E","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Uruguay","away_team_name_en":"Qatar","home_team_id":"32","away_team_id":"9"},{"id":"42","local_date":"06/25/2026 16:00","stadium_id":"9","group":"F","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Senegal","away_team_name_en":"Brazil","home_team_id":"34","away_team_id":"11"},{"id":"43","local_date":"06/25/2026 20:00","stadium_id":"10","group":"G","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Norway","away_team_name_en":"Haiti","home_team_id":"36","away_team_id":"13"},{"id":"44","local_date":"06/26/2026 12:00","stadium_id":"11","group":"H","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"45","local_date":"06/26/2026 16:00","stadium_id":"12","group":"I","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Turkey","away_team_name_en":"Jordan","home_team_id":"16","away_team_id":"40"},{"id":"46","local_date":"06/26/2026 20:00","stadium_id":"13","group":"J","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Democratic Republic of the Congo","away_team_name_en":"Germany","home_team_id":"42","away_team_id":"17"},{"id":"47","local_date":"06/27/2026 12:00","stadium_id":"14","group":"K","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ecuador","away_team_name_en":"Colombia","home_team_id":"20","away_team_id":"44"},{"id":"48","local_date":"06/27/2026 16:00","stadium_id":"15","group":"L","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Japan","away_team_name_en":"England","home_team_id":"22","away_team_id":"45"},{"id":"49","local_date":"06/27/2026 20:00","stadium_id":"16","group":"A","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Panama","away_team_name_en":"Mexico","home_team_id":"48","away_team_id":"1"},{"id":"50","local_date":"06/28/2026 12:00","stadium_id":"1","group":"B","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Tunisia","away_team_name_en":"Czech Republic","home_team_id":"24","away_team_id":"4"},{"id":"51","local_date":"06/28/2026 16:00","stadium_id":"2","group":"C","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Iran","away_team_name_en":"New Zealand","home_team_id":"27","away_team_id":"28"},{"id":"52","local_date":"06/28/2026 20:00","stadium_id":"3","group":"D","type":"group","matchday":"2","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Spain","away_team_name_en":"Paraguay","home_team_id":"29","away_team_id":"8"},{"id":"53","local_date":"06/29/2026 12:00","stadium_id":"4","group":"E","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Qatar","away_team_name_en":"Saudi Arabia","home_team_id":"9","away_team_id":"31"},{"id":"54","local_date":"06/29/2026 12:00","stadium_id":"5","group":"E","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Switzerland","away_team_name_en":"Uruguay","home_team_id":"10","away_team_id":"32"},{"id":"55","local_date":"06/29/2026 20:00","stadium_id":"6","group":"F","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Brazil","away_team_name_en":"Senegal","home_team_id":"11","away_team_id":"34"},{"id":"56","local_date":"06/29/2026 20:00","stadium_id":"7","group":"F","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Morocco","away_team_name_en":"Uzbekistan","home_team_id":"12","away_team_id":"43"},{"id":"57","local_date":"06/30/2026 12:00","stadium_id":"8","group":"G","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Scotland","away_team_name_en":"Haiti","home_team_id":"14","away_team_id":"13"},{"id":"58","local_date":"06/30/2026 12:00","stadium_id":"9","group":"G","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Norway","away_team_name_en":"Iraq","home_team_id":"36","away_team_id":"35"},{"id":"59","local_date":"06/30/2026 20:00","stadium_id":"10","group":"H","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Argentina","away_team_name_en":"Algeria","home_team_id":"37","away_team_id":"38"},{"id":"60","local_date":"06/30/2026 20:00","stadium_id":"11","group":"H","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Austria","away_team_name_en":"Algeria","home_team_id":"39","away_team_id":"38"},{"id":"61","local_date":"07/01/2026 12:00","stadium_id":"12","group":"I","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Australia","away_team_name_en":"Jordan","home_team_id":"15","away_team_id":"40"},{"id":"62","local_date":"07/01/2026 12:00","stadium_id":"13","group":"I","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Turkey","away_team_name_en":"Austria","home_team_id":"16","away_team_id":"39"},{"id":"63","local_date":"07/01/2026 20:00","stadium_id":"14","group":"J","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Germany","away_team_name_en":"Portugal","home_team_id":"17","away_team_id":"41"},{"id":"64","local_date":"07/01/2026 20:00","stadium_id":"15","group":"J","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Curacao","away_team_name_en":"Democratic Republic of the Congo","home_team_id":"18","away_team_id":"42"},{"id":"65","local_date":"07/02/2026 12:00","stadium_id":"16","group":"K","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ivory Coast","away_team_name_en":"Colombia","home_team_id":"19","away_team_id":"44"},{"id":"66","local_date":"07/02/2026 12:00","stadium_id":"1","group":"K","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Ecuador","away_team_name_en":"Uzbekistan","home_team_id":"20","away_team_id":"43"},{"id":"67","local_date":"07/02/2026 20:00","stadium_id":"2","group":"L","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Netherlands","away_team_name_en":"England","home_team_id":"21","away_team_id":"45"},{"id":"68","local_date":"07/02/2026 20:00","stadium_id":"3","group":"L","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Japan","away_team_name_en":"Croatia","home_team_id":"22","away_team_id":"46"},{"id":"69","local_date":"07/03/2026 12:00","stadium_id":"4","group":"A","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Mexico","away_team_name_en":"Ghana","home_team_id":"1","away_team_id":"47"},{"id":"70","local_date":"07/03/2026 12:00","stadium_id":"5","group":"A","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Panama","away_team_name_en":"South Africa","home_team_id":"48","away_team_id":"2"},{"id":"71","local_date":"07/03/2026 20:00","stadium_id":"6","group":"B","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"South Korea","away_team_name_en":"Tunisia","home_team_id":"3","away_team_id":"24"},{"id":"72","local_date":"07/03/2026 20:00","stadium_id":"7","group":"B","type":"group","matchday":"3","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"Belgium","away_team_name_en":"Egypt","home_team_id":"25","away_team_id":"26"},{"id":"73","local_date":"07/04/2026 15:00","stadium_id":"16","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"2A","away_team_name_en":"2B","home_team_id":"0","away_team_id":"0"},{"id":"74","local_date":"07/04/2026 19:00","stadium_id":"9","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1E","away_team_name_en":"3-ABCDF","home_team_id":"0","away_team_id":"0"},{"id":"75","local_date":"07/05/2026 15:00","stadium_id":"6","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1F","away_team_name_en":"2C","home_team_id":"0","away_team_id":"0"},{"id":"76","local_date":"07/05/2026 19:00","stadium_id":"11","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1B","away_team_name_en":"3-ACDE","home_team_id":"0","away_team_id":"0"},{"id":"77","local_date":"07/06/2026 15:00","stadium_id":"14","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1J","away_team_name_en":"2I","home_team_id":"0","away_team_id":"0"},{"id":"78","local_date":"07/06/2026 19:00","stadium_id":"7","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1K","away_team_name_en":"2L","home_team_id":"0","away_team_id":"0"},{"id":"79","local_date":"07/07/2026 15:00","stadium_id":"8","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1L","away_team_name_en":"2K","home_team_id":"0","away_team_id":"0"},{"id":"80","local_date":"07/07/2026 19:00","stadium_id":"4","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1I","away_team_name_en":"2J","home_team_id":"0","away_team_id":"0"},{"id":"81","local_date":"07/08/2026 15:00","stadium_id":"1","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1A","away_team_name_en":"2B","home_team_id":"0","away_team_id":"0"},{"id":"82","local_date":"07/08/2026 19:00","stadium_id":"5","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1C","away_team_name_en":"2D","home_team_id":"0","away_team_id":"0"},{"id":"83","local_date":"07/09/2026 15:00","stadium_id":"3","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1D","away_team_name_en":"2C","home_team_id":"0","away_team_id":"0"},{"id":"84","local_date":"07/09/2026 19:00","stadium_id":"15","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1G","away_team_name_en":"3-GHIJ","home_team_id":"0","away_team_id":"0"},{"id":"85","local_date":"07/10/2026 15:00","stadium_id":"13","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1H","away_team_name_en":"3-BDEF","home_team_id":"0","away_team_id":"0"},{"id":"86","local_date":"07/10/2026 19:00","stadium_id":"12","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"2G","away_team_name_en":"3-HIJK","home_team_id":"0","away_team_id":"0"},{"id":"87","local_date":"07/11/2026 15:00","stadium_id":"2","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"1C","away_team_name_en":"2D","home_team_id":"0","away_team_id":"0"},{"id":"88","local_date":"07/11/2026 19:00","stadium_id":"10","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"2E","away_team_name_en":"2F","home_team_id":"0","away_team_id":"0"},{"id":"89","local_date":"07/15/2026 15:00","stadium_id":"11","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W73","away_team_name_en":"W74","home_team_id":"0","away_team_id":"0"},{"id":"90","local_date":"07/15/2026 19:00","stadium_id":"7","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W77","away_team_name_en":"W78","home_team_id":"0","away_team_id":"0"},{"id":"91","local_date":"07/16/2026 15:00","stadium_id":"5","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W75","away_team_name_en":"W76","home_team_id":"0","away_team_id":"0"},{"id":"92","local_date":"07/16/2026 19:00","stadium_id":"9","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W79","away_team_name_en":"W80","home_team_id":"0","away_team_id":"0"},{"id":"93","local_date":"07/17/2026 15:00","stadium_id":"14","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W81","away_team_name_en":"W82","home_team_id":"0","away_team_id":"0"},{"id":"94","local_date":"07/17/2026 19:00","stadium_id":"1","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W85","away_team_name_en":"W86","home_team_id":"0","away_team_id":"0"},{"id":"95","local_date":"07/18/2026 15:00","stadium_id":"16","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W83","away_team_name_en":"W84","home_team_id":"0","away_team_id":"0"},{"id":"96","local_date":"07/18/2026 19:00","stadium_id":"4","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W87","away_team_name_en":"W88","home_team_id":"0","away_team_id":"0"},{"id":"97","local_date":"07/22/2026 19:00","stadium_id":"11","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W89","away_team_name_en":"W90","home_team_id":"0","away_team_id":"0"},{"id":"98","local_date":"07/22/2026 19:00","stadium_id":"6","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W91","away_team_name_en":"W92","home_team_id":"0","away_team_id":"0"},{"id":"99","local_date":"07/23/2026 19:00","stadium_id":"15","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W93","away_team_name_en":"W94","home_team_id":"0","away_team_id":"0"},{"id":"100","local_date":"07/23/2026 19:00","stadium_id":"13","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W95","away_team_name_en":"W96","home_team_id":"0","away_team_id":"0"},{"id":"101","local_date":"07/26/2026 19:00","stadium_id":"3","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W97","away_team_name_en":"W98","home_team_id":"0","away_team_id":"0"},{"id":"102","local_date":"07/26/2026 19:00","stadium_id":"8","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W99","away_team_name_en":"W100","home_team_id":"0","away_team_id":"0"},{"id":"103","local_date":"07/29/2026 15:00","stadium_id":"2","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"L101","away_team_name_en":"L102","home_team_id":"0","away_team_id":"0"},{"id":"104","local_date":"08/02/2026 15:00","stadium_id":"11","group":"","type":"knockout","matchday":"","finished":"FALSE","time_elapsed":"notstarted","home_score":"0","away_score":"0","home_team_name_en":"W101","away_team_name_en":"W102","home_team_id":"0","away_team_id":"0"}]'
)


def _fallback_games() -> list[dict]:
    """
    Fallback con los 104 partidos del Mundial 2026 con fechas y equipos reales.
    Se usa cuando worldcup26.ir no responde (403, timeout, etc.).
    Los scores se muestran en 0-0 hasta que la API externa vuelva a responder.
    """
    normalized = []
    for i, g in enumerate(_SEED_GAMES_RAW):
        try:
            normalized.append(_normalize_game(g, i))
        except Exception as exc:
            logger.warning(f"Fallback: error normalizando partido id={g.get('id')}: {exc}")
    logger.info(f"Fallback seed: {len(normalized)} partidos cargados")
    return normalized


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
            _jwt = os.getenv("WC26_JWT_TOKEN", "").strip()
            _headers = {
                "User-Agent":      "FamiliaApp/1.0 Mundial2026",
                "Accept":          "application/json",
                "Accept-Language": "es,en;q=0.8",
            }
            if _jwt:
                _headers["Authorization"] = f"Bearer {_jwt}"
            req = Request(EXTERNAL_API_URL, headers=_headers)
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

            normalized = []
            skipped = 0
            for i, g in enumerate(games_raw):
                try:
                    normalized.append(_normalize_game(g, i))
                except Exception as exc:
                    skipped += 1
                    logger.warning(f"_normalize_game skipped id={g.get('id','?')}: {exc}")
            if skipped:
                logger.warning(f"Fetch: {skipped} partidos descartados por error de normalización")
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

    TTL dinámico:
      - Partidos en curso → 20 s  (actualización casi en tiempo real)
      - Solo partidos de hoy sin live → 60 s
      - Sin partidos hoy → 120 s (valor estático CACHE_TTL_SECONDS)
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
            ttl = _dynamic_ttl(games)
            _cache.set("all_games", games, ttl=ttl)
            logger.info(f"Cache actualizado — TTL={ttl}s")
            return games, "external"
        except RuntimeError as exc:
            logger.error(f"Usando fallback local. Razón: {exc}")
            games = _fallback_games()
            # Caché más corta para que se reintente pronto
            _cache.set("all_games", games, ttl=30)
            return games, "fallback"


# ─── Helpers de filtrado ──────────────────────────────────────────────────────

_TZ_BOGOTA = timezone(timedelta(hours=-5))  # Colombia / Perú (sin DST)

# TTLs en segundos según estado del torneo
_TTL_LIVE    = int(os.getenv("MUNDIAL_TTL_LIVE",    "20"))   # partidos en curso
_TTL_HOY     = int(os.getenv("MUNDIAL_TTL_HOY",     "60"))   # hay partidos hoy (sin live)
_TTL_NORMAL  = CACHE_TTL_SECONDS                              # sin partidos hoy (2 min)


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


def _game_is_live(game: dict) -> bool:
    """True si el partido está en curso ahora mismo."""
    return game.get("estado") == "en_curso"


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


def _dynamic_ttl(games: list[dict]) -> int:
    """
    Calcula el TTL óptimo según el estado actual del torneo:
      - Hay partidos EN CURSO        → _TTL_LIVE   (20 s)
      - Hay partidos HOY sin live    → _TTL_HOY    (60 s)
      - Sin partidos hoy             → _TTL_NORMAL (120 s)
    """
    if any(_game_is_live(g) for g in games):
        return _TTL_LIVE
    if any(_game_is_today(g) for g in games):
        return _TTL_HOY
    return _TTL_NORMAL


# ─── API pública del servicio ─────────────────────────────────────────────────

def get_partidos_hoy() -> tuple[list[dict], str]:
    """
    Partidos que se juegan hoy en zona Bogotá/Lima (UTC-5).
    Incluye en_curso, programados y finalizados del día.
    Ordenados: en_curso primero, luego programados por hora, luego finalizados.
    El campo 'minuto' está presente cuando el partido es en_curso.
    """
    games, source = get_all_games()
    hoy = [g for g in games if _game_is_today(g)]

    def _prio(g: dict) -> tuple:
        estado = g.get("estado", "")
        if estado == "en_curso":   p = 0
        elif estado == "programado": p = 1
        else:                        p = 2  # finalizado
        return (p, g.get("fecha_iso") or "")

    hoy.sort(key=_prio)
    return hoy, source


def get_en_vivo() -> tuple[list[dict], str]:
    """
    Solo los partidos con estado 'en_curso' en este momento.
    Siempre fuerza refresco de caché cuando hay partidos en curso,
    para que el frontend reciba el marcador más reciente disponible.
    """
    # Primero verificamos con caché normal
    games, source = get_all_games()
    live = [g for g in games if _game_is_live(g)]

    # Si hay partidos vivos y la fuente era caché, forzamos refresh
    # para no servir datos potencialmente desactualizados
    if live and source == "cache":
        games, source = get_all_games(force_refresh=True)
        live = [g for g in games if _game_is_live(g)]

    return live, source


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


def get_live_ttl() -> int:
    """
    Devuelve el TTL activo del caché según el estado del torneo.
    El frontend lo usa para saber cada cuántos segundos refrescar.
    """
    games_cached = _cache.get("all_games")
    if games_cached is None:
        return _TTL_NORMAL
    return _dynamic_ttl(games_cached)


def hay_partidos_en_vivo() -> bool:
    """Retorna True si existe al menos un partido en_curso ahora mismo."""
    games_cached = _cache.get("all_games")
    if games_cached is None:
        return False
    return any(_game_is_live(g) for g in games_cached)


def invalidate_cache() -> None:
    """Fuerza recarga en la próxima solicitud."""
    _cache.delete("all_games")
    logger.info("Caché invalidada manualmente")
