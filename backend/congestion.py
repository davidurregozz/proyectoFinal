"""Zona de congestión vehicular donde los buses reducen su velocidad."""

import random

# Polígono (lat, lon) de la zona; se evalúa con la regla par-impar.
ZONA_CONGESTION = [
    (6.228098, -75.586695),
    (6.217045, -75.572079),
    (6.231327, -75.566020),
    (6.254735, -75.562585),
    (6.249458, -75.591692),
]

# Fracción en que se reduce la velocidad dentro de la zona (50 % a 70 %).
REDUCCION_MIN = 0.5
REDUCCION_MAX = 0.7


def reduccion_para(nombre_bus):
    """
    Reducción aleatoria de velocidad de un bus dentro de la zona.
    Se siembra con el nombre del bus para que el valor sea estable entre
    consultas y el bus no salte de posición en el mapa.
    """
    return random.Random(f"congestion:{nombre_bus}").uniform(
        REDUCCION_MIN, REDUCCION_MAX
    )


def punto_en_zona(punto, poligono=ZONA_CONGESTION):
    """Indica si (lat, lon) cae dentro del polígono (ray casting)."""
    lat, lon = punto
    dentro = False
    for (lat1, lon1), (lat2, lon2) in zip(poligono, poligono[1:] + poligono[:1]):
        if (lat1 > lat) != (lat2 > lat):
            lon_cruce = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < lon_cruce:
                dentro = not dentro
    return dentro


def _cortes_con_bordes(inicio, fin, poligono):
    """Fracciones (0, 1) del segmento donde cruza los bordes del polígono."""
    (x1, y1), (x2, y2) = inicio, fin
    cortes = []
    for (x3, y3), (x4, y4) in zip(poligono, poligono[1:] + poligono[:1]):
        denominador = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
        if not denominador:
            continue
        t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denominador
        u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denominador
        if 0 < t < 1 and 0 <= u <= 1:
            cortes.append(t)
    return sorted(cortes)


def dividir_segmento(inicio, fin, poligono=ZONA_CONGESTION):
    """
    Parte el segmento donde entra o sale de la zona.
    Devuelve [(punto_inicio, punto_fin, en_zona), ...] en orden de recorrido.
    """
    fracciones = [0.0, *_cortes_con_bordes(inicio, fin, poligono), 1.0]
    puntos = [
        (
            inicio[0] + (fin[0] - inicio[0]) * t,
            inicio[1] + (fin[1] - inicio[1]) * t,
        )
        for t in fracciones
    ]
    piezas = []
    for a, b in zip(puntos, puntos[1:]):
        medio = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        en_zona = punto_en_zona(medio, poligono)
        if piezas and piezas[-1][2] == en_zona:
            piezas[-1] = (piezas[-1][0], b, en_zona)
        else:
            piezas.append((a, b, en_zona))
    return piezas
