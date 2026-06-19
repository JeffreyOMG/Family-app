from decorators import miembro_required, financiero_required
import json
from flask import Blueprint, request, redirect, session, jsonify
from database import get_db
from cloudinary_helper import subir_a_cloudinary

fin_bp = Blueprint("finanzas", __name__)

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

def _err(msg, code=400):
    if _is_ajax():
        return jsonify({"ok": False, "error": msg}), code
    return redirect("/dashboard?s=recaudacion")

def _save_file(file_obj):
    """Sube comprobante/soporte a Cloudinary. Retorna URL o None."""
    if not file_obj or not file_obj.filename:
        return None
    url, _ = subir_a_cloudinary(file_obj, folder="familia/finanzas")
    return url

def _es_admin_o_financiero():
    return session.get("rol") == "admin" or session.get("es_financiero", False)

def _registrar_auditoria(con, actor_id, target_id, accion, campo="", valor_antes="", valor_nuevo="", motivo=""):
    """Registra acción en auditoría financiera."""
    try:
        con.execute("""
            INSERT INTO auditoria_financiera(actor_id, target_id, accion, campo, valor_antes, valor_nuevo, motivo)
            VALUES(%s, %s, %s, %s, %s, %s, %s)
        """, (actor_id, target_id, accion, campo, str(valor_antes), str(valor_nuevo), motivo))
    except Exception as e:
        print(f"Auditoría fin warning: {e}")

@fin_bp.route("/aporte", methods=["POST"])
@miembro_required
def aporte():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    tipo = request.form.get("tipo_aporte", "evento")
    if tipo == "familia":
        return _aporte_familia()
    elif tipo == "evento":
        return _aporte_evento()
    elif tipo == "polla":
        return _aporte_polla()
    return (jsonify({"ok": False, "error": "tipo desconocido"}), 400) if _is_ajax() else redirect("/dashboard?s=recaudacion")

def _aporte_familia():
    uid = session["uid"]
    con = get_db()
    accion = request.form.get("accion_familia", "seleccionar")

    if accion == "crear":
        nombre = request.form.get("nombre_cajita", "").strip()[:100]
        desc   = request.form.get("desc_cajita", "").strip()[:300]
        miembros_ids = request.form.getlist("miembros_cajita")
        if not nombre:
            return _err("Nombre requerido")
        cur = con.execute(
            "INSERT INTO cajitas_ahorro(nombre, descripcion, creador_id) VALUES(%s, %s, %s) RETURNING id",
            (nombre, desc, uid)
        )
        cajita_id = cur.fetchone()[0]
        con.execute(
            "INSERT INTO cajita_miembros(cajita_id, usuario_id) VALUES(%s, %s) ON CONFLICT DO NOTHING",
            (cajita_id, uid)
        )
        for mid in miembros_ids:
            if mid.isdigit():
                con.execute(
                    "INSERT INTO cajita_miembros(cajita_id, usuario_id) VALUES(%s, %s) ON CONFLICT DO NOTHING",
                    (cajita_id, int(mid))
                )
        con.commit()
        if _is_ajax():
            return jsonify({"ok": True, "cajita_id": cajita_id, "nombre": nombre})
        return redirect(f"/dashboard?s=recaudacion&cajita={cajita_id}")

    elif accion == "movimiento":
        cajita_id = request.form.get("cajita_id", "")
        monto_raw = request.form.get("monto_cajita", "").strip()
        desc      = request.form.get("desc_movimiento", "").strip()[:200]
        if not cajita_id.isdigit():
            return _err("cajita_id inválido")
        cajita_id = int(cajita_id)
        miembro = con.execute(
            "SELECT 1 FROM cajita_miembros WHERE cajita_id=%s AND usuario_id=%s", (cajita_id, uid)
        ).fetchone()
        if not miembro:
            return _err("No eres miembro", 403)
        try:
            monto = float(monto_raw)
            if monto <= 0: raise ValueError
        except (ValueError, TypeError):
            return _err("Monto inválido")
        con.execute(
            "INSERT INTO cajita_movimientos(cajita_id, usuario_id, monto, descripcion) VALUES(%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (cajita_id, uid, monto, desc)
        )
        con.commit()
        if _is_ajax():
            return jsonify({"ok": True, "cajita_id": cajita_id, "monto": monto})
        return redirect(f"/dashboard?s=recaudacion&cajita={cajita_id}")

    return _err("accion desconocida")

