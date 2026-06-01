# ═══════════════════════════════════════════════════════════════
# MUNDIAL 2026 — FIXTURE OFICIAL COMPLETO
# Estructura real FIFA: partidos 73-102 + 3er puesto + Final
# ═══════════════════════════════════════════════════════════════

FASES = ["Grupos", "Dieciseisavos", "Octavos", "Cuartos", "Semifinal", "Tercer puesto", "Final"]

# ─── FIXTURE OFICIAL DIECISEISAVOS (partidos 73-88) ──────────────────────────
# slot_local / slot_visitante: describe quién juega
# para los 8 cruces con terceros, slot_visitante es lista de grupos posibles
# (el admin elige cuál tercero va en cada cruce)

DIECISEISAVOS = [
    {"id": 73,  "slot_l": "2A",  "slot_v": "2B",         "fecha": "Dom. 28 jun, 15:00", "sede": "SoFi Stadium, Los Angeles",           "fijo": True},
    {"id": 74,  "slot_l": "1E",  "slot_v": "3-ABCDF",    "fecha": "Lun. 29 jun, 16:30", "sede": "Gillette Stadium, Foxborough",        "fijo": False},
    {"id": 75,  "slot_l": "1F",  "slot_v": "2C",         "fecha": "Lun. 29 jun, 21:00", "sede": "Estadio BBVA, Monterrey",             "fijo": True},
    {"id": 76,  "slot_l": "1C",  "slot_v": "2F",         "fecha": "Lun. 29 jun, 13:00", "sede": "NRG Stadium, Houston",                "fijo": True},
    {"id": 77,  "slot_l": "1I",  "slot_v": "3-CDFGH",    "fecha": "Mar. 30 jun, 17:00", "sede": "MetLife Stadium, East Rutherford",    "fijo": False},
    {"id": 78,  "slot_l": "2E",  "slot_v": "2I",         "fecha": "Mar. 30 jun, 13:00", "sede": "AT&T Stadium, Arlington",             "fijo": True},
    {"id": 79,  "slot_l": "1A",  "slot_v": "3-CEFHI",    "fecha": "Mar. 30 jun, 21:00", "sede": "Estadio Azteca, CDMX",               "fijo": False},
    {"id": 80,  "slot_l": "1L",  "slot_v": "3-EHIJK",    "fecha": "Mié. 1 jul, 12:00",  "sede": "Mercedes-Benz Stadium, Atlanta",     "fijo": False},
    {"id": 81,  "slot_l": "1D",  "slot_v": "3-BEFIJ",    "fecha": "Mié. 1 jul, 20:00",  "sede": "Levi's Stadium, Santa Clara",        "fijo": False},
    {"id": 82,  "slot_l": "1G",  "slot_v": "3-AEHIJ",    "fecha": "Mié. 1 jul, 16:00",  "sede": "Lumen Field, Seattle",               "fijo": False},
    {"id": 83,  "slot_l": "2K",  "slot_v": "2L",         "fecha": "Jue. 2 jul, 19:00",  "sede": "BMO Field, Toronto",                 "fijo": True},
    {"id": 84,  "slot_l": "1H",  "slot_v": "2J",         "fecha": "Jue. 2 jul, 15:00",  "sede": "SoFi Stadium, Los Angeles",          "fijo": True},
    {"id": 85,  "slot_l": "1B",  "slot_v": "3-EFGIJ",    "fecha": "Jue. 2 jul, 23:00",  "sede": "BC Place, Vancouver",                "fijo": False},
    {"id": 86,  "slot_l": "1J",  "slot_v": "2H",         "fecha": "Vie. 3 jul, 18:00",  "sede": "Hard Rock Stadium, Miami",           "fijo": True},
    {"id": 87,  "slot_l": "1K",  "slot_v": "3-DEIJL",    "fecha": "Vie. 3 jul, 21:30",  "sede": "Arrowhead Stadium, Kansas City",     "fijo": False},
    {"id": 88,  "slot_l": "2D",  "slot_v": "2G",         "fecha": "Vie. 3 jul, 14:00",  "sede": "AT&T Stadium, Arlington",            "fijo": True},
]

