import os, uuid
from flask import Blueprint, request, redirect, session, current_app, jsonify
from database import get_db
from werkzeug.security import generate_password_hash, check_password_hash

perfil_bp = Blueprint("perfil", __name__)

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

@perfil_bp.route("/actualizar_perfil", methods=["POST"])
def actualizar_perfil():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    uid    = session["uid"]
    nombre = request.form.get("nombre", "").strip()
    gmail  = request.form.get("gmail", "").strip()
    bio    = request.form.get("bio", "").strip()
    con    = get_db()

    foto_file = request.files.get("foto_perfil")
    foto_url  = None
    if foto_file and foto_file.filename:
        ext = foto_file.filename.rsplit(".", 1)[-1].lower()
        if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
            nombre_foto = uuid.uuid4().hex + "." + ext
            ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_foto)
            foto_file.save(ruta)
            foto_url = f"/static/uploads/{nombre_foto}"

    if foto_url:
        con.execute(
            "UPDATE usuarios SET nombre=?,gmail=?,bio=?,foto=? WHERE id=?",
            (nombre, gmail, bio, foto_url, uid)
        )
    else:
        con.execute(
            "UPDATE usuarios SET nombre=?,gmail=?,bio=? WHERE id=?",
            (nombre, gmail, bio, uid)
        )
    con.commit()
    session["nombre"] = nombre
    if _is_ajax():
        return jsonify({"ok": True, "nombre": nombre, "foto": foto_url})
    return redirect("/dashboard")

@perfil_bp.route("/cambiar_password", methods=["POST"])
def cambiar_password():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    uid     = session["uid"]
    actual  = request.form.get("actual", "")
    nueva   = request.form.get("nueva", "")
    confirm = request.form.get("confirmar", "")
    con = get_db()
    user = con.execute("SELECT password FROM usuarios WHERE id=?", (uid,)).fetchone()
    if user and check_password_hash(user["password"], actual) and nueva == confirm and len(nueva) >= 8:
        con.execute("UPDATE usuarios SET password=? WHERE id=?", (generate_password_hash(nueva), uid))
        con.commit()
        if _is_ajax():
            return jsonify({"ok": True, "msg": "Contraseña actualizada"})
    else:
        if _is_ajax():
            return jsonify({"ok": False, "error": "Datos incorrectos o contraseña muy corta"})
    return redirect("/dashboard")

@perfil_bp.route("/eliminar_aporte/<int:aporte_id>", methods=["POST"])
def eliminar_aporte(aporte_id):
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    con = get_db()
    aporte = con.execute("SELECT usuario_id FROM aportes WHERE id=?", (aporte_id,)).fetchone()
    if aporte and (aporte["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        con.execute("DELETE FROM aportes WHERE id=?", (aporte_id,))
        con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")
