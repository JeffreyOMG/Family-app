from flask import Blueprint, request, session, redirect, render_template
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
