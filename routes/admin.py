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


# ── Control de fases de pronósticos ─────────────────────────────────────────

FASES_VALIDAS = ("grupos", "r16", "octavos", "cuartos", "semis", "final")


@admin_bp.route("/admin/fases_lock")
@admin_required
def fases_lock_get():
    """Devuelve el estado de bloqueo de todas las fases."""
    con = get_db()
    resultado = {}
    for fase in FASES_VALIDAS:
        row = con.execute("SELECT valor FROM config WHERE clave=%s", (f"fase_lock_{fase}",)).fetchone()
        resultado[fase] = bool(int(row["valor"])) if row else True
    return jsonify(resultado)


@admin_bp.route("/admin/fases_lock", methods=["POST"])
@admin_required
def fases_lock_set():
    """Bloquea o desbloquea una fase."""
    fase   = request.form.get("fase", "").strip()
    estado = request.form.get("estado", "1").strip()  # "1" = bloqueado, "0" = desbloqueado
    if fase not in FASES_VALIDAS:
        return jsonify(ok=False, msg="Fase inválida"), 400
    if estado not in ("0", "1"):
        return jsonify(ok=False, msg="Estado inválido"), 400
    con = get_db()
    con.execute("""
        INSERT INTO config(clave, valor) VALUES(%s, %s)
        ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor
    """, (f"fase_lock_{fase}", estado))
    con.commit()
    accion = "bloqueada" if estado == "1" else "desbloqueada"
    return jsonify(ok=True, msg=f"Fase {fase} {accion}")


@admin_bp.route("/admin/toggle_verified", methods=["POST"])
@admin_required
def toggle_verified():
    """Activa o desactiva la verificación de un usuario."""
    uid_target = request.form.get("uid")
    if not uid_target:
        return jsonify(ok=False, msg="uid requerido"), 400
    con = get_db()
    row = con.execute("SELECT verified FROM usuarios WHERE id=%s", (uid_target,)).fetchone()
    if not row:
        return jsonify(ok=False, msg="Usuario no encontrado"), 404
    nuevo = not bool(row["verified"])
    con.execute("UPDATE usuarios SET verified=%s WHERE id=%s", (nuevo, uid_target))
    con.commit()
    return jsonify(ok=True, verified=nuevo,
                   msg="Verificación activada" if nuevo else "Verificación desactivada")
