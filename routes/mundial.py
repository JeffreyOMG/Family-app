from flask import Blueprint, request, redirect, session, jsonify
from database import get_db, GRUPOS_MUNDIAL
from mundial_bracket import generar_bracket

mundial_bp = Blueprint("mundial", __name__)

@mundial_bp.route("/api/mundial_datos")
def api_mundial_datos():
    if "uid" not in session:
        return jsonify({}), 401

    uid = session["uid"]
    con = get_db()

    partidos_raw = [dict(p) for p in con.execute("""
        SELECT pm.id, pm.grupo, pm.local, pm.visitante,
               pm.goles_local, pm.goles_visitante, pm.bloqueado,
               pr.goles_local AS p_local, pr.goles_visitante AS p_vis
        FROM partidos_mundial pm
        LEFT JOIN pronosticos pr ON pr.partido_id=pm.id AND pr.usuario_id=%s
        ORDER BY pm.grupo, pm.id
    """, (uid,)).fetchall()]

    def _split(s):
        if "|" in s:
            n, c = s.split("|", 1)
            return n.strip(), c.strip()
        return s.strip(), "xx"

    partidos = []
    for p in partidos_raw:
        ln, lc = _split(p["local"])
        vn, vc = _split(p["visitante"])
        partidos.append({
            "id": p["id"], "grupo": p["grupo"],
            "local": ln, "visitante": vn,
            "codigo_local": lc, "codigo_visitante": vc,
            "goles_local": p["goles_local"], "goles_visitante": p["goles_visitante"],
            "bloqueado": bool(p["bloqueado"]),
            "p_local": p["p_local"], "p_vis": p["p_vis"],
        })

    tabla = {}
    for letra, equipos in GRUPOS_MUNDIAL.items():
        tabla[letra] = {}
        for nombre, codigo in equipos:
            tabla[letra][nombre] = {"codigo": codigo, "pts": 0, "pj": 0, "g": 0, "emp": 0, "p": 0, "gf": 0, "gc": 0, "dg": 0}

    for p in partidos:
        if not p["bloqueado"] or p["goles_local"] is None:
            continue
        letra = p["grupo"]
        gl, gv = p["goles_local"], p["goles_visitante"]
        loc, vis = p["local"], p["visitante"]
        if letra not in tabla:
            continue
        for equipo, es_local in [(loc, True), (vis, False)]:
            if equipo not in tabla[letra]:
                continue
            t = tabla[letra][equipo]
            t["pj"] += 1
            gf = gl if es_local else gv
            gc = gv if es_local else gl
            t["gf"] += gf; t["gc"] += gc; t["dg"] = t["gf"] - t["gc"]
            if gl == gv:
                t["pts"] += 1; t["emp"] += 1
            elif (gl > gv) == es_local:
                t["pts"] += 3; t["g"] += 1
            else:
                t["p"] += 1

    tabla_ordenada = {}
    for letra, equipos in tabla.items():
        rows = [{"nombre": n, **v} for n, v in equipos.items()]
        rows.sort(key=lambda x: (-x["pts"], -x["dg"], -x["gf"]))
        tabla_ordenada[letra] = rows

    # ── RANKING: grupos + eliminación directa ────────────────────────────────
    ranking = [dict(r) for r in con.execute("""
        SELECT u.id, u.nombre,
               COALESCE(g.puntos,0)+COALESCE(e.puntos,0) AS puntos,
               COALESCE(g.penales,0)+COALESCE(e.penales,0) AS penales,
               COALESCE(g.exactos,0)+COALESCE(e.exactos,0) AS exactos,
               COALESCE(g.ganadores,0)+COALESCE(e.ganadores,0) AS ganadores
        FROM usuarios u
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores,
                   0 penales
            FROM pronosticos GROUP BY usuario_id
        ) g ON g.usuario_id=u.id
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos IN (3,4) THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores,
                   COUNT(CASE WHEN puntos=4 THEN 1 END) penales
            FROM pronosticos_eli GROUP BY usuario_id
        ) e ON e.usuario_id=u.id
        ORDER BY puntos DESC, penales DESC, exactos DESC, ganadores DESC
    """).fetchall()]

    try:
        _ensure_eliminacion_table(con)
        _auto_asignar_fijos(con)
        _auto_propagar_ganadores(con)
    except Exception:
        pass
    bracket = generar_bracket(tabla_ordenada)

    return jsonify({"partidos": partidos, "tabla": tabla_ordenada, "ranking": ranking, "bracket": bracket})


def _back():
    sec = request.args.get("s") or request.form.get("_sec") or "mundial"
    return redirect(f"/dashboard?s={sec}")

