"""Focused tests for SQLite persistence and server-side simulation."""

import tempfile
import unittest
from pathlib import Path

from backend.database import Database
from backend.service import TransitService
from backend.traffic import TrafficRoutingError


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.database.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_is_idempotent_and_preserves_road_geometry(self):
        original_routes = self.database.list_routes()
        self.database.initialize()
        routes = self.database.list_routes()

        self.assertEqual(len(routes), len(original_routes))
        self.assertEqual(routes[0]["coordenadas"], original_routes[0]["coordenadas"])
        self.assertEqual(
            routes[0]["coordenadas_regreso"],
            original_routes[0]["coordenadas_regreso"],
        )
        self.assertEqual(len(self.database.list_vehicles()), 2)

    def test_snapshot_contains_routes_buses_stops_and_arrivals(self):
        snapshot = TransitService(self.database).snapshot("San Antonio")

        self.assertEqual(len(snapshot["routes"]), 3)
        self.assertEqual(len(snapshot["buses"]), 6)
        self.assertTrue(snapshot["stops"])
        self.assertTrue(snapshot["arrivals"])
        self.assertIn("clock", snapshot)

    def test_snapshot_uses_cached_live_traffic_route(self):
        service = TransitService(self.database)
        route = self.database.list_routes()[0]
        traffic_route = {
            "coordenadas": route["coordenadas"],
            "coordenadas_regreso": route["coordenadas_regreso"],
            "duraciones_tramos_ida_s": [120.0] * 6,
            "duraciones_tramos_regreso_s": [150.0] * 6,
        }
        service._traffic_routes[route["codigo"]] = traffic_route

        snapshot = service.snapshot()

        optimized = next(
            item for item in snapshot["routes"]
            if item["codigo"] == route["codigo"]
        )
        self.assertTrue(optimized["traffic_applied"])
        self.assertEqual(
            optimized["duraciones_tramos_ida_s"],
            traffic_route["duraciones_tramos_ida_s"],
        )

    def test_refresh_uses_provider_and_keeps_saved_routes_on_failure(self):
        service = TransitService(self.database)

        class FakeRouter:
            fail = False

            def optimize(self, route):
                if self.fail:
                    raise TrafficRoutingError("test provider failure")
                stop_count = len(route["paradas"])
                return {
                    "coordenadas": route["coordenadas"],
                    "coordenadas_regreso": route["coordenadas_regreso"],
                    "duraciones_tramos_ida_s": [60.0] * (
                        stop_count if route["circular"] else stop_count - 1
                    ),
                    "duraciones_tramos_regreso_s": (
                        [] if route["circular"] else [75.0] * (stop_count - 1)
                    ),
                }

        service._traffic_router = FakeRouter()
        service._refresh_traffic_routes()
        self.assertTrue(service.snapshot()["traffic"]["available"])

        previous_routes = dict(service._traffic_routes)
        service._traffic_router.fail = True
        service._refresh_traffic_routes()

        self.assertEqual(service._traffic_routes, previous_routes)
        self.assertFalse(service.snapshot()["traffic"]["available"])

    def test_route_delete_cascades_registered_vehicles(self):
        service = TransitService(self.database)
        service.create_vehicle({
            "placa": "TEST-001",
            "tipo": "Bus urbano",
            "modelo": "Custom",
            "capacidad": 30,
            "ruta": "R1 Centro - Poblado",
            "conductor": "Prueba",
            "estado": "Operativo",
        })

        service.delete_route("R1")

        self.assertFalse(any(
            vehicle["placa"] == "TEST-001"
            for vehicle in self.database.list_vehicles()
        ))

    def test_service_prevents_deleting_last_route(self):
        service = TransitService(self.database)
        service.delete_route("R1")
        service.delete_route("R2")

        with self.assertRaises(ValueError):
            service.delete_route("R3")

    def test_new_route_survives_database_reopen(self):
        route = {
            "codigo": "R4",
            "nombre": "R4 Bello - Centro",
            "municipio": "Bello",
            "color": "#7e22ce",
            "velocidad_kmh": 25,
            "buses": 1,
            "circular": False,
            "paradas": [
                ("Terminal", 6.2779, -75.5694),
                ("Centro", 6.3370, -75.5580),
            ],
            "coordenadas": [
                (6.2779, -75.5694),
                (6.3000, -75.5600),
                (6.3370, -75.5580),
            ],
            "coordenadas_regreso": [],
        }
        TransitService(self.database).create_route(route)

        reopened = Database(self.database.path)
        reopened.initialize()
        saved = next(
            item for item in reopened.list_routes() if item["codigo"] == "R4"
        )
        self.assertEqual(saved["coordenadas"], route["coordenadas"])


if __name__ == "__main__":
    unittest.main()
