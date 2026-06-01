from flask import Blueprint, request, redirect, session, jsonify
from database import get_db

eventos_bp = Blueprint("eventos", __name__)

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

@eventos_bp.route("/crear_evento", methods=["POST"])
def crear_evento():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    titulo      = request.form.get("titulo", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    fecha_ev    = request.form.get("fecha_evento", "").strip()
    hora_ev     = request.form.get("hora_evento", "").strip()
    tipo        = request.form.get("tipo", "evento")
    if titulo and fecha_ev:
        con = get_db()
        cur = con.execute(
            "INSERT INTO eventos(usuario_id,titulo,descripcion,fecha_evento,hora_evento,tipo) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
            (session["uid"], titulo, descripcion, fecha_ev, hora_ev, tipo)
        )
        con.commit()
        if _is_ajax():
            return jsonify({"ok": True, "id": cur.fetchone()[0], "titulo": titulo, "fecha": fecha_ev, "hora": hora_ev, "tipo": tipo})
    else:
        if _is_ajax():
            return jsonify({"ok": False, "error": "Faltan datos"}), 400
    return redirect("/dashboard")

@eventos_bp.route("/eliminar_evento/<int:eid>", methods=["POST"])
def eliminar_evento(eid):
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    con = get_db()
    ev = con.execute("SELECT usuario_id FROM eventos WHERE id=?", (eid,)).fetchone()
    if ev and (ev["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        con.execute("DELETE FROM eventos WHERE id=?", (eid,))
        con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")
