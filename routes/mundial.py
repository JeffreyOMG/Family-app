from flask import Blueprint, request, redirect, session, jsonify
from database import get_db, GRUPOS_MUNDIAL
from mundial_bracket import generar_bracket


mundial_bp = Blueprint("mundial", __name__)


# ─────────────────────────────────────────────
# API: datos del mundial (partidos + tabla + ranking + bracket)
# ─────────────────────────────────────────────
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
        LEFT JOIN pronosticos pr ON pr.partido_id=pm.id AND pr.usuario_id=?
        ORDER BY pm.grupo, pm.id
    """, (uid,)).fetchall()]

    # ── limpiar nombres ──
    partidos = []

    def _split(s):
        if "|" in s:
            n, c = s.split("|", 1)
            return n.strip(), c.strip()
        return s.strip(), "xx"

    for p in partidos_raw:
        ln, lc = _split(p["local"])
        vn, vc = _split(p["visitante"])

        partidos.append({
            "id": p["id"],
            "grupo": p["grupo"],
            "local": ln,
            "visitante": vn,
            "codigo_local": lc,
            "codigo_visitante": vc,
            "goles_local": p["goles_local"],
            "goles_visitante": p["goles_visitante"],
            "bloqueado": bool(p["bloqueado"]),
            "p_local": p["p_local"],
            "p_vis": p["p_vis"],
        })

    # ─────────────────────────────
    # TABLA DE POSICIONES
    # ─────────────────────────────
    tabla = {}

    for letra, equipos in GRUPOS_MUNDIAL.items():
        tabla[letra] = {}
        for nombre, codigo in equipos:
            tabla[letra][nombre] = {
                "codigo": codigo,
                "pts": 0,
                "pj": 0,
                "g": 0,
                "emp": 0,
                "p": 0,
                "gf": 0,
                "gc": 0,
                "dg": 0
            }

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

            t["gf"] += gf
            t["gc"] += gc
            t["dg"] = t["gf"] - t["gc"]

            if gl == gv:
                t["pts"] += 1
                t["emp"] += 1
            elif (gl > gv) == es_local:
                t["pts"] += 3
                t["g"] += 1
            else:
                t["p"] += 1

    # ordenar tabla
    tabla_ordenada = {}

    for letra, equipos in tabla.items():
        rows = [{"nombre": n, **v} for n, v in equipos.items()]
        rows.sort(key=lambda x: (-x["pts"], -x["dg"], -x["gf"]))
        tabla_ordenada[letra] = rows

    # ─────────────────────────────
    # RANKING
    # ─────────────────────────────
    ranking = [dict(r) for r in con.execute("""
        SELECT u.nombre,
               COALESCE(SUM(pr.puntos),0) AS puntos,
               COUNT(CASE WHEN pr.puntos=3 THEN 1 END) AS exactos,
               COUNT(CASE WHEN pr.puntos=1 THEN 1 END) AS ganadores
        FROM usuarios u
        LEFT JOIN pronosticos pr ON pr.usuario_id=u.id
        GROUP BY u.id, u.nombre
        ORDER BY puntos DESC, exactos DESC
    """).fetchall()]

    # ─────────────────────────────
    # BRACKET MUNDIAL 2026 (DINÁMICO)
    # Auto-sincroniza cruces fijos con tabla actual antes de generar bracket
    # ─────────────────────────────
    try:
        _ensure_eliminacion_table(con)
        _auto_asignar_fijos(con)
        _auto_propagar_ganadores(con)
    except Exception:
        pass
    bracket = generar_bracket(tabla_ordenada)

    return jsonify({
        "partidos": partidos,
        "tabla": tabla_ordenada,
        "ranking": ranking,
        "bracket": bracket
    })


# ─────────────────────────────────────────────
def _back():
    sec = request.args.get("s") or request.form.get("_sec") or "mundial"
    return redirect(f"/dashboard?s={sec}")


def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


# ─────────────────────────────────────────────
# PRONÓSTICOS
# ─────────────────────────────────────────────
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
                    "SELECT bloqueado FROM partidos_mundial WHERE id=?",
                    (partido_id,)
                ).fetchone()

                if partido and not partido["bloqueado"]:
                    con.execute("""
                        INSERT INTO pronosticos(usuario_id,partido_id,goles_local,goles_visitante)
                        VALUES(?,%s,%s,%s)
                        ON CONFLICT(usuario_id,partido_id) DO UPDATE SET
                            goles_local=excluded.goles_local,
                            goles_visitante=excluded.goles_visitante
                    """, (uid, partido_id, int(gl), int(gv)))

    con.commit()

    if _is_ajax():
        return jsonify({"ok": True, "msg": "Pronósticos guardados"})

    return _back()


# ─────────────────────────────────────────────
# ADMIN RESULTADOS
# ─────────────────────────────────────────────
@mundial_bp.route("/admin_resultado", methods=["POST"])
def admin_resultado():
    if session.get("rol") != "admin":
        if _is_ajax():
            return jsonify({"ok": False, "error": "no_admin"}), 403
        return redirect("/dashboard?s=mundial")

    partido_id = int(request.form.get("partido_id", 0))
    gl = request.form.get("goles_local", "")
    gv = request.form.get("goles_visitante", "")

    if not gl.isdigit() or not gv.isdigit():
        return _back()

    gl, gv = int(gl), int(gv)

    con = get_db()

    con.execute("""
        UPDATE partidos_mundial
        SET goles_local=?, goles_visitante=?, bloqueado=1
        WHERE id=?
    """, (gl, gv, partido_id))

    pronos = con.execute("""
        SELECT id,goles_local,goles_visitante
        FROM pronosticos
        WHERE partido_id=?
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

        con.execute(
            "UPDATE pronosticos SET puntos=? WHERE id=?",
            (puntos, p["id"])
        )

    con.commit()

    if _is_ajax():
        return jsonify({"ok": True, "msg": "Resultado guardado"})

    return _back()

    # ─────────────────────────────────────────────