OCTAVOS = [
    {"id": 89,  "dep1": 74, "dep2": 77, "fecha": "Sáb. 4 jul, 17:00",  "sede": "Lincoln Financial Field, Philadelphia"},
    {"id": 90,  "dep1": 73, "dep2": 75, "fecha": "Sáb. 4 jul, 13:00",  "sede": "NRG Stadium, Houston"},
    {"id": 91,  "dep1": 76, "dep2": 78, "fecha": "Dom. 5 jul, 16:00",  "sede": "MetLife Stadium, East Rutherford"},
    {"id": 92,  "dep1": 79, "dep2": 80, "fecha": "Dom. 5 jul, 20:00",  "sede": "Estadio Azteca, CDMX"},
    {"id": 93,  "dep1": 83, "dep2": 84, "fecha": "Lun. 6 jul, 15:00",  "sede": "AT&T Stadium, Arlington"},
    {"id": 94,  "dep1": 81, "dep2": 82, "fecha": "Lun. 6 jul, 20:00",  "sede": "Lumen Field, Seattle"},
    {"id": 95,  "dep1": 86, "dep2": 88, "fecha": "Mar. 7 jul, 12:00",  "sede": "Mercedes-Benz Stadium, Atlanta"},
    {"id": 96,  "dep1": 85, "dep2": 87, "fecha": "Mar. 7 jul, 16:00",  "sede": "BC Place, Vancouver"},
]

CUARTOS = [
    {"id": 97,  "dep1": 89, "dep2": 90, "fecha": "Jue. 9 jul, 16:00",  "sede": "Gillette Stadium, Foxborough"},
    {"id": 98,  "dep1": 93, "dep2": 94, "fecha": "Vie. 10 jul, 15:00", "sede": "SoFi Stadium, Los Angeles"},
    {"id": 99,  "dep1": 91, "dep2": 92, "fecha": "Sáb. 11 jul, 17:00", "sede": "Hard Rock Stadium, Miami"},
    {"id": 100, "dep1": 95, "dep2": 96, "fecha": "Sáb. 11 jul, 21:00", "sede": "Arrowhead Stadium, Kansas City"},
]

SEMIFINALES = [
    {"id": 101, "dep1": 97, "dep2": 98,  "fecha": "Mar. 14 jul, 15:00", "sede": "AT&T Stadium, Arlington"},
    {"id": 102, "dep1": 99, "dep2": 100, "fecha": "Mié. 15 jul, 15:00", "sede": "Mercedes-Benz Stadium, Atlanta"},
]

TERCER_PUESTO = {"id": 103, "dep1": 101, "dep2": 102, "fecha": "Sáb. 18 jul, 17:00", "sede": "Hard Rock Stadium, Miami",     "tipo": "perdedor"}
FINAL         = {"id": 104, "dep1": 101, "dep2": 102, "fecha": "Dom. 19 jul, 15:00", "sede": "MetLife Stadium, East Rutherford", "tipo": "ganador"}

# IDs de cruces con tercero (admin debe asignar manualmente)
CRUCES_CON_TERCERO = {74, 77, 79, 80, 81, 82, 85, 87}


def generar_bracket(tabla_ordenada: dict) -> dict:
    """
    Retorna clasificados 1°/2° de cada grupo + estructura de fases.
    Los slots de terceros quedan como '3-?' hasta que el admin los asigne.
    """
    clasificados = {}
    terceros_candidatos = []
    grupos_completos = 0

    for letra, rows in tabla_ordenada.items():
        if not rows:
            continue
        tiene_datos = any(r.get("pj", 0) > 0 for r in rows)
        if all(r.get("pj", 0) >= 3 for r in rows):
            grupos_completos += 1
        if not tiene_datos:
            continue

        clasificados[f"1{letra}"] = {
            "nombre": rows[0]["nombre"], "codigo": rows[0]["codigo"],
            "grupo": letra, "pos": "1°",
            "pts": rows[0].get("pts", 0), "dg": rows[0].get("dg", 0), "gf": rows[0].get("gf", 0),
        }
        if len(rows) >= 2:
            clasificados[f"2{letra}"] = {
                "nombre": rows[1]["nombre"], "codigo": rows[1]["codigo"],
                "grupo": letra, "pos": "2°",
                "pts": rows[1].get("pts", 0), "dg": rows[1].get("dg", 0), "gf": rows[1].get("gf", 0),
            }
        if len(rows) >= 3:
            terceros_candidatos.append({
                "nombre": rows[2]["nombre"], "codigo": rows[2]["codigo"],
                "grupo": letra, "pos": "3°",
                "pts": rows[2].get("pts", 0), "dg": rows[2].get("dg", 0), "gf": rows[2].get("gf", 0),
            })

    terceros_candidatos.sort(key=lambda x: (-x["pts"], -x["dg"], -x["gf"]))

    return {
        "formato": "Mundial 2026 — 48 → 32 → Final",
        "fases": FASES,
        "clasificados": clasificados,
        "terceros": terceros_candidatos[:8],
        "grupos_completos": grupos_completos,
        "total_grupos": len(tabla_ordenada),
        "dieciseisavos": DIECISEISAVOS,
        "octavos": OCTAVOS,
        "cuartos": CUARTOS,
        "semifinales": SEMIFINALES,
        "tercer_puesto": TERCER_PUESTO,
        "final": FINAL,
    }
