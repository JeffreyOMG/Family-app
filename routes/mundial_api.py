"""
routes/mundial_api.py
======================
Blueprint REST del Mundial 2026 — v3.

Endpoints existentes (sin cambios):
  GET /api/mundial/partidos-hoy
  GET /api/mundial/en-vivo
  GET /api/mundial/proximos[?limit=N]
  GET /api/mundial/partido/<int:id>
  POST /api/mundial/cache/invalidar

Nuevos endpoints v3:
  GET /api/mundial/groups              → todos los grupos con tabla FIFA
  GET /api/mundial/group-table/<letra> → tabla de un grupo (A-L)
  GET /api/mundial/goals-ranking       → goles por selección DESC
  GET /api/mundial/qualified           → clasificados 1° y 2° de cada grupo
  GET /api/mundial/stats               → estadísticas globales
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
    get_groups,
    get_group_table,
    get_goals_ranking,
    get_qualified,
    get_stats,
    inject_games_from_client,
    CACHE_TTL_SECONDS,
)

logger = logging.getLogger("mundial_api")

mundial_api_bp = Blueprint("mundial_api", __name__, url_prefix="/api/mundial")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ok(data, fuente: str):
    ttl = get_live_ttl()
    resp = jsonify({
        "ok":   True,
        "data": data,
        "meta": {
            "fuente":       fuente,
            "generado":     _now_iso(),
            "ttl_segundos": ttl,
        },
        "error": None,
    })
    resp.headers["X-Poll-Interval"] = str(ttl)
    return resp, 200


def _err(message: str, status: int = 500):
    logger.error(f"Error {status}: {message}")
    return jsonify({
        "ok":   False,
        "data": None,
        "meta": {
            "fuente":       "error",
            "generado":     _now_iso(),
            "ttl_segundos": 0,
        },
        "error": message,
    }), status


def _require_auth():
    if "uid" not in session:
        return _err("No autenticado", 401)
    return None


def _require_admin():
    from database import get_db
    uid = session.get("uid")
    if not uid:
        return _err("No autenticado", 401)
    con = get_db()
    row = con.execute("SELECT rol FROM usuarios WHERE id=%s", (uid,)).fetchone()
    if not row or row["rol"] != "admin":
        return _err("Acceso denegado — se requiere rol admin", 403)
    return None


# ─── Endpoints existentes ─────────────────────────────────────────────────────

@mundial_api_bp.route("/partidos-hoy", methods=["GET"])
def api_partidos_hoy():
    guard = _require_auth()
    if guard: return guard
    try:
        partidos, fuente = get_partidos_hoy()
        return _ok(partidos, fuente)
    except Exception as exc:
        logger.exception("Error en partidos-hoy")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/en-vivo", methods=["GET"])
def api_en_vivo():
    guard = _require_auth()
    if guard: return guard
    try:
        partidos, fuente = get_en_vivo()
        return _ok(partidos, fuente)
    except Exception as exc:
        logger.exception("Error en en-vivo")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/proximos", methods=["GET"])
def api_proximos():
    guard = _require_auth()
    if guard: return guard
    try:
        limit = int(flask_request.args.get("limit", 10))
    except (TypeError, ValueError):
        return _err("El parámetro 'limit' debe ser un entero", 400)
    if not (1 <= limit <= 50):
        return _err("El parámetro 'limit' debe estar entre 1 y 50", 400)
    try:
        partidos, fuente = get_proximos(limit=limit)
        return _ok(partidos, fuente)
    except Exception as exc:
        logger.exception("Error en proximos")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/partido/<int:partido_id>", methods=["GET"])
def api_partido_detalle(partido_id: int):
    guard = _require_auth()
    if guard: return guard
    try:
        partido, fuente = get_partido(partido_id)
    except Exception as exc:
        logger.exception(f"Error en partido/{partido_id}")
        return _err(f"Error interno: {exc}")
    if partido is None:
        return _err(f"Partido con id={partido_id} no encontrado", 404)
    return _ok(partido, fuente)


@mundial_api_bp.route("/cache/invalidar", methods=["POST"])
def api_invalidar_cache():
    guard = _require_admin()
    if guard: return guard
    invalidate_cache()
    logger.info(f"Caché invalidada por admin uid={session['uid']}")
    return jsonify({
        "ok":   True,
        "data": {"mensaje": "Caché invalidada. El siguiente request recargará desde la API externa."},
        "meta": {"fuente": "manual", "generado": _now_iso(), "ttl_segundos": 0},
        "error": None,
    }), 200


# ─── Nuevos endpoints v3 ──────────────────────────────────────────────────────

@mundial_api_bp.route("/groups", methods=["GET"])
def api_groups():
    """
    GET /api/mundial/groups
    Retorna todos los grupos A-L con la tabla FIFA calculada desde partidos reales.
    """
    guard = _require_auth()
    if guard: return guard
    try:
        grupos, fuente = get_groups()
        return _ok(grupos, fuente)
    except Exception as exc:
        logger.exception("Error en groups")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/group-table/<letra>", methods=["GET"])
def api_group_table(letra: str):
    """
    GET /api/mundial/group-table/<A-L>
    Tabla de un solo grupo.
    """
    guard = _require_auth()
    if guard: return guard
    letra = letra.upper()
    if letra not in list("ABCDEFGHIJKL"):
        return _err(f"Grupo '{letra}' inválido. Use A-L.", 400)
    try:
        tabla, fuente = get_group_table(letra)
        return _ok({"grupo": letra, "tabla": tabla}, fuente)
    except Exception as exc:
        logger.exception(f"Error en group-table/{letra}")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/goals-ranking", methods=["GET"])
def api_goals_ranking():
    """
    GET /api/mundial/goals-ranking
    Selecciones ordenadas por goles a favor DESC.
    """
    guard = _require_auth()
    if guard: return guard
    try:
        ranking, fuente = get_goals_ranking()
        return _ok(ranking, fuente)
    except Exception as exc:
        logger.exception("Error en goals-ranking")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/qualified", methods=["GET"])
def api_qualified():
    """
    GET /api/mundial/qualified
    1° y 2° clasificado de cada grupo con partidos jugados.
    """
    guard = _require_auth()
    if guard: return guard
    try:
        clasificados, fuente = get_qualified()
        return _ok(clasificados, fuente)
    except Exception as exc:
        logger.exception("Error en qualified")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/stats", methods=["GET"])
def api_stats():
    """
    GET /api/mundial/stats
    Estadísticas globales del torneo.
    """
    guard = _require_auth()
    if guard: return guard
    try:
        stats, fuente = get_stats()
        return _ok(stats, fuente)
    except Exception as exc:
        logger.exception("Error en stats")
        return _err(f"Error interno: {exc}")


@mundial_api_bp.route("/sync", methods=["POST"])
def api_sync_from_client():
    """
    POST /api/mundial/sync
    El front-end (que SÍ puede llegar a worldcup26.ir) nos envía los datos
    crudos de /get/games y /get/teams para que el servidor actualice su caché.
    Body JSON: { "games": [...], "teams": [...] }
    """
    guard = _require_auth()
    if guard: return guard
    try:
        body = flask_request.get_json(silent=True) or {}
        games_raw = body.get("games")
        teams_raw = body.get("teams")
        if not games_raw or not isinstance(games_raw, list):
            return _err("Se requiere 'games' como lista", 400)
        count = inject_games_from_client(games_raw, teams_raw)
        logger.info(f"Sync desde cliente: {count} partidos inyectados")
        return jsonify({"ok": True, "data": {"partidos": count}, "error": None}), 200
    except Exception as exc:
        logger.exception("Error en /sync")
        return _err(f"Error interno: {exc}")


# ─── Manejadores de error ─────────────────────────────────────────────────────

@mundial_api_bp.errorhandler(404)
def handle_404(exc):
    return _err("Endpoint no encontrado", 404)


@mundial_api_bp.errorhandler(405)
def handle_405(exc):
    return _err("Método HTTP no permitido", 405)