def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@mundial_bp.route("/pronostico", methods=["POST"])
def pronostico():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")

    uid = session["uid"]
    con = get_db()

    for key, val in request.form.items():
        if key.startswith("local_"):
            partido_id = int(key.split("_")[1])
            gl = request.form.get(f"local_{partido_id}", "")
            gv = request.form.get(f"vis_{partido_id}", "")
            if gl.isdigit() and gv.isdigit():
                partido = con.execute(
                    "SELECT bloqueado FROM partidos_mundial WHERE id=%s", (partido_id,)
                ).fetchone()
                if partido and not partido["bloqueado"]:
                    con.execute("""
                        INSERT INTO pronosticos(usuario_id, partido_id, goles_local, goles_visitante)
                        VALUES(%s, %s, %s, %s)
                        ON CONFLICT(usuario_id, partido_id) DO UPDATE SET
                            goles_local=excluded.goles_local,
                            goles_visitante=excluded.goles_visitante
                    """, (uid, partido_id, int(gl), int(gv)))

    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Pronósticos guardados"})
    return _back()


@mundial_bp.route("/admin_resultado", methods=["POST"])
def admin_resultado():
    if session.get("rol") != "admin":
        return (jsonify({"ok": False, "error": "no_admin"}), 403) if _is_ajax() else redirect("/dashboard?s=mundial")

    partido_id = int(request.form.get("partido_id", 0))
    gl = request.form.get("goles_local", "")
    gv = request.form.get("goles_visitante", "")
    if not gl.isdigit() or not gv.isdigit():
        return _back()
    gl, gv = int(gl), int(gv)
    con = get_db()

    con.execute("""
        UPDATE partidos_mundial
        SET goles_local=%s, goles_visitante=%s, bloqueado=1
        WHERE id=%s
    """, (gl, gv, partido_id))

    pronos = con.execute("""
        SELECT id, goles_local, goles_visitante FROM pronosticos WHERE partido_id=%s
    """, (partido_id,)).fetchall()

    for p in pronos:
        puntos = 0
        if p["goles_local"] == gl and p["goles_visitante"] == gv:
            puntos = 3
        elif (
            (p["goles_local"] > p["goles_visitante"] and gl > gv) or
            (p["goles_local"] < p["goles_visitante"] and gl < gv) or
            (p["goles_local"] == p["goles_visitante"] and gl == gv)
        ):
            puntos = 1
        con.execute("UPDATE pronosticos SET puntos=%s WHERE id=%s", (puntos, p["id"]))

    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Resultado guardado"})
    return _back()


@mundial_bp.route("/admin_desbloquear", methods=["POST"])
def admin_desbloquear():
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard?s=mundial")

    partido_id = int(request.form.get("partido_id", 0))
    con = get_db()
    con.execute("""
        UPDATE partidos_mundial SET goles_local=NULL, goles_visitante=NULL, bloqueado=0 WHERE id=%s
    """, (partido_id,))
    con.execute("UPDATE pronosticos SET puntos=0 WHERE partido_id=%s", (partido_id,))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Partido desbloqueado"})
    return _back()


@mundial_bp.route("/admin_reset_mundial", methods=["POST"])
def admin_reset_mundial():
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard?s=mundial")

    con = get_db()
    con.execute("UPDATE partidos_mundial SET goles_local=NULL, goles_visitante=NULL, bloqueado=0")
    con.execute("UPDATE pronosticos SET puntos=0")
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Mundial reiniciado"})
    return _back()


@mundial_bp.route("/api/ranking_mundial")
def ranking_mundial():
    """Ranking visible en frontend: suma grupos + eliminación directa."""
    if "uid" not in session:
        return jsonify([]), 401
    con = get_db()
    try:
        _ensure_eliminacion_table(con)
    except Exception:
        pass
    ranking = [dict(r) for r in con.execute("""
        SELECT u.id, u.nombre, u.usuario, u.foto,
               COALESCE(g.puntos,0)+COALESCE(e.puntos,0) AS puntos,
               COALESCE(g.penales,0)+COALESCE(e.penales,0) AS penales,
               COALESCE(g.exactos,0)+COALESCE(e.exactos,0) AS exactos,
               COALESCE(g.ganadores,0)+COALESCE(e.ganadores,0) AS ganadores
        FROM usuarios u
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores,
                   0 penales
            FROM pronosticos GROUP BY usuario_id
        ) g ON g.usuario_id=u.id
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos IN (3,4) THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores,
                   COUNT(CASE WHEN puntos=4 THEN 1 END) penales
            FROM pronosticos_eli GROUP BY usuario_id
        ) e ON e.usuario_id=u.id
        GROUP BY u.id, u.nombre, u.usuario, u.foto, g.puntos, g.exactos, g.ganadores, g.penales, e.puntos, e.exactos, e.ganadores, e.penales
        ORDER BY puntos DESC, penales DESC, exactos DESC, ganadores DESC
    """).fetchall()]
    return jsonify(ranking)


@mundial_bp.route("/api/mundial_info")
def mundial_info():
    con = get_db()
    partidos = con.execute("SELECT COUNT(*) total FROM partidos_mundial").fetchone()["total"]
    jugados  = con.execute("SELECT COUNT(*) total FROM partidos_mundial WHERE bloqueado=1").fetchone()["total"]
    usuarios = con.execute("SELECT COUNT(*) total FROM usuarios").fetchone()["total"]
    pronos   = con.execute("SELECT COUNT(*) total FROM pronosticos").fetchone()["total"]
    return jsonify({"partidos": partidos, "jugados": jugados, "pendientes": partidos - jugados, "usuarios": usuarios, "pronosticos": pronos})


