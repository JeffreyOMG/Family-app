from flask import Blueprint, request, redirect, session, jsonify
from database import get_db, GRUPOS_MUNDIAL
from mundial_bracket import generar_bracket

mundial_bp = Blueprint("mundial", __name__)

_FASES = ("grupos", "r16", "octavos", "cuartos", "semis", "final")

def _get_fases_lock(con):
    """Retorna dict {fase: bool} — True = bloqueada."""
    resultado = {}
    for fase in _FASES:
        row = con.execute("SELECT valor FROM config WHERE clave=%s", (f"fase_lock_{fase}",)).fetchone()
        resultado[fase] = bool(int(row["valor"])) if row else True
    return resultado

def _fase_esta_bloqueada(con, fase_key):
    """Retorna True si la fase está bloqueada."""
    row = con.execute("SELECT valor FROM config WHERE clave=%s", (f"fase_lock_{fase_key}",)).fetchone()
    return bool(int(row["valor"])) if row else True

def _fase_de_partido_eli(partido_id):
    """Mapea id de partido eliminatorio a clave de fase."""
    if 73 <= partido_id <= 88:   return "r16"
    if 89 <= partido_id <= 96:   return "octavos"
    if 97 <= partido_id <= 100:  return "cuartos"
    if 101 <= partido_id <= 102: return "semis"
    if 103 <= partido_id <= 104: return "final"
    return None

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
        # Orden inicial: pts → dg → gf → alfabético
        rows.sort(key=lambda x: (-x["pts"], -x["dg"], -x["gf"], x["nombre"]))
        # H2H entre subgrupos completamente empatados
        partidos_grupo = [p for p in partidos if p["bloqueado"] and p["goles_local"] is not None and p["grupo"] == letra]
        resultado_rows = []
        i = 0
        while i < len(rows):
            j = i + 1
            while j < len(rows):
                if (rows[i]["pts"] == rows[j]["pts"] and
                        rows[i]["dg"] == rows[j]["dg"] and
                        rows[i]["gf"] == rows[j]["gf"]):
                    j += 1
                else:
                    break
            subgrupo = rows[i:j]
            if len(subgrupo) > 1:
                nombres_set = {e["nombre"] for e in subgrupo}
                h2h = {e["nombre"]: {"pts": 0, "dg": 0, "gf": 0} for e in subgrupo}
                for pg in partidos_grupo:
                    def _n(s, _s=None): return s.split("|")[0].strip() if "|" in s else s.strip()
                    loc = _n(pg["local"]); vis = _n(pg["visitante"])
                    if loc not in nombres_set or vis not in nombres_set:
                        continue
                    gl2, gv2 = pg["goles_local"], pg["goles_visitante"]
                    h2h[loc]["gf"] += gl2; h2h[loc]["dg"] += gl2 - gv2
                    h2h[vis]["gf"] += gv2; h2h[vis]["dg"] += gv2 - gl2
                    if gl2 > gv2: h2h[loc]["pts"] += 3
                    elif gl2 == gv2: h2h[loc]["pts"] += 1; h2h[vis]["pts"] += 1
                    else: h2h[vis]["pts"] += 3
                subgrupo = sorted(subgrupo, key=lambda x: (
                    -h2h[x["nombre"]]["pts"],
                    -h2h[x["nombre"]]["dg"],
                    -h2h[x["nombre"]]["gf"],
                    x["nombre"]
                ))
            resultado_rows.extend(subgrupo)
            i = j
        tabla_ordenada[letra] = resultado_rows

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
        _reconstruir_bracket_desde_grupos(con)
    except Exception:
        pass
    bracket = generar_bracket(tabla_ordenada)
    fases_lock = _get_fases_lock(con)

    return jsonify({"partidos": partidos, "tabla": tabla_ordenada, "ranking": ranking, "bracket": bracket, "fases_lock": fases_lock})


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
    rol = session.get("rol", "invitado")

    # Validación server-side: acceso aprobado + términos aceptados
    ok, motivo = _usuario_puede_pronosticar(uid, rol)
    if not ok:
        err = {"tos_no_aceptados": "Debes aceptar los términos del Mundial 2026 antes de pronosticar.",
               "acceso_no_aprobado": "Tu acceso al Mundial aún no ha sido aprobado."}.get(motivo, "Acceso denegado.")
        return (jsonify({"ok": False, "error": err}), 403) if _is_ajax() else redirect("/")

    con = get_db()

    # Verificar que la fase de grupos no esté bloqueada
    if _fase_esta_bloqueada(con, "grupos"):
        err = "La fase de Grupos aún no ha sido habilitada por el administrador."
        return (jsonify({"ok": False, "error": err}), 403) if _is_ajax() else redirect("/")

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

    # Reconstruir bracket automáticamente tras registrar resultado de grupos
    try:
        _ensure_eliminacion_table(con)
        _reconstruir_bracket_desde_grupos(con)
    except Exception:
        pass

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

    # Reconstruir bracket: recalcular clasificados 1°/2° y limpiar slots afectados
    try:
        _ensure_eliminacion_table(con)
        _reconstruir_bracket_desde_grupos(con)
    except Exception:
        pass

    if _is_ajax():
        return jsonify({"ok": True, "msg": "Partido desbloqueado"})
    return _back()


