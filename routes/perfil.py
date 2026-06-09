from flask import Blueprint, request, redirect, session, jsonify
from database import get_db
from werkzeug.security import generate_password_hash, check_password_hash
from cloudinary_helper import subir_a_cloudinary
from routes.seguidores import contar_seguidores, contar_siguiendo, esta_siguiendo

perfil_bp = Blueprint("perfil", __name__)


# ─── API: datos públicos de un usuario por @usuario ──────────────────────────
@perfil_bp.route("/api/usuario/<string:nombre_usuario>")
def api_usuario(nombre_usuario):
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    mi_uid = session["uid"]
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
            "id":              uid,
            "nombre":          u["nombre"],
            "usuario":         u["usuario"],
            "rol":             u["rol"],
            "bio":             u["bio"] or "",
            "foto":            u["foto"] or "",
            "fecha":           str(u["fecha"]) if u["fecha"] else "",
            "total_posts":     total_posts,
            "total_likes":     total_likes,
            "total_puntos":    int(total_puntos),
            # ── FASE 3.2: datos de seguidores ──
            "total_seguidores": contar_seguidores(uid),
            "total_siguiendo":  contar_siguiendo(uid),
            "yo_lo_sigo":       esta_siguiendo(mi_uid, uid),
            "es_mi_perfil":     (mi_uid == uid),
        }
    })

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


# ─── API: publicaciones del usuario ──────────────────────────────────────────
@perfil_bp.route("/api/perfil/posts/<int:uid>")
def api_perfil_posts(uid):
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con = get_db()
    rows = con.execute(
        """SELECT p.id, p.texto, p.media, p.media_tipo, p.fecha, p.fijado,
                  COALESCE(p.gif_url,'') AS gif_url,
                  u.nombre, u.usuario, u.foto,
                  (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS total_likes,
                  (SELECT COUNT(*) FROM comentarios c WHERE c.post_id=p.id) AS total_comentarios
           FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
           WHERE p.usuario_id=%s ORDER BY p.fijado DESC, p.fecha DESC""",
        (uid,)
    ).fetchall()
    posts = []
    for r in rows:
        posts.append({
            "id": r["id"],
            "texto": r["texto"] or "",
            "media": r["media"] or "",
            "media_tipo": r["media_tipo"] or "",
            "fecha": str(r["fecha"])[:10] if r["fecha"] else "",
            "fijado": bool(r["fijado"]),
            "gif_url": r["gif_url"] or "",
            "nombre": r["nombre"],
            "usuario": r["usuario"],
            "foto": r["foto"] or "",
            "total_likes": r["total_likes"],
            "total_comentarios": r["total_comentarios"],
        })
    return jsonify({"ok": True, "posts": posts})


# ─── API: pronósticos mundial del usuario ─────────────────────────────────────
@perfil_bp.route("/api/perfil/mundial/<int:uid>")
def api_perfil_mundial(uid):
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con = get_db()
    rows = con.execute(
        """SELECT pr.id, pr.goles_local, pr.goles_visitante, pr.puntos,
                  pm.local, pm.visitante, pm.grupo,
                  pm.goles_local AS res_local, pm.goles_visitante AS res_visitante
           FROM pronosticos pr
           JOIN partidos_mundial pm ON pm.id=pr.partido_id
           WHERE pr.usuario_id=%s ORDER BY pr.id ASC""",
        (uid,)
    ).fetchall()
    total_puntos = sum(r["puntos"] or 0 for r in rows)
    pronosticos = []
    for r in rows:
        pronosticos.append({
            "local": r["local"],
            "visitante": r["visitante"],
            "grupo": r["grupo"],
            "pred_local": r["goles_local"],
            "pred_visitante": r["goles_visitante"],
            "res_local": r["res_local"],
            "res_visitante": r["res_visitante"],
            "puntos": r["puntos"] or 0,
        })
    return jsonify({"ok": True, "pronosticos": pronosticos, "total_puntos": total_puntos})


# ─── API: galería del usuario ─────────────────────────────────────────────────
@perfil_bp.route("/api/perfil/galeria/<int:uid>")
def api_perfil_galeria(uid):
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    con = get_db()
    rows = con.execute(
        "SELECT id, ruta, tipo, descripcion, fecha FROM galeria WHERE usuario_id=%s ORDER BY fecha DESC",
        (uid,)
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "ruta": r["ruta"],
            "tipo": r["tipo"],
            "descripcion": r["descripcion"] or "",
            "fecha": str(r["fecha"])[:10] if r["fecha"] else "",
        })
    return jsonify({"ok": True, "items": items})

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
