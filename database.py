import sqlite3
from flask import g
from werkzeug.security import generate_password_hash, check_password_hash

DB = "familia.db"

# ─────────────────────────────────────────────
# MUNDIAL 2026 — 12 grupos × 4 equipos = 48 selecciones
# Formato: (País, código bandera ISO)
# Compatible con flag-icons (PC + móvil + web)
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

# ─────────────────────────────────────────────
# GENERAR PARTIDOS (TODOS LOS ENFRENTAMIENTOS)
# 6 partidos por grupo → 72 partidos total
# Formato DB: local/visitante = "Nombre|codigo"
# ─────────────────────────────────────────────

def _build_partidos():
    ps = []
    pid = 1
    for grupo, equipos in GRUPOS_MUNDIAL.items():
        combos = [(0,1),(2,3),(0,2),(1,3),(0,3),(1,2)]
        for i, j in combos:
            # Guardamos "Nombre|codigo" para poder separar limpiamente
            local     = f"{equipos[i][0]}|{equipos[i][1]}"
            visitante = f"{equipos[j][0]}|{equipos[j][1]}"
            ps.append((pid, grupo, local, visitante))
            pid += 1
    return ps

PARTIDOS_MUNDIAL = _build_partidos()

# ─────────────────────────────────────────────
# BASE DE DATOS FLASK
# ─────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

# ─────────────────────────────────────────────
# INICIALIZAR BASE DE DATOS
# ─────────────────────────────────────────────