@mundial_bp.route("/admin_desbloquear_eli", methods=["POST"])
def admin_desbloquear_eli():
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard?s=mundial")

    partido_id = int(request.form.get("partido_id", 0))
    con = get_db()
    _ensure_eliminacion_table(con)

    # 1. Limpiar resultado, bloqueado y marcador de obsoleto del partido resetado
    con.execute("""
        UPDATE partidos_eliminacion
        SET goles_local=NULL, goles_visit=NULL, penales_ganador=NULL,
            bloqueado=0, clasificado_obsoleto=0
        WHERE id=%s
    """, (partido_id,))
    con.execute("UPDATE pronosticos_eli SET puntos=0 WHERE partido_id=%s", (partido_id,))

    # 2. Limpiar slots G<partido_id> / P<partido_id> en partidos siguientes NO bloqueados
    partidos_sig = [dict(p) for p in con.execute(
        "SELECT id, slot_local, slot_visit, bloqueado FROM partidos_eliminacion WHERE id > %s",
        (partido_id,)
    ).fetchall()]
    for p in partidos_sig:
        if p["bloqueado"]:
            continue
        updates = {}
        for cs, ce, cc in [("slot_local","eq_local","cod_local"),("slot_visit","eq_visit","cod_visit")]:
            slot = p.get(cs) or ""
            if not slot: continue
            try: origen = int(slot[1:])
            except ValueError: continue
            if origen == partido_id:
                updates[ce] = None; updates[cc] = None
        if updates:
            sets = ", ".join(f"{k}=%s" for k in updates)
            vals = list(updates.values()) + [p["id"]]
            con.execute(f"UPDATE partidos_eliminacion SET {sets} WHERE id=%s", vals)

    con.commit()
    if _is_ajax():
        return jsonify({"ok": True, "msg": "Partido eliminatorio desbloqueado"})
    return _back()


@mundial_bp.route("/admin_reset_mundial", methods=["POST"])
def admin_reset_mundial():
    if session.get("rol") != "admin":
        return (jsonify({"ok": False}), 403) if _is_ajax() else redirect("/dashboard?s=mundial")

    con = get_db()

    # 1. Limpiar fase de grupos
    con.execute("UPDATE partidos_mundial SET goles_local=NULL, goles_visitante=NULL, bloqueado=0")
    con.execute("UPDATE pronosticos SET puntos=0")

    # 2. Limpiar fase eliminatoria: equipos y resultados
    try:
        con.execute("""
            UPDATE partidos_eliminacion SET
                eq_local=NULL, cod_local=NULL,
                eq_visit=NULL, cod_visit=NULL,
                goles_local=NULL, goles_visit=NULL,
                penales_ganador=NULL, bloqueado=0,
                clasificado_obsoleto=0
        """)
    except Exception:
        pass

    # 3. Limpiar pronósticos eliminatorios
    try:
        con.execute("UPDATE pronosticos_eli SET puntos=0")
    except Exception:
        pass

    # 4. Limpiar mejores terceros (selecciones manuales del admin)
    try:
        con.execute("DELETE FROM mejores_terceros")
    except Exception:
        pass

    con.commit()

    if _is_ajax():
        return jsonify({"ok": True, "msg": "Mundial reiniciado completamente"})
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
    _add_column_safe("partidos_eliminacion", "clasificado_obsoleto", "INTEGER DEFAULT 0")

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
    _reconstruir_bracket_desde_grupos(con)
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
    fases_lock         = _get_fases_lock(con)

    return jsonify({
        "partidos": partidos,
        "terceros_por_grupo": terceros_por_grupo,
        "mejores_terceros": mejores_terceros,
        "terceros_auto": terceros_auto,
        "fases_lock": fases_lock,
    })


