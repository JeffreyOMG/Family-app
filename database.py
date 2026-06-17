import os
import pg8000.native
from flask import g
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ─────────────────────────────────────────────
# MUNDIAL 2026
# ─────────────────────────────────────────────

GRUPOS_MUNDIAL = {
    "A": [("México","mx"),("Sudáfrica","za"),("Corea del Sur","kr"),("República Checa","cz")],
    "B": [("Canadá","ca"),("Bosnia y Herz.","ba"),("Catar","qa"),("Suiza","ch")],
    "C": [("Brasil","br"),("Marruecos","ma"),("Haití","ht"),("Escocia","gb-sct")],
    "D": [("Estados Unidos","us"),("Paraguay","py"),("Australia","au"),("Turquía","tr")],
    "E": [("Alemania","de"),("Curazao","cw"),("Costa de Marfil","ci"),("Ecuador","ec")],
    "F": [("Países Bajos","nl"),("Japón","jp"),("Suecia","se"),("Túnez","tn")],
    "G": [("Bélgica","be"),("Egipto","eg"),("Irán","ir"),("Nueva Zelanda","nz")],
    "H": [("España","es"),("Cabo Verde","cv"),("Arabia Saudita","sa"),("Uruguay","uy")],
    "I": [("Francia","fr"),("Senegal","sn"),("Irak","iq"),("Noruega","no")],
    "J": [("Argentina","ar"),("Argelia","dz"),("Austria","at"),("Jordania","jo")],
    "K": [("Portugal","pt"),("Congo","cd"),("Uzbekistán","uz"),("Colombia","co")],
    "L": [("Inglaterra","gb-eng"),("Croacia","hr"),("Ghana","gh"),("Panamá","pa")]
}

def _build_partidos():
    ps = []
    pid = 1
    for grupo, equipos in GRUPOS_MUNDIAL.items():
        combos = [(0,1),(2,3),(0,2),(1,3),(0,3),(1,2)]
        for i, j in combos:
            local     = f"{equipos[i][0]}|{equipos[i][1]}"
            visitante = f"{equipos[j][0]}|{equipos[j][1]}"
            ps.append((pid, grupo, local, visitante))
            pid += 1
    return ps

PARTIDOS_MUNDIAL = _build_partidos()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _parse_url(url):
    r = urlparse(url)
    return dict(host=r.hostname, port=r.port or 5432,
                database=r.path.lstrip("/"), user=r.username,
                password=r.password, ssl_context=True)

def _to_pg(sql, params):
    """
    Convierte SQL con %s o ? en :p1,:p2,...
    y retorna un dict {"p1":v, "p2":v, ...} para pg8000.native.
    """
    import re
    idx = [0]
    def repl(_):
        idx[0] += 1
        return f":p{idx[0]}"
    pg_sql = re.sub(r'%s|\?', repl, sql)
    pg_params = {f"p{i+1}": v for i, v in enumerate(params)}
    return pg_sql, pg_params

# ─────────────────────────────────────────────
# ROW — acceso por nombre Y por índice numérico
# ─────────────────────────────────────────────

class _Row(dict):
    @staticmethod
    def _conv(v):
        import datetime
        if isinstance(v, (datetime.datetime, datetime.date)):
            return str(v)
        return v
    def __init__(self, keys, values):
        values = [self._conv(v) for v in values]
        super().__init__(zip(keys, values))
        self._list = list(values)
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._list[key]
        return super().__getitem__(key)
    def keys(self):
        return super().keys()

# ─────────────────────────────────────────────
# CURSOR
# ─────────────────────────────────────────────

class _Cursor:
    def __init__(self, pg_conn):
        self._pg = pg_conn
        self._rows = []
        self.lastrowid = None

    def execute(self, sql, params=()):
        pg_sql, pg_params = _to_pg(sql, params)
        rows = self._pg.run(pg_sql, **pg_params)
        cols = [c["name"] for c in (self._pg.columns or [])]
        self._rows = [_Row(cols, r) for r in (rows or [])]
        if self._rows and cols and cols[0] == "id":
            self.lastrowid = self._rows[0]["id"]
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)

