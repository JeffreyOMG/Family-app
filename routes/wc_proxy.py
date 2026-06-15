"""
routes/wc_proxy.py
==================
Proxy servidor-a-servidor para worldcup26.ir.

El navegador NO puede llamar directamente a worldcup26.ir porque ese servidor
no devuelve cabeceras CORS. Este blueprint recibe las peticiones del frontend,
las reenvía a worldcup26.ir usando el JWT del entorno, y devuelve el JSON CRUDO
(sin normalizar) para que el frontend lo procese con _normWC.

Usa `mundial_service` en vez de llamar directamente a worldcup26.ir, heredando
así su caché, reintentos y fallback al seed — lo que evita los errores 502/SSL
que ocurren cuando Render intenta conectar a worldcup26.ir directamente.

Rutas expuestas:
  GET /api/wc/games   →  datos crudos de worldcup26.ir/get/games (con caché)
  GET /api/wc/teams   →  datos crudos de worldcup26.ir/get/teams (con caché)

Registro en app.py:
  from routes.wc_proxy import wc_bp
  app.register_blueprint(wc_bp)
"""

import logging
from flask import Blueprint, jsonify

from services.mundial_service import get_raw_games, get_raw_teams

logger = logging.getLogger("wc_proxy")

wc_bp = Blueprint("wc_proxy", __name__, url_prefix="/api/wc")


@wc_bp.route("/games")
def proxy_games():
    """Proxy de /get/games — devuelve JSON crudo para que el frontend lo normalice con _normWC."""
    try:
        games, source = get_raw_games()
        logger.debug(f"wc_proxy /games → {len(games)} partidos (fuente: {source})")
        return jsonify(games)
    except Exception as exc:
        logger.exception(f"wc_proxy /games error inesperado: {exc}")
        return jsonify({"error": "error interno"}), 500


@wc_bp.route("/teams")
def proxy_teams():
    """Proxy de /get/teams — devuelve JSON crudo de equipos."""
    try:
        teams, source = get_raw_teams()
        logger.debug(f"wc_proxy /teams → {len(teams)} equipos (fuente: {source})")
        return jsonify(teams)
    except Exception as exc:
        logger.exception(f"wc_proxy /teams error inesperado: {exc}")
        return jsonify({"error": "error interno"}), 500