def _calcular_tabla_grupos(con):
    """
    Calcula la tabla de posiciones de grupos con criterios de desempate completos:
    1. Puntos
    2. Diferencia de gol
    3. Goles a favor
    4. Enfrentamiento directo (Head-to-Head): pts → dg → gf (entre los empatados)
    5. Orden alfabético (criterio final de seguridad)
    """
    partidos_raw = [dict(p) for p in con.execute("""
        SELECT grupo, local, visitante, goles_local, goles_visitante
        FROM partidos_mundial WHERE bloqueado=1 AND goles_local IS NOT NULL
    """).fetchall()]

    def _nombre(s):
        return s.split("|")[0].strip() if "|" in s else s.strip()

    tabla = {}
    for letra, equipos in GRUPOS_MUNDIAL.items():
        tabla[letra] = {}
        for nombre, codigo in equipos:
            tabla[letra][nombre] = {"codigo": codigo, "pts": 0, "dg": 0, "gf": 0, "gc": 0, "pj": 0}

    # Guardar partidos por grupo para H2H
    partidos_por_grupo = {}
    for p in partidos_raw:
        letra = p["grupo"]
        if letra not in tabla:
            continue
        if letra not in partidos_por_grupo:
            partidos_por_grupo[letra] = []
        partidos_por_grupo[letra].append(p)
        gl, gv = p["goles_local"], p["goles_visitante"]
        loc, vis = _nombre(p["local"]), _nombre(p["visitante"])
        for equipo, es_local in [(loc, True), (vis, False)]:
            if equipo not in tabla.get(letra, {}):
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
            elif (gl > gv) == es_local:
                t["pts"] += 3

    def _h2h_stats(equipos_set, partidos):
        """Calcula pts/dg/gf de enfrentamiento directo entre un conjunto de equipos."""
        stats = {e: {"pts": 0, "dg": 0, "gf": 0} for e in equipos_set}
        for p in partidos:
            loc = _nombre(p["local"])
            vis = _nombre(p["visitante"])
            if loc not in equipos_set or vis not in equipos_set:
                continue
            gl, gv = p["goles_local"], p["goles_visitante"]
            # local
            stats[loc]["gf"] += gl
            stats[loc]["dg"] += gl - gv
            if gl > gv:
                stats[loc]["pts"] += 3
            elif gl == gv:
                stats[loc]["pts"] += 1
            # visitante
            stats[vis]["gf"] += gv
            stats[vis]["dg"] += gv - gl
            if gv > gl:
                stats[vis]["pts"] += 3
            elif gv == gl:
                stats[vis]["pts"] += 1
        return stats

    def _ordenar_grupo(equipos_items, partidos_grupo):
        """
        Ordena equipos con desempate completo.
        equipos_items: lista de (nombre, stats_dict)
        """
        # Orden inicial: pts → dg → gf → alfabético
        rows = sorted(equipos_items, key=lambda x: (-x[1]["pts"], -x[1]["dg"], -x[1]["gf"], x[0]))

        # Aplicar H2H entre grupos de equipos completamente empatados en pts/dg/gf
        resultado = []
        i = 0
        while i < len(rows):
            j = i + 1
            while j < len(rows):
                a = rows[i][1]
                b = rows[j][1]
                if a["pts"] == b["pts"] and a["dg"] == b["dg"] and a["gf"] == b["gf"]:
                    j += 1
                else:
                    break
            grupo_empatado = rows[i:j]
            if len(grupo_empatado) > 1:
                nombres_set = {e[0] for e in grupo_empatado}
                h2h = _h2h_stats(nombres_set, partidos_grupo)
                # Reordenar el subgrupo por H2H pts → dg → gf → alfabético
                grupo_empatado = sorted(
                    grupo_empatado,
                    key=lambda x: (
                        -h2h[x[0]]["pts"],
                        -h2h[x[0]]["dg"],
                        -h2h[x[0]]["gf"],
                        x[0]  # alfabético como criterio final
                    )
                )
            resultado.extend(grupo_empatado)
            i = j

        return resultado

    ordenada = {}
    for letra, equipos in tabla.items():
        equipos_items = list(equipos.items())
        partidos_grupo = partidos_por_grupo.get(letra, [])
        ordenada[letra] = _ordenar_grupo(equipos_items, partidos_grupo)
    return ordenada


