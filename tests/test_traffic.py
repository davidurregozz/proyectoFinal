"""Tests for traffic-based routing and time-aware route simulation."""

import json
import unittest
from unittest.mock import patch

from backend.seed_data import RUTAS
from backend.simulation import Ruta
from backend.traffic import TomTomTrafficRouter


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
    def test_tomtom_request_uses_current_traffic_and_waypoint_geometry(self):
        payload = {
            "routes": [{
                "legs": [
                    {
                        "points": [
                            {"latitude": 1.01, "longitude": 2.01},
                            {"latitude": 1.02, "longitude": 2.02},
                        ],
                        "summary": {"travelTimeInSeconds": 321},
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
            geometry, durations = TomTomTrafficRouter("test-key")._calculate(
                [(1.0, 2.0), (1.02, 2.02), (1.03, 2.03)]
            )

        request_url = open_url.call_args.args[0].full_url
        self.assertIn("traffic=true", request_url)
        self.assertIn("departAt=now", request_url)
        self.assertIn("travelMode=bus", request_url)
        self.assertEqual(geometry[0], (1.0, 2.0))
        self.assertEqual(geometry[-1], (1.03, 2.03))
        self.assertEqual(durations, [321.0, 456.0])

    def test_traffic_durations_change_route_cycle_time(self):
        route_data = dict(RUTAS[0])
        route_data["duraciones_tramos_ida_s"] = [100.0] * 6
        route_data["duraciones_tramos_regreso_s"] = [120.0] * 6

        base_route = Ruta(RUTAS[0])
        traffic_route = Ruta(route_data)

        self.assertNotEqual(base_route.ciclo_s, traffic_route.ciclo_s)
        self.assertEqual(traffic_route.duraciones_tramos_ida_s, [100.0] * 6)

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
