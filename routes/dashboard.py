from flask import Blueprint, render_template, session, redirect
from database import get_db, GRUPOS_MUNDIAL
from datetime import datetime

dash_bp = Blueprint("dashboard", __name__)

def _get_poll_for_post(con, post_id, uid):
    from routes.posts import _get_poll
    return _get_poll(con, post_id, uid)

def _sel(nombre_con_codigo):
    if "|" in nombre_con_codigo:
        nombre, codigo = nombre_con_codigo.split("|", 1)
        return nombre.strip(), codigo.strip()
    parts = nombre_con_codigo.rsplit(" ", 1)
    return parts[0], "xx"

def calcular_tabla(grupos, partidos_db):
    tabla = {}
    partidos_jugados_por_grupo = {}
    partidos_por_grupo = {}

    for letra, equipos in grupos.items():
        tabla[letra] = {}
        for nombre, codigo in equipos:
            tabla[letra][nombre] = {"bandera": codigo, "codigo": codigo, "pts": 0, "pj": 0, "g": 0, "emp": 0, "p": 0, "gf": 0, "gc": 0, "dg": 0}
        partidos_jugados_por_grupo[letra] = 0
        partidos_por_grupo[letra] = []

    for p in partidos_db:
        letra      = p["grupo"]
        local_n, local_b = _sel(p["local"])
        vis_n,   vis_b   = _sel(p["visitante"])
        info = {
            "id": p["id"], "grupo": letra,
            "local": local_n, "visitante": vis_n,
            "local_clean": local_n, "visitante_clean": vis_n,
            "bandera_local": local_b, "bandera_visitante": vis_b,
            "codigo_local": local_b, "codigo_visitante": vis_b,
            "goles_local": p["goles_local"], "goles_visitante": p["goles_visitante"],
            "bloqueado": bool(p["bloqueado"]),
            "p_local": p.get("p_local"), "p_vis": p.get("p_vis"),
        }
        if letra in partidos_por_grupo:
            partidos_por_grupo[letra].append(info)

        if p["bloqueado"] and p["goles_local"] is not None and letra in tabla:
            gl, gv = p["goles_local"], p["goles_visitante"]
            if local_n in tabla[letra] and vis_n in tabla[letra]:
                partidos_jugados_por_grupo[letra] += 1
                for eq, gf, gc in [(local_n, gl, gv), (vis_n, gv, gl)]:
                    tabla[letra][eq]["pj"] += 1
                    tabla[letra][eq]["gf"] += gf
                    tabla[letra][eq]["gc"] += gc
                    tabla[letra][eq]["dg"] += gf - gc
                if gl > gv:
                    tabla[letra][local_n]["g"] += 1; tabla[letra][local_n]["pts"] += 3
                    tabla[letra][vis_n]["p"] += 1
                elif gl < gv:
                    tabla[letra][vis_n]["g"] += 1; tabla[letra][vis_n]["pts"] += 3
                    tabla[letra][local_n]["p"] += 1
                else:
                    tabla[letra][local_n]["emp"] += 1; tabla[letra][local_n]["pts"] += 1
                    tabla[letra][vis_n]["emp"]   += 1; tabla[letra][vis_n]["pts"]   += 1

    tabla_lista = {}
    for letra, equipos in tabla.items():
        lista = [{"nombre": n, **stats} for n, stats in equipos.items()]
        lista.sort(key=lambda x: (-x["pts"], -x["dg"], -x["gf"]))
        tabla_lista[letra] = lista

    return tabla_lista, partidos_jugados_por_grupo, partidos_por_grupo

