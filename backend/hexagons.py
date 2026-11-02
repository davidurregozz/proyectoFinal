"""Malla de hexágonos sobre los recorridos para medir el tráfico por zonas."""

import math

# Origen fijo de la malla: así cada hexágono conserva su id entre consultas.
ORIGEN = (6.2442, -75.5812)
METROS_POR_GRADO_LAT = 111_320
METROS_POR_GRADO_LON = METROS_POR_GRADO_LAT * math.cos(math.radians(ORIGEN[0]))


def _a_metros(punto):
    lat, lon = punto
    return (
        (lon - ORIGEN[1]) * METROS_POR_GRADO_LON,
        (lat - ORIGEN[0]) * METROS_POR_GRADO_LAT,
    )


def _a_grados(x, y):
    return (ORIGEN[0] + y / METROS_POR_GRADO_LAT, ORIGEN[1] + x / METROS_POR_GRADO_LON)


def _redondear(q, r):
    """Redondea coordenadas axiales fraccionarias al hexágono que las contiene."""
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return rq, rr


def hexagono_de(punto, radio_m):
    """Coordenadas axiales (q, r) del hexágono (punta arriba) que contiene el punto."""
    x, y = _a_metros(punto)
    q = (math.sqrt(3) / 3 * x - y / 3) / radio_m
    r = (2 / 3 * y) / radio_m
    return _redondear(q, r)


def centro(q, r, radio_m):
    return _a_grados(radio_m * math.sqrt(3) * (q + r / 2), radio_m * 1.5 * r)


def vertices(q, r, radio_m):
    cx = radio_m * math.sqrt(3) * (q + r / 2)
    cy = radio_m * 1.5 * r
    return [
        _a_grados(
            cx + radio_m * math.cos(math.radians(30 + 60 * k)),
            cy + radio_m * math.sin(math.radians(30 + 60 * k)),
        )
        for k in range(6)
    ]


def celdas_sobre_trazados(trazados, radio_m, maximo):
    """
    Hexágonos que cubren los trazados, con el punto del recorrido más cercano
    al centro de cada uno (ahí se consulta el tráfico, sobre la vía del bus).
    Si hay más de 'maximo', se conservan los que más recorrido contienen.
    """
    paso_m = radio_m / 3
    muestras = {}
    for trazado in trazados:
        for a, b in zip(trazado, trazado[1:]):
            (x1, y1), (x2, y2) = _a_metros(a), _a_metros(b)
            pasos = max(1, math.ceil(math.hypot(x2 - x1, y2 - y1) / paso_m))
            for k in range(pasos + 1):
                t = k / pasos
                punto = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                muestras.setdefault(hexagono_de(punto, radio_m), []).append(punto)

    celdas = []
    for (q, r), puntos in muestras.items():
        cx, cy = _a_metros(centro(q, r, radio_m))
        consulta = min(
            puntos,
            key=lambda p: math.hypot(_a_metros(p)[0] - cx, _a_metros(p)[1] - cy),
        )
        celdas.append({
            "id": f"{q},{r}",
            "centro": centro(q, r, radio_m),
            "poligono": vertices(q, r, radio_m),
            "consulta": consulta,
            "muestras": len(puntos),
        })
    celdas.sort(key=lambda celda: celda["muestras"], reverse=True)
    return celdas[:maximo]
