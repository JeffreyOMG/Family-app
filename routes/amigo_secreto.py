import random
from flask import Blueprint, render_template, session, redirect, jsonify, request
from database import get_db

amigo_bp = Blueprint("amigo_secreto", __name__)

def _uid():
    return session.get("uid")

def _rol():
    return session.get("rol", "")

def _get_evento_activo(con):
    return con.execute(
        "SELECT * FROM amigo_secreto_eventos WHERE activo=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()

# ─────────────────────────────────────────
# PÁGINA PRINCIPAL
# ─────────────────────────────────────────
@amigo_bp.route("/amigo-secreto")
def pagina():
    if not _uid():
        return redirect("/")
    con = get_db()
    evento = _get_evento_activo(con)
    participantes    = []
    ya_participo     = False
    mi_asignado      = None
    cruces_generados = False
    deseos_anonimos  = []   # antes del sorteo: anónimos mezclados
    mis_deseos       = []
    deseos_asignado  = []   # después del sorteo: solo los del amigo
    estado_regalo    = "pendiente"
    mensajes_no_leidos = 0

    if evento:
        cruces_generados = bool(evento["cruces_generados"])
        participantes = [dict(p) for p in con.execute("""
            SELECT u.id, u.nombre, u.foto, u.usuario
            FROM amigo_secreto_participantes asp
            JOIN usuarios u ON u.id = asp.usuario_id
            WHERE asp.evento_id = %s
            ORDER BY u.nombre ASC
        """, (evento["id"],)).fetchall()]
        ya_participo = any(p["id"] == _uid() for p in participantes)

        if not cruces_generados:
            # Cargar TODOS los deseos sin identificar al dueño (mezclados)
            rows = con.execute("""
                SELECT ld.id, ld.titulo, ld.descripcion, ld.imagen_referencia, ld.link_referencia
                FROM lista_deseos ld
                JOIN amigo_secreto_participantes asp
                  ON asp.usuario_id = ld.usuario_id AND asp.evento_id = %s
                ORDER BY random()
            """, (evento["id"],)).fetchall()
            deseos_anonimos = [dict(r) for r in rows]

        if cruces_generados and ya_participo:
            row = con.execute("""
                SELECT u.id, u.nombre, u.foto, u.usuario
                FROM amigo_secreto_participantes asp
                JOIN usuarios u ON u.id = asp.asignado_id
                WHERE asp.evento_id = %s AND asp.usuario_id = %s
            """, (evento["id"], _uid())).fetchone()
            if row:
                mi_asignado = dict(row)
                # Deseos del asignado (privado, solo para el comprador)
                deseos_asignado = [dict(d) for d in con.execute("""
                    SELECT id, titulo, descripcion, imagen_referencia, link_referencia, orden
                    FROM lista_deseos WHERE usuario_id=%s ORDER BY orden ASC
                """, (mi_asignado["id"],)).fetchall()]
                # Estado del regalo
                est_row = con.execute(
                    "SELECT estado FROM amigo_estado_regalo WHERE evento_id=%s AND comprador_id=%s",
                    (evento["id"], _uid())
                ).fetchone()
                if est_row:
                    estado_regalo = est_row["estado"]
                # Mensajes no leídos (recibidos por el usuario actual del asignado)
                ml = con.execute("""
                    SELECT COUNT(*) as c FROM amigo_mensajes
                    WHERE evento_id=%s AND destinatario_id=%s AND leido=FALSE
                """, (evento["id"], _uid())).fetchone()
                mensajes_no_leidos = ml["c"] if ml else 0

    # Mis deseos propios
    mis_deseos = [dict(d) for d in con.execute(
        "SELECT * FROM lista_deseos WHERE usuario_id=%s ORDER BY orden ASC", (_uid(),)
    ).fetchall()]

    usuario_row = con.execute(
        "SELECT id, nombre, usuario, rol, foto FROM usuarios WHERE id=%s", (_uid(),)
    ).fetchone()

    return render_template(
        "amigo_secreto.html",
        usuario=dict(usuario_row),
        evento=dict(evento) if evento else None,
        participantes=participantes,
        ya_participo=ya_participo,
        mi_asignado=mi_asignado,
        cruces_generados=cruces_generados,
        deseos_anonimos=deseos_anonimos,
        mis_deseos=mis_deseos,
        deseos_asignado=deseos_asignado,
        estado_regalo=estado_regalo,
        mensajes_no_leidos=mensajes_no_leidos,
    )

# ─────────────────────────────────────────
# PARTICIPAR / SALIR
# ─────────────────────────────────────────
@amigo_bp.route("/api/amigo/participar", methods=["POST"])
def participar():
    if not _uid():
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        cur = con.execute(
            "INSERT INTO amigo_secreto_eventos(nombre) VALUES(%s) RETURNING id",
            ("Amigo Navideño Familiar",)
        )
        evento_id = cur.fetchone()[0]
        con.commit()
    else:
        evento_id = evento["id"]
        if evento["cruces_generados"]:
            return jsonify({"ok": False, "error": "Los cruces ya fueron generados"}), 400
    try:
        con.execute(
            "INSERT INTO amigo_secreto_participantes(evento_id, usuario_id) VALUES(%s, %s) ON CONFLICT DO NOTHING",
            (evento_id, _uid())
        )
        con.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@amigo_bp.route("/api/amigo/salir", methods=["POST"])
def salir():
    if not _uid():
        return jsonify({"ok": False}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento or evento["cruces_generados"]:
        return jsonify({"ok": False, "error": "No se puede salir ahora"}), 400
    con.execute(
        "DELETE FROM amigo_secreto_participantes WHERE evento_id=%s AND usuario_id=%s",
        (evento["id"], _uid())
    )
    con.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
# SORTEO
# ─────────────────────────────────────────
@amigo_bp.route("/api/amigo/generar_cruces", methods=["POST"])
def generar_cruces():
    if _rol() != "admin":
        return jsonify({"ok": False, "error": "Solo el admin puede generar cruces"}), 403
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        return jsonify({"ok": False, "error": "No hay evento activo"}), 400
    if evento["cruces_generados"]:
        return jsonify({"ok": False, "error": "Los cruces ya fueron generados"}), 400

    participantes = [row["usuario_id"] for row in con.execute(
        "SELECT usuario_id FROM amigo_secreto_participantes WHERE evento_id=%s", (evento["id"],)
    ).fetchall()]

    if len(participantes) < 2:
        return jsonify({"ok": False, "error": "Se necesitan al menos 2 participantes"}), 400

    asignacion = _generar_derangement(participantes)
    if not asignacion:
        return jsonify({"ok": False, "error": "No se pudo generar asignación válida"}), 500

    for uid, asignado in asignacion.items():
        con.execute(
            "UPDATE amigo_secreto_participantes SET asignado_id=%s WHERE evento_id=%s AND usuario_id=%s",
            (asignado, evento["id"], uid)
        )
    con.execute(
        "UPDATE amigo_secreto_eventos SET cruces_generados=1, sorteo_fecha=CURRENT_TIMESTAMP, sorteo_admin_id=%s WHERE id=%s",
        (_uid(), evento["id"])
    )
    con.commit()
    return jsonify({"ok": True, "total": len(participantes)})

@amigo_bp.route("/api/amigo/reiniciar", methods=["POST"])
def reiniciar():
    if _rol() != "admin":
        return jsonify({"ok": False}), 403
    con    = get_db()
    evento = _get_evento_activo(con)
    if evento:
        con.execute("UPDATE amigo_secreto_eventos SET activo=0 WHERE id=%s", (evento["id"],))
    con.execute(
        "INSERT INTO amigo_secreto_eventos(nombre) VALUES(%s) RETURNING id",
        ("Amigo Navideño Familiar",)
    )
    con.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
# DESEOS (hasta 3 por usuario)
# ─────────────────────────────────────────
@amigo_bp.route("/api/amigo/deseos", methods=["GET"])
def obtener_mis_deseos():
    if not _uid():
        return jsonify({"ok": False}), 401
    con = get_db()
    rows = con.execute(
        "SELECT * FROM lista_deseos WHERE usuario_id=%s ORDER BY orden ASC", (_uid(),)
    ).fetchall()
    return jsonify({"ok": True, "deseos": [dict(r) for r in rows]})

@amigo_bp.route("/api/amigo/deseos", methods=["POST"])
def crear_deseo():
    if not _uid():
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        return jsonify({"ok": False, "error": "No hay evento activo"}), 400
    inscrito = con.execute(
        "SELECT 1 FROM amigo_secreto_participantes WHERE evento_id=%s AND usuario_id=%s",
        (evento["id"], _uid())
    ).fetchone()
    if not inscrito:
        return jsonify({"ok": False, "error": "Debes estar inscrito"}), 403

    count = con.execute(
        "SELECT COUNT(*) as c FROM lista_deseos WHERE usuario_id=%s", (_uid(),)
    ).fetchone()["c"]
    if count >= 3:
        return jsonify({"ok": False, "error": "Máximo 3 deseos permitidos"}), 400

    data = request.get_json() or {}
    titulo = (data.get("titulo") or "").strip()
    descripcion = (data.get("descripcion") or "").strip() or None
    imagen = (data.get("imagen_referencia") or "").strip() or None
    link   = (data.get("link_referencia") or "").strip() or None
    orden  = int(count) + 1

    if not titulo:
        return jsonify({"ok": False, "error": "El título es obligatorio"}), 400

    try:
        cur = con.execute("""
            INSERT INTO lista_deseos(usuario_id, titulo, descripcion, imagen_referencia, link_referencia, orden)
            VALUES(%s, %s, %s, %s, %s, %s) RETURNING id
        """, (_uid(), titulo, descripcion, imagen, link, orden))
        new_id = cur.fetchone()[0]
        con.commit()
        return jsonify({"ok": True, "id": new_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@amigo_bp.route("/api/amigo/deseos/<int:deseo_id>", methods=["PUT"])
def editar_deseo(deseo_id):
    if not _uid():
        return jsonify({"ok": False}), 401
    con = get_db()
    row = con.execute("SELECT * FROM lista_deseos WHERE id=%s AND usuario_id=%s", (deseo_id, _uid())).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "No encontrado"}), 404

    data = request.get_json() or {}
    titulo = (data.get("titulo") or "").strip()
    descripcion = (data.get("descripcion") or "").strip() or None
    imagen = (data.get("imagen_referencia") or "").strip() or None
    link   = (data.get("link_referencia") or "").strip() or None

    if not titulo:
        return jsonify({"ok": False, "error": "El título es obligatorio"}), 400

    con.execute("""
        UPDATE lista_deseos SET titulo=%s, descripcion=%s, imagen_referencia=%s,
        link_referencia=%s, updated_at=CURRENT_TIMESTAMP
        WHERE id=%s AND usuario_id=%s
    """, (titulo, descripcion, imagen, link, deseo_id, _uid()))
    con.commit()
    return jsonify({"ok": True})

@amigo_bp.route("/api/amigo/deseos/<int:deseo_id>", methods=["DELETE"])
def eliminar_deseo(deseo_id):
    if not _uid():
        return jsonify({"ok": False}), 401
    con = get_db()
    con.execute("DELETE FROM lista_deseos WHERE id=%s AND usuario_id=%s", (deseo_id, _uid()))
    con.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
# ESTADO DEL REGALO
# ─────────────────────────────────────────
@amigo_bp.route("/api/amigo/estado_regalo", methods=["POST"])
def actualizar_estado_regalo():
    if not _uid():
        return jsonify({"ok": False}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento or not evento["cruces_generados"]:
        return jsonify({"ok": False, "error": "No aplica"}), 400
    data   = request.get_json() or {}
    estado = data.get("estado", "pendiente")
    if estado not in ("pendiente", "comprado", "envuelto", "entregado"):
        return jsonify({"ok": False, "error": "Estado inválido"}), 400
    con.execute("""
        INSERT INTO amigo_estado_regalo(evento_id, comprador_id, estado)
        VALUES(%s, %s, %s)
        ON CONFLICT(evento_id, comprador_id) DO UPDATE SET estado=%s, updated_at=CURRENT_TIMESTAMP
    """, (evento["id"], _uid(), estado, estado))
    con.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
# MENSAJES ANÓNIMOS
# ─────────────────────────────────────────
@amigo_bp.route("/api/amigo/mensajes", methods=["GET"])
def obtener_mensajes():
    if not _uid():
        return jsonify({"ok": False}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento or not evento["cruces_generados"]:
        return jsonify({"ok": True, "mensajes": []})

    # Solo entre comprador y su asignado (anónimo)
    # Verificar que el usuario tiene asignado o es asignado de alguien
    rows = con.execute("""
        SELECT m.id, m.mensaje, m.created_at,
               CASE WHEN m.remitente_id = %s THEN 'yo' ELSE 'ellos' END as direccion,
               m.leido
        FROM amigo_mensajes m
        WHERE m.evento_id=%s
          AND (m.remitente_id=%s OR m.destinatario_id=%s)
        ORDER BY m.created_at ASC
    """, (_uid(), evento["id"], _uid(), _uid())).fetchall()

    # Marcar como leídos los que llegaron a este usuario
    con.execute("""
        UPDATE amigo_mensajes SET leido=TRUE
        WHERE evento_id=%s AND destinatario_id=%s AND leido=FALSE
    """, (evento["id"], _uid()))
    con.commit()

    return jsonify({"ok": True, "mensajes": [dict(r) for r in rows]})

@amigo_bp.route("/api/amigo/mensajes", methods=["POST"])
def enviar_mensaje():
    if not _uid():
        return jsonify({"ok": False}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento or not evento["cruces_generados"]:
        return jsonify({"ok": False, "error": "No hay sorteo activo"}), 400

    data = request.get_json() or {}
    texto = (data.get("mensaje") or "").strip()
    if not texto or len(texto) > 500:
        return jsonify({"ok": False, "error": "Mensaje inválido (máx 500 caracteres)"}), 400

    # Límite de mensajes por día
    count_hoy = con.execute("""
        SELECT COUNT(*) as c FROM amigo_mensajes
        WHERE evento_id=%s AND remitente_id=%s
          AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
    """, (evento["id"], _uid())).fetchone()["c"]
    if count_hoy >= 20:
        return jsonify({"ok": False, "error": "Límite de 20 mensajes por día alcanzado"}), 429

    # Determinar destinatario: el usuario envía al que le tocó, o a quien lo tiene de asignado
    asignacion = con.execute("""
        SELECT asignado_id FROM amigo_secreto_participantes
        WHERE evento_id=%s AND usuario_id=%s
    """, (evento["id"], _uid())).fetchone()

    if not asignacion or not asignacion["asignado_id"]:
        return jsonify({"ok": False, "error": "No tienes asignado"}), 400

    destinatario_id = asignacion["asignado_id"]

    con.execute("""
        INSERT INTO amigo_mensajes(evento_id, remitente_id, destinatario_id, mensaje)
        VALUES(%s, %s, %s, %s)
    """, (evento["id"], _uid(), destinatario_id, texto))
    con.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────
# ESTADO API
# ─────────────────────────────────────────
@amigo_bp.route("/api/amigo/estado")
def estado():
    if not _uid():
        return jsonify({}), 401
    con    = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        return jsonify({"evento": None, "participantes": [], "ya_participo": False})

    participantes = [dict(p) for p in con.execute("""
        SELECT u.id, u.nombre, u.foto
        FROM amigo_secreto_participantes asp
        JOIN usuarios u ON u.id = asp.usuario_id
        WHERE asp.evento_id = %s ORDER BY u.nombre ASC
    """, (evento["id"],)).fetchall()]

    ya_participo = any(p["id"] == _uid() for p in participantes)
    return jsonify({
        "evento": dict(evento),
        "participantes": len(participantes),
        "ya_participo": ya_participo,
        "cruces_generados": bool(evento["cruces_generados"]),
    })

# ─────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────
def _generar_derangement(lista):
    ids = list(lista)
    for _ in range(1000):
        shuffled = ids[:]
        random.shuffle(shuffled)
        if all(shuffled[i] != ids[i] for i in range(len(ids))):
            return {ids[i]: shuffled[i] for i in range(len(ids))}
    return _sattolo(ids)

def _sattolo(lista):
    arr = list(lista)
    i   = len(arr)
    while i > 1:
        i -= 1
        j = random.randint(0, i - 1)
        arr[i], arr[j] = arr[j], arr[i]
    return {lista[k]: arr[k] for k in range(len(lista))}