def _reconstruir_bracket_desde_grupos(con):
    """
    Reconstruye completamente los clasificados 1°/2° en el bracket
    a partir del estado actual de los resultados de grupos.

    Flujo:
    1. Recalcular tabla de posiciones desde cero (sin caché).
    2. Para cada dieciseisavo:
       - Si NO está bloqueado: actualizar eq/cod normalmente y limpiar clasificado_obsoleto.
       - Si SÍ está bloqueado Y el clasificado cambió: marcar clasificado_obsoleto=1
         (no borrar el resultado registrado, pero marcar la inconsistencia para el frontend).
       - Si SÍ está bloqueado Y el clasificado coincide: limpiar clasificado_obsoleto.
    3. Limpiar ganadores propagados desde 16avos obsoletos (solo partidos no bloqueados).
    4. No tocar los terceros (gestionados manualmente por el admin).
    """
    from mundial_bracket import DIECISEISAVOS

    tabla = _calcular_tabla_grupos(con)

    def _resolver_slot(slot):
        if len(slot) == 2 and slot[0] in "12" and slot[1].isalpha():
            pos   = int(slot[0]) - 1
            letra = slot[1].upper()
            rows  = tabla.get(letra, [])
            if pos < len(rows):
                nombre = rows[pos][0]
                codigo = rows[pos][1]["codigo"]
                pj     = rows[pos][1].get("pj", 0)
                if pj > 0:
                    return nombre, codigo
        return None, None

    # ── Paso 1: Leer estado actual de los 16avos ────────────────────────────
    partidos_16 = {
        p["id"]: dict(p)
        for p in con.execute(
            "SELECT id, eq_local, cod_local, eq_visit, cod_visit, bloqueado, "
            "COALESCE(clasificado_obsoleto, 0) AS clasificado_obsoleto "
            "FROM partidos_eliminacion WHERE id BETWEEN 73 AND 88"
        ).fetchall()
    }

    ids_16_cambiados = set()

    # ── Paso 2: Actualizar clasificados en los 16avos ────────────────────────
    for p_data in DIECISEISAVOS:
        pid = p_data["id"]
        if pid not in partidos_16:
            continue

        actual = partidos_16[pid]
        bloqueado = bool(actual["bloqueado"])

        nombre_l, codigo_l = _resolver_slot(p_data["slot_l"])

        if p_data["fijo"]:
            nombre_v, codigo_v = _resolver_slot(p_data["slot_v"])

            if not bloqueado:
                # Partido no bloqueado: actualizar y limpiar obsoleto
                con.execute("""
                    UPDATE partidos_eliminacion
                    SET eq_local=%s, cod_local=%s, eq_visit=%s, cod_visit=%s,
                        clasificado_obsoleto=0
                    WHERE id=%s
                """, (nombre_l, codigo_l, nombre_v, codigo_v, pid))
            else:
                # Partido bloqueado: detectar si el clasificado cambió
                cambio_local  = (nombre_l != actual.get("eq_local"))
                cambio_visit  = (nombre_v != actual.get("eq_visit"))
                if cambio_local or cambio_visit:
                    # Marcar obsoleto pero NO borrar resultado
                    con.execute("""
                        UPDATE partidos_eliminacion
                        SET eq_local=%s, cod_local=%s, eq_visit=%s, cod_visit=%s,
                            clasificado_obsoleto=1
                        WHERE id=%s
                    """, (nombre_l, codigo_l, nombre_v, codigo_v, pid))
                    ids_16_cambiados.add(pid)
                else:
                    # Clasificado igual: asegurar obsoleto=0
                    con.execute("""
                        UPDATE partidos_eliminacion SET clasificado_obsoleto=0 WHERE id=%s
                    """, (pid,))
        else:
            # Solo actualizar el local (slot 1X); visitante es tercero del admin
            if not bloqueado:
                con.execute("""
                    UPDATE partidos_eliminacion
                    SET eq_local=%s, cod_local=%s, clasificado_obsoleto=0
                    WHERE id=%s
                """, (nombre_l, codigo_l, pid))
            else:
                cambio_local = (nombre_l != actual.get("eq_local"))
                if cambio_local:
                    con.execute("""
                        UPDATE partidos_eliminacion
                        SET eq_local=%s, cod_local=%s, clasificado_obsoleto=1
                        WHERE id=%s
                    """, (nombre_l, codigo_l, pid))
                    ids_16_cambiados.add(pid)
                else:
                    con.execute("""
                        UPDATE partidos_eliminacion SET clasificado_obsoleto=0 WHERE id=%s
                    """, (pid,))

    con.commit()

    # ── Paso 3: Limpiar slots G<pid> en partidos siguientes no bloqueados ───
    if ids_16_cambiados:
        partidos_siguientes = [dict(p) for p in con.execute(
            "SELECT id, slot_local, slot_visit, bloqueado "
            "FROM partidos_eliminacion WHERE id > 88"
        ).fetchall()]

        for p in partidos_siguientes:
            if p["bloqueado"]:
                continue
            updates = {}
            for campo_slot, campo_eq, campo_cod in [
                ("slot_local", "eq_local", "cod_local"),
                ("slot_visit", "eq_visit", "cod_visit"),
            ]:
                slot = p.get(campo_slot) or ""
                if not slot.startswith("G"):
                    continue
                try:
                    origen = int(slot[1:])
                except ValueError:
                    continue
                if origen in ids_16_cambiados:
                    updates[campo_eq]  = None
                    updates[campo_cod] = None

            if updates:
                sets = ", ".join(f"{k}=%s" for k in updates)
                vals = list(updates.values()) + [p["id"]]
                con.execute(f"UPDATE partidos_eliminacion SET {sets} WHERE id=%s", vals)

        con.commit()

    # ── Paso 4: Repropagar ganadores hacia adelante ──────────────────────────
    _auto_propagar_ganadores(con)




