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
        "SELECT id, nombre, usuario, gmail, rol, fecha, COALESCE(verified, FALSE) AS verified, COALESCE(es_financiero, FALSE) AS es_financiero, COALESCE(polla_activo, TRUE) AS polla_activo, COALESCE(polla_estado, 'activo') AS polla_estado FROM usuarios ORDER BY fecha DESC"
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


@admin_bp.route("/admin/usuarios_bloqueo")
@admin_required
def usuarios_bloqueo():
    """Devuelve todos los miembros con estado de bloqueo de sección y participación polla."""
    con = get_db()
    rows = con.execute("""
        SELECT u.id, u.nombre, u.usuario, u.foto, u.rol,
               COALESCE(u.rec_bloqueado, 0)      AS rec_bloqueado,
               COALESCE(u.polla_activo, TRUE)     AS polla_activo,
               COALESCE(u.polla_estado, 'activo') AS polla_estado,
               COALESCE(SUM(a.monto), 0)          AS total_aportado
        FROM usuarios u
        LEFT JOIN aportes a ON a.usuario_id = u.id
        WHERE u.rol IN ('miembro', 'admin')
        GROUP BY u.id, u.nombre, u.usuario, u.foto, u.rol,
                 u.rec_bloqueado, u.polla_activo, u.polla_estado
        ORDER BY u.nombre ASC
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/admin/toggle_bloqueo", methods=["POST"])
@admin_required
def toggle_bloqueo():
    """Bloquea o desbloquea el acceso de un miembro a la sección de recaudación."""
    uid_target = request.form.get("uid", type=int)
    if not uid_target:
        return jsonify(ok=False, msg="uid requerido"), 400
    if uid_target == session.get("uid"):
        return jsonify(ok=False, msg="No puedes bloquearte a ti mismo"), 403
    con = get_db()
    row = con.execute(
        "SELECT nombre, COALESCE(rec_bloqueado, 0) AS rec_bloqueado FROM usuarios WHERE id=%s",
        (uid_target,)
    ).fetchone()
    if not row:
        return jsonify(ok=False, msg="Usuario no encontrado"), 404
    nuevo = 0 if row["rec_bloqueado"] else 1
    con.execute("UPDATE usuarios SET rec_bloqueado=%s WHERE id=%s", (nuevo, uid_target))
    _registrar_auditoria(con, session["uid"], uid_target,
        "bloquear_seccion" if nuevo else "desbloquear_seccion",
        "rec_bloqueado", str(row["rec_bloqueado"]), str(nuevo))
    con.commit()
    bloqueado = bool(nuevo)
    return jsonify(ok=True, bloqueado=bloqueado,
                   msg=f"{'🔒 ' + row['nombre'] + ' bloqueado de la sección' if bloqueado else '🔓 ' + row['nombre'] + ' desbloqueado'}")



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


# ── Rol Financiero/a ──────────────────────────────────────────────────────────

@admin_bp.route("/admin/toggle_financiero", methods=["POST"])
@admin_required
def toggle_financiero():
    """Asigna o retira el rol Financiero/a a un usuario."""
    uid_target = request.form.get("uid", type=int)
    if not uid_target:
        return jsonify(ok=False, msg="uid requerido"), 400
    if uid_target == session.get("uid"):
        return jsonify(ok=False, msg="No puedes modificar tu propio rol financiero"), 403
    con = get_db()
    row = con.execute(
        "SELECT nombre, rol, COALESCE(es_financiero, FALSE) AS es_financiero FROM usuarios WHERE id=%s",
        (uid_target,)
    ).fetchone()
    if not row:
        return jsonify(ok=False, msg="Usuario no encontrado"), 404
    if row["rol"] == "admin":
        return jsonify(ok=False, msg="Los admins ya tienen acceso completo"), 400
    nuevo = not bool(row["es_financiero"])
    con.execute("UPDATE usuarios SET es_financiero=%s WHERE id=%s", (nuevo, uid_target))
    # Auditoría
    _registrar_auditoria(con, session["uid"], uid_target,
        "asignar_financiero" if nuevo else "retirar_financiero",
        "es_financiero", str(not nuevo), str(nuevo))
    con.commit()
    return jsonify(ok=True, es_financiero=nuevo,
                   msg=f"Rol Financiero/a {'asignado a' if nuevo else 'retirado de'} {row['nombre']}")


@admin_bp.route("/admin/financieros")
@admin_required
def listar_financieros():
    """Lista todos los usuarios con rol Financiero/a activo."""
    con = get_db()
    rows = con.execute(
        "SELECT id, nombre, usuario, rol FROM usuarios WHERE COALESCE(es_financiero, FALSE) = TRUE ORDER BY nombre"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── Gestión de participantes de polla (solo miembros) ────────────────────────

@admin_bp.route("/admin/polla_participantes")
@admin_required
def polla_participantes():
    """Devuelve todos los miembros con su estado de participación en la polla."""
    con = get_db()
    rows = con.execute("""
        SELECT u.id, u.nombre, u.usuario, u.foto,
               COALESCE(u.polla_activo, TRUE) AS polla_activo,
               COALESCE(u.polla_estado, 'activo') AS polla_estado,
               COALESCE(u.rec_bloqueado, 0) AS rec_bloqueado
        FROM usuarios u
        WHERE u.rol IN ('miembro', 'admin')
        ORDER BY u.nombre ASC
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/admin/polla_estado", methods=["POST"])
@admin_required
def polla_estado():
    """Cambia el estado de participación de un miembro en la polla."""
    uid_target = request.form.get("uid", type=int)
    nuevo_estado = request.form.get("estado", "").strip()
    motivo = request.form.get("motivo", "").strip()[:300]

    ESTADOS_VALIDOS = ("activo", "bloqueado", "inactivo", "desactivado", "excluido")
    if not uid_target or nuevo_estado not in ESTADOS_VALIDOS:
        return jsonify(ok=False, msg="Datos inválidos"), 400
    if uid_target == session.get("uid"):
        return jsonify(ok=False, msg="No puedes modificarte a ti mismo"), 403

    con = get_db()
    row = con.execute(
        "SELECT nombre, rol, COALESCE(polla_estado,'activo') AS polla_estado FROM usuarios WHERE id=%s",
        (uid_target,)
    ).fetchone()
    if not row:
        return jsonify(ok=False, msg="Usuario no encontrado"), 404
    if row["rol"] not in ("miembro", "admin"):
        return jsonify(ok=False, msg="Solo aplica a miembros"), 400

    polla_activo = (nuevo_estado == "activo")
    estado_antes = row["polla_estado"]
    con.execute(
        "UPDATE usuarios SET polla_activo=%s, polla_estado=%s WHERE id=%s",
        (polla_activo, nuevo_estado, uid_target)
    )
    _registrar_auditoria(con, session["uid"], uid_target,
        f"polla_estado_{nuevo_estado}", "polla_estado",
        estado_antes, nuevo_estado, motivo)
    con.commit()
    msgs = {
        "activo": "Participante reactivado ✅",
        "bloqueado": "Participante bloqueado 🚫",
        "inactivo": "Participante marcado como inactivo",
        "desactivado": "Participante desactivado temporalmente",
        "excluido": "Participante excluido de la polla",
    }
    return jsonify(ok=True, msg=msgs.get(nuevo_estado, "Estado actualizado"),
                   polla_activo=polla_activo, polla_estado=nuevo_estado)


# ── Auditoría ─────────────────────────────────────────────────────────────────

def _registrar_auditoria(con, actor_id, target_id, accion, campo="", valor_antes="", valor_nuevo="", motivo=""):
    """Registra una acción en la tabla de auditoría financiera."""
    try:
        con.execute("""
            INSERT INTO auditoria_financiera(actor_id, target_id, accion, campo, valor_antes, valor_nuevo, motivo)
            VALUES(%s, %s, %s, %s, %s, %s, %s)
        """, (actor_id, target_id, accion, campo, str(valor_antes), str(valor_nuevo), motivo))
    except Exception as e:
        print(f"Auditoría warning: {e}")


@admin_bp.route("/admin/auditoria")
@admin_required
def auditoria():
    """Devuelve historial de auditoría financiera (últimas 200 acciones)."""
    con = get_db()
    rows = con.execute("""
        SELECT af.id, af.accion, af.campo, af.valor_antes, af.valor_nuevo,
               af.motivo, af.fecha,
               a.nombre AS actor_nombre, a.usuario AS actor_usuario,
               t.nombre AS target_nombre, t.usuario AS target_usuario
        FROM auditoria_financiera af
        JOIN usuarios a ON a.id = af.actor_id
        LEFT JOIN usuarios t ON t.id = af.target_id
        ORDER BY af.fecha DESC
        LIMIT 200
    """).fetchall()
    return jsonify([dict(r) for r in rows])