# ── FASE ELIMINATORIA ────────────────────────────────────

def _ensure_eliminacion_table(con):
    con.cursor().execute("""
        CREATE TABLE IF NOT EXISTS partidos_eliminacion (
            id               INTEGER PRIMARY KEY,
            fase             TEXT NOT NULL,
            slot_local       TEXT NOT NULL,
            slot_visit       TEXT NOT NULL,
            fecha            TEXT DEFAULT '',
            sede             TEXT DEFAULT '',
            eq_local         TEXT DEFAULT NULL,
            cod_local        TEXT DEFAULT NULL,
            eq_visit         TEXT DEFAULT NULL,
            cod_visit        TEXT DEFAULT NULL,
            goles_local      INTEGER DEFAULT NULL,
            goles_visit      INTEGER DEFAULT NULL,
            penales_ganador  TEXT DEFAULT NULL,
            bloqueado        INTEGER DEFAULT 0
        )
    """)
    con.commit()

    # Migración segura: usar SAVEPOINT para que un fallo no aborte la transacción
    def _add_column_safe(table, column, definition):
        try:
            con.execute(f"SAVEPOINT add_col_{column}")
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            con.execute(f"RELEASE SAVEPOINT add_col_{column}")
            con.commit()
        except Exception:
            con.execute(f"ROLLBACK TO SAVEPOINT add_col_{column}")

    _add_column_safe("partidos_eliminacion", "penales_ganador", "TEXT DEFAULT NULL")

    con.execute("""
        CREATE TABLE IF NOT EXISTS pronosticos_eli (
            id              SERIAL PRIMARY KEY,
            usuario_id      INTEGER NOT NULL,
            partido_id      INTEGER NOT NULL,
            goles_local     INTEGER NOT NULL,
            goles_visit     INTEGER NOT NULL,
            penales_ganador TEXT DEFAULT NULL,
            puntos          INTEGER DEFAULT 0,
            UNIQUE(usuario_id, partido_id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
            FOREIGN KEY (partido_id) REFERENCES partidos_eliminacion(id) ON DELETE CASCADE
        )
    """)
    con.commit()

    _add_column_safe("pronosticos_eli", "penales_ganador", "TEXT DEFAULT NULL")
    # ── TABLA: mejores_terceros ─────────────────────────────────────────────
    # Guarda los 8 terceros asignados a los cruces de dieciseisavos
    # manual_override = TRUE significa que el admin lo editó manualmente
    # y el sistema automático NO debe sobreescribirlo
    con.execute("""
        CREATE TABLE IF NOT EXISTS mejores_terceros (
            partido_id      INTEGER PRIMARY KEY,
            nombre          TEXT NOT NULL,
            codigo          TEXT NOT NULL DEFAULT 'xx',
            grupo_origen    TEXT NOT NULL DEFAULT '',
            manual_override BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (partido_id) REFERENCES partidos_eliminacion(id) ON DELETE CASCADE
        )
    """)
    con.commit()
    _seed_eliminacion(con)

