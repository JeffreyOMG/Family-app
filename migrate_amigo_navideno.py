"""
Migración: Amigo Navideño
- Agrega tabla lista_deseos
- Agrega columna tarifa_premio a amigo_secreto_eventos (si no existe)

Ejecutar una vez en el servidor: python migrate_amigo_navideno.py
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
    # 1) Crear tabla lista_deseos
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lista_deseos (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER NOT NULL
                REFERENCES usuarios(id) ON DELETE CASCADE UNIQUE,
            descripcion TEXT NOT NULL,
            imagen_referencia TEXT DEFAULT NULL,
            link_referencia TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("✅ Tabla lista_deseos verificada / creada.")

    # 2) Agregar columna tarifa_premio si no existe
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='amigo_secreto_eventos' AND column_name='tarifa_premio'
    """)
    if not cur.fetchone():
        cur.execute("""
            ALTER TABLE amigo_secreto_eventos
            ADD COLUMN tarifa_premio TEXT DEFAULT 'No definido'
        """)
        print("✅ Columna tarifa_premio agregada a amigo_secreto_eventos.")
    else:
        print("ℹ️  Columna tarifa_premio ya existe.")

    conn.commit()
    print("\n🎄 Migración Amigo Navideño completada exitosamente.")
except Exception as e:
    conn.rollback()
    print(f"❌ Error en migración: {e}")
    raise
finally:
    cur.close()
    conn.close()
