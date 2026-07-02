from flask import Blueprint, request, session, redirect, render_template, jsonify
from database import get_db
from routes.dashboard import get_ctx

buscar_bp = Blueprint("buscar", __name__)

@buscar_bp.route("/buscar")
def buscar():
    if "uid" not in session:
        return redirect("/")
    uid  = session["uid"]
    q    = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "todo")
    con  = get_db()
    resultados = []

    if q:
        pat = f"%{q}%"
        if tipo in ("todo", "usuarios"):
            for u in con.execute(
                "SELECT nombre, usuario, rol, foto, COALESCE(verified,FALSE) AS verified FROM usuarios WHERE nombre LIKE %s OR usuario LIKE %s",
                (pat, pat)
            ).fetchall():
                resultados.append({"titulo": u["nombre"], "descripcion": f"@{u['usuario']} · {u['rol']}", "tipo": "Usuario", "foto": u["foto"], "usuario": u["usuario"], "verified": bool(u.get("verified", False))})
        if tipo in ("todo", "publicaciones"):
            for p in con.execute(
                "SELECT p.texto, u.nombre, p.fecha FROM publicaciones p JOIN usuarios u ON u.id=p.usuario_id WHERE p.texto LIKE %s",
                (pat,)
            ).fetchall():
                resultados.append({"titulo": p["nombre"], "descripcion": p["texto"][:100], "tipo": "Publicación", "fecha": p["fecha"][:10]})
        if tipo in ("todo", "noticias"):
            for n in con.execute(
                "SELECT titulo, contenido, fecha FROM noticias WHERE titulo LIKE %s OR contenido LIKE %s",
                (pat, pat)
            ).fetchall():
                resultados.append({"titulo": n["titulo"], "descripcion": n["contenido"][:100], "tipo": "Noticia", "fecha": n["fecha"][:10]})
        if tipo in ("todo", "eventos"):
            for e in con.execute(
                "SELECT e.titulo, e.descripcion, e.fecha_evento, e.tipo, u.nombre FROM eventos e JOIN usuarios u ON u.id=e.usuario_id WHERE e.titulo LIKE %s OR e.descripcion LIKE %s",
                (pat, pat)
            ).fetchall():
                resultados.append({"titulo": e["titulo"], "descripcion": e["descripcion"] or e["tipo"], "tipo": "Evento", "fecha": e["fecha_evento"], "autor": e["nombre"]})

    ctx = get_ctx(uid, con, extra={
        "resultados": resultados,
        "busqueda": q,
        "filtro_tipo": tipo,
        "seccion_activa": "buscador",
    })
    return render_template("dashboard.html", **ctx)


