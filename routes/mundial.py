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

    ranking = [dict(r) for r in con.execute("""
        SELECT u.nombre,
               COALESCE(g.puntos,0)+COALESCE(e.puntos,0) AS puntos,
               COALESCE(g.exactos,0)+COALESCE(e.exactos,0) AS exactos,
               COALESCE(g.ganadores,0)+COALESCE(e.ganadores,0) AS ganadores
        FROM usuarios u
        LEFT JOIN (
            SELECT usuario_id,SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores
            FROM pronosticos GROUP BY usuario_id
        ) g ON g.usuario_id=u.id
        LEFT JOIN (
            SELECT usuario_id,SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos,
                   COUNT(CASE WHEN puntos=1 THEN 1 END) ganadores
            FROM pronosticos_eli GROUP BY usuario_id
        ) e ON e.usuario_id=u.id
        ORDER BY puntos DESC, exactos DESC
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
    con = get_db()
    ranking = [dict(r) for r in con.execute("""
        SELECT u.id, u.nombre, u.usuario, u.foto, COALESCE(SUM(p.puntos),0) puntos
        FROM usuarios u
        LEFT JOIN pronosticos p ON p.usuario_id=u.id
        GROUP BY u.id, u.nombre
        ORDER BY puntos DESC
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
            id          INTEGER PRIMARY KEY,
            fase        TEXT NOT NULL,
            slot_local  TEXT NOT NULL,
            slot_visit  TEXT NOT NULL,
            fecha       TEXT DEFAULT '',
            sede        TEXT DEFAULT '',
            eq_local    TEXT DEFAULT NULL,
            cod_local   TEXT DEFAULT NULL,
            eq_visit    TEXT DEFAULT NULL,
            cod_visit   TEXT DEFAULT NULL,
            goles_local INTEGER DEFAULT NULL,
            goles_visit INTEGER DEFAULT NULL,
            bloqueado   INTEGER DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pronosticos_eli (
            id          SERIAL PRIMARY KEY,
            usuario_id  INTEGER NOT NULL,
            partido_id  INTEGER NOT NULL,
            goles_local INTEGER NOT NULL,
            goles_visit INTEGER NOT NULL,
            puntos      INTEGER DEFAULT 0,
            UNIQUE(usuario_id, partido_id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
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

    partidos = [dict(p) for p in con.execute("""
        SELECT pe.*,
               pr.goles_local AS p_local, pr.goles_visit AS p_vis
        FROM partidos_eliminacion pe
        LEFT JOIN pronosticos_eli pr ON pr.partido_id=pe.id AND pr.usuario_id=%s
        ORDER BY pe.id
    """, (uid,)).fetchall()]

    terceros_por_grupo = _get_terceros_por_grupo(con)
    return jsonify({"partidos": partidos, "terceros_por_grupo": terceros_por_grupo})


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
    partidos = [dict(p) for p in con.execute("""
        SELECT * FROM partidos_eliminacion ORDER BY id
    """).fetchall()]

    resultados = {}
    for p in partidos:
        if not p.get("bloqueado") or p.get("goles_local") is None or p.get("goles_visit") is None:
            continue
        if not p.get("eq_local") or not p.get("eq_visit"):
            continue

        if p["goles_local"] >= p["goles_visit"]:
            ganador = (p["eq_local"], p["cod_local"])
            perdedor = (p["eq_visit"], p["cod_visit"])
        else:
            ganador = (p["eq_visit"], p["cod_visit"])
            perdedor = (p["eq_local"], p["cod_local"])

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

            dato = resultados[origen]["ganador" if slot.startswith("G") else "perdedor"]
            updates[campo_eq] = dato[0]
            updates[campo_cod] = dato[1]

        if updates:
            sets = ", ".join(f"{k}=%s" for k in updates)
            vals = list(updates.values()) + [p["id"]]
            con.execute(f"UPDATE partidos_eliminacion SET {sets} WHERE id=%s", vals)

    con.commit()

def _get_terceros_por_grupo(con):
    tabla = _calcular_tabla_grupos(con)
    resultado = {}
    for letra, rows in tabla.items():
        if len(rows) >= 3:
            nombre = rows[2][0]
            codigo = rows[2][1]["codigo"]
            pts    = rows[2][1]["pts"]
            resultado[letra] = {"nombre": nombre, "codigo": codigo, "pts": pts}
    return resultado


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
            if gl.isdigit() and gv.isdigit():
                p = con.execute(
                    "SELECT bloqueado, eq_local, eq_visit FROM partidos_eliminacion WHERE id=%s", (pid,)
                ).fetchone()
                if p and not p["bloqueado"] and p["eq_local"] and p["eq_visit"]:
                    con.execute("""
                        INSERT INTO pronosticos_eli(usuario_id, partido_id, goles_local, goles_visit)
                        VALUES(%s, %s, %s, %s)
                        ON CONFLICT(usuario_id, partido_id) DO UPDATE SET
                            goles_local=excluded.goles_local,
                            goles_visit=excluded.goles_visit
                    """, (uid, pid, int(gl), int(gv)))
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
    if not gl.isdigit() or not gv.isdigit():
        return _back()
    gl, gv = int(gl), int(gv)
    con = get_db()
    _ensure_eliminacion_table(con)

    con.execute("""
        UPDATE partidos_eliminacion SET goles_local=%s, goles_visit=%s, bloqueado=1 WHERE id=%s
    """, (gl, gv, pid))

    pronos = con.execute("""
        SELECT id, goles_local, goles_visit FROM pronosticos_eli WHERE partido_id=%s
    """, (pid,)).fetchall()

    for p in pronos:
        if p["goles_local"] == gl and p["goles_visit"] == gv:
            pts = 3
        elif (
            (p["goles_local"] > p["goles_visit"] and gl > gv) or
            (p["goles_local"] < p["goles_visit"] and gl < gv) or
            (p["goles_local"] == p["goles_visit"] and gl == gv)
        ):
            pts = 1
        else:
            pts = 0
        con.execute("UPDATE pronosticos_eli SET puntos=%s WHERE id=%s", (pts, p["id"]))

    con.commit()
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
        SELECT u.nombre,
               COALESCE(g.puntos,0)+COALESCE(e.puntos,0) AS puntos,
               COALESCE(g.exactos,0)+COALESCE(e.exactos,0) AS exactos
        FROM usuarios u
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos
            FROM pronosticos GROUP BY usuario_id
        ) g ON g.usuario_id=u.id
        LEFT JOIN (
            SELECT usuario_id, SUM(puntos) puntos,
                   COUNT(CASE WHEN puntos=3 THEN 1 END) exactos
            FROM pronosticos_eli GROUP BY usuario_id
        ) e ON e.usuario_id=u.id
        ORDER BY puntos DESC, exactos DESC
    """).fetchall()]
    return jsonify(ranking)
