from decorators import miembro_required
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
               u.foto_perfil AS foto_perfil
        FROM eventos_recaudacion er JOIN usuarios u ON u.id=er.usuario_id
        WHERE u.rol IN ('miembro', 'admin')
        ORDER BY er.fecha DESC
    """).fetchall():
        registros.append({**dict(a), "tipo": "evento"})
    for p in con.execute("""
        SELECT pp.id, pp.fase, pp.monto, pp.soporte, pp.estado, pp.fecha,
               u.nombre AS usuario, u.rol AS rol, u.foto_perfil AS foto_perfil
        FROM polla_pagos pp JOIN usuarios u ON u.id=pp.usuario_id
        WHERE u.rol IN ('miembro', 'admin')
        ORDER BY pp.fecha DESC
    """).fetchall():
        registros.append({**dict(p), "tipo": "polla"})
    for m in con.execute("""
        SELECT cm.id, cm.monto, cm.descripcion, cm.fecha, u.nombre AS usuario,
               u.rol AS rol, u.foto_perfil AS foto_perfil, ca.nombre AS cajita_nombre
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
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("UPDATE eventos_recaudacion SET estado='verificado' WHERE id=%s", (eid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard?s=recaudacion")

@fin_bp.route("/eliminar_aporte/<int:aid>", methods=["POST"])
def eliminar_aporte(aid):
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("DELETE FROM aportes WHERE id=%s", (aid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")

@fin_bp.route("/verificar_aporte/<int:aid>", methods=["POST"])
def verificar_aporte(aid):
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("UPDATE aportes SET verificado=1 WHERE id=%s", (aid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")

@fin_bp.route("/verificar_polla/<int:pid>", methods=["POST"])
def verificar_polla(pid):
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    con = get_db()
    con.execute("UPDATE polla_pagos SET estado='verificado' WHERE id=%s", (pid,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard?s=recaudacion")

@fin_bp.route("/eliminar_pago/<tipo>/<int:rid>", methods=["POST"])
def eliminar_pago(tipo, rid):
    if session.get("rol") != "admin":
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
    if session.get("rol") != "admin":
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
    if session.get("rol") != "admin":
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
