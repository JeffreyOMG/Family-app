"""
routes/mundial_api.py
======================
Blueprint con los endpoints REST del Mundial 2026.

Endpoints:
  GET /api/mundial/partidos-hoy          Partidos del día actual
  GET /api/mundial/en-vivo               Solo partidos en curso (marcador en tiempo real)
  GET /api/mundial/proximos[?limit=N]    Próximos N partidos (default 10)
  GET /api/mundial/partido/<int:id>      Detalle de un partido por ID
  POST /api/mundial/cache/invalidar      Fuerza recarga (solo admin)

Cabecera X-Poll-Interval:
  Todos los endpoints incluyen esta cabecera indicando al cliente
  cada cuántos segundos debe refrescar (20s live, 60s hoy, 120s normal).

Formato de respuesta consistente:
  {
    "ok":    bool,
    "data":  ... | null,
    "meta":  { "fuente": str, "generado": str, "ttl_segundos": int },
    "error": str | null     # solo cuando ok=False
  }
"""

import logging
from datetime import datetime, timezone
from flask import Blueprint, jsonify, session, request as flask_request

from services.mundial_service import (
    get_partidos_hoy,
    get_en_vivo,
    get_proximos,
    get_partido,
    invalidate_cache,
    get_live_ttl,
    CACHE_TTL_SECONDS,
)

logger = logging.getLogger("mundial_api")

mundial_api_bp = Blueprint("mundial_api", __name__, url_prefix="/api/mundial")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ok(data, fuente: str):
    """Respuesta 200 con cabecera X-Poll-Interval dinámica."""
    ttl = get_live_ttl()
    resp = jsonify({
        "ok":    True,
        "data":  data,
        "meta":  {
            "fuente":        fuente,
            "generado":      _now_iso(),
            "ttl_segundos":  ttl,
        },
        "error": None,
    })
    resp.headers["X-Poll-Interval"] = str(ttl)
    return resp, 200


def _err(message: str, status: int = 500) -> tuple:
    logger.error(f"Error {status}: {message}")
    return jsonify({
        "ok":    False,
        "data":  None,
        "meta":  {
            "fuente":       "error",
            "generado":     _now_iso(),
            "ttl_segundos": 0,
        },
        "error": message,
    }), status


def _require_auth():
    """Devuelve respuesta 401 si no hay sesión, None si está autenticado."""
    if "uid" not in session:
        return _err("No autenticado", 401)
    return None


def _require_admin():
    """Devuelve respuesta 403 si el usuario no tiene rol admin."""
    from database import get_db
    uid = session.get("uid")
    if not uid:
        return _err("No autenticado", 401)
    con = get_db()
    row = con.execute("SELECT rol FROM usuarios WHERE id=%s", (uid,)).fetchone()
    if not row or row["rol"] != "admin":
        return _err("Acceso denegado — se requiere rol admin", 403)
    return None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@mundial_api_bp.route("/partidos-hoy", methods=["GET"])
def api_partidos_hoy():
    """
    GET /api/mundial/partidos-hoy
    Partidos del día en zona Bogotá/Lima (UTC-5).
    Incluye en_curso, programados y finalizados del día.
    La cabecera X-Poll-Interval indica cada cuántos segundos refrescar.
    """
    guard = _require_auth()
    if guard:
        return guard

    try:
        partidos, fuente = get_partidos_hoy()
        logger.info(f"partidos-hoy → {len(partidos)} partidos (fuente={fuente})")
        return _ok(partidos, fuente)
    except Exception as exc:
        logger.exception("Error inesperado en partidos-hoy")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/en-vivo", methods=["GET"])
def api_en_vivo():
    """
    GET /api/mundial/en-vivo
    Solo los partidos con estado 'en_curso' en este momento.
    Siempre intenta obtener datos frescos cuando hay partidos en curso.
    Devuelve lista vacía (no error) si no hay ningún partido vivo.
    """
    guard = _require_auth()
    if guard:
        return guard

    try:
        partidos, fuente = get_en_vivo()
        logger.info(f"en-vivo → {len(partidos)} en curso (fuente={fuente})")
        return _ok(partidos, fuente)
    except Exception as exc:
        logger.exception("Error inesperado en en-vivo")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/proximos", methods=["GET"])
def api_proximos():
    """
    GET /api/mundial/proximos[?limit=N]
    Próximos N partidos sin disputar ordenados por fecha (default 10, max 50).
    """
    guard = _require_auth()
    if guard:
        return guard

    try:
        limit = int(flask_request.args.get("limit", 10))
    except (TypeError, ValueError):
        return _err("El parámetro 'limit' debe ser un entero", 400)

    if not (1 <= limit <= 50):
        return _err("El parámetro 'limit' debe estar entre 1 y 50", 400)

    try:
        partidos, fuente = get_proximos(limit=limit)
        logger.info(f"proximos → {len(partidos)} partidos (fuente={fuente}, limit={limit})")
        return _ok(partidos, fuente)
    except Exception as exc:
        logger.exception("Error inesperado en proximos")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/partido/<int:partido_id>", methods=["GET"])
def api_partido_detalle(partido_id: int):
    """
    GET /api/mundial/partido/<id>
    Detalle de un partido por ID. 404 si no existe.
    """
    guard = _require_auth()
    if guard:
        return guard

    try:
        partido, fuente = get_partido(partido_id)
    except Exception as exc:
        logger.exception(f"Error inesperado en partido/{partido_id}")
        return _err(f"Error interno: {exc}")

    if partido is None:
        return _err(f"Partido con id={partido_id} no encontrado", 404)

    logger.info(f"partido/{partido_id} → encontrado (fuente={fuente})")
    return _ok(partido, fuente)


@mundial_api_bp.route("/cache/invalidar", methods=["POST"])
def api_invalidar_cache():
    """
    POST /api/mundial/cache/invalidar  (solo admin)
    Invalida la caché para forzar recarga inmediata desde la API externa.
    """
    guard = _require_admin()
    if guard:
        return guard

    invalidate_cache()
    logger.info(f"Caché invalidada por admin uid={session['uid']}")
    return jsonify({
        "ok":    True,
        "data":  {"mensaje": "Caché invalidada. El siguiente request recargará desde la API externa."},
        "meta":  {"fuente": "manual", "generado": _now_iso(), "ttl_segundos": 0},
        "error": None,
    }), 200


# ─── Manejadores de error del blueprint ──────────────────────────────────────

@mundial_api_bp.errorhandler(404)
def handle_404(exc):
    return _err("Endpoint no encontrado", 404)


@mundial_api_bp.errorhandler(405)
def handle_405(exc):
    return _err("Método HTTP no permitido", 405)
