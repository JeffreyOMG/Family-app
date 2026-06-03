import random
from flask import Blueprint, render_template, session, redirect, jsonify, request
from database import get_db

amigo_bp = Blueprint("amigo_secreto", __name__)

def _uid():
    return session.get("uid")

def _rol():
    return session.get("rol", "")

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

def _get_evento_activo(con):
    return con.execute(
        "SELECT * FROM amigo_secreto_eventos WHERE activo=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()

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
    lista_deseos     = []

    if evento:
        cruces_generados = bool(evento["cruces_generados"])
        participantes = [dict(p) for p in con.execute("""
            SELECT u.id, u.nombre, u.foto, u.usuario, asp.asignado_id
            FROM amigo_secreto_participantes asp
            JOIN usuarios u ON u.id = asp.usuario_id
            WHERE asp.evento_id = %s
            ORDER BY u.nombre ASC
        """, (evento["id"],)).fetchall()]
        ya_participo = any(p["id"] == _uid() for p in participantes)
        if cruces_generados and ya_participo:
            row = con.execute("""
                SELECT u.nombre, u.foto FROM amigo_secreto_participantes asp
                JOIN usuarios u ON u.id = asp.asignado_id
                WHERE asp.evento_id = %s AND asp.usuario_id = %s
            """, (evento["id"], _uid())).fetchone()
            if row:
                mi_asignado = dict(row)

        # Cargar lista de deseos de todos los participantes
        participante_ids = [p["id"] for p in participantes]
        if participante_ids:
            placeholders = ",".join(["%s"] * len(participante_ids))
            deseos_rows = con.execute(f"""
                SELECT u.id as usuario_id, u.nombre, u.foto,
                       ld.descripcion, ld.imagen_referencia, ld.link_referencia
                FROM usuarios u
                LEFT JOIN lista_deseos ld ON ld.usuario_id = u.id
                WHERE u.id IN ({placeholders})
                ORDER BY u.nombre ASC
            """, tuple(participante_ids)).fetchall()
            lista_deseos = [dict(r) for r in deseos_rows]
        else:
            lista_deseos = []

    # Deseo del usuario actual (para editar)
    mi_deseo = None
    row_deseo = con.execute(
        "SELECT * FROM lista_deseos WHERE usuario_id=%s", (_uid(),)
    ).fetchone()
    if row_deseo:
        mi_deseo = dict(row_deseo)

    return render_template(
        "amigo_secreto.html",
        usuario=dict(con.execute(
            "SELECT id, nombre, usuario, rol, foto FROM usuarios WHERE id=%s", (_uid(),)
        ).fetchone()),
        evento=dict(evento) if evento else None,
        participantes=participantes,
        ya_participo=ya_participo,
        mi_asignado=mi_asignado,
        cruces_generados=cruces_generados,
        lista_deseos=lista_deseos,
        mi_deseo=mi_deseo,
    )

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
        "UPDATE amigo_secreto_eventos SET cruces_generados=1 WHERE id=%s", (evento["id"],)
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
        WHERE asp.evento_id = %s
        ORDER BY u.nombre ASC
    """, (evento["id"],)).fetchall()]

    ya_participo = any(p["id"] == _uid() for p in participantes)
    mi_asignado  = None
    if evento["cruces_generados"] and ya_participo:
        row = con.execute("""
            SELECT u.nombre, u.foto FROM amigo_secreto_participantes asp
            JOIN usuarios u ON u.id = asp.asignado_id
            WHERE asp.evento_id = %s AND asp.usuario_id = %s
        """, (evento["id"], _uid())).fetchone()
        if row:
            mi_asignado = dict(row)

    return jsonify({
        "evento": dict(evento),
        "participantes": participantes,
        "ya_participo": ya_participo,
        "cruces_generados": bool(evento["cruces_generados"]),
        "mi_asignado": mi_asignado,
    })

# ── DESEOS ──────────────────────────────────────────────
@amigo_bp.route("/api/amigo/deseo", methods=["POST"])
def guardar_deseo():
    if not _uid():
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con    = get_db()
    evento = _get_evento_activo(con)

    # Solo participantes inscritos pueden agregar deseos
    if not evento:
        return jsonify({"ok": False, "error": "No hay evento activo"}), 400
    inscrito = con.execute(
        "SELECT 1 FROM amigo_secreto_participantes WHERE evento_id=%s AND usuario_id=%s",
        (evento["id"], _uid())
    ).fetchone()
    if not inscrito:
        return jsonify({"ok": False, "error": "Debes estar inscrito para agregar un deseo"}), 403

    data = request.get_json() or {}
    descripcion      = (data.get("descripcion") or "").strip()
    imagen_referencia = (data.get("imagen_referencia") or "").strip() or None
    link_referencia   = (data.get("link_referencia") or "").strip() or None

    if not descripcion:
        return jsonify({"ok": False, "error": "La descripción es obligatoria"}), 400

    try:
        existing = con.execute(
            "SELECT id FROM lista_deseos WHERE usuario_id=%s", (_uid(),)
        ).fetchone()
        if existing:
            con.execute("""
                UPDATE lista_deseos
                SET descripcion=%s, imagen_referencia=%s, link_referencia=%s,
                    updated_at=CURRENT_TIMESTAMP
                WHERE usuario_id=%s
            """, (descripcion, imagen_referencia, link_referencia, _uid()))
        else:
            con.execute("""
                INSERT INTO lista_deseos(usuario_id, descripcion, imagen_referencia, link_referencia)
                VALUES(%s, %s, %s, %s)
            """, (_uid(), descripcion, imagen_referencia, link_referencia))
        con.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@amigo_bp.route("/api/amigo/deseo", methods=["GET"])
def obtener_deseo():
    if not _uid():
        return jsonify({"ok": False}), 401
    con = get_db()
    row = con.execute(
        "SELECT * FROM lista_deseos WHERE usuario_id=%s", (_uid(),)
    ).fetchone()
    return jsonify({"ok": True, "deseo": dict(row) if row else None})

# ── UTILIDADES ──────────────────────────────────────────
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