def init_db():
    db = sqlite3.connect(DB)
    cur = db.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        usuario TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        rol TEXT DEFAULT 'miembro',
        gmail TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        foto TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS publicaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        texto TEXT DEFAULT '',
        media TEXT DEFAULT '',
        media_tipo TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS likes (
        usuario_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        PRIMARY KEY (usuario_id, post_id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (post_id) REFERENCES publicaciones(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS comentarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        texto TEXT NOT NULL,
        parent_id INTEGER DEFAULT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (post_id) REFERENCES publicaciones(id) ON DELETE CASCADE,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS noticias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        contenido TEXT NOT NULL,
        categoria TEXT DEFAULT 'general',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        titulo TEXT NOT NULL,
        descripcion TEXT DEFAULT '',
        fecha_evento TEXT NOT NULL,
        hora_evento TEXT DEFAULT '',
        tipo TEXT DEFAULT 'evento',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS aportes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        monto REAL DEFAULT 0,
        descripcion TEXT DEFAULT '',
        comprobante TEXT DEFAULT '',
        verificado INTEGER DEFAULT 0,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS galeria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        ruta TEXT NOT NULL,
        tipo TEXT NOT NULL,
        descripcion TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS partidos_mundial (
        id INTEGER PRIMARY KEY,
        grupo TEXT NOT NULL,
        local TEXT NOT NULL,
        visitante TEXT NOT NULL,
        goles_local INTEGER DEFAULT NULL,
        goles_visitante INTEGER DEFAULT NULL,
        bloqueado INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS pronosticos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        partido_id INTEGER NOT NULL,
        goles_local INTEGER NOT NULL,
        goles_visitante INTEGER NOT NULL,
        puntos INTEGER DEFAULT 0,
        UNIQUE(usuario_id, partido_id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (partido_id) REFERENCES partidos_mundial(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cajitas_ahorro (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        descripcion TEXT DEFAULT '',
        creador_id INTEGER NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (creador_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cajita_miembros (
        cajita_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        PRIMARY KEY (cajita_id, usuario_id),
        FOREIGN KEY (cajita_id) REFERENCES cajitas_ahorro(id) ON DELETE CASCADE,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cajita_movimientos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cajita_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        monto REAL NOT NULL,
        descripcion TEXT DEFAULT '',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (cajita_id) REFERENCES cajitas_ahorro(id) ON DELETE CASCADE,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS eventos_recaudacion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        nombre_evento TEXT NOT NULL,
        descripcion TEXT DEFAULT '',
        monto REAL NOT NULL,
        responsables TEXT DEFAULT '',
        soporte TEXT NOT NULL,
        estado TEXT DEFAULT 'pendiente',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS polla_pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        fase INTEGER NOT NULL,
        monto REAL NOT NULL,
        soporte TEXT NOT NULL,
        estado TEXT DEFAULT 'pagado',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(usuario_id, fase),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS polla_pronosticos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        fase INTEGER NOT NULL,
        datos TEXT NOT NULL,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(usuario_id, fase),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS config (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS bookmarks (
        usuario_id INTEGER NOT NULL,
        post_id    INTEGER NOT NULL,
        fecha      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (usuario_id, post_id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (post_id)    REFERENCES publicaciones(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS reposts (
        usuario_id INTEGER NOT NULL,
        post_id    INTEGER NOT NULL,
        fecha      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (usuario_id, post_id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (post_id)    REFERENCES publicaciones(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS amigo_secreto_eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        activo INTEGER DEFAULT 1,
        cruces_generados INTEGER DEFAULT 0,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS amigo_secreto_participantes (
        evento_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        asignado_id INTEGER DEFAULT NULL,
        PRIMARY KEY (evento_id, usuario_id),
        FOREIGN KEY (evento_id) REFERENCES amigo_secreto_eventos(id) ON DELETE CASCADE,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cajitas_ahorro_codigos (
        cajita_id INTEGER PRIMARY KEY,
        codigo TEXT UNIQUE NOT NULL,
        FOREIGN KEY (cajita_id) REFERENCES cajitas_ahorro(id) ON DELETE CASCADE
    );
    """)

    # ─── ADMIN ───
    admin_hash = generate_password_hash("admin1234")
    cur.execute("""
        INSERT OR IGNORE INTO usuarios (nombre, usuario, password, rol, gmail)
        VALUES ('Administrador','admin',?,'admin','admin@familia.com')
    """, (admin_hash,))

    # ─── CONFIG POR DEFECTO ───
    cur.execute("INSERT OR IGNORE INTO config(clave,valor) VALUES('meta_recaudacion','500000')")

    # ─── INSERTAR PARTIDOS ───
    for pid, grupo, local, visitante in PARTIDOS_MUNDIAL:
        cur.execute("""
            INSERT OR IGNORE INTO partidos_mundial (id, grupo, local, visitante)
            VALUES (?, ?, ?, ?)
        """, (pid, grupo, local, visitante))

    db.commit()
    db.close()

# ─────────────────────────────────────────────
# SEGURIDAD
# ─────────────────────────────────────────────

def hash_password(p):
    return generate_password_hash(p)

def verify_password(h, p):
    return check_password_hash(h, p)

# ─────────────────────────────────────────────
# AMIGO SECRETO — tablas adicionales
# ─────────────────────────────────────────────

def init_amigo_secreto():
    """Crear tablas para Amigo Secreto si no existen."""
    db = sqlite3.connect(DB)
    cur = db.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS amigo_secreto_eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        activo INTEGER DEFAULT 1,
        cruces_generados INTEGER DEFAULT 0,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS amigo_secreto_participantes (
        evento_id INTEGER NOT NULL,
        usuario_id INTEGER NOT NULL,
        asignado_id INTEGER DEFAULT NULL,
        PRIMARY KEY (evento_id, usuario_id),
        FOREIGN KEY (evento_id) REFERENCES amigo_secreto_eventos(id) ON DELETE CASCADE,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cajitas_ahorro_codigos (
        cajita_id INTEGER PRIMARY KEY,
        codigo TEXT UNIQUE NOT NULL,
        FOREIGN KEY (cajita_id) REFERENCES cajitas_ahorro(id) ON DELETE CASCADE
    );
    """)
    db.commit()
    db.close()