def _auto_propagar_ganadores(con):
    """
    Propaga ganadores (y perdedores para tercer puesto) a lo largo del bracket.
    - Si hay empate en tiempo reglamentario sin penales definidos, NO propagamos.
    - Si el partido origen tiene clasificado_obsoleto=1, NO propagamos desde él
      (evita que un resultado inválido se extienda al bracket).
    """
    partidos = [dict(p) for p in con.execute("""
        SELECT *, COALESCE(clasificado_obsoleto, 0) AS clasificado_obsoleto
        FROM partidos_eliminacion ORDER BY id
    """).fetchall()]

    resultados = {}
    for p in partidos:
        if not p.get("bloqueado") or p.get("goles_local") is None or p.get("goles_visit") is None:
            continue
        if not p.get("eq_local") or not p.get("eq_visit"):
            continue
        # No propagar desde partidos con clasificado obsoleto
        if p.get("clasificado_obsoleto"):
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
    rol = session.get("rol", "invitado")

    # Validación server-side: acceso aprobado + términos aceptados
    ok, motivo = _usuario_puede_pronosticar(uid, rol)
    if not ok:
        err = {"tos_no_aceptados": "Debes aceptar los términos del Mundial 2026 antes de pronosticar.",
               "acceso_no_aprobado": "Tu acceso al Mundial aún no ha sido aprobado."}.get(motivo, "Acceso denegado.")
        return (jsonify({"ok": False, "error": err}), 403) if _is_ajax() else redirect("/")

    con = get_db()
    _ensure_eliminacion_table(con)

    for key in request.form:
        if key.startswith("local_"):
            pid = int(key.split("_")[1])
            gl  = request.form.get(f"local_{pid}", "")
            gv  = request.form.get(f"vis_{pid}", "")
            pen = request.form.get(f"pen_{pid}", "").strip() or None
            if gl.isdigit() and gv.isdigit():
                # Verificar bloqueo de fase
                fase_key = _fase_de_partido_eli(pid)
                if fase_key and _fase_esta_bloqueada(con, fase_key):
                    nombres = {"r16": "16avos de Final", "octavos": "Octavos", "cuartos": "Cuartos",
                               "semis": "Semifinales", "final": "Final"}
                    err = f"La fase de {nombres.get(fase_key, fase_key)} aún no ha sido habilitada por el administrador."
                    return (jsonify({"ok": False, "error": err}), 403) if _is_ajax() else redirect("/")
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

    # No permitir cambiar equipos en partidos ya bloqueados
    partido_row = con.execute(
        "SELECT bloqueado FROM partidos_eliminacion WHERE id=%s", (pid,)
    ).fetchone()
    if partido_row and partido_row["bloqueado"]:
        if _is_ajax():
            return jsonify({"ok": False, "error": "No se puede cambiar el equipo de un partido con resultado registrado. Desbloquéalo primero."})
        return _back()

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