# DESBLOQUEAR PARTIDO (ADMIN)
# ─────────────────────────────────────────────
@mundial_bp.route("/admin_desbloquear", methods=["POST"])
def admin_desbloquear():

    if session.get("rol") != "admin":
        if _is_ajax():
            return jsonify({"ok": False}), 403
        return redirect("/dashboard?s=mundial")

    partido_id = int(request.form.get("partido_id", 0))

    con = get_db()

    con.execute("""
        UPDATE partidos_mundial
        SET goles_local=NULL,
            goles_visitante=NULL,
            bloqueado=0
        WHERE id=?
    """, (partido_id,))

    con.execute("""
        UPDATE pronosticos
        SET puntos=0
        WHERE partido_id=?
    """, (partido_id,))

    con.commit()

    if _is_ajax():
        return jsonify({
            "ok": True,
            "msg": "Partido desbloqueado"
        })

    return _back()


# ─────────────────────────────────────────────
# RESET MUNDIAL (ADMIN)
# ─────────────────────────────────────────────
@mundial_bp.route("/admin_reset_mundial", methods=["POST"])
def admin_reset_mundial():

    if session.get("rol") != "admin":
        if _is_ajax():
            return jsonify({"ok": False}), 403
        return redirect("/dashboard?s=mundial")

    con = get_db()

    con.execute("""
        UPDATE partidos_mundial
        SET goles_local=NULL,
            goles_visitante=NULL,
            bloqueado=0
    """)

    con.execute("""
        UPDATE pronosticos
        SET puntos=0
    """)

    con.commit()

    if _is_ajax():
        return jsonify({
            "ok": True,
            "msg": "Mundial reiniciado"
        })

    return _back()


# ─────────────────────────────────────────────
# TOP USUARIOS POLLA
# ─────────────────────────────────────────────
@mundial_bp.route("/api/ranking_mundial")
def ranking_mundial():

    con = get_db()

    ranking = [dict(r) for r in con.execute("""
        SELECT
            u.id,
            u.nombre,
            u.usuario,
            u.foto,
            COALESCE(SUM(p.puntos),0) puntos
        FROM usuarios u
        LEFT JOIN pronosticos p
            ON p.usuario_id=u.id
        GROUP BY u.id, u.nombre
        ORDER BY puntos DESC
    """).fetchall()]

    return jsonify(ranking)