@buscar_bp.route("/api/buscar/pronosticos")
def api_buscar_pronosticos():
    """Devuelve pronósticos de partidos YA finalizados (bloqueados con resultado oficial).
    Parámetros opcionales: q (nombre usuario), fecha (YYYY-MM-DD o parte del grupo).
    Solo muestra pronósticos con puntos calculados para evitar copias.
    """
    if "uid" not in session:
        return jsonify({"ok": False, "msg": "No autenticado"}), 401

    q     = request.args.get("q", "").strip()
    fecha = request.args.get("fecha", "").strip()
    con   = get_db()

    # ── Fase de grupos ──────────────────────────────────────────────────────
    sql_grupos = """
        SELECT
            u.nombre        AS usuario_nombre,
            u.foto          AS usuario_foto,
            u.usuario       AS usuario_handle,
            pm.grupo        AS grupo,
            pm.local        AS local,
            pm.visitante    AS visitante,
            pm.goles_local  AS res_local,
            pm.goles_visitante AS res_visit,
            pr.goles_local  AS p_local,
            pr.goles_visitante AS p_vis,
            pr.puntos       AS puntos,
            pm.id           AS partido_id,
            NULL            AS res_penales,
            NULL            AS p_penales
        FROM pronosticos pr
        JOIN usuarios u          ON u.id  = pr.usuario_id
        JOIN partidos_mundial pm ON pm.id = pr.partido_id
        WHERE pm.bloqueado = 1
          AND pm.goles_local IS NOT NULL
          AND pm.goles_visitante IS NOT NULL
          AND pr.puntos IS NOT NULL
    """
    params_g = []
    if q:
        sql_grupos += " AND (u.nombre LIKE %s OR u.usuario LIKE %s)"
        params_g += [f"%{q}%", f"%{q}%"]
    if fecha:
        sql_grupos += " AND pm.grupo = %s"
        params_g += [fecha.upper()]
    sql_grupos += " ORDER BY pm.id, u.nombre"

    # ── Fase eliminatoria ───────────────────────────────────────────────────
    sql_eli = """
        SELECT
            u.nombre        AS usuario_nombre,
            u.foto          AS usuario_foto,
            u.usuario       AS usuario_handle,
            pe.fase         AS grupo,
            pe.eq_local     AS local,
            pe.eq_visit     AS visitante,
            pe.goles_local  AS res_local,
            pe.goles_visit  AS res_visit,
            pe_pr.goles_local  AS p_local,
            pe_pr.goles_visit  AS p_vis,
            pe_pr.puntos    AS puntos,
            pe.id           AS partido_id,
            pe.penales_ganador  AS res_penales,
            pe_pr.penales_ganador AS p_penales
        FROM pronosticos_eli pe_pr
        JOIN usuarios u              ON u.id  = pe_pr.usuario_id
        JOIN partidos_eliminacion pe ON pe.id = pe_pr.partido_id
        WHERE pe.bloqueado = 1
          AND pe.goles_local IS NOT NULL
          AND pe.goles_visit IS NOT NULL
          AND pe_pr.puntos IS NOT NULL
    """
    params_e = []
    if q:
        sql_eli += " AND (u.nombre LIKE %s OR u.usuario LIKE %s)"
        params_e += [f"%{q}%", f"%{q}%"]
    if fecha:
        sql_eli += " AND pe.fecha LIKE %s"
        params_e += [f"%{fecha}%"]
    sql_eli += " ORDER BY pe.id, u.nombre"

    def _split(s):
        if s and "|" in s:
            return s.split("|", 1)[0].strip()
        return (s or "").strip()

    resultados = []
    for r in con.execute(sql_grupos, params_g).fetchall():
        resultados.append({
            "usuario_nombre":  r["usuario_nombre"],
            "usuario_foto":    r["usuario_foto"],
            "usuario_handle":  r["usuario_handle"],
            "grupo":           r["grupo"],
            "local":           _split(r["local"]),
            "visitante":       _split(r["visitante"]),
            "res_local":       r["res_local"],
            "res_visit":       r["res_visit"],
            "p_local":         r["p_local"],
            "p_vis":           r["p_vis"],
            "puntos":          r["puntos"],
            "partido_id":      r["partido_id"],
            "fase":            "Grupos",
            "res_penales":     None,
            "p_penales":       None,
        })
    for r in con.execute(sql_eli, params_e).fetchall():
        resultados.append({
            "usuario_nombre":  r["usuario_nombre"],
            "usuario_foto":    r["usuario_foto"],
            "usuario_handle":  r["usuario_handle"],
            "grupo":           r["grupo"],
            "local":           _split(r["local"]),
            "visitante":       _split(r["visitante"]),
            "res_local":       r["res_local"],
            "res_visit":       r["res_visit"],
            "p_local":         r["p_local"],
            "p_vis":           r["p_vis"],
            "puntos":          r["puntos"],
            "partido_id":      r["partido_id"],
            "fase":            "Eliminatoria",
            "res_penales":     r["res_penales"],
            "p_penales":       r["p_penales"],
        })

    # Grupos disponibles para el filtro (solo fase de grupos con resultados)
    grupos_sql = """
        SELECT DISTINCT grupo FROM partidos_mundial
        WHERE bloqueado=1 AND goles_local IS NOT NULL
        ORDER BY grupo
    """
    grupos = [row["grupo"] for row in con.execute(grupos_sql).fetchall()]

    return jsonify({"ok": True, "data": resultados, "fechas": grupos})
