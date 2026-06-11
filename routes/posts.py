from decorators import miembro_required, login_required
from flask import Blueprint, request, redirect, session, jsonify, render_template_string
from database import get_db
from cloudinary_helper import subir_a_cloudinary
import json as _json
import datetime

posts_bp = Blueprint("posts", __name__)

def _get_poll(con, post_id, uid=None):
    """Retorna datos de encuesta para un post, con % por opción y voto del usuario."""
    enc = con.execute(
        "SELECT id, expira_en, anonima FROM encuestas WHERE post_id=%s", (post_id,)
    ).fetchone()
    if not enc:
        return None
    enc_id = enc["id"]
    opciones = con.execute(
        "SELECT id, texto, imagen FROM encuesta_opciones WHERE encuesta_id=%s ORDER BY orden",
        (enc_id,)
    ).fetchall()
    total = con.execute(
        "SELECT COUNT(*) FROM encuesta_votos WHERE encuesta_id=%s", (enc_id,)
    ).fetchone()[0]
    mi_voto = None
    if uid:
        v = con.execute(
            "SELECT opcion_id FROM encuesta_votos WHERE encuesta_id=%s AND usuario_id=%s",
            (enc_id, uid)
        ).fetchone()
        if v:
            mi_voto = v["opcion_id"]
    expira_str = str(enc["expira_en"]) if enc["expira_en"] else None
    expirada = False
    if expira_str:
        try:
            expirada = datetime.datetime.utcnow() > datetime.datetime.fromisoformat(expira_str)
        except Exception:
            pass
    result_opciones = []
    for op in opciones:
        cnt = con.execute(
            "SELECT COUNT(*) FROM encuesta_votos WHERE opcion_id=%s", (op["id"],)
        ).fetchone()[0]
        pct = round((cnt / total * 100) if total else 0, 1)
        votantes = []
        if not enc["anonima"]:
            rows = con.execute(
                """SELECT u.nombre, u.usuario, u.foto FROM encuesta_votos ev
                   JOIN usuarios u ON u.id=ev.usuario_id
                   WHERE ev.opcion_id=%s ORDER BY ev.votado_en DESC LIMIT 8""",
                (op["id"],)
            ).fetchall()
            votantes = [dict(r) for r in rows]
        result_opciones.append({
            "id": op["id"], "texto": op["texto"], "imagen": op["imagen"],
            "votos": cnt, "pct": pct, "votantes": votantes,
        })
    return {
        "id": enc_id, "anonima": bool(enc["anonima"]),
        "expira_en": expira_str, "expirada": expirada,
        "total_votos": total, "mi_voto": mi_voto,
        "opciones": result_opciones,
    }
ALLOWED = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "mov", "avi", "webm"}

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"

