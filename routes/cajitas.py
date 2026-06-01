"""
Cajitas de Ahorro Familiar — rutas adicionales para "unirse" a una cajita.
Las rutas de crear/aportar siguen en finanzas.py para no romper el sistema.
"""
import secrets
from flask import Blueprint, session, jsonify, request
from database import get_db

cajitas_bp = Blueprint("cajitas", __name__)


def _uid():
    return session.get("uid")

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _gen_codigo():
    return secrets.token_urlsafe(6).upper()[:8]


def _asegurar_codigo(con, cajita_id):
    """Asigna un código único a una cajita si no tiene uno todavía."""
    row = con.execute(
        "SELECT codigo FROM cajitas_ahorro_codigos WHERE cajita_id=?", (cajita_id,)
    ).fetchone()
    if row:
        return row["codigo"]
    for _ in range(10):
        codigo = _gen_codigo()
        try:
            con.execute(
                "INSERT INTO cajitas_ahorro_codigos(cajita_id,codigo) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (cajita_id, codigo)
            )
            con.commit()
            return codigo
        except Exception:
            continue
    return None


@cajitas_bp.route("/api/cajita/<int:cid>/codigo")
def get_codigo(cid):
    if not _uid():
        return jsonify({"ok": False}), 401
    con = get_db()
    # Solo miembros o admin pueden ver el código
    es_miembro = con.execute(
        "SELECT 1 FROM cajita_miembros WHERE cajita_id=? AND usuario_id=?", (cid, _uid())
    ).fetchone()
    if not es_miembro and session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    codigo = _asegurar_codigo(con, cid)
    return jsonify({"ok": True, "codigo": codigo})


@cajitas_bp.route("/api/cajita/unirse", methods=["POST"])
def unirse():
    if not _uid():
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or "").strip().upper()
    if not codigo:
        return jsonify({"ok": False, "error": "Código requerido"}), 400
    con = get_db()
    row = con.execute(
        "SELECT cajita_id FROM cajitas_ahorro_codigos WHERE codigo=?", (codigo,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Código inválido"}), 404
    cajita_id = row["cajita_id"]
    con.execute(
        "INSERT INTO cajita_miembros(cajita_id,usuario_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
        (cajita_id, _uid())
    )
    con.commit()
    cajita = con.execute(
        "SELECT id, nombre, descripcion FROM cajitas_ahorro WHERE id=?", (cajita_id,)
    ).fetchone()
    return jsonify({"ok": True, "cajita": dict(cajita)})


@cajitas_bp.route("/api/cajita/<int:cid>/miembros")
def cajita_miembros(cid):
    if not _uid():
        return jsonify([]), 401
    con = get_db()
    es_miembro = con.execute(
        "SELECT 1 FROM cajita_miembros WHERE cajita_id=? AND usuario_id=?", (cid, _uid())
    ).fetchone()
    if not es_miembro:
        return jsonify([])
    miembros = [dict(m) for m in con.execute("""
        SELECT u.id, u.nombre, u.foto,
               COALESCE(SUM(cm.monto),0) AS total_aportado
        FROM cajita_miembros mb
        JOIN usuarios u ON u.id = mb.usuario_id
        LEFT JOIN cajita_movimientos cm ON cm.cajita_id=mb.cajita_id AND cm.usuario_id=u.id
        WHERE mb.cajita_id=?
        GROUP BY u.id
        ORDER BY total_aportado DESC
    """, (cid,)).fetchall()]
    return jsonify(miembros)


@cajitas_bp.route("/api/cajita/<int:cid>/detalle")
def cajita_detalle(cid):
    if not _uid():
        return jsonify({}), 401
    con = get_db()
    es_miembro = con.execute(
        "SELECT 1 FROM cajita_miembros WHERE cajita_id=? AND usuario_id=?", (cid, _uid())
    ).fetchone()
    if not es_miembro and session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    cajita = con.execute("""
        SELECT ca.id, ca.nombre, ca.descripcion, ca.creador_id, ca.fecha,
               COALESCE(SUM(cm.monto),0) AS total,
               COUNT(DISTINCT mb.usuario_id) AS num_miembros
        FROM cajitas_ahorro ca
        LEFT JOIN cajita_movimientos cm ON cm.cajita_id=ca.id
        LEFT JOIN cajita_miembros mb ON mb.cajita_id=ca.id
        WHERE ca.id=?
        GROUP BY ca.id
    """, (cid,)).fetchone()
    if not cajita:
        return jsonify({"ok": False}), 404
    return jsonify(dict(cajita))
