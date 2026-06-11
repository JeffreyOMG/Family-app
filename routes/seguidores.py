"""
FASE 3.1 - Sistema de Seguidores
Backend puro: sin cambios visuales, solo lógica y endpoints.
"""
from flask import Blueprint, jsonify, session
from database import get_db

seguidores_bp = Blueprint("seguidores", __name__)


# ─────────────────────────────────────────────
# FUNCIONES BACKEND (lógica reutilizable)
# ─────────────────────────────────────────────

def seguir_usuario(follower_id: int, following_id: int) -> dict:
    """
    El usuario follower_id empieza a seguir a following_id.
    Reglas:
      - Un usuario no puede seguirse a sí mismo.
      - Si ya existe la relación, no se crea un duplicado.
    Retorna dict con ok, mensaje y acción realizada.
    """
    if follower_id == following_id:
        return {"ok": False, "error": "Un usuario no puede seguirse a sí mismo."}

    con = get_db()

    # Verificar si ya existe la relación
    existe = con.execute(
        "SELECT id FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, following_id)
    ).fetchone()

    if existe:
        return {"ok": True, "accion": "ya_seguia", "msg": "Ya seguías a este usuario."}

    # Verificar que el usuario objetivo existe
    objetivo = con.execute(
        "SELECT id FROM usuarios WHERE id=%s", (following_id,)
    ).fetchone()
    if not objetivo:
        return {"ok": False, "error": "Usuario no encontrado."}

    con.execute(
        "INSERT INTO followers (follower_id, following_id) VALUES (%s, %s)",
        (follower_id, following_id)
    )
    con.commit()

    # ── Notificación de nuevo seguidor ────────────────────────────────────────
    try:
        from routes.notificaciones import crear_notificacion
        crear_notificacion(con, dest_id=following_id, tipo="seguidor",
                           actor_id=follower_id)
        con.commit()
    except Exception:
        pass

    return {"ok": True, "accion": "seguido", "msg": "Ahora sigues a este usuario."}


def dejar_de_seguir(follower_id: int, following_id: int) -> dict:
    """
    El usuario follower_id deja de seguir a following_id.
    Si no existía la relación, responde sin error (idempotente).
    """
    if follower_id == following_id:
        return {"ok": False, "error": "Operación inválida."}

    con = get_db()
    con.execute(
        "DELETE FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, following_id)
    )
    con.commit()
    return {"ok": True, "accion": "dejado_de_seguir", "msg": "Dejaste de seguir a este usuario."}


def obtener_seguidores(usuario_id: int) -> list:
    """
    Retorna lista de usuarios que siguen a usuario_id.
    Cada elemento incluye: id, nombre, usuario, foto.
    """
    con = get_db()
    rows = con.execute(
        """SELECT u.id, u.nombre, u.usuario, u.foto, COALESCE(u.verified,FALSE) AS verified
           FROM followers f
           JOIN usuarios u ON u.id = f.follower_id
           WHERE f.following_id = %s
           ORDER BY f.created_at DESC""",
        (usuario_id,)
    ).fetchall()
    return [
        {
            "id":      r["id"],
            "nombre":  r["nombre"],
            "usuario": r["usuario"],
            "foto":    r["foto"] or "",
            "verified": bool(r.get("verified", False)),
        }
        for r in rows
    ]


def obtener_siguiendo(usuario_id: int) -> list:
    """
    Retorna lista de usuarios a los que sigue usuario_id.
    Cada elemento incluye: id, nombre, usuario, foto.
    """
    con = get_db()
    rows = con.execute(
        """SELECT u.id, u.nombre, u.usuario, u.foto, COALESCE(u.verified,FALSE) AS verified
           FROM followers f
           JOIN usuarios u ON u.id = f.following_id
           WHERE f.follower_id = %s
           ORDER BY f.created_at DESC""",
        (usuario_id,)
    ).fetchall()
    return [
        {
            "id":      r["id"],
            "nombre":  r["nombre"],
            "usuario": r["usuario"],
            "foto":    r["foto"] or "",
            "verified": bool(r.get("verified", False)),
        }
        for r in rows
    ]


def contar_seguidores(usuario_id: int) -> int:
    """Retorna el número de seguidores de usuario_id."""
    con = get_db()
    row = con.execute(
        "SELECT COUNT(*) FROM followers WHERE following_id=%s", (usuario_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def contar_siguiendo(usuario_id: int) -> int:
    """Retorna el número de usuarios que sigue usuario_id."""
    con = get_db()
    row = con.execute(
        "SELECT COUNT(*) FROM followers WHERE follower_id=%s", (usuario_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def esta_siguiendo(follower_id: int, following_id: int) -> bool:
    """Comprueba si follower_id ya sigue a following_id."""
    if follower_id == following_id:
        return False
    con = get_db()
    row = con.execute(
        "SELECT id FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, following_id)
    ).fetchone()
    return row is not None


# ─────────────────────────────────────────────
# ENDPOINTS REST
# ─────────────────────────────────────────────

def _auth_required():
    """Helper: retorna uid de sesión o None."""
    return session.get("uid")


@seguidores_bp.route("/api/seguir/<int:following_id>", methods=["POST"])
def endpoint_seguir(following_id):
    """POST /api/seguir/<id> — Seguir a un usuario."""
    uid = _auth_required()
    if not uid:
        return jsonify({"ok": False, "error": "No autenticado."}), 401
    resultado = seguir_usuario(uid, following_id)
    status = 200 if resultado["ok"] else 400
    return jsonify(resultado), status


@seguidores_bp.route("/api/dejar_de_seguir/<int:following_id>", methods=["POST"])
def endpoint_dejar_de_seguir(following_id):
    """POST /api/dejar_de_seguir/<id> — Dejar de seguir a un usuario."""
    uid = _auth_required()
    if not uid:
        return jsonify({"ok": False, "error": "No autenticado."}), 401
    resultado = dejar_de_seguir(uid, following_id)
    return jsonify(resultado), 200


@seguidores_bp.route("/api/seguidores/<int:usuario_id>")
def endpoint_seguidores(usuario_id):
    """GET /api/seguidores/<id> — Lista de seguidores de un usuario."""
    if not _auth_required():
        return jsonify({"ok": False, "error": "No autenticado."}), 401
    lista = obtener_seguidores(usuario_id)
    total = contar_seguidores(usuario_id)
    return jsonify({"ok": True, "total": total, "seguidores": lista})


@seguidores_bp.route("/api/siguiendo/<int:usuario_id>")
def endpoint_siguiendo(usuario_id):
    """GET /api/siguiendo/<id> — Lista de usuarios que sigue usuario_id."""
    if not _auth_required():
        return jsonify({"ok": False, "error": "No autenticado."}), 401
    lista = obtener_siguiendo(usuario_id)
    total = contar_siguiendo(usuario_id)
    return jsonify({"ok": True, "total": total, "siguiendo": lista})


@seguidores_bp.route("/api/conteo_seguidores/<int:usuario_id>")
def endpoint_conteo(usuario_id):
    """
    GET /api/conteo_seguidores/<id>
    Retorna conteo de seguidores, siguiendo, y si el usuario
    autenticado ya sigue a este perfil.
    """
    uid = _auth_required()
    if not uid:
        return jsonify({"ok": False, "error": "No autenticado."}), 401
    return jsonify({
        "ok":              True,
        "seguidores":      contar_seguidores(usuario_id),
        "siguiendo":       contar_siguiendo(usuario_id),
        "yo_lo_sigo":      esta_siguiendo(uid, usuario_id),
        "me_sigue":        esta_siguiendo(usuario_id, uid),
    })