# ─────────────────────────────────────────────
# CONEXIÓN — imita sqlite3
# ─────────────────────────────────────────────

class _Conn:
    def __init__(self):
        self._pg = pg8000.native.Connection(**_parse_url(DATABASE_URL))
        self._pg.run("BEGIN")

    def execute(self, sql, params=()):
        cur = _Cursor(self._pg)
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._pg.run("COMMIT")
        self._pg.run("BEGIN")

    def close(self):
        try:
            self._pg.run("COMMIT")
        except Exception:
            pass
        self._pg.close()

    def cursor(self):
        return _Cursor(self._pg)


def get_db():
    if "db" not in g:
        g.db = _Conn()
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

# ─────────────────────────────────────────────
# INICIALIZAR TABLAS
# ─────────────────────────────────────────────

_TABLES = [
    """CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY, nombre TEXT NOT NULL,
        usuario TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        rol TEXT DEFAULT 'invitado', gmail TEXT DEFAULT '',
        bio TEXT DEFAULT '', foto TEXT DEFAULT '',
        es_nuevo BOOLEAN DEFAULT TRUE,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    # Migración segura: añade la columna si la tabla ya existía sin ella
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS es_nuevo BOOLEAN DEFAULT TRUE""",
    # Columna para solicitud de pago al mundial (NULL=no solicitó, 'pendiente', 'aprobado', 'rechazado')
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS mundial_pagado TEXT DEFAULT NULL""",
    # Columnas de perfil extendido
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS portada TEXT""",
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS ciudad TEXT""",
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS sitio_web TEXT""",
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fecha_nacimiento DATE""",
    # Bloqueo de sección de recaudación (1 = bloqueado, no puede ver ni registrar aportes)
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS rec_bloqueado INTEGER DEFAULT 0""",
    """CREATE TABLE IF NOT EXISTS publicaciones (
        id SERIAL PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        texto TEXT DEFAULT '', media TEXT DEFAULT '', media_tipo TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    # Migración: columna visibilidad ('general' = todos ven, 'privada' = solo miembros/admin)
    """ALTER TABLE publicaciones ADD COLUMN IF NOT EXISTS visibilidad TEXT DEFAULT 'general'""",
    """ALTER TABLE publicaciones ADD COLUMN IF NOT EXISTS fijado BOOLEAN DEFAULT FALSE""",
    """ALTER TABLE publicaciones ADD COLUMN IF NOT EXISTS fijado_admin BOOLEAN DEFAULT FALSE""",
    """ALTER TABLE publicaciones ADD COLUMN IF NOT EXISTS gif_url TEXT DEFAULT ''""",
    """ALTER TABLE comentarios ADD COLUMN IF NOT EXISTS gif_url TEXT DEFAULT ''""",
    """CREATE TABLE IF NOT EXISTS likes (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        post_id INTEGER NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
        PRIMARY KEY (usuario_id, post_id))""",
    """CREATE TABLE IF NOT EXISTS comentarios (
        id SERIAL PRIMARY KEY,
        post_id INTEGER NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        texto TEXT NOT NULL, parent_id INTEGER DEFAULT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS noticias (
        id SERIAL PRIMARY KEY, titulo TEXT NOT NULL, contenido TEXT NOT NULL,
        categoria TEXT DEFAULT 'general', fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS eventos (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        titulo TEXT NOT NULL, descripcion TEXT DEFAULT '',
        fecha_evento TEXT NOT NULL, hora_evento TEXT DEFAULT '',
        tipo TEXT DEFAULT 'evento', fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS aportes (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        monto REAL DEFAULT 0, descripcion TEXT DEFAULT '',
        comprobante TEXT DEFAULT '', verificado INTEGER DEFAULT 0,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS galeria (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        ruta TEXT NOT NULL, tipo TEXT NOT NULL, descripcion TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS partidos_mundial (
        id INTEGER PRIMARY KEY, grupo TEXT NOT NULL,
        local TEXT NOT NULL, visitante TEXT NOT NULL,
        goles_local INTEGER DEFAULT NULL, goles_visitante INTEGER DEFAULT NULL,
        bloqueado INTEGER DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS pronosticos (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        partido_id INTEGER NOT NULL REFERENCES partidos_mundial(id) ON DELETE CASCADE,
        goles_local INTEGER NOT NULL, goles_visitante INTEGER NOT NULL,
        puntos INTEGER DEFAULT 0, UNIQUE(usuario_id, partido_id))""",
    """CREATE TABLE IF NOT EXISTS cajitas_ahorro (
        id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, descripcion TEXT DEFAULT '',
        creador_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS cajita_miembros (
        cajita_id INTEGER NOT NULL REFERENCES cajitas_ahorro(id) ON DELETE CASCADE,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        PRIMARY KEY (cajita_id, usuario_id))""",
    """CREATE TABLE IF NOT EXISTS cajita_movimientos (
        id SERIAL PRIMARY KEY,
        cajita_id INTEGER NOT NULL REFERENCES cajitas_ahorro(id) ON DELETE CASCADE,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        monto REAL NOT NULL, descripcion TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS eventos_recaudacion (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        nombre_evento TEXT NOT NULL, descripcion TEXT DEFAULT '',
        monto REAL NOT NULL, responsables TEXT DEFAULT '',
        soporte TEXT NOT NULL, estado TEXT DEFAULT 'pendiente',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS polla_pagos (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        fase INTEGER NOT NULL, monto REAL NOT NULL, soporte TEXT NOT NULL,
        estado TEXT DEFAULT 'pagado', fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(usuario_id, fase))""",
    """CREATE TABLE IF NOT EXISTS polla_pronosticos (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        fase INTEGER NOT NULL, datos TEXT NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(usuario_id, fase))""",
    """CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS bookmarks (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        post_id INTEGER NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (usuario_id, post_id))""",
    """CREATE TABLE IF NOT EXISTS reposts (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        post_id INTEGER NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (usuario_id, post_id))""",
    """CREATE TABLE IF NOT EXISTS amigo_secreto_eventos (
        id SERIAL PRIMARY KEY, nombre TEXT NOT NULL,
        activo INTEGER DEFAULT 1, cruces_generados INTEGER DEFAULT 0,
        tarifa_premio TEXT DEFAULT 'No definido',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS amigo_secreto_participantes (
        evento_id INTEGER NOT NULL REFERENCES amigo_secreto_eventos(id) ON DELETE CASCADE,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        asignado_id INTEGER DEFAULT NULL, PRIMARY KEY (evento_id, usuario_id))""",
    """CREATE TABLE IF NOT EXISTS lista_deseos (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE UNIQUE,
        descripcion TEXT NOT NULL,
        imagen_referencia TEXT DEFAULT NULL,
        link_referencia TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS cajitas_ahorro_codigos (
        cajita_id INTEGER PRIMARY KEY REFERENCES cajitas_ahorro(id) ON DELETE CASCADE,
        codigo TEXT UNIQUE NOT NULL)""",
    # ─── FASE 4: Usuarios Verificados ──────────────────────────────────────────
    """ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE""",
    # ─── FASE 3.1: Sistema de Seguidores ───────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS followers (
        id SERIAL PRIMARY KEY,
        follower_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        following_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT no_self_follow CHECK (follower_id <> following_id),
        UNIQUE (follower_id, following_id))""",
    # ── Encuestas ────────────────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS encuestas (
        id SERIAL PRIMARY KEY,
        post_id INTEGER NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
        expira_en TIMESTAMP,
        anonima BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS encuesta_opciones (
        id SERIAL PRIMARY KEY,
        encuesta_id INTEGER NOT NULL REFERENCES encuestas(id) ON DELETE CASCADE,
        texto TEXT NOT NULL,
        imagen TEXT DEFAULT '',
        orden INTEGER DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS encuesta_votos (
        id SERIAL PRIMARY KEY,
        encuesta_id INTEGER NOT NULL REFERENCES encuestas(id) ON DELETE CASCADE,
        opcion_id INTEGER NOT NULL REFERENCES encuesta_opciones(id) ON DELETE CASCADE,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        votado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (encuesta_id, usuario_id))""",

    # ── Índices para acelerar queries del feed ──────────────────────────────
    "CREATE INDEX IF NOT EXISTS idx_likes_post      ON likes(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_likes_usuario   ON likes(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_reposts_post    ON reposts(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_reposts_usuario ON reposts(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_bookmarks_post  ON bookmarks(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_bookmarks_user  ON bookmarks(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_pub_fecha       ON publicaciones(fecha DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pub_usuario     ON publicaciones(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_coment_post     ON comentarios(post_id)",
    # ── Sistema de Notificaciones ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS notificaciones (
        id             SERIAL PRIMARY KEY,
        dest_id        INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        tipo           TEXT    NOT NULL,
        actor_id       INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        post_id        INTEGER REFERENCES publicaciones(id) ON DELETE CASCADE,
        comentario_id  INTEGER REFERENCES comentarios(id) ON DELETE CASCADE,
        texto_extra    TEXT    DEFAULT '',
        leida          BOOLEAN DEFAULT FALSE,
        fecha          TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX IF NOT EXISTS idx_notif_dest  ON notificaciones(dest_id, leida)",
    "CREATE INDEX IF NOT EXISTS idx_notif_fecha ON notificaciones(fecha DESC)",
]

def init_db():
    pg = pg8000.native.Connection(**_parse_url(DATABASE_URL))
    for sql in _TABLES:
        try:
            pg.run(sql)
        except Exception as e:
            print(f"Table warning: {e}")

    admin_hash = generate_password_hash("admin1234")
    try:
        pg.run("INSERT INTO usuarios(nombre,usuario,password,rol,gmail) VALUES(:p1,:p2,:p3,:p4,:p5) ON CONFLICT(usuario) DO NOTHING", p1="Administrador", p2="admin", p3=admin_hash, p4="admin", p5="admin@familia.com")
    except Exception as e:
        print(f"Admin warning: {e}")

    try:
        pg.run("INSERT INTO config(clave,valor) VALUES(:p1,:p2) ON CONFLICT(clave) DO NOTHING", p1="meta_recaudacion", p2="500000")
    except Exception as e:
        print(f"Config warning: {e}")

    # ── Fases de pronósticos: bloqueadas por defecto ─────────────────────────
    for fase_key in ("fase_lock_grupos", "fase_lock_r16", "fase_lock_octavos",
                     "fase_lock_cuartos", "fase_lock_semis", "fase_lock_final"):
        try:
            pg.run("INSERT INTO config(clave,valor) VALUES(:p1,:p2) ON CONFLICT(clave) DO NOTHING",
                   p1=fase_key, p2="1")
        except Exception as e:
            print(f"Config fase warning: {e}")

    for pid, grupo, local, visitante in PARTIDOS_MUNDIAL:
        try:
            pg.run("INSERT INTO partidos_mundial(id,grupo,local,visitante) VALUES(:p1,:p2,:p3,:p4) ON CONFLICT(id) DO NOTHING", p1=pid, p2=grupo, p3=local, p4=visitante)
        except Exception as e:
            print(f"Partido warning: {e}")

    pg.run("COMMIT")
    pg.close()

def init_amigo_secreto():
    pass

def hash_password(p):
    return generate_password_hash(p)

def verify_password(h, p):
    return check_password_hash(h, p)
