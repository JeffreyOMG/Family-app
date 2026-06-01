"""
Migración: añade tablas nuevas si no existen.
Ejecutar una vez: python migrate.py
"""
import sqlite3

DB = "familia.db"
db = sqlite3.connect(DB)
cur = db.cursor()

cur.executescript("""
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
""")

db.commit()
db.close()
print("✅ Migración completada.")