def _aporte_evento():
    uid = session["uid"]
    con = get_db()
    nombre_ev    = request.form.get("nombre_evento", "").strip()[:150]
    desc         = request.form.get("desc_evento", "").strip()[:400]
    monto_raw    = request.form.get("monto_evento", "").strip()
    responsables = request.form.get("responsables", "").strip()[:300]
    soporte_f    = request.files.get("soporte_evento")

    if not nombre_ev:
        return _err("Nombre de evento requerido")
    soporte_url = _save_file(soporte_f)
    if not soporte_url:
        return _err("Comprobante requerido")
    try:
        monto = float(monto_raw)
        if monto <= 0: raise ValueError
    except (ValueError, TypeError):
        return _err("Monto inválido")

    con.execute(
        "INSERT INTO eventos_recaudacion(usuario_id, nombre_evento, descripcion, monto, responsables, soporte, estado) "
        "VALUES(%s, %s, %s, %s, %s, %s, %s)",
        (uid, nombre_ev, desc, monto, responsables, soporte_url, "pendiente")
    )
    con.execute(
        "INSERT INTO aportes(usuario_id, monto, descripcion, comprobante, verificado) VALUES(%s, %s, %s, %s, 0) ON CONFLICT DO NOTHING",
        (uid, monto, f"Evento: {nombre_ev}", soporte_url)
    )
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Aporte registrado"})
    return redirect("/dashboard?s=recaudacion")

FASES_POLLA  = {1: 30000, 2: 20000, 3: 10000}
FASES_NOMBRES = {1: "Fase 1 – Grupos", 2: "Fase 2 – Eliminatorias", 3: "Fase 3 – Semifinal y Final"}

def _aporte_polla():
    uid = session["uid"]
    con = get_db()
    fase_raw  = request.form.get("fase_polla", "")
    soporte_f = request.files.get("soporte_polla")

    if not fase_raw.isdigit():
        return _err("fase inválida")
    fase = int(fase_raw)
    if fase not in FASES_POLLA:
        return _err("fase desconocida")

    ya_pagado = con.execute(
        "SELECT 1 FROM polla_pagos WHERE usuario_id=%s AND fase=%s", (uid, fase)
    ).fetchone()
    if ya_pagado:
        return _err("Ya pagaste esta fase")

    soporte_url = _save_file(soporte_f)
    if not soporte_url:
        return _err("Comprobante requerido")

    monto = FASES_POLLA[fase]
    con.execute(
        "INSERT INTO polla_pagos(usuario_id, fase, monto, soporte, estado) VALUES(%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (uid, fase, monto, soporte_url, "pagado")
    )
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "fase": fase, "monto": monto})
    return redirect(f"/dashboard?s=recaudacion&polla_fase={fase}")

@fin_bp.route("/polla_pronostico", methods=["POST"])
def polla_pronostico():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    uid = session["uid"]
    con = get_db()
    fase_raw = request.form.get("fase", "")
    if not fase_raw.isdigit():
        return _err("fase inválida")
    fase = int(fase_raw)
    pagado = con.execute(
        "SELECT 1 FROM polla_pagos WHERE usuario_id=%s AND fase=%s", (uid, fase)
    ).fetchone()
    if not pagado:
        return _err("No has pagado esta fase", 403)
    datos = {k: v for k, v in request.form.items() if k != "fase"}
    con.execute(
        "INSERT INTO polla_pronosticos(usuario_id, fase, datos) VALUES(%s, %s, %s) "
        "ON CONFLICT(usuario_id, fase) DO UPDATE SET datos=excluded.datos",
        (uid, fase, json.dumps(datos))
    )
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Pronóstico guardado"})
    return redirect("/dashboard?s=recaudacion")

@fin_bp.route("/api/mis_cajitas")
def api_mis_cajitas():
    if "uid" not in session:
        return jsonify([])
    uid = session["uid"]
    con = get_db()
    cajitas = [dict(c) for c in con.execute("""
        SELECT ca.id, ca.nombre, ca.descripcion, ca.creador_id,
               COALESCE(SUM(cm.monto),0) AS total
        FROM cajitas_ahorro ca
        JOIN cajita_miembros m ON m.cajita_id=ca.id AND m.usuario_id=%s
        LEFT JOIN cajita_movimientos cm ON cm.cajita_id=ca.id
        GROUP BY ca.id ORDER BY ca.fecha DESC
    """, (uid,)).fetchall()]
    return jsonify(cajitas)

@fin_bp.route("/api/cajita/<int:cid>/movimientos")
def api_cajita_movimientos(cid):
    if "uid" not in session:
        return jsonify([])
    uid = session["uid"]
    con = get_db()
    miembro = con.execute(
        "SELECT 1 FROM cajita_miembros WHERE cajita_id=%s AND usuario_id=%s", (cid, uid)
    ).fetchone()
    if not miembro:
        return jsonify([])
    movs = [dict(m) for m in con.execute("""
        SELECT cm.id, cm.monto, cm.descripcion, cm.fecha, u.nombre
        FROM cajita_movimientos cm JOIN usuarios u ON u.id=cm.usuario_id
        WHERE cm.cajita_id=%s ORDER BY cm.fecha DESC
    """, (cid,)).fetchall()]
    return jsonify(movs)

