"""
Migración v2: Amigo Navideño Mejorado
- Elimina UNIQUE constraint de lista_deseos (permite hasta 3 deseos)
- Agrega columna titulo a lista_deseos
- Crea tabla amigo_pistas (mensajes anónimos/pistas)
- Crea tabla amigo_reacciones (reacciones privadas a deseos)
- Crea tabla amigo_estado_regalo (estado del regalo)

Ejecutar: python migrate_amigo_navideno_v2.py
"""
import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("⚠️  Define DATABASE_URL en las variables de entorno.")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False
cur = conn.cursor()

try:
    # 1) Eliminar UNIQUE constraint de lista_deseos.usuario_id si existe
    cur.execute("""
        SELECT constraint_name FROM information_schema.table_constraints
        WHERE table_name='lista_deseos' AND constraint_type='UNIQUE'
    """)
    constraints = cur.fetchall()
    for (cname,) in constraints:
        cur.execute(f"ALTER TABLE lista_deseos DROP CONSTRAINT IF EXISTS {cname}")
        print(f"✅ Eliminado constraint UNIQUE: {cname}")

    # 2) Agregar columna titulo si no existe
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='lista_deseos' AND column_name='titulo'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE lista_deseos ADD COLUMN titulo TEXT DEFAULT ''")
        print("✅ Columna titulo agregada a lista_deseos.")

    # 3) Agregar columna orden si no existe
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='lista_deseos' AND column_name='orden'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE lista_deseos ADD COLUMN orden INTEGER DEFAULT 1")
        print("✅ Columna orden agregada a lista_deseos.")

    # 4) Tabla de mensajes/pistas anónimos
    cur.execute("""
        CREATE TABLE IF NOT EXISTS amigo_mensajes (
            id SERIAL PRIMARY KEY,
            evento_id INTEGER NOT NULL REFERENCES amigo_secreto_eventos(id) ON DELETE CASCADE,
            remitente_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            destinatario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            mensaje TEXT NOT NULL,
            leido BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✅ Tabla amigo_mensajes verificada / creada.")

    # 5) Tabla de reacciones privadas a deseos
    cur.execute("""
        CREATE TABLE IF NOT EXISTS amigo_reacciones (
            id SERIAL PRIMARY KEY,
            deseo_id INTEGER NOT NULL REFERENCES lista_deseos(id) ON DELETE CASCADE,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            reaccion TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(deseo_id, usuario_id)
        )
    """)
    print("✅ Tabla amigo_reacciones verificada / creada.")

    # 6) Tabla estado del regalo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS amigo_estado_regalo (
            id SERIAL PRIMARY KEY,
            evento_id INTEGER NOT NULL REFERENCES amigo_secreto_eventos(id) ON DELETE CASCADE,
            comprador_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            estado TEXT DEFAULT 'pendiente',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(evento_id, comprador_id)
        )
    """)
    print("✅ Tabla amigo_estado_regalo verificada / creada.")

    # 7) Columna sorteo_fecha en eventos
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='amigo_secreto_eventos' AND column_name='sorteo_fecha'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE amigo_secreto_eventos ADD COLUMN sorteo_fecha TIMESTAMP DEFAULT NULL")
        print("✅ Columna sorteo_fecha agregada a amigo_secreto_eventos.")

    # 8) Columna sorteo_admin_id en eventos
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='amigo_secreto_eventos' AND column_name='sorteo_admin_id'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE amigo_secreto_eventos ADD COLUMN sorteo_admin_id INTEGER DEFAULT NULL")
        print("✅ Columna sorteo_admin_id agregada.")

    conn.commit()
    print("\n🎄 Migración v2 Amigo Navideño completada exitosamente.")
except Exception as e:
    conn.rollback()
    print(f"❌ Error en migración: {e}")
    raise
finally:
    cur.close()
    conn.close()
