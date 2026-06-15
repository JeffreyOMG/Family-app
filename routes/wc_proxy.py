"""
routes/wc_proxy.py
==================
Proxy servidor-a-servidor para worldcup26.ir.

El navegador NO puede llamar directamente a worldcup26.ir porque ese servidor
no devuelve cabeceras CORS. Este blueprint recibe las peticiones del frontend,
las reenvía a worldcup26.ir usando el JWT del entorno, y devuelve el JSON.

Rutas expuestas:
  GET /api/wc/games   →  worldcup26.ir/get/games
  GET /api/wc/teams   →  worldcup26.ir/get/teams

Registro en app.py:
  from routes.wc_proxy import wc_bp
  app.register_blueprint(wc_bp)
"""

import json
import logging
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify

logger = logging.getLogger("wc_proxy")

wc_bp = Blueprint("wc_proxy", __name__, url_prefix="/api/wc")

_WC_BASE    = "https://worldcup26.ir"
_TIMEOUT    = 8   # segundos — más generoso que el caché interno
_USER_AGENT = "FamiliaApp/1.0 Mundial2026"


def _jwt() -> str:
    return os.getenv("WC26_JWT_TOKEN", "").strip()


def _get_json(path: str):
    """Hace GET autenticado a worldcup26.ir y devuelve el objeto Python."""
    url = f"{_WC_BASE}{path}"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept":     "application/json",
    }
    token = _jwt()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    with urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


@wc_bp.route("/games")
def proxy_games():
    """Proxy de /get/games — el frontend llama a /api/wc/games."""
    try:
        data = _get_json("/get/games")
        return jsonify(data)
    except (URLError, OSError) as exc:
        logger.warning(f"wc_proxy /games error de red: {exc}")
        return jsonify({"error": "worldcup26.ir no disponible", "detail": str(exc)}), 502
    except Exception as exc:
        logger.exception(f"wc_proxy /games error inesperado: {exc}")
        return jsonify({"error": "error interno"}), 500


@wc_bp.route("/teams")
def proxy_teams():
    """Proxy de /get/teams — el frontend llama a /api/wc/teams."""
    try:
        data = _get_json("/get/teams")
        return jsonify(data)
    except (URLError, OSError) as exc:
        logger.warning(f"wc_proxy /teams error de red: {exc}")
        return jsonify({"error": "worldcup26.ir no disponible", "detail": str(exc)}), 502
    except Exception as exc:
        logger.exception(f"wc_proxy /teams error inesperado: {exc}")
        return jsonify({"error": "error interno"}), 500
