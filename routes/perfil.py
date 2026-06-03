from flask import Blueprint, request, redirect, session, jsonify
from database import get_db
from werkzeug.security import generate_password_hash, check_password_hash
from cloudinary_helper import subir_a_cloudinary

perfil_bp = Blueprint("perfil", __name__)


# ─── API: datos públicos de un usuario por @usuario ──────────────────────────
@perfil_bp.route("/api/usuario/<string:nombre_usuario>")
def api_usuario(nombre_usuario):
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    con = get_db()
    u = con.execute(
        "SELECT id, nombre, usuario, rol, bio, foto, fecha FROM usuarios WHERE usuario=%s",
        (nombre_usuario,)
    ).fetchone()

    if not u:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    uid = u["id"]
    total_posts  = con.execute("SELECT COUNT(*) FROM publicaciones WHERE usuario_id=%s", (uid,)).fetchone()[0]
    total_likes  = con.execute(
        "SELECT COUNT(*) FROM likes l JOIN publicaciones p ON p.id=l.post_id WHERE p.usuario_id=%s", (uid,)
    ).fetchone()[0]
    total_puntos = con.execute(
        "SELECT COALESCE(SUM(puntos),0) FROM pronosticos WHERE usuario_id=%s", (uid,)
    ).fetchone()[0]

    return jsonify({
        "ok": True,
        "usuario": {
            "id":           uid,
            "nombre":       u["nombre"],
            "usuario":      u["usuario"],
            "rol":          u["rol"],
            "bio":          u["bio"] or "",
            "foto":         u["foto"] or "",
            "fecha":        str(u["fecha"]) if u["fecha"] else "",
            "total_posts":  total_posts,
            "total_likes":  total_likes,
            "total_puntos": int(total_puntos),
        }
    })

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

    foto_url = None
    foto_file = request.files.get("foto_perfil")
    if foto_file and foto_file.filename:
        url, _ = subir_a_cloudinary(foto_file, folder="familia/perfiles")
        if url:
            foto_url = url
        else:
            if _is_ajax():
                return jsonify({"ok": False, "error": "No se pudo subir la foto. Verifica las credenciales de Cloudinary."}), 500
            return redirect("/dashboard")

    if foto_url:
        con.execute(
            "UPDATE usuarios SET nombre=%s, gmail=%s, bio=%s, foto=%s WHERE id=%s",
            (nombre, gmail, bio, foto_url, uid)
        )
    else:
        con.execute(
            "UPDATE usuarios SET nombre=%s, gmail=%s, bio=%s WHERE id=%s",
            (nombre, gmail, bio, uid)
        )
        row = con.execute("SELECT foto FROM usuarios WHERE id=%s", (uid,)).fetchone()
        if row:
            foto_url = row["foto"]
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
    con  = get_db()
    user = con.execute("SELECT password FROM usuarios WHERE id=%s", (uid,)).fetchone()
    if user and check_password_hash(user["password"], actual) and nueva == confirm and len(nueva) >= 8:
        con.execute("UPDATE usuarios SET password=%s WHERE id=%s", (generate_password_hash(nueva), uid))
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
    con    = get_db()
    aporte = con.execute("SELECT usuario_id FROM aportes WHERE id=%s", (aporte_id,)).fetchone()
    if aporte and (aporte["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        con.execute("DELETE FROM aportes WHERE id=%s", (aporte_id,))
        con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard")
