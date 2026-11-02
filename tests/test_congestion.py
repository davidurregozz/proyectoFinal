"""Tests for the vehicle congestion zone."""

import unittest

from backend.congestion import (
    REDUCCION_MAX,
    REDUCCION_MIN,
    dividir_segmento,
    punto_en_zona,
    reduccion_para,
)
from backend.seed_data import ESPERA_EN_PARADA_S
from backend.simulation import Bus, Ruta


def ruta_que_cruza_la_zona():
    # Recta de oeste a este a la latitud 6.24, que atraviesa la zona.
    return {
        "nombre": "T1 Prueba", "codigo": "T1", "color": "#000000",
        "circular": False, "buses": 1, "velocidad_kmh": 36,
        "paradas": [("Oeste", 6.24, -75.60), ("Este", 6.24, -75.55)],
    }


class CongestionTests(unittest.TestCase):
    def test_point_inside_and_outside_zone(self):
        self.assertTrue(punto_en_zona((6.24, -75.575)))
        self.assertFalse(punto_en_zona((6.20, -75.575)))
        self.assertFalse(punto_en_zona((6.24, -75.60)))

    def test_segment_is_split_at_zone_borders(self):
        piezas = dividir_segmento((6.24, -75.60), (6.24, -75.55))
        self.assertEqual([en_zona for _, _, en_zona in piezas], [False, True, False])
        self.assertEqual(piezas[0][0], (6.24, -75.60))
        self.assertEqual(piezas[-1][1], (6.24, -75.55))

    def test_reduction_is_random_in_range_and_stable_per_bus(self):
        valores = {reduccion_para(f"R1-{n}") for n in range(50)}
        self.assertGreater(len(valores), 1)
        self.assertTrue(all(REDUCCION_MIN <= v <= REDUCCION_MAX for v in valores))
        self.assertEqual(reduccion_para("ABC123"), reduccion_para("ABC123"))

    def test_bus_travels_slower_inside_zone(self):
        ruta = Ruta(ruta_que_cruza_la_zona())
        bus = Bus(ruta, 1, 0)
        piezas = ruta._piezas_tramos[0]
        metros_zona = sum(largo for _, _, largo, zona in piezas if zona is not None)

        recorrido_base = ruta.ciclo_s - 2 * ESPERA_EN_PARADA_S
        recorrido_bus = ruta.ciclo_con_congestion(bus.reduccion) - 2 * ESPERA_EN_PARADA_S
        extra_por_sentido = (recorrido_bus - recorrido_base) / 2
        tiempo_zona_base = metros_zona / 10                 # 36 km/h = 10 m/s
        self.assertAlmostEqual(
            extra_por_sentido,
            tiempo_zona_base / (1 - bus.reduccion) - tiempo_zona_base,
            places=3,
        )

    def test_position_inside_zone_moves_at_reduced_speed(self):
        ruta = Ruta(ruta_que_cruza_la_zona())
        reduccion = 0.6
        _, _, _, tiempos = ruta._horario(reduccion)
        inicio_zona = ESPERA_EN_PARADA_S + tiempos[0][0]
        lat1, lon1, _, _ = ruta.estado(inicio_zona + 1, reduccion)
        lat2, lon2, _, _ = ruta.estado(inicio_zona + 11, reduccion)
        self.assertTrue(punto_en_zona((lat1, lon1)))
        metros = Ruta._distancia_tramo([(lat1, lon1), (lat2, lon2)])
        self.assertAlmostEqual(metros, 10 * 10 * (1 - reduccion), delta=0.5)

    def test_speed_is_zero_at_stop_and_reduced_inside_zone(self):
        ruta = Ruta(ruta_que_cruza_la_zona())
        reduccion = 0.6
        _, _, _, tiempos = ruta._horario(reduccion)
        self.assertEqual(ruta.velocidad_actual_kmh(1, reduccion), 0.0)
        self.assertAlmostEqual(
            ruta.velocidad_actual_kmh(ESPERA_EN_PARADA_S + 1, reduccion), 36, places=3
        )
        en_zona = ESPERA_EN_PARADA_S + tiempos[0][0] + 1
        self.assertAlmostEqual(
            ruta.velocidad_actual_kmh(en_zona, reduccion), 36 * (1 - reduccion), places=3
        )


if __name__ == "__main__":
    unittest.main()
