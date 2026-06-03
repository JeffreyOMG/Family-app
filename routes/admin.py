from flask import Blueprint, render_template, request, redirect, session, jsonify
from database import get_db
from functools import wraps

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("rol") != "admin":
            return redirect("/dashboard")
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/admin")
@admin_required
def panel():
    con = get_db()
    usuarios = con.execute(
        "SELECT id, nombre, usuario, gmail, rol, fecha FROM usuarios ORDER BY fecha DESC"
    ).fetchall()
    return render_template("admin/panel.html", usuarios=usuarios,
                           usuario={"nombre": session["nombre"], "rol": session["rol"], "foto": ""})


@admin_bp.route("/admin/cambiar_rol", methods=["POST"])
@admin_required
def cambiar_rol():
    uid  = request.form.get("uid", type=int)
    rol  = request.form.get("rol", "").strip()
    ROLES_VALIDOS = ("invitado", "miembro", "admin")
    if not uid or rol not in ROLES_VALIDOS:
        return jsonify(ok=False, msg="Datos inválidos"), 400

    # Evitar que el admin se quite su propio rol
    if uid == session.get("uid") and rol != "admin":
        return jsonify(ok=False, msg="No puedes cambiar tu propio rol de admin"), 403

    con = get_db()
    con.execute("UPDATE usuarios SET rol=%s WHERE id=%s", (rol, uid))
    con.commit()
    return jsonify(ok=True, msg=f"Rol actualizado a {rol}")


@admin_bp.route("/admin/banear", methods=["POST"])
@admin_required
def banear():
    uid    = request.form.get("uid", type=int)
    accion = request.form.get("accion", "ban")  # 'ban' | 'unban'
    if not uid:
        return jsonify(ok=False, msg="Datos inválidos"), 400
    if uid == session.get("uid"):
        return jsonify(ok=False, msg="No puedes banearte a ti mismo"), 403

    con = get_db()
    if accion == "ban":
        con.execute("UPDATE usuarios SET rol='baneado' WHERE id=%s", (uid,))
    else:
        con.execute("UPDATE usuarios SET rol='invitado' WHERE id=%s", (uid,))
    con.commit()
    return jsonify(ok=True)


@admin_bp.route("/admin/eliminar", methods=["POST"])
@admin_required
def eliminar():
    uid = request.form.get("uid", type=int)
    if not uid or uid == session.get("uid"):
        return jsonify(ok=False, msg="Acción no permitida"), 403
    con = get_db()
    con.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
    con.commit()
    return jsonify(ok=True)


@admin_bp.route("/admin/mundial_solicitudes")
@admin_required
def mundial_solicitudes():
    """Lista invitados con solicitud de pago pendiente o rechazada."""
    con = get_db()
    solicitudes = con.execute("""
        SELECT id, nombre, usuario, gmail, mundial_pagado
        FROM usuarios
        WHERE mundial_pagado IS NOT NULL AND mundial_pagado != 'aprobado'
        ORDER BY nombre
    """).fetchall()
    return jsonify([dict(s) for s in solicitudes])


@admin_bp.route("/admin/mundial_verificar", methods=["POST"])
@admin_required
def mundial_verificar():
    """Admin aprueba o rechaza el acceso al mundial de un invitado."""
    uid    = request.form.get("uid", type=int)
    accion = request.form.get("accion", "")  # 'aprobar' | 'rechazar'
    if not uid or accion not in ("aprobar", "rechazar"):
        return jsonify(ok=False, msg="Datos inválidos"), 400

    con = get_db()
    nuevo_estado = "aprobado" if accion == "aprobar" else "rechazado"
    con.execute("UPDATE usuarios SET mundial_pagado=%s WHERE id=%s", (nuevo_estado, uid))
    con.commit()
    return jsonify(ok=True, msg=f"Usuario {'aprobado' if accion=='aprobar' else 'rechazado'} para el mundial")
