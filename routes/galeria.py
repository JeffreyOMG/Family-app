import os, uuid
from flask import Blueprint, request, redirect, session, current_app, jsonify
from database import get_db

galeria_bp = Blueprint("galeria", __name__)

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

@galeria_bp.route("/subir_archivo", methods=["POST"])
def subir_archivo():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return (jsonify({"ok": False, "error": "Sin archivo"}), 400) if _is_ajax() else redirect("/dashboard")
    ext = archivo.filename.rsplit(".", 1)[-1].lower()
    allowed = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "mov", "avi", "webm"}
    if ext not in allowed:
        return (jsonify({"ok": False, "error": "Tipo no permitido"}), 400) if _is_ajax() else redirect("/dashboard")
    nombre = uuid.uuid4().hex + "." + ext
    ruta   = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre)
    archivo.save(ruta)
    tipo   = "video" if ext in {"mp4", "mov", "avi", "webm"} else "imagen"
    desc   = request.form.get("descripcion", "").strip()
    con    = get_db()
    con.execute(
        "INSERT INTO galeria(usuario_id,ruta,tipo,descripcion) VALUES(?,?,?,?)",
        (session["uid"], f"/static/uploads/{nombre}", tipo, desc)
    )
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "url": f"/static/uploads/{nombre}", "tipo": tipo, "desc": desc})
    return redirect("/dashboard")

@galeria_bp.route("/eliminar_media/<int:mid>", methods=["POST"])
def eliminar_media(mid):
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    con = get_db()
    item = con.execute("SELECT usuario_id,ruta FROM galeria WHERE id=?", (mid,)).fetchone()
    if item and (item["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        try:
            path = os.path.join(os.path.dirname(__file__), "..", "static", "uploads",
                                item["ruta"].split("/")[-1])
            if os.path.exists(path): os.remove(path)
        except: pass
        con.execute("DELETE FROM galeria WHERE id=?", (mid,))
        con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")