@mundial_bp.route("/api/ranking_mundial_v2")
def ranking_mundial_v2():
    """
    Ranking con 3 categorías (global/grupos/eliminatorias),
    cambio de posición (▲▼—) y métricas de participación.
    """
    if "uid" not in session:
        return jsonify({}), 401

    con = get_db()
    try:
        _ensure_eliminacion_table(con)
    except Exception:
        pass
    _ensure_ranking_tables(con)

    # ── Totales de partidos por tipo ─────────────────────────────────────
    total_grupos = con.execute(
        "SELECT COUNT(*) AS n FROM partidos_mundial"
    ).fetchone()["n"]
    total_eli = con.execute(
        "SELECT COUNT(*) AS n FROM partidos_eliminacion"
    ).fetchone()["n"]
    total_global = total_grupos + total_eli

    # ── Query única agregada por usuario ────────────────────────────────────
    rows = con.execute("""
        SELECT u.id, u.nombre, u.usuario, u.foto,
               COALESCE(g.puntos,0)    AS pts_g,
               COALESCE(g.exactos,0)   AS ex_g,
               COALESCE(g.ganadores,0) AS gan_g,
               COALESCE(g.pronosticos,0) AS pron_g,
               COALESCE(e.puntos,0)    AS pts_e,
               COALESCE(e.exactos,0)   AS ex_e,
               COALESCE(e.ganadores,0) AS gan_e,
               COALESCE(e.penales,0)   AS pen_e,
               COALESCE(e.pronosticos,0) AS pron_e
        FROM usuarios u
        LEFT JOIN (
            SELECT usuario_id,
                   SUM(puntos)                          AS puntos,
                   COUNT(CASE WHEN puntos=3  THEN 1 END) AS exactos,
                   COUNT(CASE WHEN puntos=1  THEN 1 END) AS ganadores,
                   COUNT(*)                              AS pronosticos
            FROM pronosticos GROUP BY usuario_id
        ) g ON g.usuario_id = u.id
        LEFT JOIN (
            SELECT usuario_id,
                   SUM(puntos)                             AS puntos,
                   COUNT(CASE WHEN puntos IN(3,4) THEN 1 END) AS exactos,
                   COUNT(CASE WHEN puntos=1  THEN 1 END)   AS ganadores,
                   COUNT(CASE WHEN puntos=4  THEN 1 END)   AS penales,
                   COUNT(*)                                AS pronosticos
            FROM pronosticos_eli GROUP BY usuario_id
        ) e ON e.usuario_id = u.id
    """).fetchall()

    # ── Construir los 3 rankings ─────────────────────────────────────────
    def _rank(lst, key_pts, key_pen, key_ex, key_gan, key_nom, key_id):
        sorted_lst = sorted(lst, key=lambda r: (
            -r[key_pts], -r[key_pen], -r[key_ex], -r[key_gan],
            r[key_nom].lower(), r[key_id]
        ))
        # Asignar posición (empates comparten posición)
        result = []
        for i, r in enumerate(sorted_lst):
            if i == 0:
                pos = 1
            else:
                prev = result[-1]
                same = (
                    r[key_pts] == prev["_pts"] and
                    r[key_pen] == prev["_pen"] and
                    r[key_ex]  == prev["_ex"]  and
                    r[key_gan] == prev["_gan"]
                )
                pos = prev["posicion"] if same else i + 1
            result.append({**dict(r), "posicion": pos,
                           "_pts": r[key_pts], "_pen": r[key_pen],
                           "_ex": r[key_ex], "_gan": r[key_gan]})
        return result

    # Global
    for r in rows:
        r = dict(r)
    raw = [dict(r) for r in rows]
    for r in raw:
        r["pts_global"] = r["pts_g"] + r["pts_e"]
        r["pen_global"] = r["pen_e"]
        r["ex_global"]  = r["ex_g"] + r["ex_e"]
        r["gan_global"] = r["gan_g"] + r["gan_e"]
        r["pron_global"]= r["pron_g"] + r["pron_e"]

    ranking_global_list = _rank(raw, "pts_global", "pen_global", "ex_global", "gan_global", "nombre", "id")
    ranking_grupos_list  = _rank(raw, "pts_g",      "pen_e",      "ex_g",      "gan_g",      "nombre", "id")
    ranking_eli_list     = _rank(raw, "pts_e",      "pen_e",      "ex_e",      "gan_e",      "nombre", "id")

    # ── Cargar snapshot anterior para calcular cambios ───────────────────
    def _load_snapshot(categoria):
        row = con.execute(
            "SELECT datos FROM ranking_snapshot WHERE categoria=%s", (categoria,)
        ).fetchone()
        if not row:
            return {}
        import json
        try:
            return {int(k): v for k, v in json.loads(row["datos"]).items()}
        except Exception:
            return {}

    snap_global = _load_snapshot("global")
    snap_grupos = _load_snapshot("grupos")
    snap_eli    = _load_snapshot("eliminatorias")

    def _apply_cambio(ranking_list, snapshot):
        result = []
        for r in ranking_list:
            uid_r = r["id"]
            prev = snapshot.get(uid_r)
            if prev is None:
                cambio = 0
            else:
                cambio = prev - r["posicion"]  # positivo = subió
            result.append({**r, "cambio": cambio})
        return result

    ranking_global_list = _apply_cambio(ranking_global_list, snap_global)
    ranking_grupos_list  = _apply_cambio(ranking_grupos_list,  snap_grupos)
    ranking_eli_list     = _apply_cambio(ranking_eli_list,     snap_eli)

    # ── Guardar nuevo snapshot y historial ────────────────────────────────
    import json
    def _save_snapshot(categoria, ranking_list):
        """Solo actualiza el snapshot si han pasado al menos 5 minutos desde el último,
        o si es la primera vez. Así el cambio de posición es real entre ciclos."""
        # Verificar cuándo fue el último guardado
        last = con.execute(
            "SELECT actualizado FROM ranking_snapshot WHERE categoria=%s", (categoria,)
        ).fetchone()
        if last:
            from datetime import datetime, timezone
            try:
                # actualizado puede venir como string o datetime
                ts = last["actualizado"]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                # Si tiene timezone, usar UTC; si no, asumir UTC
                if ts.tzinfo is None:
                    from datetime import timezone
                    ts = ts.replace(tzinfo=timezone.utc)
                ahora = datetime.now(timezone.utc)
                diff = (ahora - ts).total_seconds()
                if diff < 300:  # menos de 5 minutos → no actualizar
                    return
            except Exception:
                pass  # si falla la comparación, igual guarda
        datos = json.dumps({r["id"]: r["posicion"] for r in ranking_list})
        con.execute("""
            INSERT INTO ranking_snapshot(categoria, datos, actualizado)
            VALUES(%s, %s, NOW())
            ON CONFLICT(categoria) DO UPDATE
            SET datos=%s, actualizado=NOW()
        """, (categoria, datos, datos))

    def _save_historial(categoria, ranking_list):
        datos = json.dumps([{
            "id": r["id"], "nombre": r["nombre"],
            "posicion": r["posicion"], "puntos": r.get("pts_global", r.get("pts_g", r.get("pts_e", 0)))
        } for r in ranking_list])
        con.execute("""
            INSERT INTO ranking_historial(categoria, datos, creado)
            VALUES(%s, %s, NOW())
        """, (categoria, datos))
        # Limpiar registros > 7 días
        con.execute("""
            DELETE FROM ranking_historial
            WHERE creado < NOW() - INTERVAL '7 days'
        """)

    _save_snapshot("global",        ranking_global_list)
    _save_snapshot("grupos",        ranking_grupos_list)
    _save_snapshot("eliminatorias", ranking_eli_list)
    _save_historial("global",        ranking_global_list)
    con.commit()

    # ── Formatear respuesta ───────────────────────────────────────────────
    def _fmt(lst, pts_key, pron_key, total):
        out = []
        for r in lst:
            uid_r = r["id"]
            out.append({
                "id":       uid_r,
                "nombre":   r["nombre"],
                "usuario":  r.get("usuario", ""),
                "foto":     r.get("foto", ""),
                "puntos":   r[pts_key],
                "penales":  r.get("pen_global", r.get("pen_e", 0)),
                "exactos":  r.get("ex_global", r.get("ex_g", r.get("ex_e", 0))),
                "ganadores":r.get("gan_global", r.get("gan_g", r.get("gan_e", 0))),
                "posicion": r["posicion"],
                "cambio":   r["cambio"],
                "pronosticos_hechos": r[pron_key],
                "total_partidos": total,
            })
        return out

    return jsonify({
        "ranking_global": _fmt(ranking_global_list, "pts_global", "pron_global", total_global),
        "ranking_grupos":  _fmt(ranking_grupos_list,  "pts_g",      "pron_g",      total_grupos),
        "ranking_eli":     _fmt(ranking_eli_list,     "pts_e",      "pron_e",      total_eli),
    })


