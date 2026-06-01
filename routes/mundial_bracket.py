# mundial_bracket.py

BRACKET_FIFA_2026 = {
    "formato": "32 equipos - Dieciseisavos de final",
    "terceros_mejores": {
        "criterios": [
            "puntos",
            "diferencia de goles",
            "goles a favor",
            "fair play",
            "ranking FIFA"
        ]
    },
    "cruces_octavos": {
        "ganadores_grupo_vs_segundos": [
            {"1C": "2F"},
            {"1F": "2C"},
            {"1H": "2J"},
            {"1J": "2H"}
        ],
        "ganadores_vs_terceros": [
            {"1A": ["3C","3E","3F","3H","3I"]},
            {"1B": ["3E","3F","3G","3I","3J"]},
            {"1D": ["3B","3E","3F","3I","3J"]},
            {"1E": ["3A","3B","3C","3D","3F"]},
            {"1G": ["3A","3E","3H","3I","3J"]},
            {"1I": ["3C","3D","3F","3G","3H"]},
            {"1K": ["3D","3E","3I","3J","3L"]},
            {"1L": ["3E","3H","3I","3J","3K"]}
        ]
    },
    "fases": [
        "Dieciseisavos",
        "Octavos",
        "Cuartos",
        "Semifinales",
        "Tercer puesto",
        "Final"
    ]
}