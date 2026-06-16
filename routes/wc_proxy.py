"""
routes/wc_proxy.py
==================
Proxy servidor-a-servidor para worldcup26.ir.

El navegador NO puede llamar directamente a worldcup26.ir porque ese servidor
no devuelve cabeceras CORS. Este blueprint recibe las peticiones del frontend
y devuelve el JSON crudo usando mundial_service (con caché y fallback seed).

Rutas expuestas:
  GET /api/wc/games   →  worldcup26.ir/get/games  (cacheado / seed fallback)
  GET /api/wc/teams   →  worldcup26.ir/get/teams  (cacheado / seed fallback)

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
    """Proxy de /get/games — el frontend llama a /api/wc/games."""
    try:
        data, source = get_raw_games()
        resp = jsonify(data)
        resp.headers["X-Data-Source"] = source
        # Sin caché en el cliente para que el poller siempre vea datos frescos
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as exc:
        logger.exception(f"wc_proxy /games error inesperado: {exc}")
        return jsonify({"error": "error interno"}), 500


@wc_bp.route("/teams")
def proxy_teams():
    """Proxy de /get/teams — el frontend llama a /api/wc/teams."""
    try:
        data, source = get_raw_teams()
        resp = jsonify(data)
        resp.headers["X-Data-Source"] = source
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as exc:
        logger.exception(f"wc_proxy /teams error inesperado: {exc}")
        return jsonify({"error": "error interno"}), 500
