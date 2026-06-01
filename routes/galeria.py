from flask import Blueprint, request, redirect, session, jsonify
from database import get_db
from cloudinary_helper import subir_a_cloudinary, eliminar_de_cloudinary

galeria_bp = Blueprint("galeria", __name__)

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@galeria_bp.route("/subir_archivo", methods=["POST"])
def subir_archivo():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")

    archivo = request.files.get("archivo")
    url, tipo = subir_a_cloudinary(archivo, folder="familia/galeria")

    if not url:
        return (jsonify({"ok": False, "error": "Tipo no permitido o error al subir"}), 400) if _is_ajax() else redirect("/dashboard")

    desc = request.form.get("descripcion", "").strip()
    con  = get_db()
    con.execute(
        "INSERT INTO galeria(usuario_id, ruta, tipo, descripcion) VALUES(%s, %s, %s, %s)",
        (session["uid"], url, tipo, desc)
    )
    con.commit()

    if _is_ajax():
        return jsonify({"ok": True, "url": url, "tipo": tipo, "desc": desc})
    return redirect("/dashboard")


@galeria_bp.route("/eliminar_media/<int:mid>", methods=["POST"])
def eliminar_media(mid):
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")

    con  = get_db()
    item = con.execute("SELECT usuario_id, ruta FROM galeria WHERE id=%s", (mid,)).fetchone()

    if item and (item["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        eliminar_de_cloudinary(item["ruta"])
        con.execute("DELETE FROM galeria WHERE id=%s", (mid,))
        con.commit()

    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")
