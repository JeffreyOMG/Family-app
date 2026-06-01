from flask import Blueprint, request, redirect, session, jsonify
from database import get_db
from werkzeug.security import check_password_hash

ajustes_bp = Blueprint("ajustes", __name__)

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

@ajustes_bp.route("/guardar_ajustes", methods=["POST"])
def guardar_ajustes():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    nombre = request.form.get("nombre", "").strip()
    gmail  = request.form.get("gmail", "").strip()
    if nombre:
        con = get_db()
        con.execute(
            "UPDATE usuarios SET nombre=%s, gmail=%s WHERE id=%s",
            (nombre, gmail, session["uid"])
        )
        con.commit()
        session["nombre"] = nombre
    if _is_ajax():
        return jsonify({"ok": True, "nombre": nombre})
    return redirect("/dashboard#ajustes")

@ajustes_bp.route("/eliminar_cuenta", methods=["POST"])
def eliminar_cuenta():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    uid = session["uid"]
    pwd = request.form.get("password_confirm", "")
    con = get_db()
    user = con.execute("SELECT password, rol FROM usuarios WHERE id=%s", (uid,)).fetchone()
    if not user:
        return (jsonify({"ok": False}), 404) if _is_ajax() else redirect("/")
    if user["rol"] == "admin":
        if _is_ajax():
            return jsonify({"ok": False, "error": "admin_no_puede"})
        return redirect("/dashboard#ajustes")
    if check_password_hash(user["password"], pwd):
        con.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
        con.commit()
        session.clear()
        if _is_ajax():
            return jsonify({"ok": True, "redirect": "/"})
        return redirect("/")
    if _is_ajax():
        return jsonify({"ok": False, "error": "password_incorrecto"})
    return redirect("/dashboard#ajustes")