# ─────────────────────────────────────────────
# INFO GENERAL MUNDIAL
# ─────────────────────────────────────────────
@mundial_bp.route("/api/mundial_info")
def mundial_info():

    con = get_db()

    partidos = con.execute("""
        SELECT COUNT(*) total
        FROM partidos_mundial
    """).fetchone()["total"]

    jugados = con.execute("""
        SELECT COUNT(*) total
        FROM partidos_mundial
        WHERE bloqueado=1
    """).fetchone()["total"]

    usuarios = con.execute("""
        SELECT COUNT(*) total
        FROM usuarios
    """).fetchone()["total"]

    pronos = con.execute("""
        SELECT COUNT(*) total
        FROM pronosticos
    """).fetchone()["total"]

    return jsonify({
        "partidos": partidos,
        "jugados": jugados,
        "pendientes": partidos - jugados,
        "usuarios": usuarios,
        "pronosticos": pronos
    })




# ─────────────────────────────────────────────
# MIGRACIÓN: tabla partidos_eliminacion
# ─────────────────────────────────────────────
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
    filas.append((TERCER_PUESTO["id"], "Tercer puesto",
                  f"P{TERCER_PUESTO['dep1']}", f"P{TERCER_PUESTO['dep2']}",
                  TERCER_PUESTO["fecha"], TERCER_PUESTO["sede"]))
    filas.append((FINAL["id"], "Final",
                  f"G{FINAL['dep1']}", f"G{FINAL['dep2']}",
                  FINAL["fecha"], FINAL["sede"]))
    for fila in filas:
        con.execute("""
            INSERT INTO partidos_eliminacion
                (id, fase, slot_local, slot_visit, fecha, sede)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, fila)
    con.commit()


# ─────────────────────────────────────────────
# API: datos fase eliminatoria
# ─────────────────────────────────────────────
@mundial_bp.route("/api/eliminacion_datos")
def api_eliminacion_datos():
    if "uid" not in session:
        return jsonify({}), 401
    uid = session["uid"]
    con = get_db()
    _ensure_eliminacion_table(con)

    # ── Auto-asignar cruces fijos desde la tabla de grupos real ──
    _auto_asignar_fijos(con)
    # ── Propagar ganadores a octavos/cuartos/semis/final ──
    _auto_propagar_ganadores(con)

    partidos = [dict(p) for p in con.execute("""
        SELECT pe.*,
               pr.goles_local AS p_local,
               pr.goles_visit AS p_vis
        FROM partidos_eliminacion pe
        LEFT JOIN pronosticos_eli pr ON pr.partido_id=pe.id AND pr.usuario_id=?
        ORDER BY pe.id
    """, (uid,)).fetchall()]

    # ── Terceros actuales por grupo (para dropdowns de admin) ──
    terceros_por_grupo = _get_terceros_por_grupo(con)

    return jsonify({
        "partidos": partidos,
        "terceros_por_grupo": terceros_por_grupo,
    })


def _calcular_tabla_grupos(con):
    """Devuelve {letra: [(nombre, codigo, pts, dg, gf), ...]} ordenado."""
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
        ordenada[letra] = rows  # [(nombre, stats_dict), ...]
    return ordenada


def _auto_asignar_fijos(con):
    """
    Recalcula 1°/2° de cada grupo desde resultados reales y actualiza
    SIEMPRE los cruces fijos no bloqueados, limpiando el valor anterior.
    Esto garantiza que si la tabla cambia, el bracket refleja el estado actual.
    """
    from mundial_bracket import DIECISEISAVOS
    tabla = _calcular_tabla_grupos(con)

    def _resolver_slot(slot):
        """'1A' → 1° del grupo A, '2B' → 2° del grupo B"""
        if len(slot) == 2 and slot[0] in "12" and slot[1].isalpha():
            pos   = int(slot[0]) - 1   # 0=primero, 1=segundo
            letra = slot[1].upper()
            rows  = tabla.get(letra, [])
            if pos < len(rows):
                nombre = rows[pos][0]
                codigo = rows[pos][1]["codigo"]
                return nombre, codigo
        return None, None

    for p_data in DIECISEISAVOS:
        if not p_data["fijo"]:
            continue

        row = con.execute(
            "SELECT bloqueado FROM partidos_eliminacion WHERE id=?",
            (p_data["id"],)
        ).fetchone()
        if not row or row["bloqueado"]:
            continue   # partido ya jugado → no tocar

        nombre_l, codigo_l = _resolver_slot(p_data["slot_l"])
        nombre_v, codigo_v = _resolver_slot(p_data["slot_v"])

        # Siempre limpiar primero y reasignar desde tabla actual
        # Esto evita que quede un equipo "pegado" de una tabla anterior
        con.execute("""
            UPDATE partidos_eliminacion
            SET eq_local  = ?,
                cod_local = ?,
                eq_visit  = ?,
                cod_visit = ?
            WHERE id = ?
        """, (nombre_l, codigo_l, nombre_v, codigo_v, p_data["id"]))

    con.commit()


def _auto_propagar_ganadores(con):
    """
    Cuando un partido eliminatorio tiene resultado, propaga el ganador
    al siguiente cruce automáticamente.
    Slots en BD: G74 = ganador partido 74, P101 = perdedor partido 101
    """
    # Leer todos los partidos eliminatorios con resultado
    jugados = [dict(p) for p in con.execute("""
        SELECT id, goles_local, goles_visit, eq_local, cod_local, eq_visit, cod_visit
        FROM partidos_eliminacion
        WHERE bloqueado=1 AND goles_local IS NOT NULL AND eq_local IS NOT NULL AND eq_visit IS NOT NULL
    """).fetchall()]

    # Construir mapa: partido_id → {ganador: (nombre,cod), perdedor: (nombre,cod)}
    resultados = {}
    for p in jugados:
        gl, gv = p["goles_local"], p["goles_visit"]
        if gl > gv:
            gan = (p["eq_local"],  p["cod_local"])
            per = (p["eq_visit"],  p["cod_visit"])
        elif gv > gl:
            gan = (p["eq_visit"],  p["cod_visit"])
            per = (p["eq_local"],  p["cod_local"])
        else:
            # Empate en eliminatoria — de momento ganador es local (penales no están en sistema)
            gan = (p["eq_local"],  p["cod_local"])
            per = (p["eq_visit"],  p["cod_visit"])
        resultados[p["id"]] = {"ganador": gan, "perdedor": per}

    # Buscar todos los partidos no bloqueados con slot G/P
    pendientes = [dict(p) for p in con.execute("""
        SELECT id, slot_local, slot_visit, eq_local, eq_visit
        FROM partidos_eliminacion WHERE bloqueado=0
    """).fetchall()]

    def _resolver_slot_gp(slot):
        """'G74' → ganador partido 74, 'P101' → perdedor partido 101"""
        if not slot or len(slot) < 2:
            return None, None
        tipo = slot[0]  # G o P
        try:
            pid = int(slot[1:])
        except ValueError:
            return None, None
        if pid not in resultados:
            return None, None
        if tipo == "G":
            return resultados[pid]["ganador"]
        elif tipo == "P":
            return resultados[pid]["perdedor"]
        return None, None

    for p in pendientes:
        # Siempre recalcular desde resultados reales (no solo si está vacío)
        if p["slot_local"] and p["slot_local"][0] in ("G", "P"):
            nombre, codigo = _resolver_slot_gp(p["slot_local"])
            # Si no hay resultado aún, poner NULL para limpiar valor viejo
            con.execute(
                "UPDATE partidos_eliminacion SET eq_local=?, cod_local=? WHERE id=?",
                (nombre, codigo, p["id"])
            )
        if p["slot_visit"] and p["slot_visit"][0] in ("G", "P"):
            nombre, codigo = _resolver_slot_gp(p["slot_visit"])
            con.execute(
                "UPDATE partidos_eliminacion SET eq_visit=?, cod_visit=? WHERE id=?",
                (nombre, codigo, p["id"])
            )

    con.commit()


def _get_terceros_por_grupo(con):
    """Devuelve el 3er lugar actual de cada grupo con nombre y código."""
    tabla = _calcular_tabla_grupos(con)
    resultado = {}
    for letra, rows in tabla.items():
        if len(rows) >= 3:
            nombre = rows[2][0]
            codigo = rows[2][1]["codigo"]
            pts    = rows[2][1]["pts"]
            resultado[letra] = {"nombre": nombre, "codigo": codigo, "pts": pts}
    return resultado


# ─────────────────────────────────────────────
# PRONÓSTICO FASE ELIMINATORIA (usuario)
# ─────────────────────────────────────────────
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
            gl = request.form.get(f"local_{pid}", "")
            gv = request.form.get(f"vis_{pid}", "")
            if gl.isdigit() and gv.isdigit():
                p = con.execute(
                    "SELECT bloqueado, eq_local, eq_visit FROM partidos_eliminacion WHERE id=?", (pid,)
                ).fetchone()
                if p and not p["bloqueado"] and p["eq_local"] and p["eq_visit"]:
                    con.execute("""
                        INSERT INTO pronosticos_eli(usuario_id,partido_id,goles_local,goles_visit)
                        VALUES(?,%s,%s,%s)
                        ON CONFLICT(usuario_id,partido_id) DO UPDATE SET
                            goles_local=excluded.goles_local,
                            goles_visit=excluded.goles_visit
                    """, (uid, pid, int(gl), int(gv)))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Pronósticos guardados"})
    return _back()


# ─────────────────────────────────────────────
# ADMIN: asignar equipo a partido eliminación
# ─────────────────────────────────────────────
@mundial_bp.route("/admin_eli_equipo", methods=["POST"])
def admin_eli_equipo():
    if session.get("rol") != "admin":
        return jsonify({"ok": False}), 403
    con = get_db()
    _ensure_eliminacion_table(con)

    pid    = int(request.form.get("partido_id", 0))
    lado   = request.form.get("lado", "")   # "local" o "visit"
    nombre = request.form.get("nombre", "").strip()

    # Buscar código automáticamente desde GRUPOS_MUNDIAL — sin escribir nada
    codigo = "xx"
    for equipos in GRUPOS_MUNDIAL.values():
        for n, c in equipos:
            if n == nombre:
                codigo = c
                break

    if lado == "local":
        con.execute("UPDATE partidos_eliminacion SET eq_local=?, cod_local=? WHERE id=?",
                    (nombre, codigo, pid))
    elif lado == "visit":
        con.execute("UPDATE partidos_eliminacion SET eq_visit=?, cod_visit=? WHERE id=?",
                    (nombre, codigo, pid))
    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "codigo": codigo})
    return _back()


# ─────────────────────────────────────────────
# ADMIN: guardar resultado fase eliminatoria
# ─────────────────────────────────────────────
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
        UPDATE partidos_eliminacion
        SET goles_local=?, goles_visit=?, bloqueado=1
        WHERE id=?
    """, (gl, gv, pid))

    pronos = con.execute("""
        SELECT id, goles_local, goles_visit FROM pronosticos_eli WHERE partido_id=?
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
        con.execute("UPDATE pronosticos_eli SET puntos=? WHERE id=?", (pts, p["id"]))

    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Resultado guardado"})
    return _back()


# ─────────────────────────────────────────────
# RANKING GLOBAL (grupos + eliminación)
# ─────────────────────────────────────────────
@mundial_bp.route("/api/ranking_global")
def ranking_global():
    if "uid" not in session:
        return jsonify([]), 401
    con = get_db()
    _ensure_eliminacion_table(con)
    ranking = [dict(r) for r in con.execute("""
        SELECT u.nombre,
               COALESCE(SUM(pr.puntos),0) + COALESCE(SUM(pe.puntos),0) AS puntos,
               COUNT(CASE WHEN pr.puntos=3 THEN 1 END) +
               COUNT(CASE WHEN pe.puntos=3 THEN 1 END) AS exactos
        FROM usuarios u
        LEFT JOIN pronosticos    pr ON pr.usuario_id=u.id
        LEFT JOIN pronosticos_eli pe ON pe.usuario_id=u.id
        GROUP BY u.id, u.nombre ORDER BY puntos DESC, exactos DESC
    """).fetchall()]
    return jsonify(ranking)

# ─────────────────────────────────────────────
# FIN MUNDIAL.PY
# ─────────────────────────────────────────────