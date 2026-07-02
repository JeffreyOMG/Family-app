"""
routes/mundial_ranking_probabilidades.py
==========================================
Endpoint NUEVO e independiente. No modifica routes/mundial.py.
Solo expone el motor de services/ranking_probabilidades.py.

GET /api/mundial_ranking_probabilidades?categoria=global|grupos|eli&sims=N
"""

import logging
from flask import Blueprint, jsonify, session, request

from database import get_db
from services.ranking_probabilidades import (
    calcular_probabilidades_ranking,
    N_SIMULACIONES_DEFAULT,
    N_SIMULACIONES_MIN,
    N_SIMULACIONES_MAX,
)

logger = logging.getLogger("mundial_ranking_probabilidades")

mundial_prob_bp = Blueprint("mundial_prob", __name__)


@mundial_prob_bp.route("/api/mundial_ranking_probabilidades", methods=["GET"])
def api_mundial_ranking_probabilidades():
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    categoria = (request.args.get("categoria") or "global").strip().lower()
    if categoria not in ("global", "grupos", "eli"):
        categoria = "global"

    try:
        sims = int(request.args.get("sims", N_SIMULACIONES_DEFAULT))
    except (TypeError, ValueError):
        sims = N_SIMULACIONES_DEFAULT
    sims = max(N_SIMULACIONES_MIN, min(sims, N_SIMULACIONES_MAX))

    con = get_db()
    try:
        data = calcular_probabilidades_ranking(con, categoria=categoria, n_sim_solicitado=sims)
        return jsonify({"ok": True, **data})
    except Exception as exc:
        logger.exception("Error calculando probabilidades del ranking")
        return jsonify({"ok": False, "error": str(exc)}), 500
