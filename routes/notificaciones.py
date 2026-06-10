from flask import Blueprint, jsonify, session
from database import get_db
import re

notif_bp = Blueprint("notif", __name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

def crear_notificacion(con, dest_id, tipo, actor_id=None, post_id=None,
                       comentario_id=None, texto_extra=""):
    """Inserta una notificación. No lanza excepción si falla."""
    try:
        # No auto-notificar
        if actor_id and actor_id == dest_id:
            return
        # Anti-spam: no duplicar la misma acción en < 60 min
        dup = con.run(
            """SELECT id FROM notificaciones
               WHERE dest_id=:d AND tipo=:t AND actor_id=:a
                 AND post_id IS NOT DISTINCT FROM :p
                 AND fecha > NOW() - INTERVAL '60 minutes'
               LIMIT 1""",
            d=dest_id, t=tipo, a=actor_id, p=post_id
        )
        if dup:
            return
        con.run(
            """INSERT INTO notificaciones
               (dest_id, tipo, actor_id, post_id, comentario_id, texto_extra)
               VALUES (:d, :t, :a, :p, :c, :x)""",
            d=dest_id, t=tipo, a=actor_id, p=post_id,
            c=comentario_id, x=texto_extra or ""
        )
    except Exception:
        pass


def notificar_menciones(con, actor_id, texto, post_id=None, comentario_id=None):
    """Detecta @usuario en texto y crea notificaciones de mención."""
    try:
        menciones = re.findall(r"@(\w+)", texto or "")
        for username in set(menciones):
            row = con.run(
                "SELECT id FROM usuarios WHERE username=:u LIMIT 1",
                u=username
            )
            if row:
                dest_id = row[0][0]
                crear_notificacion(
                    con, dest_id=dest_id, tipo="mencion",
                    actor_id=actor_id, post_id=post_id,
                    comentario_id=comentario_id
                )
    except Exception:
        pass


def notificar_admin_post(con, post_id, admin_id):
    """Notifica a todos los usuarios (excepto el admin) de un nuevo post de admin."""
    try:
        usuarios = con.run(
            "SELECT id FROM usuarios WHERE id != :a",
            a=admin_id
        )
        for (uid,) in usuarios:
            crear_notificacion(
                con, dest_id=uid, tipo="admin_post",
                actor_id=admin_id, post_id=post_id
            )
    except Exception:
        pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@notif_bp.get("/api/notificaciones")
def api_listar():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"ok": False, "error": "no auth"}), 401
    con = get_db()
    try:
        rows = con.run(
            """SELECT n.id, n.tipo, n.leida, n.fecha, n.texto_extra,
                      n.post_id, n.comentario_id,
                      u.username AS actor_nombre, u.foto AS actor_foto
               FROM notificaciones n
               LEFT JOIN usuarios u ON u.id = n.actor_id
               WHERE n.dest_id = :uid
               ORDER BY n.fecha DESC
               LIMIT 50""",
            uid=uid
        )
        cols = ["id","tipo","leida","fecha","texto_extra",
                "post_id","comentario_id","actor_nombre","actor_foto"]
        notifs = []
        for r in rows:
            d = dict(zip(cols, r))
            d["leida"] = bool(d["leida"])
            d["fecha"] = d["fecha"].isoformat() if d["fecha"] else None
            notifs.append(d)
        return jsonify({"ok": True, "notificaciones": notifs})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@notif_bp.get("/api/notificaciones/no_leidas")
def api_no_leidas():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"count": 0}), 401
    con = get_db()
    try:
        row = con.run(
            "SELECT COUNT(*) FROM notificaciones WHERE dest_id=:uid AND leida=FALSE",
            uid=uid
        )
        return jsonify({"count": row[0][0] if row else 0})
    except Exception:
        return jsonify({"count": 0})


@notif_bp.post("/api/notificaciones/marcar_leidas")
def api_marcar_leidas():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"ok": False}), 401
    con = get_db()
    try:
        con.run(
            "UPDATE notificaciones SET leida=TRUE WHERE dest_id=:uid AND leida=FALSE",
            uid=uid
        )
        return jsonify({"ok": True, "count": 0})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@notif_bp.post("/api/notificaciones/marcar_una/<int:nid>")
def api_marcar_una(nid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"ok": False}), 401
    con = get_db()
    try:
        con.run(
            "UPDATE notificaciones SET leida=TRUE WHERE id=:nid AND dest_id=:uid",
            nid=nid, uid=uid
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
