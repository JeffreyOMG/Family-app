from flask import Blueprint, jsonify, session
from database import get_db
import re

notif_bp = Blueprint("notif", __name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

def crear_notificacion(con, dest_id, tipo, actor_id=None, post_id=None,
                       comentario_id=None, texto_extra=""):
    """Inserta una notificación. No lanza excepción si falla."""
    try:
        if not dest_id:
            return
        # No auto-notificar
        if actor_id and actor_id == dest_id:
            return
        # Anti-spam: no duplicar la misma acción en < 60 min
        dup = con.execute(
            """SELECT id FROM notificaciones
               WHERE dest_id=%s AND tipo=%s AND actor_id=%s
                 AND (post_id=%s OR (post_id IS NULL AND %s IS NULL))
                 AND fecha > NOW() - INTERVAL '60 minutes'
               LIMIT 1""",
            (dest_id, tipo, actor_id, post_id, post_id)
        ).fetchone()
        if dup:
            return
        con.execute(
            """INSERT INTO notificaciones
               (dest_id, tipo, actor_id, post_id, comentario_id, texto_extra)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (dest_id, tipo, actor_id, post_id, comentario_id, texto_extra or "")
        )
        con.commit()
    except Exception as e:
        print(f"[notif] crear_notificacion error: {e}")


def notificar_menciones(con, actor_id, texto, post_id=None, comentario_id=None):
    """Detecta @usuario en texto y crea notificaciones de mención."""
    try:
        menciones = re.findall(r"@(\w+)", texto or "")
        for username in set(menciones):
            row = con.execute(
                "SELECT id FROM usuarios WHERE usuario=%s LIMIT 1",
                (username,)
            ).fetchone()
            if row:
                dest_id = row["id"]
                crear_notificacion(
                    con, dest_id=dest_id, tipo="mencion",
                    actor_id=actor_id, post_id=post_id,
                    comentario_id=comentario_id
                )
    except Exception as e:
        print(f"[notif] notificar_menciones error: {e}")


def notificar_admin_post(con, post_id, admin_id):
    """Notifica a todos los usuarios (excepto el admin) de un nuevo post de admin."""
    try:
        usuarios = con.execute(
            "SELECT id FROM usuarios WHERE id != %s",
            (admin_id,)
        ).fetchall()
        for u in usuarios:
            crear_notificacion(
                con, dest_id=u["id"], tipo="admin_post",
                actor_id=admin_id, post_id=post_id
            )
    except Exception as e:
        print(f"[notif] notificar_admin_post error: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@notif_bp.get("/api/notificaciones")
def api_listar():
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False, "error": "no auth"}), 401
    con = get_db()
    try:
        rows = con.execute(
            """SELECT n.id, n.tipo, n.leida, n.fecha, n.texto_extra,
                      n.post_id, n.comentario_id,
                      u.usuario AS actor_nombre, u.foto AS actor_foto
               FROM notificaciones n
               LEFT JOIN usuarios u ON u.id = n.actor_id
               WHERE n.dest_id = %s
               ORDER BY n.fecha DESC
               LIMIT 50""",
            (uid,)
        ).fetchall()
        notifs = []
        for r in rows:
            notifs.append({
                "id":            r["id"],
                "tipo":          r["tipo"],
                "leida":         bool(r["leida"]),
                "fecha":         str(r["fecha"]) if r["fecha"] else None,
                "texto_extra":   r["texto_extra"] or "",
                "post_id":       r["post_id"],
                "comentario_id": r["comentario_id"],
                "actor_nombre":  r["actor_nombre"] or "",
                "actor_foto":    r["actor_foto"] or "",
            })
        return jsonify({"ok": True, "notificaciones": notifs})
    except Exception as e:
        print(f"[notif] api_listar error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@notif_bp.get("/api/notificaciones/no_leidas")
def api_no_leidas():
    uid = session.get("uid")
    if not uid:
        return jsonify({"count": 0}), 401
    con = get_db()
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM notificaciones WHERE dest_id=%s AND leida=FALSE",
            (uid,)
        ).fetchone()
        return jsonify({"count": int(row[0] if row else 0)})
    except Exception as e:
        print(f"[notif] api_no_leidas error: {e}")
        return jsonify({"count": 0})


@notif_bp.post("/api/notificaciones/marcar_leidas")
def api_marcar_leidas():
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False}), 401
    con = get_db()
    try:
        con.execute(
            "UPDATE notificaciones SET leida=TRUE WHERE dest_id=%s AND leida=FALSE",
            (uid,)
        )
        con.commit()
        return jsonify({"ok": True, "count": 0})
    except Exception as e:
        print(f"[notif] api_marcar_leidas error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@notif_bp.post("/api/notificaciones/marcar_una/<int:nid>")
def api_marcar_una(nid):
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False}), 401
    con = get_db()
    try:
        con.execute(
            "UPDATE notificaciones SET leida=TRUE WHERE id=%s AND dest_id=%s",
            (nid, uid)
        )
        con.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[notif] api_marcar_una error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
