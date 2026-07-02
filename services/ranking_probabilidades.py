"""
services/ranking_probabilidades.py
====================================================================
Motor INDEPENDIENTE de simulación del RANKING DE USUARIOS del Mundial 2026.

NO modifica ni importa lógica de puntuación desde routes/mundial.py: vuelve a
leer las mismas tablas (partidos_mundial, pronosticos, partidos_eliminacion,
pronosticos_eli, usuarios) de forma solamente-lectura y reimplementa, en este
archivo aislado, exactamente las mismas reglas ya existentes en el sistema:

  Puntuación fase de grupos (ver routes/mundial.py::admin_resultado):
      3 pts  → marcador exacto
      1 pt   → acierta ganador/empate (sin marcador exacto)
      0 pts  → falla

  Puntuación fase eliminatoria (ver routes/mundial.py::admin_resultado_eli):
      4 pts  → marcador exacto en un empate real + acierta el ganador de penales
      3 pts  → marcador exacto (sin empate, o empate sin acertar penales)
      1 pt   → acierta ganador/empate (sin marcador exacto)
      0 pts  → falla

  Orden del ranking (ver routes/mundial.py::ranking_mundial / api_mundial_datos):
      Puntos DESC → Penales DESC → Exactos DESC → Ganadores DESC
      (en la categoría "grupos" no existen penales, por lo que ese criterio
      se omite y el orden queda Puntos → Exactos → Ganadores)

────────────────────────────────────────────────────────────────────
QUÉ CALCULA ESTE MOTOR
────────────────────────────────────────────────────────────────────
Para cada usuario, la probabilidad de terminar Campeón (1°), Top 2 y Top 3
del RANKING (no del Mundial), usando:

  - Los puntos/penales/exactos/ganadores YA obtenidos (partidos bloqueados).
  - Los pronósticos que cada usuario YA registró para partidos pendientes.
  - Los partidos que aún faltan por jugar y para los que existe un pronóstico
    guardado (en eliminatorias, solo los que ya tienen equipos definidos:
    sin equipos definidos no existe pronóstico posible todavía).

Este motor NO intenta predecir quién gana el Mundial. Para "repartir" los
puntos pendientes entre los pronósticos ya guardados, cada partido pendiente
se resuelve, en cada simulación, mediante un sorteo NEUTRO y simétrico
(1/3 victoria local, 1/3 empate, 1/3 victoria visitante — ninguna selección
tiene ventaja sobre otra). El resultado sorteado es solamente el mecanismo
para decidir a qué pronóstico le tocan los puntos; nunca es una predicción
futbolística. No se usa ningún modelo de fuerza de selecciones, cuotas ni
distribución de Poisson.

La búsqueda se resuelve por simulación Monte Carlo de alta precisión
(por defecto 1.000.000 de simulaciones) usando numpy si está disponible.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("ranking_probabilidades")

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover - entorno sin numpy instalado
    _HAS_NUMPY = False

N_SIMULACIONES_DEFAULT = 1_000_000
N_SIMULACIONES_MIN     = 1_000_000
N_SIMULACIONES_MAX     = 3_000_000
# Techo de "trabajo" (partidos_pendientes * simulaciones) para no colgar el
# request si al inicio del torneo hay decenas de partidos pendientes a la vez.
_TRABAJO_MAX = 45_000_000

TOTAL_PARTIDOS = {"global": 104, "grupos": 72, "eli": 32}

_CANDIDATOS_BASE = {
    # Marcadores "semilla" para que siempre exista variedad dentro de cada
    # categoría (L=local gana, D=empate, V=visitante gana), incluso si nadie
    # pronosticó ese resultado. Se completan con los pronósticos reales.
    "L": [(1, 0), (2, 0), (2, 1), (3, 0)],
    "D": [(0, 0), (1, 1), (2, 2), (3, 3)],
    "V": [(0, 1), (0, 2), (1, 2), (0, 3)],
}


def _categoria(gl: int, gv: int) -> str:
    if gl > gv:
        return "L"
    if gl < gv:
        return "V"
    return "D"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ────────────────────────────────────────────────────────────────
# 1) LECTURA DE DATOS (solo lectura, ninguna escritura a la BD)
# ────────────────────────────────────────────────────────────────

def _cargar_usuarios(con) -> dict[int, str]:
    rows = con.execute("SELECT id, nombre FROM usuarios ORDER BY id").fetchall()
    return {int(r["id"]): r["nombre"] for r in rows}


def _cargar_base(con, categoria: str) -> dict[int, dict]:
    """
    Puntos/penales/exactos/ganadores YA obtenidos (partidos bloqueados),
    replicando exactamente el cálculo de /api/ranking_mundial.
    """
    if categoria == "grupos":
        sql = """
            SELECT u.id, u.nombre,
                   COALESCE(g.puntos,0)    AS puntos,
                   0                        AS penales,
                   COALESCE(g.exactos,0)   AS exactos,
                   COALESCE(g.ganadores,0) AS ganadores
            FROM usuarios u
            LEFT JOIN (
                SELECT pr.usuario_id, SUM(pr.puntos) puntos,
                       COUNT(CASE WHEN pr.puntos=3 THEN 1 END) exactos,
                       COUNT(CASE WHEN pr.puntos=1 THEN 1 END) ganadores
                FROM pronosticos pr
                JOIN partidos_mundial pm ON pm.id=pr.partido_id AND pm.bloqueado=1
                GROUP BY pr.usuario_id
            ) g ON g.usuario_id=u.id
        """
    elif categoria == "eli":
        sql = """
            SELECT u.id, u.nombre,
                   COALESCE(e.puntos,0)    AS puntos,
                   COALESCE(e.penales,0)   AS penales,
                   COALESCE(e.exactos,0)   AS exactos,
                   COALESCE(e.ganadores,0) AS ganadores
            FROM usuarios u
            LEFT JOIN (
                SELECT pr.usuario_id, SUM(pr.puntos) puntos,
                       COUNT(CASE WHEN pr.puntos IN (3,4) THEN 1 END) exactos,
                       COUNT(CASE WHEN pr.puntos=1 THEN 1 END) ganadores,
                       COUNT(CASE WHEN pr.puntos=4 THEN 1 END) penales
                FROM pronosticos_eli pr
                JOIN partidos_eliminacion pe ON pe.id=pr.partido_id AND pe.bloqueado=1
                GROUP BY pr.usuario_id
            ) e ON e.usuario_id=u.id
        """
    else:  # global
        sql = """
            SELECT u.id, u.nombre,
                   COALESCE(g.puntos,0)+COALESCE(e.puntos,0)       AS puntos,
                   COALESCE(g.penales,0)+COALESCE(e.penales,0)     AS penales,
                   COALESCE(g.exactos,0)+COALESCE(e.exactos,0)     AS exactos,
                   COALESCE(g.ganadores,0)+COALESCE(e.ganadores,0) AS ganadores
            FROM usuarios u
            LEFT JOIN (
                SELECT pr.usuario_id, SUM(pr.puntos) puntos,
                       COUNT(CASE WHEN pr.puntos=3 THEN 1 END) exactos,
                       COUNT(CASE WHEN pr.puntos=1 THEN 1 END) ganadores,
                       0 AS penales
                FROM pronosticos pr
                JOIN partidos_mundial pm ON pm.id=pr.partido_id AND pm.bloqueado=1
                GROUP BY pr.usuario_id
            ) g ON g.usuario_id=u.id
            LEFT JOIN (
                SELECT pr.usuario_id, SUM(pr.puntos) puntos,
                       COUNT(CASE WHEN pr.puntos IN (3,4) THEN 1 END) exactos,
                       COUNT(CASE WHEN pr.puntos=1 THEN 1 END) ganadores,
                       COUNT(CASE WHEN pr.puntos=4 THEN 1 END) penales
                FROM pronosticos_eli pr
                JOIN partidos_eliminacion pe ON pe.id=pr.partido_id AND pe.bloqueado=1
                GROUP BY pr.usuario_id
            ) e ON e.usuario_id=u.id
        """
    rows = con.execute(sql).fetchall()
    out = {}
    for r in rows:
        out[int(r["id"])] = {
            "puntos": int(r["puntos"] or 0),
            "penales": int(r["penales"] or 0),
            "exactos": int(r["exactos"] or 0),
            "ganadores": int(r["ganadores"] or 0),
        }
    return out


def _cargar_pendientes_grupo(con) -> list[dict]:
    """Partidos de grupos aún sin resultado + pronósticos ya guardados."""
    partidos = con.execute(
        "SELECT id FROM partidos_mundial WHERE bloqueado=0 OR goles_local IS NULL "
        "ORDER BY id"
    ).fetchall()
    por_partido: dict[int, dict[int, tuple[int, int]]] = {int(p["id"]): {} for p in partidos}
    if not por_partido:
        return []

    pronos = con.execute("""
        SELECT pr.usuario_id, pr.partido_id, pr.goles_local, pr.goles_visitante
        FROM pronosticos pr
        JOIN partidos_mundial pm ON pm.id = pr.partido_id
        WHERE pm.bloqueado=0 OR pm.goles_local IS NULL
    """).fetchall()
    for p in pronos:
        pid = int(p["partido_id"])
        if pid not in por_partido:
            continue
        por_partido[pid][int(p["usuario_id"])] = (
            int(p["goles_local"]), int(p["goles_visitante"])
        )
    return [{"id": pid, "eli": False, "pronosticos": pronos_pid}
            for pid, pronos_pid in por_partido.items()]


def _cargar_pendientes_eli(con) -> list[dict]:
    """
    Partidos eliminatorios aún sin resultado, CON equipos ya definidos
    (solo esos admiten pronóstico), + pronósticos ya guardados.
    """
    partidos = con.execute("""
        SELECT id, eq_local, eq_visit FROM partidos_eliminacion
        WHERE (bloqueado=0 OR goles_local IS NULL)
        AND eq_local IS NOT NULL AND eq_visit IS NOT NULL
        AND eq_local <> '' AND eq_visit <> ''
        ORDER BY id
    """).fetchall()
    if not partidos:
        return []
    eq_map = {int(p["id"]): (p["eq_local"], p["eq_visit"]) for p in partidos}
    por_partido: dict[int, dict[int, tuple]] = {pid: {} for pid in eq_map}

    pronos = con.execute("""
        SELECT pr.usuario_id, pr.partido_id, pr.goles_local, pr.goles_visit, pr.penales_ganador
        FROM pronosticos_eli pr
        JOIN partidos_eliminacion pe ON pe.id = pr.partido_id
        WHERE (pe.bloqueado=0 OR pe.goles_local IS NULL)
        AND pe.eq_local IS NOT NULL AND pe.eq_visit IS NOT NULL
        AND pe.eq_local <> '' AND pe.eq_visit <> ''
    """).fetchall()
    for p in pronos:
        pid = int(p["partido_id"])
        if pid not in por_partido:
            continue
        eq_local, eq_visit = eq_map[pid]
        pen = p["penales_ganador"]
        if pen == eq_local:
            pen_side = "L"
        elif pen == eq_visit:
            pen_side = "V"
        else:
            pen_side = None
        por_partido[pid][int(p["usuario_id"])] = (
            int(p["goles_local"]), int(p["goles_visit"]), pen_side
        )
    return [{"id": pid, "eli": True, "pronosticos": pronos_pid}
            for pid, pronos_pid in por_partido.items()]


# ────────────────────────────────────────────────────────────────
# 2) CONSTRUCCIÓN DE CANDIDATOS DE RESULTADO POR PARTIDO
# ────────────────────────────────────────────────────────────────

def _candidatos_partido(pronosticos: dict) -> list[tuple[float, int, int, str]]:
    """
    Devuelve lista [(peso, gl, gv, categoria), ...] con:
      - probabilidad total 1/3 para cada categoría (L, D, V) — sorteo neutro,
        sin ventaja para ningún equipo/selección.
      - dentro de cada categoría, todos los candidatos (marcadores base +
        marcadores realmente pronosticados por los usuarios) tienen el mismo
        peso, para que cualquier pronóstico ya guardado tenga una
        probabilidad real de resultar exacto.
    """
    sets = {"L": set(_CANDIDATOS_BASE["L"]), "D": set(_CANDIDATOS_BASE["D"]), "V": set(_CANDIDATOS_BASE["V"])}
    for pron in pronosticos.values():
        gl, gv = pron[0], pron[1]
        sets[_categoria(gl, gv)].add((gl, gv))

    candidatos = []
    for cat, marcadores in sets.items():
        peso_cat = 1.0 / 3.0
        peso_cada = peso_cat / len(marcadores)
        for (gl, gv) in sorted(marcadores):
            candidatos.append((peso_cada, gl, gv, cat))
    return candidatos


def _puntos_grupo(pred: tuple[int, int], cand: tuple[int, int, str]) -> tuple[int, int, int]:
    """Devuelve (puntos, delta_exactos, delta_ganadores) para fase de grupos."""
    gl_p, gv_p = pred
    gl_c, gv_c, cat_c = cand
    if gl_p == gl_c and gv_p == gv_c:
        return 3, 1, 0
    if _categoria(gl_p, gv_p) == cat_c:
        return 1, 0, 1
    return 0, 0, 0


def _puntos_eli(pred: tuple[int, int, str], cand: tuple[int, int, str]) -> tuple[int, int, int, bool]:
    """
    Devuelve (puntos_base, delta_exactos, delta_ganadores, depende_de_penales).
    Si depende_de_penales es True, el simulador debe sumar +1 punto y +1
    penal extra cuando el lado de penales sorteado coincide con pred[2].
    """
    gl_p, gv_p, _pen_p = pred
    gl_c, gv_c, cat_c = cand
    if gl_p == gl_c and gv_p == gv_c:
        if cat_c == "D":
            return 3, 1, 0, True    # +1 extra si acierta también el penal
        return 3, 1, 0, False
    if _categoria(gl_p, gv_p) == cat_c:
        return 1, 0, 1, False
    return 0, 0, 0, False


# ────────────────────────────────────────────────────────────────
# 3) MÁXIMO TEÓRICO (con los pronósticos ya hechos)
# ────────────────────────────────────────────────────────────────

def _max_extra_por_partido(pronosticos: dict, eli: bool) -> dict[int, int]:
    """Puntos máximos que cada usuario podría sumar en ESTE partido pendiente
    (asumiendo que el resultado real coincide exactamente con su pronóstico
    y, en eliminatorias, que también acierta el ganador de penales)."""
    extra = {}
    for uid, pred in pronosticos.items():
        if eli:
            extra[uid] = 4 if pred[2] is not None else 3
        else:
            extra[uid] = 3
    return extra


# ────────────────────────────────────────────────────────────────
# 4) SIMULACIÓN MONTE CARLO
# ────────────────────────────────────────────────────────────────

def _simular_numpy(ids, base, pendientes, n_sim, seed=None):
    U = len(ids)
    idx_of = {uid: i for i, uid in enumerate(ids)}
    rng = np.random.default_rng(seed)

    pts = np.zeros((U, n_sim), dtype=np.int32)
    pen = np.zeros((U, n_sim), dtype=np.int16)
    exa = np.zeros((U, n_sim), dtype=np.int16)
    gan = np.zeros((U, n_sim), dtype=np.int16)
    for uid, i in idx_of.items():
        b = base.get(uid, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})
        pts[i, :] = b["puntos"]
        pen[i, :] = b["penales"]
        exa[i, :] = b["exactos"]
        gan[i, :] = b["ganadores"]

    for match in pendientes:
        pronosticos = match["pronosticos"]
        if not pronosticos:
            continue
        candidatos = _candidatos_partido(pronosticos)
        K = len(candidatos)
        pesos = np.array([c[0] for c in candidatos], dtype=np.float64)
        pesos = pesos / pesos.sum()
        idx_sorteo = rng.choice(K, size=n_sim, p=pesos)

        necesita_pen = match["eli"] and any(c[3] == "D" for c in candidatos)
        pen_sorteo = None
        if necesita_pen:
            # 0 = gana local por penales, 1 = gana visitante por penales
            pen_sorteo = rng.integers(0, 2, size=n_sim)

        for uid, pred in pronosticos.items():
            i = idx_of.get(uid)
            if i is None:
                continue
            base_pts = np.empty(K, dtype=np.int32)
            d_exa = np.empty(K, dtype=np.int16)
            d_gan = np.empty(K, dtype=np.int16)
            d_pen = np.zeros(K, dtype=bool)
            for k, (_w, gl_c, gv_c, cat_c) in enumerate(candidatos):
                if match["eli"]:
                    p_, e_, g_, dep = _puntos_eli(pred, (gl_c, gv_c, cat_c))
                else:
                    p_, e_, g_ = _puntos_grupo((pred[0], pred[1]), (gl_c, gv_c, cat_c))
                    dep = False
                base_pts[k] = p_
                d_exa[k] = e_
                d_gan[k] = g_
                d_pen[k] = dep

            pts_delta = base_pts[idx_sorteo]
            exa_delta = d_exa[idx_sorteo]
            gan_delta = d_gan[idx_sorteo]
            pts[i] += pts_delta
            exa[i] += exa_delta
            gan[i] += gan_delta

            if match["eli"] and pred[2] is not None:
                depende_mask = d_pen[idx_sorteo]
                if depende_mask.any():
                    lado_usuario = 0 if pred[2] == "L" else 1
                    acierto_pen = depende_mask & (pen_sorteo == lado_usuario)
                    pts[i] += acierto_pen.astype(pts.dtype)
                    pen[i] += acierto_pen.astype(pen.dtype)

    return pts, pen, exa, gan


def _simular_python(ids, base, pendientes, n_sim, seed=None):
    """Fallback puro-Python (sin numpy) — usa muchas menos simulaciones."""
    import random as _random
    rnd = _random.Random(seed)
    U = len(ids)
    idx_of = {uid: i for i, uid in enumerate(ids)}
    pts = [[0] * n_sim for _ in range(U)]
    pen = [[0] * n_sim for _ in range(U)]
    exa = [[0] * n_sim for _ in range(U)]
    gan = [[0] * n_sim for _ in range(U)]
    for uid, i in idx_of.items():
        b = base.get(uid, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})
        for s in range(n_sim):
            pts[i][s] = b["puntos"]; pen[i][s] = b["penales"]
            exa[i][s] = b["exactos"]; gan[i][s] = b["ganadores"]

    for match in pendientes:
        pronosticos = match["pronosticos"]
        if not pronosticos:
            continue
        candidatos = _candidatos_partido(pronosticos)
        pesos = [c[0] for c in candidatos]
        for s in range(n_sim):
            cand = rnd.choices(candidatos, weights=pesos, k=1)[0]
            _w, gl_c, gv_c, cat_c = cand
            pen_lado = None
            if match["eli"] and cat_c == "D":
                pen_lado = rnd.choice(["L", "V"])
            for uid, pred in pronosticos.items():
                i = idx_of.get(uid)
                if i is None:
                    continue
                if match["eli"]:
                    p_, e_, g_, dep = _puntos_eli(pred, (gl_c, gv_c, cat_c))
                    if dep and pred[2] is not None and pen_lado == pred[2]:
                        p_ += 1
                        pen[i][s] += 1
                else:
                    p_, e_, g_ = _puntos_grupo((pred[0], pred[1]), (gl_c, gv_c, cat_c))
                pts[i][s] += p_
                exa[i][s] += e_
                gan[i][s] += g_
    return pts, pen, exa, gan


# ────────────────────────────────────────────────────────────────
# 5) CÁLCULO DE POSICIONES / PROBABILIDADES
# ────────────────────────────────────────────────────────────────

def _posiciones_numpy(pts, pen, exa, gan, categoria):
    """Calcula, por simulación (columna), la posición RANK() de cada usuario
    según el criterio real de desempate: Puntos → Penales → Exactos → Ganadores
    (en 'grupos' no hay penales)."""
    U = pts.shape[0]
    if categoria == "grupos":
        score = (pts.astype(np.int64) * 1_000_000) + (exa.astype(np.int64) * 1_000) + gan.astype(np.int64)
    else:
        score = (((pts.astype(np.int64) * 1000) + pen.astype(np.int64)) * 1000 + exa.astype(np.int64)) * 1000 + gan.astype(np.int64)

    posicion = np.ones_like(score, dtype=np.int32)
    for i in range(U):
        mejor_que_i = (score > score[i:i + 1, :]).sum(axis=0)
        posicion[i, :] = mejor_que_i + 1
    return posicion


def _posiciones_python(pts, pen, exa, gan, categoria, n_sim):
    U = len(pts)
    posicion = [[1] * n_sim for _ in range(U)]

    def score_of(i, s):
        if categoria == "grupos":
            return (pts[i][s], exa[i][s], gan[i][s])
        return (pts[i][s], pen[i][s], exa[i][s], gan[i][s])

    for s in range(n_sim):
        scores = [score_of(i, s) for i in range(U)]
        for i in range(U):
            mejor = sum(1 for j in range(U) if scores[j] > scores[i])
            posicion[i][s] = mejor + 1
    return posicion


# ────────────────────────────────────────────────────────────────
# 6) ORQUESTADOR PRINCIPAL
# ────────────────────────────────────────────────────────────────

def _posicion_actual(base: dict[int, dict], categoria: str) -> dict[int, int]:
    """Posición actual (RANK, ties comparten posición) según datos ya bloqueados."""
    def key(u):
        b = base.get(u, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})
        if categoria == "grupos":
            return (-b["puntos"], -b["exactos"], -b["ganadores"])
        return (-b["puntos"], -b["penales"], -b["exactos"], -b["ganadores"])

    ordenado = sorted(base.keys(), key=key)
    posiciones = {}
    prev_key = None
    prev_pos = 0
    for i, uid in enumerate(ordenado):
        k = key(uid)
        if k != prev_key:
            prev_pos = i + 1
            prev_key = k
        posiciones[uid] = prev_pos
    return posiciones


def _desempate_vs_lider(base: dict, uid: int, lider_id: int, categoria: str):
    """Explica, con los datos YA obtenidos (sin simular), si un usuario
    empatado en puntos con el líder ganaría o perdería el desempate hoy."""
    u = base.get(uid, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})
    l = base.get(lider_id, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})
    if u["puntos"] != l["puntos"] or uid == lider_id:
        return False, None

    criterios = (
        [("exactos", u["exactos"], l["exactos"]), ("ganadores", u["ganadores"], l["ganadores"])]
        if categoria == "grupos" else
        [("penales", u["penales"], l["penales"]),
         ("exactos", u["exactos"], l["exactos"]),
         ("ganadores", u["ganadores"], l["ganadores"])]
    )
    for nombre, vu, vl in criterios:
        if vu > vl:
            return True, {"resultado": "gana", "criterio": nombre, "usuario": vu, "lider": vl}
        if vu < vl:
            return True, {"resultado": "pierde", "criterio": nombre, "usuario": vu, "lider": vl}
    return True, {"resultado": "empate_total", "criterio": None, "usuario": None, "lider": None}


def calcular_probabilidades_ranking(con, categoria: str = "global", n_sim_solicitado: int = N_SIMULACIONES_DEFAULT) -> dict:
    if categoria not in ("global", "grupos", "eli"):
        categoria = "global"

    usuarios = _cargar_usuarios(con)
    base = _cargar_base(con, categoria)

    if categoria == "grupos":
        pendientes = _cargar_pendientes_grupo(con)
    elif categoria == "eli":
        pendientes = _cargar_pendientes_eli(con)
    else:
        pendientes = _cargar_pendientes_grupo(con) + _cargar_pendientes_eli(con)

    ids = sorted(usuarios.keys())
    U = max(len(ids), 1)

    n_sim = max(N_SIMULACIONES_MIN, min(int(n_sim_solicitado or N_SIMULACIONES_DEFAULT), N_SIMULACIONES_MAX))
    n_partidos = max(len(pendientes), 1)
    ajustado = False
    if n_sim * n_partidos > _TRABAJO_MAX:
        n_sim_ajustado = max(200_000, _TRABAJO_MAX // n_partidos)
        if n_sim_ajustado < n_sim:
            n_sim = n_sim_ajustado
            ajustado = True

    if _HAS_NUMPY:
        pts, pen, exa, gan = _simular_numpy(ids, base, pendientes, n_sim)
        posiciones = _posiciones_numpy(pts, pen, exa, gan, categoria)
        prob_campeon = {}
        prob_top2 = {}
        prob_top3 = {}
        for i, uid in enumerate(ids):
            fila = posiciones[i]
            prob_campeon[uid] = float((fila == 1).mean())
            prob_top2[uid] = float((fila <= 2).mean())
            prob_top3[uid] = float((fila <= 3).mean())
    else:
        logger.warning("numpy no disponible: usando fallback puro-Python con muchas menos simulaciones")
        n_sim = min(n_sim, 5000)
        pts, pen, exa, gan = _simular_python(ids, base, pendientes, n_sim)
        posiciones = _posiciones_python(pts, pen, exa, gan, categoria, n_sim)
        prob_campeon = {}
        prob_top2 = {}
        prob_top3 = {}
        for i, uid in enumerate(ids):
            fila = posiciones[i]
            prob_campeon[uid] = sum(1 for x in fila if x == 1) / n_sim
            prob_top2[uid] = sum(1 for x in fila if x <= 2) / n_sim
            prob_top3[uid] = sum(1 for x in fila if x <= 3) / n_sim

    pos_actual = _posicion_actual(base, categoria)
    lider_id = min(base.keys(), key=lambda u: pos_actual.get(u, 999)) if base else None

    max_puntos_actual = max((b["puntos"] for b in base.values()), default=0)

    salida_usuarios = []
    for uid in ids:
        b = base.get(uid, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})

        extra_max = 0
        for match in pendientes:
            pred = match["pronosticos"].get(uid)
            if pred is None:
                continue
            extra_max += (4 if (match["eli"] and pred[2] is not None) else 3)
        max_teorico = b["puntos"] + extra_max

        max_otros = max(
            (base[u]["puntos"] for u in base if u != uid), default=0
        )
        puede_ser_campeon = max_teorico >= max_otros

        depende, detalle = _desempate_vs_lider(base, uid, lider_id, categoria) if lider_id is not None else (False, None)

        pc = round(prob_campeon.get(uid, 0.0) * 100, 2)
        p2 = round(prob_top2.get(uid, 0.0) * 100, 2)
        p3 = round(prob_top3.get(uid, 0.0) * 100, 2)

        salida_usuarios.append({
            "id": uid,
            "nombre": usuarios.get(uid, "?"),
            "puntos_actuales": b["puntos"],
            "penales_actuales": b["penales"],
            "exactos_actuales": b["exactos"],
            "ganadores_actuales": b["ganadores"],
            "posicion_actual": pos_actual.get(uid),
            "max_teorico_puntos": max_teorico,
            "puede_ser_campeon": bool(puede_ser_campeon),
            "prob_campeon": pc,
            "prob_top2": p2,
            "prob_top3": p3,
            "prob_fuera_podio": round(max(0.0, 100.0 - p3), 2),
            "depende_desempate_con_lider": bool(depende),
            "desempate_detalle": detalle,
        })

    salida_usuarios.sort(key=lambda r: (r["posicion_actual"] if r["posicion_actual"] is not None else 999))

    return {
        "generado_en": _now_iso(),
        "categoria": categoria,
        "simulaciones_realizadas": n_sim,
        "simulaciones_ajustadas": ajustado,
        "motor": "numpy" if _HAS_NUMPY else "python",
        "total_partidos_categoria": TOTAL_PARTIDOS.get(categoria, 104),
        "partidos_pendientes_con_pronosticos": len([m for m in pendientes if m["pronosticos"]]),
        "partidos_pendientes_totales": len(pendientes),
        "metodologia": (
            "Cada partido pendiente se resuelve por sorteo neutro 1/3-1/3-1/3 "
            "(victoria local / empate / victoria visitante) únicamente para repartir "
            "los puntos entre los pronósticos ya guardados. No estima fuerza de "
            "selecciones ni usa modelos de resultados de fútbol."
        ),
        "usuarios": salida_usuarios,
    }