def get_ctx(uid, con, extra=None):
    usuario = con.execute(
        "SELECT id, nombre, usuario, rol, gmail, bio, foto, fecha FROM usuarios WHERE id=%s", (uid,)
    ).fetchone()
    if not usuario: return None
    usuario = dict(usuario)

    rol = usuario['rol']  # 'invitado', 'miembro', 'admin'
    vis_filter = "" if rol in ('miembro', 'admin') else "AND COALESCE(p.visibilidad,'general') = 'general'"

    publicaciones = [dict(p, liked=bool(p["liked"]), bookmarked=bool(p["bookmarked"])) for p in con.execute(f"""
        SELECT p.id, p.texto, p.media, p.media_tipo, p.fecha,
               COALESCE(p.visibilidad,'general') AS visibilidad,
               u.nombre, u.usuario, u.foto, u.id AS usuario_id,
               EXISTS(SELECT 1 FROM likes l WHERE l.usuario_id=%s AND l.post_id=p.id) AS liked,
               (SELECT COUNT(*) FROM likes l2 WHERE l2.post_id=p.id) AS total_likes,
               (SELECT COUNT(*) FROM reposts r WHERE r.post_id=p.id) AS total_reposts,
               EXISTS(SELECT 1 FROM bookmarks b WHERE b.usuario_id=%s AND b.post_id=p.id) AS bookmarked
        FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
        WHERE 1=1 {vis_filter}
        ORDER BY p.fecha DESC
    """, (uid, uid)).fetchall()]
    for _p in publicaciones:
        _p['poll'] = _get_poll_for_post(con, _p['id'], uid)

    tendencias = [dict(p, liked=bool(p["liked"]), bookmarked=bool(p["bookmarked"])) for p in con.execute(f"""
        SELECT p.id, p.texto, p.media, p.media_tipo, p.fecha,
               COALESCE(p.visibilidad,'general') AS visibilidad,
               u.nombre, u.usuario, u.foto, u.id AS usuario_id,
               EXISTS(SELECT 1 FROM likes l WHERE l.usuario_id=%s AND l.post_id=p.id) AS liked,
               (SELECT COUNT(*) FROM likes l2 WHERE l2.post_id=p.id) AS total_likes,
               (SELECT COUNT(*) FROM reposts r WHERE r.post_id=p.id) AS total_reposts,
               EXISTS(SELECT 1 FROM bookmarks b WHERE b.usuario_id=%s AND b.post_id=p.id) AS bookmarked
        FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
        WHERE 1=1 {vis_filter}
        ORDER BY total_likes DESC, p.fecha DESC
    """, (uid, uid)).fetchall()]
    for _p in tendencias:
        _p['poll'] = _get_poll_for_post(con, _p['id'], uid)

    guardados = [dict(p, liked=bool(p["liked"]), bookmarked=True) for p in con.execute(f"""
        SELECT p.id, p.texto, p.media, p.media_tipo, p.fecha,
               COALESCE(p.visibilidad,'general') AS visibilidad,
               u.nombre, u.usuario, u.foto, u.id AS usuario_id,
               EXISTS(SELECT 1 FROM likes l WHERE l.usuario_id=%s AND l.post_id=p.id) AS liked,
               (SELECT COUNT(*) FROM likes l2 WHERE l2.post_id=p.id) AS total_likes,
               (SELECT COUNT(*) FROM reposts r WHERE r.post_id=p.id) AS total_reposts,
               1 AS bookmarked
        FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.id IN (
            SELECT post_id FROM bookmarks WHERE usuario_id=%s
            UNION
            SELECT post_id FROM reposts WHERE usuario_id=%s
        ) {vis_filter}
        ORDER BY p.fecha DESC
    """, (uid, uid, uid)).fetchall()]
    for _p in guardados:
        _p['poll'] = _get_poll_for_post(con, _p['id'], uid)

    comentarios_rows = con.execute("""
        SELECT c.id, c.post_id, c.texto, c.parent_id, c.fecha, c.usuario_id, u.nombre, u.usuario, u.foto
        FROM comentarios c JOIN usuarios u ON u.id=c.usuario_id ORDER BY c.fecha ASC
    """).fetchall()
    comentarios_por_post = {}
    for c in comentarios_rows:
        comentarios_por_post.setdefault(c["post_id"], []).append(dict(c))

    total_global  = con.execute("SELECT COALESCE(SUM(monto),0) FROM aportes").fetchone()[0]
    total_aportes = con.execute("SELECT COALESCE(SUM(monto),0) FROM aportes WHERE usuario_id=%s", (uid,)).fetchone()[0]
    cfg_meta = con.execute("SELECT valor FROM config WHERE clave='meta_recaudacion'").fetchone()
    META = float(cfg_meta["valor"]) if cfg_meta else 500000
    pct  = min(round((total_global / META) * 100, 1), 100) if META > 0 else 0
    ranking = [dict(r, porcentaje=min(round((r["total"] / META) * 100, 1), 100)) for r in con.execute("""
        SELECT u.nombre, COALESCE(SUM(a.monto),0) AS total
        FROM usuarios u LEFT JOIN aportes a ON a.usuario_id=u.id
        GROUP BY u.id, u.nombre ORDER BY total DESC
    """).fetchall()]

    todos_aportes = [dict(a) for a in con.execute("""
        SELECT a.id, a.monto, a.descripcion, a.comprobante, a.verificado, a.fecha, u.nombre, u.foto
        FROM aportes a JOIN usuarios u ON u.id=a.usuario_id ORDER BY a.fecha DESC
    """).fetchall()]

    mis_aportes = [dict(a) for a in con.execute(
        "SELECT id, monto, descripcion, comprobante, verificado, fecha FROM aportes WHERE usuario_id=%s ORDER BY fecha DESC",
        (uid,)
    ).fetchall()]

    noticias = [dict(n) for n in con.execute(
        "SELECT id, titulo, contenido, categoria, fecha FROM noticias ORDER BY fecha DESC LIMIT 10"
    ).fetchall()]

    hoy = datetime.now().strftime("%Y-%m-%d")
    eventos_lista = [dict(e) for e in con.execute("""
        SELECT e.id, e.titulo, e.descripcion, e.fecha_evento, e.hora_evento, e.tipo, u.nombre AS autor
        FROM eventos e JOIN usuarios u ON u.id=e.usuario_id
        WHERE e.fecha_evento >= %s ORDER BY e.fecha_evento ASC
    """, (hoy,)).fetchall()]
    todos_eventos = [dict(e) for e in con.execute("""
        SELECT e.id, e.titulo, e.descripcion, e.fecha_evento, e.hora_evento, e.tipo,
               u.nombre AS autor, e.usuario_id
        FROM eventos e JOIN usuarios u ON u.id=e.usuario_id ORDER BY e.fecha_evento ASC
    """).fetchall()]

    archivos     = [dict(a) for a in con.execute("SELECT id, ruta, tipo, descripcion FROM galeria ORDER BY fecha DESC LIMIT 24").fetchall()]
    total_fotos  = con.execute("SELECT COUNT(*) FROM galeria WHERE tipo='imagen'").fetchone()[0]
    total_videos = con.execute("SELECT COUNT(*) FROM galeria WHERE tipo='video'").fetchone()[0]

    partidos_raw = [dict(p) for p in con.execute("""
        SELECT pm.id, pm.grupo, pm.local, pm.visitante, pm.goles_local, pm.goles_visitante, pm.bloqueado,
               pr.goles_local AS p_local, pr.goles_visitante AS p_vis
        FROM partidos_mundial pm
        LEFT JOIN pronosticos pr ON pr.partido_id=pm.id AND pr.usuario_id=%s
        ORDER BY pm.grupo, pm.id
    """, (uid,)).fetchall()]

    tabla_grupos, partidos_jugados_por_grupo, partidos_por_grupo = calcular_tabla(GRUPOS_MUNDIAL, partidos_raw)

    def _enrich(p):
        local_n, local_c = p["local"].split("|", 1)   if "|" in p["local"]     else (p["local"],     "xx")
        vis_n,   vis_c   = p["visitante"].split("|", 1) if "|" in p["visitante"] else (p["visitante"], "xx")
        return {**p,
            "local":              local_n.strip(),
            "visitante":          vis_n.strip(),
            "local_clean":        local_n.strip(),
            "visitante_clean":    vis_n.strip(),
            "codigo_local":       local_c.strip(),
            "codigo_visitante":   vis_c.strip(),
        }
    partidos_clean = [_enrich(p) for p in partidos_raw]

    try:
        # Crear tablas de eliminación si no existen (deploy nuevo / BD limpia)
        con.execute("""
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
        ranking_mundial = [dict(r) for r in con.execute("""
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
            WHERE COALESCE(g.puntos,0)+COALESCE(e.puntos,0) > 0
               OR (SELECT COUNT(*) FROM pronosticos WHERE usuario_id=u.id) > 0
               OR (SELECT COUNT(*) FROM pronosticos_eli WHERE usuario_id=u.id) > 0
            ORDER BY puntos DESC, penales DESC, exactos DESC, ganadores DESC
        """).fetchall()]
    except Exception:
        # Fallback: rollback de la transacción abortada y solo consultar grupos
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        ranking_mundial = [dict(r) for r in con.execute("""
            SELECT u.id, u.nombre, COALESCE(SUM(pr.puntos),0) AS puntos,
                   COUNT(CASE WHEN pr.puntos=3 THEN 1 END) AS exactos,
                   COUNT(CASE WHEN pr.puntos=1 THEN 1 END) AS ganadores,
                   0 AS penales
            FROM usuarios u LEFT JOIN pronosticos pr ON pr.usuario_id=u.id
            GROUP BY u.id, u.nombre
            HAVING COALESCE(SUM(pr.puntos),0)>0 OR (SELECT COUNT(*) FROM pronosticos WHERE usuario_id=u.id)>0
            ORDER BY puntos DESC, exactos DESC
        """).fetchall()]

    usuario_posts  = con.execute("SELECT COUNT(*) FROM publicaciones WHERE usuario_id=%s", (uid,)).fetchone()[0]
    usuario_likes  = con.execute("SELECT COUNT(*) FROM likes l JOIN publicaciones p ON p.id=l.post_id WHERE p.usuario_id=%s", (uid,)).fetchone()[0]
    usuario_puntos = con.execute("SELECT COALESCE(SUM(puntos),0) FROM pronosticos WHERE usuario_id=%s", (uid,)).fetchone()[0]

    miembros = [dict(m) for m in con.execute(
        "SELECT id, nombre, usuario, foto, rol FROM usuarios ORDER BY nombre ASC"
    ).fetchall()]

    polla_pagos_usuario = {p["fase"]: dict(p) for p in con.execute(
        "SELECT fase, monto, estado, fecha FROM polla_pagos WHERE usuario_id=%s", (uid,)
    ).fetchall()}

    eventos_recaudacion = [dict(e) for e in con.execute("""
        SELECT er.id, er.nombre_evento, er.monto, er.estado, er.fecha, u.nombre AS usuario
        FROM eventos_recaudacion er JOIN usuarios u ON u.id=er.usuario_id
        ORDER BY er.fecha DESC LIMIT 20
    """).fetchall()]

    noticias_recientes = [dict(n) for n in con.execute(
        "SELECT id, titulo, categoria, fecha FROM noticias ORDER BY fecha DESC LIMIT 4"
    ).fetchall()]

    ctx = dict(
        usuario=usuario,
        publicaciones=publicaciones,
        tendencias=tendencias,
        guardados=guardados,
        comentarios_por_post=comentarios_por_post,
        total_aportes=total_aportes,
        total=total_global,
        meta=META, pct=pct, porcentaje=pct,
        ranking=ranking,
        todos_aportes=todos_aportes,
        noticias=noticias,
        eventos=eventos_lista,
        todos_eventos=todos_eventos,
        archivos=archivos,
        total_fotos=total_fotos, total_videos=total_videos,
        total_albumes=1,
        albumes=[{"nombre": "General", "cantidad": total_fotos + total_videos}],
        partidos=partidos_clean,
        grupos=GRUPOS_MUNDIAL,
        tabla_grupos=tabla_grupos,
        partidos_jugados_por_grupo=partidos_jugados_por_grupo,
        partidos_por_grupo=partidos_por_grupo,
        ranking_mundial=ranking_mundial,
        usuario_aportes=total_aportes,
        usuario_posts=usuario_posts,
        usuario_likes=usuario_likes,
        usuario_puntos=usuario_puntos,
        mis_aportes=mis_aportes,
        miembros=miembros,
        polla_pagos_usuario=polla_pagos_usuario,
        eventos_recaudacion=eventos_recaudacion,
        noticias_recientes=noticias_recientes,
        actividades_usuario=[],
        cumpleanos=[],
        resultados=None,
        busqueda="",
        filtro_tipo="todo",
        seccion_activa="inicio",
        ahora=datetime.now().strftime("%d/%m/%Y"),
    )
    if extra:
        ctx.update(extra)
    return ctx

@dash_bp.route("/dashboard")
def dashboard():
    if "uid" not in session:
        return redirect("/")
    con     = get_db()
    from flask import request as req
    seccion = req.args.get("s", "inicio")
    ctx     = get_ctx(session["uid"], con, extra={"seccion_activa": seccion})
    if not ctx:
        session.clear()
        return redirect("/")
    return render_template("dashboard.html", **ctx)