def _seed_eliminacion(con):
    from mundial_bracket import DIECISEISAVOS, OCTAVOS, CUARTOS, SEMIFINALES, TERCER_PUESTO, FINAL
    filas = []
    for p in DIECISEISAVOS:
        filas.append((p["id"], "Dieciseisavos", p["slot_l"], p["slot_v"], p["fecha"], p["sede"]))
    for p in OCTAVOS:
        filas.append((p["id"], "Octavos", f"G{p['dep1']}", f"G{p['dep2']}", p["fecha"], p["sede"]))
    for p in CUARTOS:
        filas.append((p["id"], "Cuartos", f"G{p['dep1']}", f"G{p['dep2']}", p["fecha"], p["sede"]))
    for p in SEMIFINALES:
        filas.append((p["id"], "Semifinales", f"G{p['dep1']}", f"G{p['dep2']}", p["fecha"], p["sede"]))
    filas.append((TERCER_PUESTO["id"], "Tercer puesto", f"P{TERCER_PUESTO['dep1']}", f"P{TERCER_PUESTO['dep2']}", TERCER_PUESTO["fecha"], TERCER_PUESTO["sede"]))
    filas.append((FINAL["id"], "Final", f"G{FINAL['dep1']}", f"G{FINAL['dep2']}", FINAL["fecha"], FINAL["sede"]))
    for fila in filas:
        con.execute("""
            INSERT INTO partidos_eliminacion(id, fase, slot_local, slot_visit, fecha, sede)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, fila)
    con.commit()


@mundial_bp.route("/api/eliminacion_datos")
def api_eliminacion_datos():
    if "uid" not in session:
        return jsonify({}), 401
    uid = session["uid"]
    con = get_db()
    _ensure_eliminacion_table(con)
    _auto_asignar_fijos(con)
    _auto_propagar_ganadores(con)
    # Aplicar terceros guardados en mejores_terceros (solo si no manual_override ya aplicado)
    _aplicar_mejores_terceros(con)

    partidos = [dict(p) for p in con.execute("""
        SELECT pe.*,
               pr.goles_local AS p_local, pr.goles_visit AS p_vis,
               pr.penales_ganador AS p_penales
        FROM partidos_eliminacion pe
        LEFT JOIN pronosticos_eli pr ON pr.partido_id=pe.id AND pr.usuario_id=%s
        ORDER BY pe.id
    """, (uid,)).fetchall()]

    terceros_por_grupo = _get_terceros_por_grupo(con)
    mejores_terceros   = _get_mejores_terceros_guardados(con)
    terceros_auto      = _calcular_mejores_terceros_auto(con)

    return jsonify({
        "partidos": partidos,
        "terceros_por_grupo": terceros_por_grupo,
        "mejores_terceros": mejores_terceros,
        "terceros_auto": terceros_auto,
    })


def _calcular_tabla_grupos(con):
    partidos_raw = [dict(p) for p in con.execute("""
        SELECT grupo, local, visitante, goles_local, goles_visitante
        FROM partidos_mundial WHERE bloqueado=1 AND goles_local IS NOT NULL
    """).fetchall()]

    tabla = {}
    for letra, equipos in GRUPOS_MUNDIAL.items():
        tabla[letra] = {}
        for nombre, codigo in equipos:
            tabla[letra][nombre] = {"codigo": codigo, "pts": 0, "dg": 0, "gf": 0, "gc": 0, "pj": 0}

    for p in partidos_raw:
        letra = p["grupo"]
        if letra not in tabla: continue
        gl, gv = p["goles_local"], p["goles_visitante"]
        def _nombre(s): return s.split("|")[0].strip() if "|" in s else s.strip()
        loc, vis = _nombre(p["local"]), _nombre(p["visitante"])
        for equipo, es_local in [(loc, True), (vis, False)]:
            if equipo not in tabla.get(letra, {}): continue
            t = tabla[letra][equipo]
            t["pj"] += 1
            gf = gl if es_local else gv
            gc = gv if es_local else gl
            t["gf"] += gf; t["gc"] += gc; t["dg"] = t["gf"] - t["gc"]
            if gl == gv:   t["pts"] += 1
            elif (gl > gv) == es_local: t["pts"] += 3

    ordenada = {}
    for letra, equipos in tabla.items():
        rows = sorted(equipos.items(), key=lambda x: (-x[1]["pts"], -x[1]["dg"], -x[1]["gf"]))
        ordenada[letra] = rows
    return ordenada


def _auto_asignar_fijos(con):
    from mundial_bracket import DIECISEISAVOS
    tabla = _calcular_tabla_grupos(con)

    def _resolver_slot(slot):
        if len(slot) == 2 and slot[0] in "12" and slot[1].isalpha():
            pos   = int(slot[0]) - 1
            letra = slot[1].upper()
            rows  = tabla.get(letra, [])
            if pos < len(rows):
                return rows[pos][0], rows[pos][1]["codigo"]
        return None, None

    for p_data in DIECISEISAVOS:
        if not p_data["fijo"]:
            continue
        row = con.execute(
            "SELECT bloqueado FROM partidos_eliminacion WHERE id=%s", (p_data["id"],)
        ).fetchone()
        if not row or row["bloqueado"]:
            continue
        nombre_l, codigo_l = _resolver_slot(p_data["slot_l"])
        nombre_v, codigo_v = _resolver_slot(p_data["slot_v"])
        con.execute("""
            UPDATE partidos_eliminacion
            SET eq_local=%s, cod_local=%s, eq_visit=%s, cod_visit=%s
            WHERE id=%s
        """, (nombre_l, codigo_l, nombre_v, codigo_v, p_data["id"]))
    con.commit()


def _auto_propagar_ganadores(con):
    """
    Propaga ganadores (y perdedores para tercer puesto) a lo largo del bracket.
    En eliminatorias, si hay empate en tiempo reglamentario el admin debería
    registrar el resultado final (incluyendo penales). Por eso si goles_local==goles_visit
    NO propagamos — el admin debe editar para reflejar el resultado real (penales).
    """
    partidos = [dict(p) for p in con.execute("""
        SELECT * FROM partidos_eliminacion ORDER BY id
    """).fetchall()]

    resultados = {}
    for p in partidos:
        if not p.get("bloqueado") or p.get("goles_local") is None or p.get("goles_visit") is None:
            continue
        if not p.get("eq_local") or not p.get("eq_visit"):
            continue

        gl = p["goles_local"]
        gv = p["goles_visit"]

        if gl > gv:
            ganador  = (p["eq_local"],  p["cod_local"])
            perdedor = (p["eq_visit"],  p["cod_visit"])
        elif gv > gl:
            ganador  = (p["eq_visit"],  p["cod_visit"])
            perdedor = (p["eq_local"],  p["cod_local"])
        elif p.get("penales_ganador"):
            # Empate con penales definidos
            pen_gan = p["penales_ganador"]
            if pen_gan == p["eq_local"]:
                ganador  = (p["eq_local"],  p["cod_local"])
                perdedor = (p["eq_visit"],  p["cod_visit"])
            elif pen_gan == p["eq_visit"]:
                ganador  = (p["eq_visit"],  p["cod_visit"])
                perdedor = (p["eq_local"],  p["cod_local"])
            else:
                ganador  = None
                perdedor = None
        else:
            # Empate sin penales definidos — no podemos propagar
            ganador  = None
            perdedor = None

        resultados[p["id"]] = {"ganador": ganador, "perdedor": perdedor}

    for p in partidos:
        updates = {}

        for campo_slot, campo_eq, campo_cod in [
            ("slot_local", "eq_local", "cod_local"),
            ("slot_visit", "eq_visit", "cod_visit")
        ]:
            slot = p.get(campo_slot) or ""

            if slot[:1] not in ("G", "P"):
                continue

            try:
                origen = int(slot[1:])
            except Exception:
                continue

            if origen not in resultados:
                continue

            tipo = "ganador" if slot.startswith("G") else "perdedor"
            dato = resultados[origen][tipo]

            if dato is None:
                # Empate sin penales definidos — no propagar ni borrar,
                # el admin aún debe ingresar quién ganó en penales
                continue
            else:
                updates[campo_eq]  = dato[0]
                updates[campo_cod] = dato[1]

        if updates:
            sets = ", ".join(f"{k}=%s" for k in updates)
            vals = list(updates.values()) + [p["id"]]
            con.execute(f"UPDATE partidos_eliminacion SET {sets} WHERE id=%s", vals)

    con.commit()


def _get_terceros_por_grupo(con):
    """Retorna el mejor 3ro de cada grupo (posición 3 en la tabla)."""
    tabla = _calcular_tabla_grupos(con)
    resultado = {}
    for letra, rows in tabla.items():
        if len(rows) >= 3:
            nombre = rows[2][0]
            codigo = rows[2][1]["codigo"]
            pts    = rows[2][1]["pts"]
            dg     = rows[2][1]["dg"]
            gf     = rows[2][1]["gf"]
            resultado[letra] = {"nombre": nombre, "codigo": codigo, "pts": pts, "dg": dg, "gf": gf}
    return resultado


def _calcular_mejores_terceros_auto(con):
    """
    Calcula automáticamente los 8 mejores terceros usando criterios oficiales FIFA:
    1. Puntos  2. Diferencia de gol  3. Goles a favor
    Retorna lista ordenada de hasta 12 candidatos (todos los terceros disponibles).
    """
    por_grupo = _get_terceros_por_grupo(con)
    candidatos = []
    for letra, datos in por_grupo.items():
        candidatos.append({
            "grupo": letra,
            "nombre": datos["nombre"],
            "codigo": datos["codigo"],
            "pts": datos["pts"],
            "dg": datos["dg"],
            "gf": datos["gf"],
        })
    candidatos.sort(key=lambda x: (-x["pts"], -x["dg"], -x["gf"]))
    return candidatos  # Primeros 8 son los mejores


def _get_mejores_terceros_guardados(con):
    """Retorna los terceros guardados en la tabla mejores_terceros."""
    try:
        rows = con.execute("""
            SELECT partido_id, nombre, codigo, grupo_origen, manual_override
            FROM mejores_terceros
        """).fetchall()
        return {r["partido_id"]: dict(r) for r in rows}
    except Exception:
        return {}


def _aplicar_mejores_terceros(con):
    """
    Aplica los terceros guardados en mejores_terceros a partidos_eliminacion.
    Solo actualiza partidos que NO están bloqueados.
    """
    from mundial_bracket import CRUCES_CON_TERCERO
    try:
        rows = con.execute("""
            SELECT partido_id, nombre, codigo FROM mejores_terceros
        """).fetchall()
        for r in rows:
            pid = r["partido_id"]
            partido = con.execute(
                "SELECT bloqueado FROM partidos_eliminacion WHERE id=%s", (pid,)
            ).fetchone()
            if partido and not partido["bloqueado"]:
                con.execute("""
                    UPDATE partidos_eliminacion
                    SET eq_visit=%s, cod_visit=%s
                    WHERE id=%s
                """, (r["nombre"], r["codigo"], pid))
        con.commit()
    except Exception:
        pass


# ── API: obtener y guardar mejores terceros ───────────────────────────────────

@mundial_bp.route("/api/mejores_terceros")
def api_mejores_terceros():
    if "uid" not in session:
        return jsonify({}), 401
    con = get_db()
    _ensure_eliminacion_table(con)
    guardados = _get_mejores_terceros_guardados(con)
    auto      = _calcular_mejores_terceros_auto(con)
    return jsonify({"guardados": guardados, "auto": auto})


@mundial_bp.route("/admin_guardar_terceros", methods=["POST"])
def admin_guardar_terceros():
    """
    Guarda la asignación manual de terceros.
    Body JSON o form: lista de {partido_id, nombre, codigo, grupo_origen}
    Marca manual_override=True para los partidos modificados.
    """
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    con = get_db()
    _ensure_eliminacion_table(con)

    import json
    try:
        data = request.get_json(silent=True) or {}
        terceros = data.get("terceros", [])
    except Exception:
        terceros = []

    if not terceros:
        # Fallback: form data (lista de campos)
        for pid in request.form.getlist("partido_id"):
            nombre  = request.form.get(f"nombre_{pid}", "").strip()
            codigo  = request.form.get(f"codigo_{pid}", "xx").strip()
            grupo   = request.form.get(f"grupo_{pid}", "").strip()
            if nombre:
                terceros.append({"partido_id": int(pid), "nombre": nombre, "codigo": codigo, "grupo_origen": grupo})

    for t in terceros:
        pid    = int(t.get("partido_id", 0))
        nombre = t.get("nombre", "").strip()
        codigo = t.get("codigo", "xx").strip()
        grupo  = t.get("grupo_origen", "").strip()
        if not pid or not nombre:
            continue
        # Buscar código si no viene
        if not codigo or codigo == "xx":
            for equipos in GRUPOS_MUNDIAL.values():
                for n, c in equipos:
                    if n == nombre:
                        codigo = c
                        break
        con.execute("""
            INSERT INTO mejores_terceros(partido_id, nombre, codigo, grupo_origen, manual_override)
            VALUES(%s, %s, %s, %s, TRUE)
            ON CONFLICT(partido_id) DO UPDATE SET
                nombre=excluded.nombre,
                codigo=excluded.codigo,
                grupo_origen=excluded.grupo_origen,
                manual_override=TRUE
        """, (pid, nombre, codigo, grupo))
        # Actualizar partido_eliminacion también
        partido = con.execute("SELECT bloqueado FROM partidos_eliminacion WHERE id=%s", (pid,)).fetchone()
        if partido and not partido["bloqueado"]:
            con.execute("""
                UPDATE partidos_eliminacion SET eq_visit=%s, cod_visit=%s WHERE id=%s
            """, (nombre, codigo, pid))

    con.commit()
    return jsonify({"ok": True, "msg": f"{len(terceros)} terceros guardados"})


@mundial_bp.route("/admin_recalcular_terceros", methods=["POST"])
def admin_recalcular_terceros():
    """
    Recalcula automáticamente los 8 mejores terceros y los asigna a los
    8 cruces con tercero, RESPETANDO los manual_override ya existentes.
    """
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    con = get_db()
    _ensure_eliminacion_table(con)

    from mundial_bracket import CRUCES_CON_TERCERO, DIECISEISAVOS

    auto = _calcular_mejores_terceros_auto(con)
    top8 = auto[:8]

    if len(top8) < 8:
        return jsonify({"ok": False, "msg": f"Solo hay {len(top8)} terceros calculables. Necesitas más partidos de grupos jugados."})

    # Obtener los cruces con tercero en orden (IDs de DIECISEISAVOS fijo=False)
    cruces_tercero = [p["id"] for p in DIECISEISAVOS if not p["fijo"]]  # 8 cruces

    # Obtener overrides existentes
    overrides = set()
    try:
        rows = con.execute("SELECT partido_id FROM mejores_terceros WHERE manual_override=TRUE").fetchall()
        overrides = {r["partido_id"] for r in rows}
    except Exception:
        pass

    asignados = 0
    for i, pid in enumerate(cruces_tercero):
        if pid in overrides:
            continue  # Respetar manual_override
        if i >= len(top8):
            break
        t = top8[i]
        con.execute("""
            INSERT INTO mejores_terceros(partido_id, nombre, codigo, grupo_origen, manual_override)
            VALUES(%s, %s, %s, %s, FALSE)
            ON CONFLICT(partido_id) DO UPDATE SET
                nombre=excluded.nombre,
                codigo=excluded.codigo,
                grupo_origen=excluded.grupo_origen,
                manual_override=FALSE
        """, (pid, t["nombre"], t["codigo"], t["grupo"]))
        partido = con.execute("SELECT bloqueado FROM partidos_eliminacion WHERE id=%s", (pid,)).fetchone()
        if partido and not partido["bloqueado"]:
            con.execute("""
                UPDATE partidos_eliminacion SET eq_visit=%s, cod_visit=%s WHERE id=%s
            """, (t["nombre"], t["codigo"], pid))
        asignados += 1

    con.commit()
    return jsonify({"ok": True, "msg": f"Recalculado: {asignados} terceros asignados automáticamente (overrides respetados: {len(overrides)})", "auto": top8})


@mundial_bp.route("/admin_restablecer_terceros", methods=["POST"])
def admin_restablecer_terceros():
    """
    Elimina TODOS los manual_override y recalcula desde cero.
    """
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    con = get_db()
    _ensure_eliminacion_table(con)

    # Limpiar todos los terceros guardados
    try:
        con.execute("DELETE FROM mejores_terceros")
        con.commit()
    except Exception:
        pass

    from mundial_bracket import DIECISEISAVOS
    auto  = _calcular_mejores_terceros_auto(con)
    top8  = auto[:8]
    cruces_tercero = [p["id"] for p in DIECISEISAVOS if not p["fijo"]]

    asignados = 0
    for i, pid in enumerate(cruces_tercero):
        if i >= len(top8):
            break
        t = top8[i]
        con.execute("""
            INSERT INTO mejores_terceros(partido_id, nombre, codigo, grupo_origen, manual_override)
            VALUES(%s, %s, %s, %s, FALSE)
            ON CONFLICT(partido_id) DO UPDATE SET
                nombre=excluded.nombre,
                codigo=excluded.codigo,
                grupo_origen=excluded.grupo_origen,
                manual_override=FALSE
        """, (pid, t["nombre"], t["codigo"], t["grupo"]))
        partido = con.execute("SELECT bloqueado FROM partidos_eliminacion WHERE id=%s", (pid,)).fetchone()
        if partido and not partido["bloqueado"]:
            con.execute("""
                UPDATE partidos_eliminacion SET eq_visit=%s, cod_visit=%s WHERE id=%s
            """, (t["nombre"], t["codigo"], pid))
        asignados += 1

    con.commit()
    return jsonify({"ok": True, "msg": f"Restablecido automáticamente: {asignados} terceros asignados", "auto": top8})


@mundial_bp.route("/pronostico_eli", methods=["POST"])
def pronostico_eli():
    if "uid" not in session:
        return (jsonify({"ok": False}), 401) if _is_ajax() else redirect("/")
    uid = session["uid"]
    con = get_db()
    _ensure_eliminacion_table(con)

    for key in request.form:
        if key.startswith("local_"):
            pid = int(key.split("_")[1])
            gl  = request.form.get(f"local_{pid}", "")
            gv  = request.form.get(f"vis_{pid}", "")
            pen = request.form.get(f"pen_{pid}", "").strip() or None
            if gl.isdigit() and gv.isdigit():
                p = con.execute(
                    "SELECT bloqueado, eq_local, eq_visit FROM partidos_eliminacion WHERE id=%s", (pid,)
                ).fetchone()
                if p and not p["bloqueado"] and p["eq_local"] and p["eq_visit"]:
                    # Solo guardar penales si hay empate
                    if int(gl) != int(gv):
                        pen = None
                    con.execute("""
                        INSERT INTO pronosticos_eli(usuario_id, partido_id, goles_local, goles_visit, penales_ganador)
                        VALUES(%s, %s, %s, %s, %s)
                        ON CONFLICT(usuario_id, partido_id) DO UPDATE SET
                            goles_local=excluded.goles_local,
                            goles_visit=excluded.goles_visit,
                            penales_ganador=excluded.penales_ganador
                    """, (uid, pid, int(gl), int(gv), pen))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Pronósticos guardados"})
    return _back()


@mundial_bp.route("/admin_eli_equipo", methods=["POST"])
def admin_eli_equipo():
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    con    = get_db()
    _ensure_eliminacion_table(con)
    pid    = int(request.form.get("partido_id", 0))
    lado   = request.form.get("lado", "")
    nombre = request.form.get("nombre", "").strip()

    codigo = "xx"
    for equipos in GRUPOS_MUNDIAL.values():
        for n, c in equipos:
            if n == nombre:
                codigo = c
                break

    if lado == "local":
        con.execute("UPDATE partidos_eliminacion SET eq_local=%s, cod_local=%s WHERE id=%s", (nombre, codigo, pid))
    elif lado == "visit":
        con.execute("UPDATE partidos_eliminacion SET eq_visit=%s, cod_visit=%s WHERE id=%s", (nombre, codigo, pid))
        # Si este partido es un cruce con tercero, guardar como manual_override
        from mundial_bracket import CRUCES_CON_TERCERO
        if pid in CRUCES_CON_TERCERO:
            grupo_origen = ""
            for letra, equipos in GRUPOS_MUNDIAL.items():
                for n, c in equipos:
                    if n == nombre:
                        grupo_origen = letra
                        break
            con.execute("""
                INSERT INTO mejores_terceros(partido_id, nombre, codigo, grupo_origen, manual_override)
                VALUES(%s, %s, %s, %s, TRUE)
                ON CONFLICT(partido_id) DO UPDATE SET
                    nombre=excluded.nombre,
                    codigo=excluded.codigo,
                    grupo_origen=excluded.grupo_origen,
                    manual_override=TRUE
            """, (pid, nombre, codigo, grupo_origen))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "codigo": codigo})
    return _back()


@mundial_bp.route("/admin_resultado_eli", methods=["POST"])
def admin_resultado_eli():
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    pid = int(request.form.get("partido_id", 0))
    gl  = request.form.get("goles_local", "")
    gv  = request.form.get("goles_visitante", "")
    pen = request.form.get("penales_ganador", "").strip() or None
    if not gl.isdigit() or not gv.isdigit():
        return _back()
    gl, gv = int(gl), int(gv)
    es_empate_real = (gl == gv)
    # Penales solo aplican en empate de eliminatorias
    if not es_empate_real:
        pen = None

    con = get_db()
    _ensure_eliminacion_table(con)

    # Obtener info del partido ANTES de actualizar
    partido_info = con.execute(
        "SELECT eq_local, eq_visit, cod_local, cod_visit FROM partidos_eliminacion WHERE id=%s", (pid,)
    ).fetchone()

    con.execute("""
        UPDATE partidos_eliminacion SET goles_local=%s, goles_visit=%s, penales_ganador=%s, bloqueado=1 WHERE id=%s
    """, (gl, gv, pen, pid))

    # Calcular puntos para cada pronóstico
    pronos = con.execute("""
        SELECT id, goles_local, goles_visit, penales_ganador FROM pronosticos_eli WHERE partido_id=%s
    """, (pid,)).fetchall()

    for p in pronos:
        es_empate_pred = (p["goles_local"] == p["goles_visit"])
        marcador_exacto = (p["goles_local"] == gl and p["goles_visit"] == gv)
        acerto_resultado = (
            (p["goles_local"] > p["goles_visit"] and gl > gv) or
            (p["goles_local"] < p["goles_visit"] and gl < gv) or
            (es_empate_pred and es_empate_real)
        )

        acerto_penales = (es_empate_real and pen and p["penales_ganador"] and p["penales_ganador"] == pen)

        if marcador_exacto:
            if es_empate_real and pen:
                # Marcador exacto en empate con penales definidos
                # +3 base por exacto, +1 extra si también acertó ganador de penales = 4
                pts = 4 if acerto_penales else 3
            else:
                pts = 3
        elif acerto_resultado:
            if es_empate_real and pen:
                # Acertó empate (no exacto) con penales definidos = 1 base
                # No hay bonus extra por penales si no acertó el marcador exacto
                pts = 1
            else:
                pts = 1
        else:
            pts = 0
        con.execute("UPDATE pronosticos_eli SET puntos=%s WHERE id=%s", (pts, p["id"]))

    con.commit()

    # Siempre propagar ganadores/perdedores al bracket después de guardar resultado
    _auto_propagar_ganadores(con)

    if _is_ajax():
        return jsonify({"ok": True, "msg": "Resultado guardado"})
    return _back()


@mundial_bp.route("/api/ranking_global")
def ranking_global():
    if "uid" not in session:
        return jsonify([]), 401
    con = get_db()
    _ensure_eliminacion_table(con)
    ranking = [dict(r) for r in con.execute("""
        SELECT u.id, u.nombre,
               COALESCE(g.puntos,0)+COALESCE(e.puntos,0) AS puntos,
               COALESCE(g.penales,0)+COALESCE(e.penales,0) AS penales,
               COALESCE(g.exactos,0)+COALESCE(e.exactos,0) AS exactos,
               COALESCE(g.ganadores,0)+COALESCE(e.ganadores,0) AS ganadores
        FROM usuarios u
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores,
                   0 penales
            FROM pronosticos GROUP BY usuario_id
        ) g ON g.usuario_id=u.id
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos IN (3,4) THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores,
                   COUNT(CASE WHEN puntos=4 THEN 1 END) penales
            FROM pronosticos_eli GROUP BY usuario_id
        ) e ON e.usuario_id=u.id
        ORDER BY puntos DESC, penales DESC, exactos DESC, ganadores DESC
    """).fetchall()]
    return jsonify(ranking)


# ══════════════════════════════════════════
# GATE DEL MUNDIAL — verificación por admin
# ══════════════════════════════════════════

@mundial_bp.route("/api/mundial_gate", methods=["POST"])
def mundial_gate():
    """El invitado envía su código de pago para que el admin lo revise.
    Guarda la solicitud como pendiente en la BD.
    """
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401

    uid = session["uid"]
    con = get_db()
    usuario = con.execute("SELECT mundial_pagado FROM usuarios WHERE id=%s", (uid,)).fetchone()
    if usuario and usuario["mundial_pagado"] == "aprobado":
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    codigo_ingresado = str(data.get("code", "")).strip()

    if not codigo_ingresado:
        return jsonify({"ok": False, "error": "Ingresa un código de pago"})

    # Guardar código y marcar como pendiente para revisión del admin
    con.execute(
        "UPDATE usuarios SET mundial_pagado=%s WHERE id=%s",
        (f"pendiente:{codigo_ingresado}", uid)
    )
    con.commit()

    return jsonify({"ok": False, "pending": True,
                    "error": "✅ Código enviado. El administrador verificará tu pago pronto."})


@mundial_bp.route("/api/mundial_gate_status")
def mundial_gate_status():
    """Devuelve el estado real del acceso desde la BD (no sesión)."""
    if "uid" not in session:
        return jsonify({"ok": False}), 401

    # Admin y miembros siempre tienen acceso
    if session.get("rol") in ("admin", "miembro"):
        return jsonify({"ok": True})

    uid = session["uid"]
    con = get_db()
    usuario = con.execute("SELECT mundial_pagado FROM usuarios WHERE id=%s", (uid,)).fetchone()
    if not usuario:
        return jsonify({"ok": False, "status": None})

    estado = usuario["mundial_pagado"] or ""
    if estado == "aprobado":
        return jsonify({"ok": True, "status": "aprobado"})
    elif estado.startswith("pendiente"):
        return jsonify({"ok": False, "status": "pendiente"})
    elif estado == "rechazado":
        return jsonify({"ok": False, "status": "rechazado"})
    else:
        return jsonify({"ok": False, "status": None})