def _ensure_ranking_tables(con):
    """Crea las tablas ranking_snapshot y ranking_historial si no existen."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS ranking_snapshot (
            categoria   TEXT PRIMARY KEY,
            datos       TEXT NOT NULL,
            actualizado TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ranking_historial (
            id        SERIAL PRIMARY KEY,
            categoria TEXT NOT NULL,
            datos     TEXT NOT NULL,
            creado    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    con.commit()


@mundial_bp.route("/api/admin/ranking_snapshot_reset", methods=["POST"])
def ranking_snapshot_reset():
    """Admin: borra snapshots para que el tracking de cambios empiece limpio."""
    if "uid" not in session:
        return jsonify({}), 401
    con = get_db()
    u = con.execute("SELECT rol FROM usuarios WHERE id=%s", (session["uid"],)).fetchone()
    if not u or u["rol"] != "admin":
        return jsonify({}), 403
    con.execute("DELETE FROM ranking_snapshot")
    con.commit()
    return jsonify({"ok": True})


@mundial_bp.route("/api/admin/ranking_eli_toggle", methods=["POST"])
def ranking_eli_toggle():
    if "uid" not in session:
        return jsonify({}), 401
    con = get_db()
    # Verificar que es admin
    u = con.execute("SELECT rol FROM usuarios WHERE id=%s", (session["uid"],)).fetchone()
    if not u or u["rol"] != "admin":
        return jsonify({}), 403
    row = con.execute("SELECT valor FROM config WHERE clave='ranking_eli_visible'").fetchone()
    current = row and row["valor"] == "1"
    new_val = "0" if current else "1"
    con.execute("""
        INSERT INTO config(clave, valor) VALUES('ranking_eli_visible', %s)
        ON CONFLICT(clave) DO UPDATE SET valor=%s
    """, (new_val, new_val))
    con.commit()
    return jsonify({"visible": new_val == "1"})


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
# TÉRMINOS MUNDIAL 2026 — aceptación con audit trail
# ══════════════════════════════════════════

# Versión activa del reglamento — incrementar si cambian las reglas
# para forzar nueva aceptación a todos los usuarios.
MUNDIAL_TOS_VERSION = "2026-v1"


def _ensure_tos_schema():
    """
    Crea/migra las estructuras necesarias para TOS:
      - Columna mundial_tos_accepted en usuarios (caché rápido para gate)
      - Tabla mundial_tos_log (audit trail completo: userId, fecha, versión, IP)
    """
    con = get_db()

    def _col(table, column, definition):
        try:
            con.execute(f"SAVEPOINT add_col_{column}")
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            con.execute(f"RELEASE SAVEPOINT add_col_{column}")
            con.commit()
        except Exception:
            con.execute(f"ROLLBACK TO SAVEPOINT add_col_{column}")

    _col("usuarios", "mundial_tos_accepted",    "BOOLEAN DEFAULT FALSE")
    _col("usuarios", "mundial_tos_version",     "TEXT DEFAULT NULL")
    _col("usuarios", "mundial_tos_fecha",       "TIMESTAMPTZ DEFAULT NULL")

    con.execute("""
        CREATE TABLE IF NOT EXISTS mundial_tos_log (
            id          SERIAL PRIMARY KEY,
            usuario_id  INTEGER NOT NULL,
            version     TEXT NOT NULL,
            aceptado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ip          TEXT,
            user_agent  TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
    """)
    con.commit()


def _usuario_puede_pronosticar(uid, rol):
    """
    Comprueba que el usuario tiene acceso completo al Mundial:
      - Invitados: deben tener mundial_pagado='aprobado'
      - Todos: deben haber aceptado la versión activa de los términos
    Devuelve (ok: bool, motivo: str | None)
    """
    con = get_db()
    _ensure_tos_schema()
    row = con.execute(
        "SELECT mundial_pagado, mundial_tos_accepted, mundial_tos_version FROM usuarios WHERE id=%s",
        (uid,)
    ).fetchone()
    if not row:
        return False, "usuario_no_encontrado"

    # Invitados deben estar aprobados
    if rol == "invitado" and row["mundial_pagado"] != "aprobado":
        return False, "acceso_no_aprobado"

    # Todos deben haber aceptado la versión activa
    if not row["mundial_tos_accepted"] or row["mundial_tos_version"] != MUNDIAL_TOS_VERSION:
        return False, "tos_no_aceptados"

    return True, None


@mundial_bp.route("/api/mundial_tos", methods=["GET"])
def mundial_tos_status():
    """
    Devuelve si el usuario aceptó la versión activa de los términos.
    Respuesta: { accepted: bool, version: str }
    """
    if "uid" not in session:
        return jsonify({"accepted": False}), 401
    _ensure_tos_schema()
    uid = session["uid"]
    con = get_db()
    row = con.execute(
        "SELECT mundial_tos_accepted, mundial_tos_version FROM usuarios WHERE id=%s", (uid,)
    ).fetchone()
    accepted = bool(
        row
        and row["mundial_tos_accepted"]
        and row["mundial_tos_version"] == MUNDIAL_TOS_VERSION
    )
    return jsonify({"accepted": accepted, "version": MUNDIAL_TOS_VERSION})


@mundial_bp.route("/api/mundial_tos", methods=["POST"])
def mundial_tos_accept():
    """
    Registra la aceptación de los términos en la BD con audit trail completo.
    Guarda: userId, versión, fecha/hora (server-side), IP, User-Agent.
    """
    if "uid" not in session:
        return jsonify({"ok": False, "error": "No autenticado"}), 401
    _ensure_tos_schema()
    uid  = session["uid"]
    rol  = session.get("rol", "invitado")
    con  = get_db()
    ip   = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ua   = request.headers.get("User-Agent", "")[:512]

    # Invitado sin aprobación no puede aceptar
    if rol == "invitado":
        row = con.execute(
            "SELECT mundial_pagado FROM usuarios WHERE id=%s", (uid,)
        ).fetchone()
        if not row or row["mundial_pagado"] != "aprobado":
            return jsonify({"ok": False, "error": "Acceso no aprobado"}), 403

    # Actualizar columnas de caché en usuarios
    con.execute("""
        UPDATE usuarios
        SET mundial_tos_accepted = TRUE,
            mundial_tos_version  = %s,
            mundial_tos_fecha    = NOW()
        WHERE id = %s
    """, (MUNDIAL_TOS_VERSION, uid))

    # Insertar registro en audit log (siempre, incluso si ya lo había aceptado antes)
    con.execute("""
        INSERT INTO mundial_tos_log (usuario_id, version, ip, user_agent)
        VALUES (%s, %s, %s, %s)
    """, (uid, MUNDIAL_TOS_VERSION, ip, ua))

    con.commit()
    return jsonify({"ok": True, "version": MUNDIAL_TOS_VERSION})


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