def allowed(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED

def save_file(f):
    """Sube archivo a Cloudinary, retorna (url, tipo)."""
    url, tipo = subir_a_cloudinary(f, folder="familia/posts")
    return url, tipo

POST_TMPL = """
<article class="post-card" id="post-{{ p.id }}">
  <div class="post-header">
    {% if p.foto %}<img src="{{ p.foto }}" class="user-avatar-img post-av">
    {% else %}<div class="user-avatar post-av">{{ p.nombre[0]|upper }}</div>{% endif %}
    <div class="post-meta-block">
      <span class="post-name">{{ p.nombre }}</span>
      <span class="post-handle">@{{ p.usuario }} · {% if p.fecha %}{{ p.fecha[:10] }}{% endif %}</span>
    </div>
    <form method="POST" action="/eliminar_post/{{ p.id }}" class="post-delete-form ajax-form" data-ajax="true">
      <button type="submit" class="post-delete-btn" title="Eliminar">
        <span class="material-symbols-outlined">more_horiz</span>
      </button>
    </form>
  </div>
  {% if p.texto %}<p class="post-text">{{ p.texto }}</p>{% endif %}
  {% if p.get('gif_url') %}
    <img src="{{ p.gif_url }}" alt="GIF" class="post-gif-img" loading="lazy"
         onclick="abrirMediaModal('{{ p.gif_url }}','imagen')">
  {% endif %}
  {% if p.media %}
    {% if p.media_tipo=='multi' %}
      {% set imgs = p.media|fromjson %}
      <div class="post-carousel" data-imgs='{{ p.media }}'>
        <div class="pc-track">
          {% for img in imgs %}
          <div class="pc-slide"><img src="{{ img }}" class="pc-img" onclick="abrirMediaModal('{{ img }}','imagen')"></div>
          {% endfor %}
        </div>
        {% if imgs|length > 1 %}
        <button class="pc-btn pc-prev" onclick="pcMove(this,-1)">&#8249;</button>
        <button class="pc-btn pc-next" onclick="pcMove(this,1)">&#8250;</button>
        <div class="pc-dots">{% for img in imgs %}<span class="pc-dot{% if loop.first %} active{% endif %}"></span>{% endfor %}</div>
        {% endif %}
      </div>
    {% elif p.media_tipo=='imagen' %}
      <img src="{{ p.media }}" class="post-media" onclick="abrirMediaModal('{{ p.media }}','imagen')">
    {% else %}
      <video controls class="post-media"><source src="{{ p.media }}"></video>
    {% endif %}
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
    <button type="button" class="post-action-btn share-btn" onclick="compartirPost({{ p.id }}, `{{ p.texto[:80]|replace('`','') if p.texto else '' }}`)">
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
@login_required
def publicar():
    if "uid" not in session:
        return redirect("/")
    _guardar_post()
    return redirect("/dashboard")

@posts_bp.route("/publicar_ajax", methods=["POST"])
@login_required
def publicar_ajax():
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    post_id = _guardar_post()
    if not post_id:
        return jsonify({"ok": False}), 400
    uid = session["uid"]
    con = get_db()
    p = con.execute("""
        SELECT p.id,p.texto,p.media,p.media_tipo,p.fecha,p.gif_url,u.nombre,u.usuario,u.foto
        FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.id=%s
    """, (post_id,)).fetchone()
    if not p:
        return jsonify({"ok": False}), 400
    poll = _get_poll(con, post_id, uid)
    html = render_template_string(POST_TMPL, p=dict(p), poll=poll)
    # Disparar notificaciones post-publicación (no bloquea la respuesta)
    _notificar_post(con, post_id, uid, p["texto"] or "")
    return jsonify({"ok": True, "html": html})

def _guardar_post():
    uid     = session["uid"]
    texto   = request.form.get("texto", "").strip()
    archivos = request.files.getlist("media")[:5]  # max 5
    urls, tipos = [], []
    con = get_db()
    for archivo in archivos:
        if archivo and archivo.filename and allowed(archivo.filename):
            url, tipo = save_file(archivo)
            if url:
                urls.append(url)
                tipos.append(tipo)
                con.execute(
                    "INSERT INTO galeria(usuario_id, ruta, tipo) VALUES(%s, %s, %s) ON CONFLICT DO NOTHING",
                    (uid, url, tipo)
                )
    if urls:
        con.commit()
    if len(urls) == 0:
        media, media_tipo = "", ""
    elif len(urls) == 1:
        media, media_tipo = urls[0], tipos[0]
    else:
        media      = _json.dumps(urls)
        media_tipo = "multi"

    # ── Poll ──
    poll_opts_raw = request.form.get("poll_options", "")
    poll_opts = []
    if poll_opts_raw:
        try:
            poll_opts = _json.loads(poll_opts_raw)
        except Exception:
            poll_opts = []
    has_poll = len(poll_opts) >= 2

    gif_url = request.form.get('gif_url', '').strip()

    if not texto and not media and not has_poll and not gif_url:
        return None

    if texto and len(texto) > 800:
        return None   # silently reject oversized text (frontend already blocks it)

    visibilidad = request.form.get('visibilidad', 'general')
    if visibilidad not in ('general', 'privada'):
        visibilidad = 'general'
    if session.get('rol', 'invitado') == 'invitado':
        visibilidad = 'general'

    cur = con.execute(
        "INSERT INTO publicaciones(usuario_id, texto, media, media_tipo, visibilidad, gif_url) VALUES(%s, %s, %s, %s, %s, %s) RETURNING id",
        (uid, texto, media, media_tipo, visibilidad, gif_url)
    )
    con.commit()
    post_id = cur.fetchone()[0]

    if has_poll:
        dias    = int(request.form.get("poll_dias", 1) or 1)
        horas   = int(request.form.get("poll_horas", 0) or 0)
        minutos = int(request.form.get("poll_minutos", 0) or 0)
        total_mins = dias * 24 * 60 + horas * 60 + minutos
        if total_mins < 5:
            total_mins = 1440
        expira_en = datetime.datetime.utcnow() + datetime.timedelta(minutes=total_mins)
        anonima_val = request.form.get("poll_anonima", "true").lower() != "false"
        cur_enc = con.execute(
            "INSERT INTO encuestas(post_id, expira_en, anonima) VALUES(%s, %s, %s) RETURNING id",
            (post_id, expira_en, anonima_val)
        )
        con.commit()
        enc_id = cur_enc.fetchone()[0]
        for i, opt_text in enumerate(poll_opts[:4]):
            img_url = ""
            img_file = request.files.get(f"poll_img_{i}")
            if img_file and img_file.filename:
                img_url, _ = subir_a_cloudinary(img_file, folder="familia/polls")
            con.execute(
                "INSERT INTO encuesta_opciones(encuesta_id, texto, imagen, orden) VALUES(%s, %s, %s, %s)",
                (enc_id, str(opt_text)[:25], img_url or "", i)
            )
        con.commit()

    return post_id


def _notificar_post(con, post_id, uid, texto):
    """Lanza notificaciones después de publicar un post."""
    try:
        from routes.notificaciones import notificar_menciones, notificar_admin_post
        # Menciones en el texto del post
        notificar_menciones(con, actor_id=uid, texto=texto, post_id=post_id)
        # Si es admin, notificar a todos
        if session.get("rol") == "admin":
            notificar_admin_post(con, post_id, uid)
        con.commit()
    except Exception:
        pass

@posts_bp.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    exist = con.execute("SELECT 1 FROM likes WHERE usuario_id=%s AND post_id=%s", (uid, post_id)).fetchone()
    if exist:
        con.execute("DELETE FROM likes WHERE usuario_id=%s AND post_id=%s", (uid, post_id))
        liked = False
    else:
        con.execute("INSERT INTO likes(usuario_id, post_id) VALUES(%s, %s) ON CONFLICT DO NOTHING", (uid, post_id))
        liked = True
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM likes WHERE post_id=%s", (post_id,)).fetchone()[0]

    # ── Notificación de like ──────────────────────────────────────────────────
    if liked:
        try:
            from routes.notificaciones import crear_notificacion
            post_owner = con.execute("SELECT usuario_id FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
            if post_owner:
                crear_notificacion(con, dest_id=post_owner["usuario_id"], tipo="like",
                                   actor_id=uid, post_id=post_id)
                con.commit()
        except Exception:
            pass

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
        con.execute(
            "INSERT INTO comentarios(post_id, usuario_id, texto, parent_id) VALUES(%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (post_id, uid, texto, parent_id)
        )
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
    gif_url   = request.form.get("gif_url", "").strip()
    if not (texto or gif_url) or not post_id:
        return jsonify({"ok": False}), 400
    con = get_db()
    con.execute(
        "INSERT INTO comentarios(post_id, usuario_id, texto, parent_id, gif_url) VALUES(%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (post_id, uid, texto, parent_id, gif_url)
    )
    con.commit()
    usuario = con.execute("SELECT nombre, foto, usuario, COALESCE(verified,FALSE) AS verified FROM usuarios WHERE id=%s", (uid,)).fetchone()
    nombre   = usuario["nombre"] if usuario else "?"
    inicial  = nombre[0].upper() if nombre else "?"
    foto     = (usuario["foto"] or "") if usuario else ""
    uname    = (usuario["usuario"] or "") if usuario else ""
    verified = bool(usuario["verified"]) if usuario else False
    cmt_id  = con.execute("SELECT lastval()").fetchone()[0]

    # ── Notificaciones de comentario y menciones ──────────────────────────────
    try:
        from routes.notificaciones import crear_notificacion, notificar_menciones
        # Notificar al dueño del post
        post_owner = con.execute("SELECT usuario_id FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
        if post_owner:
            crear_notificacion(con, dest_id=post_owner["usuario_id"], tipo="comentario",
                               actor_id=uid, post_id=int(post_id), comentario_id=cmt_id,
                               texto_extra=(texto or "")[:120])
        # Si es respuesta, notificar al autor del comentario padre
        if parent_id:
            parent = con.execute("SELECT usuario_id FROM comentarios WHERE id=%s", (parent_id,)).fetchone()
            if parent and parent["usuario_id"] != (post_owner["usuario_id"] if post_owner else None):
                crear_notificacion(con, dest_id=parent["usuario_id"], tipo="respuesta",
                                   actor_id=uid, post_id=int(post_id), comentario_id=cmt_id,
                                   texto_extra=(texto or "")[:120])
        # Menciones en el texto
        notificar_menciones(con, actor_id=uid, texto=texto,
                            post_id=int(post_id), comentario_id=cmt_id)
        con.commit()
    except Exception:
        pass

    return jsonify({"ok": True, "nombre": nombre, "foto": foto, "texto": texto, "inicial": inicial, "id": cmt_id, "usuario_id": uid, "usuario": uname, "gif_url": gif_url, "verified": verified})

@posts_bp.route("/eliminar_post/<int:post_id>", methods=["POST"])
def eliminar_post(post_id):
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    con  = get_db()
    post = con.execute("SELECT usuario_id FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
    if post and (post["usuario_id"] == session["uid"] or session.get("rol") == "admin"):
        con.execute("DELETE FROM publicaciones WHERE id=%s", (post_id,))
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
        cur = con.execute(
            "INSERT INTO noticias(titulo, contenido) VALUES(%s, %s) RETURNING id",
            (titulo, contenido)
        )
        con.commit()
        if _is_ajax():
            return jsonify({"ok": True, "id": cur.fetchone()[0], "titulo": titulo})
    elif _is_ajax():
        return jsonify({"ok": False, "error": "Datos requeridos"}), 400
    return redirect("/dashboard#noticias")

@posts_bp.route("/bookmark/<int:post_id>", methods=["POST"])
def bookmark(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    exist = con.execute("SELECT 1 FROM bookmarks WHERE usuario_id=%s AND post_id=%s", (uid, post_id)).fetchone()
    if exist:
        con.execute("DELETE FROM bookmarks WHERE usuario_id=%s AND post_id=%s", (uid, post_id))
        saved = False
    else:
        con.execute("INSERT INTO bookmarks(usuario_id, post_id) VALUES(%s, %s) ON CONFLICT DO NOTHING", (uid, post_id))
        saved = True
    con.commit()
    return jsonify({"ok": True, "saved": saved})

@posts_bp.route("/repost/<int:post_id>", methods=["POST"])
def repost(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    exist = con.execute("SELECT 1 FROM reposts WHERE usuario_id=%s AND post_id=%s", (uid, post_id)).fetchone()
    if exist:
        con.execute("DELETE FROM reposts WHERE usuario_id=%s AND post_id=%s", (uid, post_id))
        reposted = False
    else:
        con.execute("INSERT INTO reposts(usuario_id, post_id) VALUES(%s, %s) ON CONFLICT DO NOTHING", (uid, post_id))
        reposted = True
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM reposts WHERE post_id=%s", (post_id,)).fetchone()[0]

    # ── Notificación de repost ────────────────────────────────────────────────
    if reposted:
        try:
            from routes.notificaciones import crear_notificacion
            post_owner = con.execute("SELECT usuario_id FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
            if post_owner:
                crear_notificacion(con, dest_id=post_owner["usuario_id"], tipo="repost",
                                   actor_id=uid, post_id=post_id)
                con.commit()
        except Exception:
            pass

    return jsonify({"ok": True, "reposted": reposted, "reposts": total})


# ─── FIJAR POST ───────────────────────────────────────────────────────────────
@posts_bp.route("/fijar_post/<int:post_id>", methods=["POST"])
def fijar_post(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    post = con.execute("SELECT usuario_id, fijado FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
    if not post or post["usuario_id"] != uid:
        return jsonify({"ok": False, "error": "No autorizado"}), 403

    ya_fijado = bool(post["fijado"])

    if ya_fijado:
        # Desfijar este post
        con.execute("UPDATE publicaciones SET fijado=FALSE WHERE id=%s AND usuario_id=%s", (post_id, uid))
        con.commit()
        return jsonify({"ok": True, "fijado": False})
    else:
        # Desfijar cualquier otro post previo del usuario y fijar este
        con.execute("UPDATE publicaciones SET fijado=FALSE WHERE usuario_id=%s", (uid,))
        con.execute("UPDATE publicaciones SET fijado=TRUE  WHERE id=%s AND usuario_id=%s", (post_id, uid))
        con.commit()
        return jsonify({"ok": True, "fijado": True})


# ─── FIJAR PARA TODOS (solo admin) ──────────────────────────────────────────
@posts_bp.route("/fijar_admin/<int:post_id>", methods=["POST"])
def fijar_admin(post_id):
    if "uid" not in session or session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    con = get_db()
    post = con.execute("SELECT id, fijado_admin FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
    if not post:
        return jsonify({"ok": False, "error": "Post no encontrado"}), 404

    ya_fijado = bool(post["fijado_admin"])
    if ya_fijado:
        con.execute("UPDATE publicaciones SET fijado_admin=FALSE WHERE id=%s", (post_id,))
        con.commit()
        return jsonify({"ok": True, "fijado_admin": False})
    else:
        # Solo puede haber uno fijado por admin a la vez
        con.execute("UPDATE publicaciones SET fijado_admin=FALSE WHERE fijado_admin=TRUE")
        con.execute("UPDATE publicaciones SET fijado_admin=TRUE WHERE id=%s", (post_id,))
        con.commit()
        return jsonify({"ok": True, "fijado_admin": True})


# ─── ACTIVIDAD DEL POST ───────────────────────────────────────────────────────
@posts_bp.route("/api/post_actividad/<int:post_id>")
def post_actividad(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    post = con.execute("SELECT usuario_id FROM publicaciones WHERE id=%s", (post_id,)).fetchone()
    if not post or post["usuario_id"] != uid:
        return jsonify({"ok": False, "error": "No autorizado"}), 403

    total_likes    = con.execute("SELECT COUNT(*) FROM likes    WHERE post_id=%s", (post_id,)).fetchone()[0]
    total_reposts  = con.execute("SELECT COUNT(*) FROM reposts  WHERE post_id=%s", (post_id,)).fetchone()[0]
    total_comments = con.execute("SELECT COUNT(*) FROM comentarios WHERE post_id=%s", (post_id,)).fetchone()[0]
    total_bookmarks= con.execute("SELECT COUNT(*) FROM bookmarks WHERE post_id=%s", (post_id,)).fetchone()[0]

    return jsonify({
        "ok": True,
        "likes":     int(total_likes),
        "reposts":   int(total_reposts),
        "comments":  int(total_comments),
        "bookmarks": int(total_bookmarks),
    })

# ─── VER POST COMPLETO ───────────────────────────────────────────────────────
@posts_bp.route("/api/post/<int:post_id>")
def api_ver_post(post_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()

    p = con.execute("""
        SELECT p.id, p.texto, p.media, p.media_tipo, p.fecha,
               COALESCE(p.visibilidad,'general') AS visibilidad,
               COALESCE(p.gif_url,'') AS gif_url,
               u.nombre, u.usuario, u.foto, u.id AS usuario_id,
               COALESCE(u.verified, FALSE) AS verified,
               EXISTS(SELECT 1 FROM likes l WHERE l.usuario_id=%s AND l.post_id=p.id) AS liked,
               (SELECT COUNT(*) FROM likes l2 WHERE l2.post_id=p.id) AS total_likes,
               (SELECT COUNT(*) FROM reposts r WHERE r.post_id=p.id) AS total_reposts,
               EXISTS(SELECT 1 FROM bookmarks b WHERE b.usuario_id=%s AND b.post_id=p.id) AS bookmarked
        FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.id=%s
    """, (uid, uid, post_id)).fetchone()

    if not p:
        return jsonify({"ok": False, "error": "Post no encontrado"}), 404

    # Visibilidad: invitados solo ven posts generales
    rol = session.get("rol", "invitado")
    if rol not in ("miembro", "admin") and p["visibilidad"] == "privada":
        return jsonify({"ok": False, "error": "No autorizado"}), 403

    # Ensure likes table exists before querying
    con.execute("""CREATE TABLE IF NOT EXISTS comentario_likes (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        comentario_id INTEGER NOT NULL REFERENCES comentarios(id) ON DELETE CASCADE,
        PRIMARY KEY (usuario_id, comentario_id))""")

    comentarios_rows = con.execute("""
        SELECT c.id, c.texto, c.fecha, c.usuario_id, c.parent_id,
               COALESCE(c.gif_url,'') AS gif_url,
               u.nombre, u.usuario, u.foto, COALESCE(u.verified, FALSE) AS verified,
               (SELECT COUNT(*) FROM comentario_likes cl WHERE cl.comentario_id=c.id) AS total_likes,
               EXISTS(SELECT 1 FROM comentario_likes cl2 WHERE cl2.comentario_id=c.id AND cl2.usuario_id=%s) AS liked_by_me
        FROM comentarios c JOIN usuarios u ON u.id=c.usuario_id
        WHERE c.post_id=%s ORDER BY c.fecha ASC
    """, (uid, post_id,)).fetchall()

    comentarios = []
    for c in comentarios_rows:
        row = dict(c)
        row['total_likes'] = int(row.get('total_likes') or 0)
        row['liked_by_me'] = bool(row.get('liked_by_me'))
        comentarios.append(row)
    poll = _get_poll(con, post_id, uid)

    return jsonify({
        "ok": True,
        "post": {
            "id":           p["id"],
            "texto":        p["texto"] or "",
            "media":        p["media"] or "",
            "media_tipo":   p["media_tipo"] or "",
            "gif_url":      p["gif_url"] or "",
            "fecha":        str(p["fecha"])[:10] if p["fecha"] else "",
            "visibilidad":  p["visibilidad"],
            "nombre":       p["nombre"],
            "usuario":      p["usuario"],
            "foto":         p["foto"] or "",
            "verified":     bool(p.get("verified", False)),
            "usuario_id":   p["usuario_id"],
            "liked":        bool(p["liked"]),
            "bookmarked":   bool(p["bookmarked"]),
            "total_likes":  int(p["total_likes"]),
            "total_reposts":int(p["total_reposts"]),
            "comentarios":  comentarios,
            "poll":         poll,
        }
    })


# ─── ENCUESTA: VOTAR ──────────────────────────────────────────────────────────
@posts_bp.route("/votar_encuesta/<int:enc_id>/<int:opcion_id>", methods=["POST"])
def votar_encuesta(enc_id, opcion_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    enc = con.execute("SELECT id, expira_en FROM encuestas WHERE id=%s", (enc_id,)).fetchone()
    if not enc:
        return jsonify({"ok": False, "error": "Encuesta no encontrada"}), 404
    expira = enc["expira_en"]
    if expira:
        try:
            if datetime.datetime.utcnow() > datetime.datetime.fromisoformat(str(expira)):
                return jsonify({"ok": False, "error": "Encuesta cerrada"}), 400
        except Exception:
            pass
    op = con.execute(
        "SELECT id FROM encuesta_opciones WHERE id=%s AND encuesta_id=%s", (opcion_id, enc_id)
    ).fetchone()
    if not op:
        return jsonify({"ok": False}), 400
    exist = con.execute(
        "SELECT id FROM encuesta_votos WHERE encuesta_id=%s AND usuario_id=%s", (enc_id, uid)
    ).fetchone()
    if exist:
        con.execute(
            "UPDATE encuesta_votos SET opcion_id=%s, votado_en=NOW() WHERE encuesta_id=%s AND usuario_id=%s",
            (opcion_id, enc_id, uid)
        )
    else:
        con.execute(
            "INSERT INTO encuesta_votos(encuesta_id, opcion_id, usuario_id) VALUES(%s, %s, %s)",
            (enc_id, opcion_id, uid)
        )
    con.commit()
    post = con.execute("SELECT post_id FROM encuestas WHERE id=%s", (enc_id,)).fetchone()
    poll = _get_poll(con, post["post_id"], uid)
    return jsonify({"ok": True, "poll": poll})


# ─── ENCUESTA: QUITAR VOTO ────────────────────────────────────────────────────
@posts_bp.route("/quitar_voto/<int:enc_id>", methods=["POST"])
def quitar_voto(enc_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    enc = con.execute("SELECT id, expira_en FROM encuestas WHERE id=%s", (enc_id,)).fetchone()
    if not enc:
        return jsonify({"ok": False}), 404
    expira = enc["expira_en"]
    if expira:
        try:
            if datetime.datetime.utcnow() > datetime.datetime.fromisoformat(str(expira)):
                return jsonify({"ok": False, "error": "Encuesta cerrada"}), 400
        except Exception:
            pass
    con.execute(
        "DELETE FROM encuesta_votos WHERE encuesta_id=%s AND usuario_id=%s", (enc_id, uid)
    )
    con.commit()
    post = con.execute("SELECT post_id FROM encuestas WHERE id=%s", (enc_id,)).fetchone()
    poll = _get_poll(con, post["post_id"], uid)
    return jsonify({"ok": True, "poll": poll})


# ─── ENCUESTA: RESULTADOS (tiempo real) ───────────────────────────────────────
@posts_bp.route("/poll_resultados/<int:enc_id>")
def poll_resultados(enc_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    post = con.execute("SELECT post_id FROM encuestas WHERE id=%s", (enc_id,)).fetchone()
    if not post:
        return jsonify({"ok": False}), 404
    poll = _get_poll(con, post["post_id"], uid)
    return jsonify({"ok": True, "poll": poll})


# ─── EDITAR COMENTARIO ───────────────────────────────────────────────────────
@posts_bp.route("/editar_comentario/<int:cmt_id>", methods=["POST"])
def editar_comentario(cmt_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid  = session["uid"]
    texto = request.form.get("texto", "").strip()
    if not texto:
        return jsonify({"ok": False, "error": "Texto vacío"}), 400
    con  = get_db()
    cmt  = con.execute("SELECT usuario_id FROM comentarios WHERE id=%s", (cmt_id,)).fetchone()
    if not cmt:
        return jsonify({"ok": False, "error": "No encontrado"}), 404
    if cmt["usuario_id"] != uid and session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    con.execute("UPDATE comentarios SET texto=%s WHERE id=%s", (texto, cmt_id))
    con.commit()
    return jsonify({"ok": True, "texto": texto})


# ─── ELIMINAR COMENTARIO ─────────────────────────────────────────────────────
@posts_bp.route("/eliminar_comentario/<int:cmt_id>", methods=["POST"])
def eliminar_comentario(cmt_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    cmt = con.execute("SELECT usuario_id, post_id FROM comentarios WHERE id=%s", (cmt_id,)).fetchone()
    if not cmt:
        return jsonify({"ok": False, "error": "No encontrado"}), 404
    if cmt["usuario_id"] != uid and session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "No autorizado"}), 403
    post_id = cmt["post_id"]
    con.execute("DELETE FROM comentarios WHERE id=%s OR parent_id=%s", (cmt_id, cmt_id))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM comentarios WHERE post_id=%s", (post_id,)).fetchone()[0]
    return jsonify({"ok": True, "total": int(total)})


# ─── LIKE A COMENTARIO ───────────────────────────────────────────────────────
@posts_bp.route("/like_comentario/<int:cmt_id>", methods=["POST"])
def like_comentario(cmt_id):
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid = session["uid"]
    con = get_db()
    # Ensure table exists (lazy migration)
    con.execute("""CREATE TABLE IF NOT EXISTS comentario_likes (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        comentario_id INTEGER NOT NULL REFERENCES comentarios(id) ON DELETE CASCADE,
        PRIMARY KEY (usuario_id, comentario_id))""")
    con.commit()
    exist = con.execute(
        "SELECT 1 FROM comentario_likes WHERE usuario_id=%s AND comentario_id=%s", (uid, cmt_id)
    ).fetchone()
    if exist:
        con.execute("DELETE FROM comentario_likes WHERE usuario_id=%s AND comentario_id=%s", (uid, cmt_id))
        liked = False
    else:
        con.execute("INSERT INTO comentario_likes(usuario_id, comentario_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (uid, cmt_id))
        liked = True
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM comentario_likes WHERE comentario_id=%s", (cmt_id,)).fetchone()[0]
    return jsonify({"ok": True, "liked": liked, "total": int(total)})


# ─── RESPONDER COMENTARIO (ajax) ─────────────────────────────────────────────
@posts_bp.route("/responder_comentario", methods=["POST"])
def responder_comentario():
    if "uid" not in session:
        return jsonify({"ok": False}), 401
    uid       = session["uid"]
    post_id   = request.form.get("post_id")
    parent_id = request.form.get("parent_id")
    texto     = request.form.get("comentario", "").strip()
    if not texto or not post_id or not parent_id:
        return jsonify({"ok": False}), 400
    con = get_db()
    con.execute(
        "INSERT INTO comentarios(post_id, usuario_id, texto, parent_id) VALUES(%s,%s,%s,%s)",
        (post_id, uid, texto, parent_id)
    )
    con.commit()
    usuario = con.execute("SELECT nombre, usuario, foto, COALESCE(verified,FALSE) AS verified FROM usuarios WHERE id=%s", (uid,)).fetchone()
    nombre  = usuario["nombre"] if usuario else "?"
    return jsonify({
        "ok":       True,
        "nombre":   nombre,
        "usuario":  usuario["usuario"] if usuario else "",
        "foto":     (usuario["foto"] or "") if usuario else "",
        "texto":    texto,
        "inicial":  nombre[0].upper() if nombre else "?",
        "id":       con.execute("SELECT lastval()").fetchone()[0],
        "verified": bool(usuario["verified"]) if usuario else False,
    })
