from flask import Flask
from database import init_db, init_amigo_secreto, close_db
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "familia-secret-2026")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

app.teardown_appcontext(close_db)

import json as _json
@app.template_filter('fromjson')
def fromjson_filter(s):
    try: return _json.loads(s)
    except: return []

# ── Filtro Cloudinary: transforma URLs para servir imágenes optimizadas ────────
from cloudinary_transform import (
    cl_url as _cl_url,
    cl_video as _cl_video,
    cl_poster as _cl_poster,
    cl_url_js_presets as _cl_presets,
)
@app.template_filter('cl_url')
def cl_url_filter(url, preset='feed'):
    return _cl_url(url, preset)

@app.template_filter('cl_video')
def cl_video_filter(url, preset='feed'):
    return _cl_video(url, preset)

@app.template_filter('cl_poster')
def cl_poster_filter(url):
    return _cl_poster(url)

# Exponer los presets al contexto global de templates (para el helper JS)
@app.context_processor
def inject_cl_presets():
    return {'CL_PRESETS_JS': _cl_presets()}

from routes.auth           import auth_bp
from routes.dashboard      import dash_bp
from routes.posts          import posts_bp
from routes.finanzas       import fin_bp
from routes.perfil         import perfil_bp
from routes.galeria        import galeria_bp
from routes.mundial        import mundial_bp
from routes.buscar         import buscar_bp
from routes.eventos        import eventos_bp
from routes.ajustes        import ajustes_bp
from routes.amigo_secreto  import amigo_bp
from routes.cajitas        import cajitas_bp
from routes.admin          import admin_bp          # ← NUEVO
from routes.seguidores     import seguidores_bp     # ← FASE 3.1
from routes.notificaciones import notif_bp           # ← Notificaciones
from routes.mundial_api    import mundial_api_bp     # ← API Mundial 2026
from routes.wc_proxy import wc_bp
app.register_blueprint(wc_bp)

for bp in [auth_bp, dash_bp, posts_bp, fin_bp, perfil_bp,
           galeria_bp, mundial_bp, buscar_bp, eventos_bp, ajustes_bp,
           amigo_bp, cajitas_bp, admin_bp, seguidores_bp, notif_bp,
           mundial_api_bp]:
    app.register_blueprint(bp)

with app.app_context():
    try:
        init_db()
        init_amigo_secreto()
    except Exception as e:
        print(f"DB init warning: {e}")

if __name__ == "__main__":
    app.run(port=5000)