@fin_bp.route("/api/mi_polla")
def api_mi_polla():
    if "uid" not in session:
        return jsonify({})
    uid = session["uid"]
    con = get_db()
    pagos = {p["fase"]: dict(p) for p in con.execute(
        "SELECT fase, monto, estado, fecha FROM polla_pagos WHERE usuario_id=%s", (uid,)
    ).fetchall()}
    return jsonify(pagos)

@fin_bp.route("/api/historial")
def api_historial():
    if "uid" not in session:
        return jsonify([])
    uid = session["uid"]
    con = get_db()
    registros = []
    for a in con.execute("""
        SELECT er.id, er.nombre_evento, er.descripcion, er.monto, er.responsables,
               er.soporte, er.estado, er.fecha, u.nombre AS usuario, u.rol AS rol,
               u.foto AS foto_perfil
        FROM eventos_recaudacion er JOIN usuarios u ON u.id=er.usuario_id
        WHERE u.rol IN ('miembro', 'admin')
        ORDER BY er.fecha DESC
    """).fetchall():
        registros.append({**dict(a), "tipo": "evento"})
    for p in con.execute("""
        SELECT pp.id, pp.fase, pp.monto, pp.soporte, pp.estado, pp.fecha,
               u.nombre AS usuario, u.rol AS rol, u.foto AS foto_perfil
        FROM polla_pagos pp JOIN usuarios u ON u.id=pp.usuario_id
        WHERE u.rol IN ('miembro', 'admin')
          AND COALESCE(u.polla_estado, 'activo') != 'excluido'
        ORDER BY pp.fecha DESC
    """).fetchall():
        registros.append({**dict(p), "tipo": "polla"})
    for m in con.execute("""
        SELECT cm.id, cm.monto, cm.descripcion, cm.fecha, u.nombre AS usuario,
               u.rol AS rol, u.foto AS foto_perfil, ca.nombre AS cajita_nombre
        FROM cajita_movimientos cm
        JOIN usuarios u ON u.id=cm.usuario_id
        JOIN cajitas_ahorro ca ON ca.id=cm.cajita_id
        JOIN cajita_miembros mb ON mb.cajita_id=ca.id AND mb.usuario_id=%s
        WHERE u.rol IN ('miembro', 'admin')
        ORDER BY cm.fecha DESC
    """, (uid,)).fetchall():
        registros.append({**dict(m), "tipo": "familia"})
    registros.sort(key=lambda x: x["fecha"], reverse=True)
    return jsonify(registros)

