import random
import string
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
    participantes = []
    ya_participo = False
    mi_asignado = None
    cruces_generados = False

    if evento:
        cruces_generados = bool(evento["cruces_generados"])
        participantes = [dict(p) for p in con.execute("""
            SELECT u.id, u.nombre, u.foto, u.usuario,
                   asp.asignado_id
            FROM amigo_secreto_participantes asp
            JOIN usuarios u ON u.id = asp.usuario_id
            WHERE asp.evento_id = ?
            ORDER BY u.nombre ASC
        """, (evento["id"],)).fetchall()]
        ya_participo = any(p["id"] == _uid() for p in participantes)
        if cruces_generados and ya_participo:
            row = con.execute("""
                SELECT u.nombre, u.foto FROM amigo_secreto_participantes asp
                JOIN usuarios u ON u.id = asp.asignado_id
                WHERE asp.evento_id = ? AND asp.usuario_id = ?
            """, (evento["id"], _uid())).fetchone()
            if row:
                mi_asignado = dict(row)

    return render_template(
        "amigo_secreto.html",
        usuario=dict(con.execute(
            "SELECT id,nombre,usuario,rol,foto FROM usuarios WHERE id=?", (_uid(),)
        ).fetchone()),
        evento=dict(evento) if evento else None,
        participantes=participantes,
        ya_participo=ya_participo,
        mi_asignado=mi_asignado,
        cruces_generados=cruces_generados,
    )


@amigo_bp.route("/api/amigo/participar", methods=["POST"])
def participar():
    if not _uid():
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        # Crear evento automáticamente si no existe
        cur = con.execute(
            "INSERT INTO amigo_secreto_eventos(nombre) VALUES(?)",
            ("Amigo Secreto Familiar",)
        )
        evento_id = cur.lastrowid
        con.commit()
    else:
        evento_id = evento["id"]
        if evento["cruces_generados"]:
            return jsonify({"ok": False, "error": "Los cruces ya fueron generados"}), 400

    try:
        con.execute(
            "INSERT OR IGNORE INTO amigo_secreto_participantes(evento_id, usuario_id) VALUES(?,?)",
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
    con = get_db()
    evento = _get_evento_activo(con)
    if not evento or evento["cruces_generados"]:
        return jsonify({"ok": False, "error": "No se puede salir ahora"}), 400
    con.execute(
        "DELETE FROM amigo_secreto_participantes WHERE evento_id=? AND usuario_id=?",
        (evento["id"], _uid())
    )
    con.commit()
    return jsonify({"ok": True})


@amigo_bp.route("/api/amigo/generar_cruces", methods=["POST"])
def generar_cruces():
    if _rol() != "admin":
        return jsonify({"ok": False, "error": "Solo el admin puede generar cruces"}), 403
    con = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        return jsonify({"ok": False, "error": "No hay evento activo"}), 400
    if evento["cruces_generados"]:
        return jsonify({"ok": False, "error": "Los cruces ya fueron generados"}), 400

    participantes = [row["usuario_id"] for row in con.execute(
        "SELECT usuario_id FROM amigo_secreto_participantes WHERE evento_id=?",
        (evento["id"],)
    ).fetchall()]

    n = len(participantes)
    if n < 2:
        return jsonify({"ok": False, "error": "Se necesitan al menos 2 participantes"}), 400

    # Generar derangement válido (nadie se regala a sí mismo)
    asignacion = _generar_derangement(participantes)
    if not asignacion:
        return jsonify({"ok": False, "error": "No se pudo generar asignación válida"}), 500

    for uid, asignado in asignacion.items():
        con.execute(
            "UPDATE amigo_secreto_participantes SET asignado_id=? WHERE evento_id=? AND usuario_id=?",
            (asignado, evento["id"], uid)
        )
    con.execute(
        "UPDATE amigo_secreto_eventos SET cruces_generados=1 WHERE id=?",
        (evento["id"],)
    )
    con.commit()
    return jsonify({"ok": True, "total": n})


@amigo_bp.route("/api/amigo/reiniciar", methods=["POST"])
def reiniciar():
    if _rol() != "admin":
        return jsonify({"ok": False}), 403
    con = get_db()
    evento = _get_evento_activo(con)
    if evento:
        con.execute("UPDATE amigo_secreto_eventos SET activo=0 WHERE id=?", (evento["id"],))
    con.execute(
        "INSERT INTO amigo_secreto_eventos(nombre) VALUES(?)",
        ("Amigo Secreto Familiar",)
    )
    con.commit()
    return jsonify({"ok": True})


@amigo_bp.route("/api/amigo/estado")
def estado():
    if not _uid():
        return jsonify({}), 401
    con = get_db()
    evento = _get_evento_activo(con)
    if not evento:
        return jsonify({"evento": None, "participantes": [], "ya_participo": False})

    participantes = [dict(p) for p in con.execute("""
        SELECT u.id, u.nombre, u.foto
        FROM amigo_secreto_participantes asp
        JOIN usuarios u ON u.id = asp.usuario_id
        WHERE asp.evento_id = ?
        ORDER BY u.nombre ASC
    """, (evento["id"],)).fetchall()]

    ya_participo = any(p["id"] == _uid() for p in participantes)
    mi_asignado = None
    if evento["cruces_generados"] and ya_participo:
        row = con.execute("""
            SELECT u.nombre, u.foto FROM amigo_secreto_participantes asp
            JOIN usuarios u ON u.id = asp.asignado_id
            WHERE asp.evento_id = ? AND asp.usuario_id = ?
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


# ── UTILIDADES ─────────────────────────────────────────
def _generar_derangement(lista):
    """Genera un derangement válido (permutación sin puntos fijos).
    Maneja listas impares y pares."""
    ids = list(lista)
    max_intentos = 1000
    for _ in range(max_intentos):
        shuffled = ids[:]
        random.shuffle(shuffled)
        # Verificar que nadie se repita a sí mismo
        valido = all(shuffled[i] != ids[i] for i in range(len(ids)))
        if valido:
            return {ids[i]: shuffled[i] for i in range(len(ids))}
    # Fallback: algoritmo determinista (Sattolo cycle)
    return _sattolo(ids)


def _sattolo(lista):
    """Algoritmo de Sattolo: genera permutación sin puntos fijos."""
    arr = list(lista)
    i = len(arr)
    while i > 1:
        i -= 1
        j = random.randint(0, i - 1)
        arr[i], arr[j] = arr[j], arr[i]
    return {lista[k]: arr[k] for k in range(len(lista))}
