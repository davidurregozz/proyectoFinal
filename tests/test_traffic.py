"""Tests for traffic-based routing and time-aware route simulation."""

import json
import unittest
from unittest.mock import patch

from backend.seed_data import RUTAS
from backend.simulation import Ruta
from backend.traffic import TomTomTrafficFlow, TomTomTrafficRouter


class MockResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TrafficTests(unittest.TestCase):
    def test_tomtom_request_draws_a_fixed_path_through_the_waypoints(self):
        payload = {
            "routes": [{
                "legs": [
                    {
                        "points": [
                            {"latitude": 1.01, "longitude": 2.01},
                            {"latitude": 1.02, "longitude": 2.02},
                        ],
                        "summary": {
                            "travelTimeInSeconds": 321,
                            "noTrafficTravelTimeInSeconds": 200,
                        },
                    },
                    {
                        "points": [
                            {"latitude": 1.02, "longitude": 2.02},
                            {"latitude": 1.03, "longitude": 2.03},
                        ],
                        "summary": {"travelTimeInSeconds": 456},
                    },
                ],
            }],
        }
        with patch("backend.traffic.urlopen", return_value=MockResponse(payload)) as open_url:
            geometry, durations, free = TomTomTrafficRouter("test-key")._calculate(
                [(1.0, 2.0), (1.02, 2.02), (1.03, 2.03)]
            )

        request_url = open_url.call_args.args[0].full_url
        # Ruta fija como la de un bus real: el tráfico no cambia el recorrido.
        self.assertIn("traffic=false", request_url)
        self.assertNotIn("departAt", request_url)
        self.assertIn("travelMode=bus", request_url)
        self.assertEqual(geometry[0], (1.0, 2.0))
        self.assertEqual(geometry[-1], (1.03, 2.03))
        self.assertEqual(durations, [321.0, 456.0])
        # Sin dato de flujo libre se usa la duración con tráfico.
        self.assertEqual(free, [200.0, 456.0])

    def test_flow_returns_current_and_free_speed_for_point(self):
        payload = {"flowSegmentData": {
            "currentSpeed": 18, "freeFlowSpeed": 45, "roadClosure": False, "confidence": 0.9,
        }}
        with patch("backend.traffic.urlopen", return_value=MockResponse(payload)) as open_url:
            speed = TomTomTrafficFlow("test-key").speed((6.25, -75.57))

        self.assertIn("point=6.250000%2C-75.570000", open_url.call_args.args[0].full_url)
        self.assertEqual(speed["current_kmh"], 18.0)
        self.assertEqual(speed["free_kmh"], 45.0)
        self.assertFalse(speed["closed"])

    def test_route_is_drawn_once_and_reused_on_every_refresh(self):
        router = TomTomTrafficRouter("test-key")
        drawn = []
        router._draw = lambda route: drawn.append(route["nombre"]) or {"coordenadas": []}

        router.optimize(RUTAS[0])
        router.optimize(RUTAS[0])

        self.assertEqual(drawn, [RUTAS[0]["nombre"]])

    def test_stop_causing_a_detour_moves_onto_the_natural_road(self):
        # B queda en la calzada contraria: llegar a ella obliga a ir 3 km al norte y volver.
        a, b, c = (6.20, -75.58), (6.20, -75.57), (6.20, -75.56)
        on_road = (6.2004, -75.57)                     # misma vía que A -> C, a 45 m de B

        def fake_calculate(points):
            if points == [a, c]:
                return [a, on_road, c], [60.0], [60.0]
            if points == [a, b, c]:
                return [a, (6.23, -75.575), b, c], [400.0, 60.0], [400.0, 60.0]
            return list(points), [60.0] * (len(points) - 1), [60.0] * (len(points) - 1)

        router = TomTomTrafficRouter("test-key")
        router._calculate = fake_calculate

        points = router._direction_stop_points([a, b, c], circular=False)

        self.assertEqual(points, [a, on_road, c])

    def test_bus_waits_at_its_direction_stop_point(self):
        route_data = {
            "nombre": "T1 Prueba", "codigo": "T1", "color": "#000000",
            "circular": False, "buses": 1, "velocidad_kmh": 36,
            "paradas": [("A", 6.20, -75.58), ("B", 6.20, -75.57)],
            "coordenadas": [(6.20, -75.58), (6.20, -75.57)],
            "coordenadas_regreso": [(6.2003, -75.57), (6.2003, -75.58)],
            "paraderos_regreso": [(6.2003, -75.58), (6.2003, -75.57)],
        }
        route = Ruta(route_data)
        llegada_b = route.horario[1][0]                 # llega a B; desde ahí sale el regreso

        lat, lon, stop, remaining = route.estado(llegada_b + 1)

        self.assertEqual((lat, lon), (6.2003, -75.57))  # paradero del regreso, cruzando la vía
        self.assertEqual((stop, remaining), ("B", 0.0))

    def test_traffic_durations_change_route_cycle_time(self):
        route_data = dict(RUTAS[0])
        legs = len(route_data["paradas"]) if route_data["circular"] else len(route_data["paradas"]) - 1
        route_data["duraciones_tramos_ida_s"] = [100.0] * legs
        if not route_data["circular"]:
            route_data["duraciones_tramos_regreso_s"] = [120.0] * legs

        base_route = Ruta(RUTAS[0])
        traffic_route = Ruta(route_data)

        self.assertNotEqual(base_route.ciclo_s, traffic_route.ciclo_s)
        self.assertEqual(traffic_route.duraciones_tramos_ida_s, [100.0] * legs)

    def test_circular_route_can_apply_closing_leg_duration(self):
        route_data = dict(RUTAS[2])
        route_data["duraciones_tramos_ida_s"] = [
            90.0
        ] * len(route_data["paradas"])

        route = Ruta(route_data)

        self.assertEqual(
            len(route.duraciones_tramos_ida_s), len(route.paradas)
        )
        self.assertEqual(route.coordenadas[0], route.coordenadas[-1])


if __name__ == "__main__":
    unittest.main()