@fin_bp.route("/verificar_evento/<int:eid>", methods=["POST"])
def verificar_evento(eid):
    if not _es_admin_o_financiero():
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("UPDATE eventos_recaudacion SET estado='verificado' WHERE id=%s", (eid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard?s=recaudacion")

@fin_bp.route("/eliminar_aporte/<int:aid>", methods=["POST"])
def eliminar_aporte(aid):
    if not _es_admin_o_financiero():
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("DELETE FROM aportes WHERE id=%s", (aid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")

@fin_bp.route("/verificar_aporte/<int:aid>", methods=["POST"])
def verificar_aporte(aid):
    if not _es_admin_o_financiero():
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("UPDATE aportes SET verificado=1 WHERE id=%s", (aid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")

@fin_bp.route("/verificar_polla/<int:pid>", methods=["POST"])
def verificar_polla(pid):
    if not _es_admin_o_financiero():
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("UPDATE polla_pagos SET estado='verificado' WHERE id=%s", (pid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard?s=recaudacion")

@fin_bp.route("/eliminar_pago/<tipo>/<int:rid>", methods=["POST"])
def eliminar_pago(tipo, rid):
    if not _es_admin_o_financiero():
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    if tipo == "evento":
        ev = con.execute("SELECT nombre_evento FROM eventos_recaudacion WHERE id=%s", (rid,)).fetchone()
        con.execute("DELETE FROM eventos_recaudacion WHERE id=%s", (rid,))
        if ev:
            con.execute("DELETE FROM aportes WHERE descripcion=%s", (f"Evento: {ev['nombre_evento']}",))
    elif tipo == "polla":
        con.execute("DELETE FROM polla_pagos WHERE id=%s", (rid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard?s=recaudacion")

@fin_bp.route("/api/admin/meta", methods=["POST"])
def api_admin_meta():
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    try:
        nueva_meta = float(data.get("meta", 0))
        if nueva_meta <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Meta inválida"}), 400
    con = get_db()
    con.execute(
        "INSERT INTO config(clave, valor) VALUES('meta_recaudacion', %s) "
        "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
        (str(nueva_meta),)
    )
    con.commit()
    return jsonify({"ok": True, "meta": nueva_meta})

@fin_bp.route("/api/admin/fix_polla_montos", methods=["POST"])
def fix_polla_montos():
    """Corrige montos de polla_pagos existentes segun los precios actuales por fase."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    con = get_db()
    actualizados = 0
    for fase, monto_correcto in FASES_POLLA.items():
        result = con.execute(
            "UPDATE polla_pagos SET monto=%s WHERE fase=%s AND monto!=%s",
            (monto_correcto, fase, monto_correcto)
        )
        actualizados += result.rowcount
    con.commit()
    return jsonify({"ok": True, "actualizados": actualizados})

@fin_bp.route("/api/admin/bloquear_recaudacion", methods=["POST"])
def bloquear_recaudacion():
    """Bloquea o desbloquea a un usuario de la sección de recaudación."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    usuario_id = data.get("usuario_id")
    if not usuario_id:
        return jsonify({"ok": False, "error": "usuario_id requerido"}), 400
    # No permitir bloquear al propio admin ni a ningún admin
    if int(usuario_id) == int(session.get("usuario_id", 0)):
        return jsonify({"ok": False, "error": "No puedes bloquearte a ti mismo"}), 400
    con = get_db()
    # Verificar que el objetivo no sea admin
    target = con.execute("SELECT rol, rec_bloqueado FROM usuarios WHERE id=%s", (usuario_id,)).fetchone()
    if target and target["rol"] == "admin":
        return jsonify({"ok": False, "error": "No se puede bloquear a un administrador"}), 400
    # Toggle: si ya está bloqueado, desbloquear; si no, bloquear
    row = target
    if not row:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404
    nuevo_estado = 0 if row["rec_bloqueado"] else 1
    con.execute("UPDATE usuarios SET rec_bloqueado=%s WHERE id=%s", (nuevo_estado, usuario_id))
    con.commit()
    return jsonify({"ok": True, "bloqueado": bool(nuevo_estado)})

@fin_bp.route("/api/admin/quitar_polla", methods=["POST"])
def quitar_polla():
    """Elimina el pago de polla de un usuario en una fase específica (admin)."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    usuario_id = data.get("usuario_id")
    fase = data.get("fase")
    if not usuario_id or not fase:
        return jsonify({"ok": False, "error": "usuario_id y fase requeridos"}), 400
    con = get_db()
    result = con.execute(
        "DELETE FROM polla_pagos WHERE usuario_id=%s AND fase=%s",
        (usuario_id, fase)
    )
    con.commit()
    if result.rowcount == 0:
        return jsonify({"ok": False, "error": "No se encontró el pago"}), 404
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# NUEVOS ENDPOINTS: Gestión de Invitados, Edición Rápida, Auditoría
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# NUEVOS ENDPOINTS: Gestión de Invitados, Edición Rápida, Auditoría
# ══════════════════════════════════════════════════════════════════════════════

@fin_bp.route("/api/fin/invitados")
def api_invitados():
    """
    Lista todos los usuarios con rol 'invitado' con datos financieros completos.
    Incluye invitado_de: el miembro responsable de cada invitado.
    Reutiliza tablas existentes: aportes, polla_pagos, usuarios.
    """
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    con = get_db()
    PRECIO_POLLA = {1: 30000, 2: 20000, 3: 10000}

    # Datos base de todos los invitados + responsable (miembro que los trajo)
    rows = con.execute("""
        SELECT
            u.id, u.nombre, u.usuario, u.foto,
            COALESCE(u.mundial_pagado, 'sin_solicitud')   AS mundial_pagado,
            COALESCE(u.rec_bloqueado, 0)                   AS rec_bloqueado,
            COALESCE(u.invitado_de, 0)                     AS invitado_de,
            resp.nombre                                    AS responsable_nombre,
            resp.usuario                                   AS responsable_usuario,
            COALESCE(SUM(a.monto), 0)                      AS total_aportes,
            COUNT(DISTINCT a.id)                           AS num_aportes,
            COALESCE(SUM(CASE WHEN a.verificado=1 THEN a.monto ELSE 0 END), 0)
                                                           AS aportes_verificados,
            MAX(a.fecha)                                   AS ultima_actualizacion
        FROM usuarios u
        LEFT JOIN usuarios resp ON resp.id = u.invitado_de
        LEFT JOIN aportes a ON a.usuario_id = u.id
        WHERE u.rol = 'invitado'
        GROUP BY u.id, u.nombre, u.usuario, u.foto,
                 u.mundial_pagado, u.rec_bloqueado, u.invitado_de,
                 resp.nombre, resp.usuario
        ORDER BY u.nombre ASC
    """).fetchall()

    # Pagos polla de invitados
    ids_inv = [r["id"] for r in rows]
    pagos_polla = {}
    if ids_inv:
        ph = ",".join(["%s"] * len(ids_inv))
        for p in con.execute(
            f"SELECT usuario_id, fase, monto, estado FROM polla_pagos WHERE usuario_id IN ({ph})",
            ids_inv
        ).fetchall():
            pagos_polla.setdefault(p["usuario_id"], []).append(dict(p))

    # Último modificador desde auditoría
    ultimos = {}
    try:
        for a in con.execute("""
            SELECT DISTINCT ON (af.target_id)
                af.target_id, af.fecha AS audit_fecha, u.nombre AS modificado_por
            FROM auditoria_financiera af
            JOIN usuarios u ON u.id = af.actor_id
            WHERE af.target_id = ANY(%s::int[])
            ORDER BY af.target_id, af.fecha DESC
        """, (ids_inv,)).fetchall():
            ultimos[a["target_id"]] = {"fecha": str(a["audit_fecha"])[:16], "por": a["modificado_por"]}
    except Exception:
        pass

    # Miembros disponibles para asignar como responsable
    miembros = [dict(m) for m in con.execute(
        "SELECT id, nombre, usuario FROM usuarios WHERE rol IN ('miembro','admin') ORDER BY nombre"
    ).fetchall()]

    resultado = []
    for r in rows:
        inv = dict(r)
        fases = pagos_polla.get(r["id"], [])
        polla_pag  = sum(PRECIO_POLLA.get(f["fase"], f["monto"] or 0) for f in fases if f["estado"] in ("pagado","verificado"))
        polla_pend = sum(PRECIO_POLLA.get(f["fase"], f["monto"] or 0) for f in fases if f["estado"] == "pendiente")
        total_pag  = float(r["aportes_verificados"]) + polla_pag
        saldo      = max(float(r["total_aportes"]) - float(r["aportes_verificados"]) + polla_pend, 0)
        uc = ultimos.get(r["id"], {})
        inv.update({
            "polla_pagado":         polla_pag,
            "polla_pendiente":      polla_pend,
            "polla_fases":          fases,
            "participa_polla":      len(fases) > 0,
            "total_pagado":         total_pag,
            "saldo_pendiente":      saldo,
            "ultima_actualizacion": str(r["ultima_actualizacion"] or "")[:10],
            "modificado_por":       uc.get("por", "—"),
        })
        resultado.append(inv)

    return jsonify({"invitados": resultado, "miembros": miembros})


@fin_bp.route("/api/fin/set_responsable", methods=["POST"])
def set_responsable():
    """Asigna o cambia el miembro responsable de un invitado (columna invitado_de)."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    inv_id  = data.get("invitado_id")
    resp_id = data.get("responsable_id")  # None = quitar responsable
    nota    = data.get("nota", "")
    if not inv_id:
        return jsonify({"ok": False, "error": "invitado_id requerido"}), 400
    con = get_db()
    row = con.execute(
        "SELECT nombre, COALESCE(invitado_de, 0) AS invitado_de FROM usuarios WHERE id=%s AND rol='invitado'",
        (inv_id,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Invitado no encontrado"}), 404
    con.execute("UPDATE usuarios SET invitado_de=%s WHERE id=%s", (resp_id or None, inv_id))
    _registrar_auditoria(con, session["uid"], inv_id,
        "asignar_responsable", "invitado_de", str(row["invitado_de"]),
        str(resp_id or "") + (f" | nota: {nota}" if nota else ""))
    con.commit()
    return jsonify({"ok": True, "msg": "Responsable actualizado"})






@fin_bp.route("/api/fin/set_estado_invitado", methods=["POST"])
def set_estado_invitado():
    """Fija explícitamente el estado (Activo/Bloqueado) de un invitado.
    A diferencia de /api/admin/bloquear_recaudacion (que solo alterna),
    este recibe el valor deseado directamente — útil para el modal de edición."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    inv_id = data.get("invitado_id")
    bloqueado = data.get("bloqueado")
    if not inv_id or bloqueado is None:
        return jsonify({"ok": False, "error": "invitado_id y bloqueado requeridos"}), 400
    con = get_db()
    row = con.execute(
        "SELECT rec_bloqueado FROM usuarios WHERE id=%s AND rol='invitado'", (inv_id,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Invitado no encontrado"}), 404
    nuevo = 1 if bloqueado else 0
    if int(row["rec_bloqueado"] or 0) != nuevo:
        con.execute("UPDATE usuarios SET rec_bloqueado=%s WHERE id=%s", (nuevo, inv_id))
        _registrar_auditoria(con, session["uid"], inv_id, "editar_estado_invitado",
            "rec_bloqueado", row["rec_bloqueado"], nuevo, data.get("motivo", ""))
        con.commit()
    return jsonify({"ok": True, "bloqueado": bool(nuevo)})


@fin_bp.route("/api/fin/ajustar_finanzas", methods=["POST"])
def ajustar_finanzas():
    """Permite a Admin/Financiero fijar manualmente el TOTAL APORTADO y el
    PAGADO de un invitado. Internamente se registra como ajustes en la
    tabla `aportes` (sin tocar el esquema) para mantener consistencia con
    el resto del sistema y quedar reflejado en auditoría/historial.
    El SALDO se recalcula solo a partir de estos dos valores."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403

    data = request.get_json(silent=True) or {}
    inv_id = data.get("invitado_id")
    if not inv_id:
        return jsonify({"ok": False, "error": "invitado_id requerido"}), 400

    con = get_db()
    inv = con.execute(
        "SELECT id, nombre FROM usuarios WHERE id=%s AND rol='invitado'", (inv_id,)
    ).fetchone()
    if not inv:
        return jsonify({"ok": False, "error": "Invitado no encontrado"}), 404

    motivo = data.get("motivo", "") or "Ajuste manual desde Gestión de Invitados"
    actor_id = session["uid"]
    cambios = []

    # Estado actual real
    actual = con.execute("""
        SELECT COALESCE(SUM(monto),0) AS total,
               COALESCE(SUM(CASE WHEN verificado=1 THEN monto ELSE 0 END),0) AS pagado
        FROM aportes WHERE usuario_id=%s
    """, (inv_id,)).fetchone()
    total_actual  = float(actual["total"])
    pagado_actual = float(actual["pagado"])

    nuevo_total  = data.get("total")
    nuevo_pagado = data.get("pagado")

    # 1) Ajustar PAGADO primero (esto también afecta el total, por eso se
    #    corrige el total después con el valor ya actualizado).
    if nuevo_pagado is not None:
        try:
            nuevo_pagado = float(nuevo_pagado)
            if nuevo_pagado < 0: raise ValueError
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Pagado inválido"}), 400
        delta_pagado = round(nuevo_pagado - pagado_actual, 2)
        if delta_pagado != 0:
            con.execute(
                "INSERT INTO aportes(usuario_id, monto, descripcion, verificado) VALUES(%s,%s,%s,1)",
                (inv_id, delta_pagado, "Ajuste manual (pagado)")
            )
            _registrar_auditoria(con, actor_id, inv_id, "ajustar_pagado_invitado",
                "pagado", pagado_actual, nuevo_pagado, motivo)
            total_actual += delta_pagado
            cambios.append("pagado")

    # 2) Ajustar TOTAL APORTADO al valor deseado (no afecta lo ya pagado).
    if nuevo_total is not None:
        try:
            nuevo_total = float(nuevo_total)
            if nuevo_total < 0: raise ValueError
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Total inválido"}), 400
        delta_total = round(nuevo_total - total_actual, 2)
        if delta_total != 0:
            con.execute(
                "INSERT INTO aportes(usuario_id, monto, descripcion, verificado) VALUES(%s,%s,%s,0)",
                (inv_id, delta_total, "Ajuste manual (total)")
            )
            _registrar_auditoria(con, actor_id, inv_id, "ajustar_total_invitado",
                "total_aportado", total_actual, nuevo_total, motivo)
            cambios.append("total")

    con.commit()
    if not cambios:
        return jsonify({"ok": True, "campos": [], "msg": "Sin cambios"})
    return jsonify({"ok": True, "campos": cambios, "msg": "Valores actualizados"})


@fin_bp.route("/api/fin/invitado/<int:uid_target>/aportes")
def api_invitado_aportes(uid_target):
    """Detalle de aportes de un invitado específico."""
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    con = get_db()
    aportes = con.execute("""
        SELECT id, monto, descripcion, comprobante, verificado, fecha
        FROM aportes WHERE usuario_id=%s ORDER BY fecha DESC
    """, (uid_target,)).fetchall()
    return jsonify([dict(a) for a in aportes])


@fin_bp.route("/api/fin/editar_aporte", methods=["POST"])
def editar_aporte():
    """Edición rápida de un aporte (monto, descripción, estado) para Admin/Financiero."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    aporte_id = data.get("id")
    if not aporte_id:
        return jsonify({"ok": False, "error": "id requerido"}), 400

    con = get_db()
    aporte = con.execute(
        "SELECT id, monto, descripcion, verificado, usuario_id FROM aportes WHERE id=%s",
        (aporte_id,)
    ).fetchone()
    if not aporte:
        return jsonify({"ok": False, "error": "Aporte no encontrado"}), 404

    cambios = []
    motivo = data.get("motivo", "")

    if "monto" in data:
        try:
            nuevo_monto = float(data["monto"])
            if nuevo_monto <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Monto inválido"}), 400
        _registrar_auditoria(con, session["uid"], aporte["usuario_id"],
            "editar_monto_aporte", "monto", aporte["monto"], nuevo_monto, motivo)
        con.execute("UPDATE aportes SET monto=%s WHERE id=%s", (nuevo_monto, aporte_id))
        cambios.append("monto")

    if "descripcion" in data:
        nueva_desc = str(data["descripcion"])[:300]
        _registrar_auditoria(con, session["uid"], aporte["usuario_id"],
            "editar_desc_aporte", "descripcion", aporte["descripcion"], nueva_desc, motivo)
        con.execute("UPDATE aportes SET descripcion=%s WHERE id=%s", (nueva_desc, aporte_id))
        cambios.append("descripcion")

    if "verificado" in data:
        nuevo_ver = 1 if data["verificado"] else 0
        _registrar_auditoria(con, session["uid"], aporte["usuario_id"],
            "editar_verificado_aporte", "verificado", aporte["verificado"], nuevo_ver, motivo)
        con.execute("UPDATE aportes SET verificado=%s WHERE id=%s", (nuevo_ver, aporte_id))
        cambios.append("verificado")

    con.commit()
    return jsonify({"ok": True, "campos": cambios})


@fin_bp.route("/api/fin/editar_evento", methods=["POST"])
def editar_evento():
    """Edición rápida de un evento de recaudación."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    ev_id = data.get("id")
    if not ev_id:
        return jsonify({"ok": False, "error": "id requerido"}), 400

    con = get_db()
    ev = con.execute(
        "SELECT id, monto, nombre_evento, estado, usuario_id FROM eventos_recaudacion WHERE id=%s",
        (ev_id,)
    ).fetchone()
    if not ev:
        return jsonify({"ok": False, "error": "Evento no encontrado"}), 404

    motivo = data.get("motivo", "")
    cambios = []

    if "monto" in data:
        try:
            nuevo_monto = float(data["monto"])
            if nuevo_monto <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"ok": False, "error": "Monto inválido"}), 400
        _registrar_auditoria(con, session["uid"], ev["usuario_id"],
            "editar_monto_evento", "monto", ev["monto"], nuevo_monto, motivo)
        con.execute("UPDATE eventos_recaudacion SET monto=%s WHERE id=%s", (nuevo_monto, ev_id))
        # Sync con tabla aportes
        con.execute("UPDATE aportes SET monto=%s WHERE descripcion=%s",
                    (nuevo_monto, f"Evento: {ev['nombre_evento']}"))
        cambios.append("monto")

    if "estado" in data:
        estados_v = ("pendiente", "verificado", "rechazado")
        nuevo_estado = data["estado"] if data["estado"] in estados_v else None
        if nuevo_estado:
            _registrar_auditoria(con, session["uid"], ev["usuario_id"],
                "editar_estado_evento", "estado", ev["estado"], nuevo_estado, motivo)
            con.execute("UPDATE eventos_recaudacion SET estado=%s WHERE id=%s", (nuevo_estado, ev_id))
            cambios.append("estado")

    con.commit()
    return jsonify({"ok": True, "campos": cambios})


@fin_bp.route("/api/fin/editar_polla_pago", methods=["POST"])
def editar_polla_pago():
    """Edición rápida de un pago de polla (estado)."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    data = request.get_json(silent=True) or {}
    pago_id = data.get("id")
    if not pago_id:
        return jsonify({"ok": False, "error": "id requerido"}), 400

    con = get_db()
    pago = con.execute(
        "SELECT id, estado, usuario_id, fase FROM polla_pagos WHERE id=%s", (pago_id,)
    ).fetchone()
    if not pago:
        return jsonify({"ok": False, "error": "Pago no encontrado"}), 404

    motivo = data.get("motivo", "")
    if "estado" in data:
        estados_v = ("pagado", "verificado", "pendiente", "rechazado")
        nuevo_estado = data["estado"] if data["estado"] in estados_v else None
        if nuevo_estado:
            _registrar_auditoria(con, session["uid"], pago["usuario_id"],
                "editar_estado_polla", "estado", pago["estado"], nuevo_estado, motivo)
            con.execute("UPDATE polla_pagos SET estado=%s WHERE id=%s", (nuevo_estado, pago_id))
            con.commit()
            return jsonify({"ok": True})

    return jsonify({"ok": False, "error": "Nada que actualizar"}), 400


@fin_bp.route("/api/fin/auditoria")
def api_auditoria():
    """Historial de auditoría financiera — Admin y Financiero."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    con = get_db()
    try:
        rows = con.execute("""
            SELECT af.id, af.accion, af.campo, af.valor_antes, af.valor_nuevo,
                   af.motivo, af.fecha,
                   a.nombre AS actor_nombre, a.usuario AS actor_usuario,
                   t.nombre AS target_nombre, t.usuario AS target_usuario
            FROM auditoria_financiera af
            JOIN usuarios a ON a.id = af.actor_id
            LEFT JOIN usuarios t ON t.id = af.target_id
            ORDER BY af.fecha DESC
            LIMIT 100
        """).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception:
        return jsonify([])


@fin_bp.route("/api/fin/estadisticas")
def api_estadisticas():
    """Estadísticas de recaudación para Admin y Financiero."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    con = get_db()
    total_general = con.execute("SELECT COALESCE(SUM(monto),0) FROM aportes").fetchone()[0]
    total_eventos = con.execute(
        "SELECT COALESCE(SUM(monto),0) FROM eventos_recaudacion WHERE estado='verificado'"
    ).fetchone()[0]
    total_polla = con.execute(
        "SELECT COALESCE(SUM(monto),0) FROM polla_pagos WHERE estado='verificado'"
    ).fetchone()[0]
    pendientes = con.execute(
        "SELECT COUNT(*) FROM eventos_recaudacion WHERE estado='pendiente'"
    ).fetchone()[0]
    participantes_activos = con.execute(
        "SELECT COUNT(*) FROM usuarios WHERE rol='miembro' AND COALESCE(polla_activo, TRUE)=TRUE AND COALESCE(polla_estado,'activo') != 'excluido'"
    ).fetchone()[0]
    invitados_count = con.execute(
        "SELECT COUNT(*) FROM usuarios WHERE rol='invitado'"
    ).fetchone()[0]
    cfg_meta = con.execute("SELECT valor FROM config WHERE clave='meta_recaudacion'").fetchone()
    meta = float(cfg_meta["valor"]) if cfg_meta else 500000
    return jsonify({
        "total_general": float(total_general),
        "total_eventos": float(total_eventos),
        "total_polla": float(total_polla),
        "pendientes_verificacion": int(pendientes),
        "participantes_activos": int(participantes_activos),
        "invitados_count": int(invitados_count),
        "meta": float(meta),
        "pct": round(float(total_general) / float(meta) * 100, 1) if meta > 0 else 0,
    })

@fin_bp.route("/api/fin/aporte_manual", methods=["POST"])
def aporte_manual():
    """Registra un pago manual verificado para un invitado.
    Solo accesible por admin o financiero."""
    if not _es_admin_o_financiero():
        return jsonify({"ok": False, "error": "Sin permiso"}), 403

    data = request.get_json(silent=True) or {}
    uid_target = data.get("usuario_id")
    monto      = data.get("monto", 0)
    nota       = data.get("nota", "Pago manual")

    if not uid_target or float(monto) <= 0:
        return jsonify({"ok": False, "error": "usuario_id y monto requeridos"}), 400

    con = get_db()
    # Verificar que el target existe y es invitado
    target = con.execute(
        "SELECT id, nombre, rol FROM usuarios WHERE id=%s", (uid_target,)
    ).fetchone()
    if not target or target["rol"] != "invitado":
        return jsonify({"ok": False, "error": "Usuario no encontrado o no es invitado"}), 400

    actor_id = session["uid"]
    monto_f  = float(monto)

    # Insertar aporte ya verificado
    con.execute("""
        INSERT INTO aportes (usuario_id, monto, descripcion, verificado, fecha)
        VALUES (%s, %s, %s, 1, NOW())
    """, (uid_target, monto_f, nota))

    # Auditoría
    con.execute("""
        INSERT INTO auditoria_financiera
            (actor_id, target_id, accion, campo, valor_antes, valor_despues, fecha)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (actor_id, uid_target, "pago_manual", "monto", "0", str(monto_f)))

    con.commit()
    return jsonify({"ok": True, "msg": f"Pago de ${monto_f:,.0f} registrado para {target['nombre']}"})
