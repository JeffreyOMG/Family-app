import os, uuid
from flask import Blueprint, request, redirect, session, jsonify, current_app, render_template_string
from database import get_db
from werkzeug.utils import secure_filename

posts_bp = Blueprint("posts", __name__)
ALLOWED = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "mov", "avi", "webm"}

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

def allowed(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED

def save_file(f):
    ext   = f.filename.rsplit(".", 1)[1].lower()
    name  = uuid.uuid4().hex + "." + ext
    path  = os.path.join(current_app.config["UPLOAD_FOLDER"], name)
    f.save(path)
    tipo  = "video" if ext in {"mp4", "mov", "avi", "webm"} else "imagen"
    return f"/static/uploads/{name}", tipo

POST_TMPL = """
<article class="post-card" id="post-{{ p.id }}">
  <div class="post-header">
    {% if p.foto %}<img src="{{ p.foto }}" class="user-avatar-img post-av">
    {% else %}<div class="user-avatar post-av">{{ p.nombre[0]|upper }}</div>{% endif %}
    <div class="post-meta-block">
      <span class="post-name">{{ p.nombre }}</span>
      <span class="post-handle">@{{ p.usuario }} · ahora</span>
    </div>
    <form method="POST" action="/eliminar_post/{{ p.id }}" class="post-delete-form ajax-form" data-ajax="true">
      <button type="submit" class="post-delete-btn" title="Eliminar">
        <span class="material-symbols-outlined">more_horiz</span>
      </button>
    </form>
  </div>
  {% if p.texto %}<p class="post-text">{{ p.texto }}</p>{% endif %}
  {% if p.media %}
    {% if p.media_tipo=='imagen' %}<img src="{{ p.media }}" class="post-media" onclick="abrirMediaModal('{{ p.media }}','imagen')">
    {% else %}<video controls class="post-media"><source src="{{ p.media }}"></video>{% endif %}
  {% endif %}
  <div class="post-actions">
    <button type="button" class="post-action-btn like-btn" onclick="darLike({{ p.id }},this)">
      <span class="material-symbols-outlined heart-icon">favorite</span>
      <span class="like-count">0</span>
    </button>
    <button type="button" class="post-action-btn" onclick="abrirComentarios({{ p.id }})">
      <span class="material-symbols-outlined">chat_bubble</span>
      <span id="cmt-count-{{ p.id }}">0</span>
    </button>
    <button type="button" class="post-action-btn repost-btn" onclick="repostear({{ p.id }},this)">
      <span class="material-symbols-outlined">repeat</span>
      <span class="repost-count">0</span>
    </button>
    <button type="button" class="post-action-btn share-btn" onclick="compartirPost({{ p.id }}, `{{ p.texto[:80]|replace('\`','') if p.texto else '' }}`)">
      <span class="material-symbols-outlined">share</span>
    </button>
    <button type="button" class="post-action-btn bookmark-btn" style="margin-left:auto;" onclick="this.classList.toggle('saved')">
      <span class="material-symbols-outlined">bookmark</span>
    </button>
  </div>
  <div id="comentarios-{{ p.id }}" class="comments-section">
    <div class="comment-form">
      <div class="user-avatar comment-av">?</div>
      <input type="text" class="comment-input" placeholder="Escribe un comentario..."
        id="cinput-{{ p.id }}"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();enviarComentario({{ p.id }},this);}">
      <button type="button" class="btn-comment" onclick="enviarComentario({{ p.id }},document.getElementById('cinput-{{ p.id }}'))">
        <span class="material-symbols-outlined">arrow_upward</span>
      </button>
    </div>
  </div>
</article>
"""

@posts_bp.route("/publicar", methods=["POST"])
def publicar():
    if "uid" not in session:
        return redirect("/")
    _guardar_post()
    return redirect("/dashboard")

@posts_bp.route("/publicar_ajax", methods=["POST"])
def publicar_ajax():
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    post_id = _guardar_post()
    if not post_id:
        return jsonify({"ok": False}), 400
    con = get_db()
    p = con.execute("""
        SELECT p.id,p.texto,p.media,p.media_tipo,u.nombre,u.usuario,u.foto
        FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.id=?
    """, (post_id,)).fetchone()
    if not p:
        return jsonify({"ok": False}), 400
    html = render_template_string(POST_TMPL, p=dict(p))
    return jsonify({"ok": True, "html": html})

def _guardar_post():
    uid    = session["uid"]
    texto  = request.form.get("texto", "").strip()
    archivo = request.files.get("media")
    media, media_tipo = "", ""
    if archivo and archivo.filename and allowed(archivo.filename):
        media, media_tipo = save_file(archivo)
        con = get_db()
        con.execute("INSERT INTO galeria(usuario_id,ruta,tipo) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (uid, media, media_tipo))
        con.commit()
    if not texto and not media:
        return None
    con = get_db()
    cur = con.execute(
        "INSERT INTO publicaciones(usuario_id,texto,media,media_tipo) VALUES(%s,%s,%s,%s) RETURNING id",
        (uid, texto, media, media_tipo)
    )
    con.commit()
    return cur.fetchone()[0]

@posts_bp.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    exist = con.execute("SELECT 1 FROM likes WHERE usuario_id=? AND post_id=?", (uid, post_id)).fetchone()
    if exist:
        con.execute("DELETE FROM likes WHERE usuario_id=? AND post_id=?", (uid, post_id))
        liked = False
    else:
        con.execute("INSERT INTO likes(usuario_id,post_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (uid, post_id))
        liked = True
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM likes WHERE post_id=?", (post_id,)).fetchone()[0]
    return jsonify({"ok": True, "likes": total, "liked": liked})

@posts_bp.route("/comentar", methods=["POST"])
def comentar():
    if "uid" not in session:
        return redirect("/")
    uid       = session["uid"]
    post_id   = request.form.get("post_id")
    texto     = request.form.get("comentario", "").strip()
    parent_id = request.form.get("parent_id") or None
    if texto and post_id:
        con = get_db()
        con.execute("INSERT INTO comentarios(post_id,usuario_id,texto,parent_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (post_id, uid, texto, parent_id))
        con.commit()
    return redirect("/dashboard#inicio")

@posts_bp.route("/comentar_ajax", methods=["POST"])
def comentar_ajax():
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid       = session["uid"]
    post_id   = request.form.get("post_id")
    texto     = request.form.get("comentario", "").strip()
    parent_id = request.form.get("parent_id") or None
    if not texto or not post_id:
        return jsonify({"ok": False}), 400
    con = get_db()
    con.execute("INSERT INTO comentarios(post_id,usuario_id,texto,parent_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (post_id, uid, texto, parent_id))
    con.commit()
    usuario = con.execute("SELECT nombre, foto FROM usuarios WHERE id=?", (uid,)).fetchone()
    nombre = usuario["nombre"] if usuario else "?"
    inicial = nombre[0].upper() if nombre else "?"
    return jsonify({"ok": True, "nombre": nombre, "texto": texto, "inicial": inicial})

@posts_bp.route("/eliminar_post/<int:post_id>", methods=["POST"])
def eliminar_post(post_id):
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    con  = get_db()
    post = con.execute("SELECT usuario_id FROM publicaciones WHERE id=?", (post_id,)).fetchone()
    if post and (post["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        con.execute("DELETE FROM publicaciones WHERE id=?", (post_id,))
        con.commit()
    if _is_ajax():
        return jsonify({"ok": True})
    return redirect("/dashboard#inicio")

@posts_bp.route("/crear_noticia", methods=["POST"])
def crear_noticia():
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard")
    titulo    = request.form.get("titulo", "").strip()
    contenido = request.form.get("contenido", "").strip()
    if titulo and contenido:
        con = get_db()
        cur = con.execute("INSERT INTO noticias(titulo,contenido) VALUES(%s,%s) RETURNING id", (titulo, contenido))
        con.commit()
        if _is_ajax():
            return jsonify({"ok": True, "id": cur.fetchone()[0], "titulo": titulo})
    elif _is_ajax():
        return jsonify({"ok": False, "error": "Datos requeridos"}), 400
    return redirect("/dashboard#noticias")

# ── BOOKMARK (guardar/desguardar) ──
@posts_bp.route("/bookmark/<int:post_id>", methods=["POST"])
def bookmark(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    exist = con.execute("SELECT 1 FROM bookmarks WHERE usuario_id=? AND post_id=?", (uid, post_id)).fetchone()
    if exist:
        con.execute("DELETE FROM bookmarks WHERE usuario_id=? AND post_id=?", (uid, post_id))
        saved = False
    else:
        con.execute("INSERT INTO bookmarks(usuario_id,post_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (uid, post_id))
        saved = True
    con.commit()
    return jsonify({"ok": True, "saved": saved})

# ── REPOST ──
@posts_bp.route("/repost/<int:post_id>", methods=["POST"])
def repost(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    exist = con.execute("SELECT 1 FROM reposts WHERE usuario_id=? AND post_id=?", (uid, post_id)).fetchone()
    if exist:
        con.execute("DELETE FROM reposts WHERE usuario_id=? AND post_id=?", (uid, post_id))
        reposted = False
    else:
        con.execute("INSERT INTO reposts(usuario_id,post_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (uid, post_id))
        reposted = True
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM reposts WHERE post_id=?", (post_id,)).fetchone()[0]
    return jsonify({"ok": True, "reposted": reposted, "reposts": total})
