"""
services/ranking_probabilidades.py
====================================================================
Motor INDEPENDIENTE de simulación del RANKING DE USUARIOS del Mundial 2026.

Versión corregida:
- Cálculo de máximo teórico basado en todos los partidos restantes del torneo.
- Lógica de eliminación matemática (puede_ser_campeon) corregida.
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

N_SIMULACIONES_DEFAULT = 30_000
N_SIMULACIONES_MIN     = 5_000
N_SIMULACIONES_MAX     = 100_000
_TRABAJO_MAX = 2_000_000

TOTAL_PARTIDOS = {"global": 104, "grupos": 72, "eli": 32}

_CANDIDATOS_BASE = {
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


def _conteo_partidos_futuros(con, categoria: str) -> dict[str, dict[str, int]]:
    """
    Cuenta TODOS los partidos que faltan por jugar en el torneo,
    independientemente de si tienen equipos definidos o no.
    """
    res = {"grupos": {"total": 0, "con_pronostico_posible": 0}, "eli": {"total": 0, "con_pronostico_posible": 0}}
    
    if categoria in ("global", "grupos"):
        # Grupos: bloqueado=0 o sin goles_local
        # Solo contamos partidos que NO tienen resultado registrado (goles_local IS NULL).
        # Esto garantiza que los partidos ya jugados sin pronóstico no se vuelvan a sumar.
        c_grupos_total = con.execute(
            "SELECT COUNT(*) as c FROM partidos_mundial WHERE goles_local IS NULL"
        ).fetchone()
        res["grupos"]["total"] = int(c_grupos_total["c"] or 0)
        # Para grupos, todos los partidos pendientes admiten pronóstico
        res["grupos"]["con_pronostico_posible"] = res["grupos"]["total"]
        
    if categoria in ("global", "eli"):
        # Eliminatorias: bloqueado=0 o sin goles_local
        # Solo contamos partidos que NO tienen resultado registrado (goles_local IS NULL).
        c_eli_total = con.execute(
            "SELECT COUNT(*) as c FROM partidos_eliminacion WHERE goles_local IS NULL"
        ).fetchone()
        res["eli"]["total"] = int(c_eli_total["c"] or 0)
        # Eliminatorias con pronóstico posible (equipos definidos)
        c_eli_con_pron = con.execute("""
            SELECT COUNT(*) as c FROM partidos_eliminacion
            WHERE (bloqueado=0 OR goles_local IS NULL)
            AND eq_local IS NOT NULL AND eq_visit IS NOT NULL
            AND eq_local <> '' AND eq_visit <> ''
        """).fetchone()
        res["eli"]["con_pronostico_posible"] = int(c_eli_con_pron["c"] or 0)
        
    return res


# ────────────────────────────────────────────────────────────────
# 2) CONSTRUCCIÓN DE CANDIDATOS DE RESULTADO POR PARTIDO
# ────────────────────────────────────────────────────────────────

def _candidatos_partido(pronosticos: dict) -> list[tuple[float, int, int, str]]:
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
    gl_p, gv_p = pred
    gl_c, gv_c, cat_c = cand
    if gl_p == gl_c and gv_p == gv_c:
        return 3, 1, 0
    if _categoria(gl_p, gv_p) == cat_c:
        return 1, 0, 1
    return 0, 0, 0


def _puntos_eli(pred: tuple[int, int, str], cand: tuple[int, int, str]) -> tuple[int, int, int, bool]:
    gl_p, gv_p, _pen_p = pred
    gl_c, gv_c, cat_c = cand
    if gl_p == gl_c and gv_p == gv_c:
        if cat_c == "D":
            return 3, 1, 0, True
        return 3, 1, 0, False
    if _categoria(gl_p, gv_p) == cat_c:
        return 1, 0, 1, False
    return 0, 0, 0, False


# ────────────────────────────────────────────────────────────────
# 4) SIMULACIÓN (Monte Carlo)
# ────────────────────────────────────────────────────────────────

def _simular_numpy(ids, base, pendientes, n_sim, rng=None):
    if rng is None:
        rng = np.random.default_rng()
    U = len(ids)
    P = len(pendientes)
    pts = np.zeros((U, n_sim), dtype=np.int32)
    pen = np.zeros((U, n_sim), dtype=np.int32)
    exa = np.zeros((U, n_sim), dtype=np.int32)
    gan = np.zeros((U, n_sim), dtype=np.int32)

    for i, uid in enumerate(ids):
        b = base.get(uid, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})
        pts[i, :] = b["puntos"]
        pen[i, :] = b["penales"]
        exa[i, :] = b["exactos"]
        gan[i, :] = b["ganadores"]

    for match in pendientes:
        candidatos = _candidatos_partido(match["pronosticos"])
        pesos = [c[0] for c in candidatos]
        idx_res = rng.choice(len(candidatos), size=n_sim, p=pesos)
        
        is_eli = match["eli"]
        idx_pen = None
        if is_eli:
            idx_pen = rng.integers(0, 2, size=n_sim)

        for i, uid in enumerate(ids):
            pred = match["pronosticos"].get(uid)
            if pred is None:
                continue
            
            for r_idx in range(len(candidatos)):
                mask = (idx_res == r_idx)
                if not np.any(mask):
                    continue
                
                cand = candidatos[r_idx][1:]
                if is_eli:
                    p_base, de, dg, dep_pen = _puntos_eli(pred, cand)
                    pts[i, mask] += p_base
                    exa[i, mask] += de
                    gan[i, mask] += dg
                    if dep_pen:
                        p_side = pred[2]
                        if p_side == "L":
                            p_mask = (idx_pen[mask] == 0)
                            pts[i, np.where(mask)[0][p_mask]] += 1
                            pen[i, np.where(mask)[0][p_mask]] += 1
                        elif p_side == "V":
                            p_mask = (idx_pen[mask] == 1)
                            pts[i, np.where(mask)[0][p_mask]] += 1
                            pen[i, np.where(mask)[0][p_mask]] += 1
                else:
                    p_base, de, dg = _puntos_grupo(pred, cand)
                    pts[i, mask] += p_base
                    exa[i, mask] += de
                    gan[i, mask] += dg
                    
    return pts, pen, exa, gan


def _posiciones_numpy(pts, pen, exa, gan, categoria):
    U, n_sim = pts.shape
    scores = []
    if categoria == "grupos":
        # Puntos -> Exactos -> Ganadores
        scores = [pts, exa, gan]
    else:
        # Puntos -> Penales -> Exactos -> Ganadores
        scores = [pts, pen, exa, gan]

    posiciones = np.ones((U, n_sim), dtype=np.int32)
    for i in range(U):
        better_mask = np.zeros(n_sim, dtype=bool)
        for s_idx, score_mat in enumerate(scores):
            # Si en este criterio ya es mejor, no hace falta mirar los siguientes
            is_better = (score_mat > score_mat[i, :])
            is_equal = (score_mat == score_mat[i, :])
            
            # Alguien es mejor si era mejor en criterios previos O (era igual y es mejor en este)
            # Pero como iteramos, vamos construyendo la máscara de "quién sigue siendo candidato a ser mejor"
            if s_idx == 0:
                better_mask = is_better
                equal_mask = is_equal
            else:
                better_mask = better_mask | (equal_mask & is_better)
                equal_mask = equal_mask & is_equal
        
        # Contar cuántos usuarios j tienen better_mask == True para cada simulación
        # Pero better_mask es para un usuario i fijo vs todos los j. 
        # Hay que hacerlo eficiente.
    
    # Versión vectorizada real de posiciones:
    # Para cada simulación, ordenar usuarios.
    posiciones = np.zeros((U, n_sim), dtype=np.int32)
    for s in range(n_sim):
        if categoria == "grupos":
            # Usamos lexsort (ordena por la última clave primero)
            # Queremos DESC, lexsort es ASC, así que negamos.
            idx = np.lexsort((-gan[:, s], -exa[:, s], -pts[:, s]))
        else:
            idx = np.lexsort((-gan[:, s], -exa[:, s], -pen[:, s], -pts[:, s]))
        
        # Ranking con empates (mismo score = misma posición)
        rank = 1
        for j in range(U):
            if j > 0:
                curr = idx[j]
                prev = idx[j-1]
                if categoria == "grupos":
                    same = (pts[curr, s] == pts[prev, s] and exa[curr, s] == exa[prev, s] and gan[curr, s] == gan[prev, s])
                else:
                    same = (pts[curr, s] == pts[prev, s] and pen[curr, s] == pen[prev, s] and exa[curr, s] == exa[prev, s] and gan[curr, s] == gan[prev, s])
                if not same:
                    rank = j + 1
            posiciones[idx[j], s] = rank
    return posiciones


def _simular_y_contar_numpy(ids, base, pendientes, n_sim, categoria):
    U = len(ids)
    campeon_count = np.zeros(U, dtype=np.int64)
    top2_count = np.zeros(U, dtype=np.int64)
    top3_count = np.zeros(U, dtype=np.int64)

    rng = np.random.default_rng()
    chunk_size = 5000
    restante = n_sim
    while restante > 0:
        n_chunk = min(chunk_size, restante)
        pts, pen, exa, gan = _simular_numpy(ids, base, pendientes, n_chunk, rng=rng)
        posiciones_chunk = _posiciones_numpy(pts, pen, exa, gan, categoria)

        campeon_count += (posiciones_chunk == 1).sum(axis=1)
        top2_count += (posiciones_chunk <= 2).sum(axis=1)
        top3_count += (posiciones_chunk <= 3).sum(axis=1)

        del pts, pen, exa, gan, posiciones_chunk
        restante -= n_chunk

    prob_campeon = {uid: float(campeon_count[i] / n_sim) for i, uid in enumerate(ids)}
    prob_top2 = {uid: float(top2_count[i] / n_sim) for i, uid in enumerate(ids)}
    prob_top3 = {uid: float(top3_count[i] / n_sim) for i, uid in enumerate(ids)}
    return prob_campeon, prob_top2, prob_top3


def _simular_python(ids, base, pendientes, n_sim):
    import random
    U = len(ids)
    pts = [[base.get(uid, {"puntos":0})["puntos"]] * n_sim for uid in ids]
    pen = [[base.get(uid, {"penales":0})["penales"]] * n_sim for uid in ids]
    exa = [[base.get(uid, {"exactos":0})["exactos"]] * n_sim for uid in ids]
    gan = [[base.get(uid, {"ganadores":0})["ganadores"]] * n_sim for uid in ids]

    for match in pendientes:
        candidatos = _candidatos_partido(match["pronosticos"])
        pesos = [c[0] for c in candidatos]
        is_eli = match["eli"]
        
        for s in range(n_sim):
            res = random.choices(candidatos, weights=pesos, k=1)[0]
            cand = res[1:]
            p_side_sorteo = random.choice(["L", "V"]) if is_eli else None
            
            for i, uid in enumerate(ids):
                pred = match["pronosticos"].get(uid)
                if pred is None: continue
                
                if is_eli:
                    p_base, de, dg, dep_pen = _puntos_eli(pred, cand)
                    pts[i][s] += p_base
                    exa[i][s] += de
                    gan[i][s] += dg
                    if dep_pen and pred[2] == p_side_sorteo:
                        pts[i][s] += 1
                        pen[i][s] += 1
                else:
                    p_base, de, dg = _puntos_grupo(pred, cand)
                    pts[i][s] += p_base
                    exa[i][s] += de
                    gan[i][s] += dg
    return pts, pen, exa, gan


def _posiciones_python(pts, pen, exa, gan, categoria, n_sim):
    U = len(pts)
    posicion = [[1] * n_sim for _ in range(U)]

    def score_of(i, s):
        if categoria == "grupos":
            return (pts[i][s], exa[i][s], gan[i][s])
        return (pts[i][s], pen[i][s], exa[i][s], gan[i][s])

    for s in range(n_sim):
        scores = [score_of(i, s) for i in range(U)]
        sorted_scores = sorted(set(scores), reverse=True)
        rank_map = {}
        curr_rank = 1
        for sc in sorted_scores:
            rank_map[sc] = curr_rank
            curr_rank += sum(1 for x in scores if x == sc)
            
        for i in range(U):
            posicion[i][s] = rank_map[scores[i]]
    return posicion


# ────────────────────────────────────────────────────────────────
# 6) ORQUESTADOR PRINCIPAL
# ────────────────────────────────────────────────────────────────

def _posicion_actual(base: dict[int, dict], categoria: str) -> dict[int, int]:
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
    
    # Partidos para la simulación (solo los que tienen pronósticos y equipos definidos)
    if categoria == "grupos":
        pendientes_sim = _cargar_pendientes_grupo(con)
    elif categoria == "eli":
        pendientes_sim = _cargar_pendientes_eli(con)
    else:
        pendientes_sim = _cargar_pendientes_grupo(con) + _cargar_pendientes_eli(con)

    # Conteo de partidos totales restantes para el máximo teórico
    futuros = _conteo_partidos_futuros(con, categoria)
    
    ids = sorted(usuarios.keys())
    n_sim = max(N_SIMULACIONES_MIN, min(int(n_sim_solicitado or N_SIMULACIONES_DEFAULT), N_SIMULACIONES_MAX))
    n_partidos_sim = max(len(pendientes_sim), 1)
    ajustado = False
    if n_sim * n_partidos_sim > _TRABAJO_MAX:
        n_sim_ajustado = max(N_SIMULACIONES_MIN, _TRABAJO_MAX // n_partidos_sim)
        if n_sim_ajustado < n_sim:
            n_sim = n_sim_ajustado
            ajustado = True

    if _HAS_NUMPY:
        prob_campeon, prob_top2, prob_top3 = _simular_y_contar_numpy(
            ids, base, pendientes_sim, n_sim, categoria
        )
    else:
        n_sim = min(n_sim, 5000)
        pts, pen, exa, gan = _simular_python(ids, base, pendientes_sim, n_sim)
        posiciones = _posiciones_python(pts, pen, exa, gan, categoria, n_sim)
        prob_campeon = {uid: sum(1 for x in posiciones[i] if x == 1) / n_sim for i, uid in enumerate(ids)}
        prob_top2 = {uid: sum(1 for x in posiciones[i] if x <= 2) / n_sim for i, uid in enumerate(ids)}
        prob_top3 = {uid: sum(1 for x in posiciones[i] if x <= 3) / n_sim for i, uid in enumerate(ids)}

    pos_actual = _posicion_actual(base, categoria)
    lider_id = min(base.keys(), key=lambda u: pos_actual.get(u, 999)) if base else None

    # Mínimos puntos que el líder (o el mejor de los otros) va a tener.
    # Como el motor es neutro y no sabemos pronósticos futuros, el mínimo es lo que ya tienen.
    # Para una eliminación matemática rigurosa, comparamos mi Máximo vs Mínimo de los demás.
    
    salida_usuarios = []
    for uid in ids:
        b = base.get(uid, {"puntos": 0, "penales": 0, "exactos": 0, "ganadores": 0})

        # Cálculo del máximo teórico para el usuario `uid`:
        # Suma los puntos actuales, más los puntos máximos que puede obtener
        # de partidos que aún no se jugaron (goles_local IS NULL).
        # Se asume que el usuario puede pronosticar y acertar todos estos partidos.
        
        # Según la lógica de mundial.py, un partido está 'cerrado' cuando tiene resultado.
        # Mientras no tenga resultado (goles_local IS NULL), el usuario aún puede puntuar.
        
        max_teorico = b["puntos"] + (futuros["grupos"]["total"] * 3) + (futuros["eli"]["total"] * 4)

        # Lógica de `puede_ser_campeon`:
        # Un usuario puede ser campeón si su máximo teórico es mayor o igual
        # al máximo teórico de cualquier otro competidor. Esto requiere calcular
        # el máximo teórico para CADA usuario, no solo comparar con los puntos actuales del líder.
        # Para simplificar, y dado que el motor no simula pronósticos futuros de otros,
        # la condición mínima para no estar eliminado matemáticamente es que el máximo
        # teórico del usuario sea mayor o igual a los puntos actuales del líder.
        # Si se quisiera una comprobación más estricta, se necesitaría simular el máximo
        # teórico de cada rival, lo cual no es el alcance actual de esta función.
        
        # Para esta versión, mantenemos la lógica de comparar con el máximo actual de los otros
        # como una condición necesaria (aunque no suficiente) para no estar eliminado.
        max_otros_actual = max((base[u]["puntos"] for u in base if u != uid), default=0)
        puede_ser_campeon = max_teorico >= max_otros_actual

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
        "partidos_pendientes_con_pronosticos": len([m for m in pendientes_sim if m["pronosticos"]]),
        "partidos_pendientes_totales": futuros["grupos"] + futuros["eli"],
        "metodologia": (
            "Cada partido pendiente con pronóstico se resuelve por sorteo neutro 1/3-1/3-1/3. "
            "El máximo teórico considera los puntos actuales más los puntos máximos de todos los partidos "
            "que aún no tienen resultado registrado (asumiendo que el usuario los pronostica y acierta)."
        ),
        "usuarios": salida_usuarios,
    }
