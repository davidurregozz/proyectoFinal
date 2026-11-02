"""Focused tests for SQLite persistence and server-side simulation."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backend.database import Database
from backend.seed_data import RUTAS
from backend.service import ZONA_HORARIA, TransitService, clasificar_trafico
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

        self.assertEqual(len(snapshot["routes"]), len(RUTAS))
        self.assertEqual(len(snapshot["buses"]), sum(route["buses"] for route in RUTAS))
        self.assertTrue(snapshot["stops"])
        self.assertTrue(snapshot["arrivals"])
        self.assertIn("speed_kmh", snapshot["arrivals"][0])
        self.assertIn("clock", snapshot)

    def test_snapshot_clock_is_real_colombian_time(self):
        snapshot = TransitService(self.database).snapshot()

        now = datetime.now(ZONA_HORARIA)
        clock = datetime.strptime(snapshot["clock"], "%H:%M:%S").replace(
            year=now.year, month=now.month, day=now.day, tzinfo=ZONA_HORARIA
        )
        self.assertLess(abs((now - clock).total_seconds()), 5)
        self.assertNotIn("factor", snapshot)

    def test_traffic_is_classified_by_share_of_free_flow_speed(self):
        self.assertEqual(clasificar_trafico(40, 45)[1], None)
        self.assertEqual(clasificar_trafico(30, 45)[1], "moderado")
        self.assertEqual(clasificar_trafico(20, 45)[1], "alto")
        self.assertEqual(clasificar_trafico(10, 45)[1], "severo")
        self.assertEqual(clasificar_trafico(40, 45, closed=True), (0.85, "severo"))

    def test_measured_hexagons_become_slow_zones_that_slow_buses(self):
        service = TransitService(self.database)
        free_cycle = {route["codigo"]: route["ciclo_s"] for route in service.snapshot()["routes"]}

        class FakeFlow:
            def speed(self, point):
                # Tráfico pesado solo en el centro de Medellín.
                slow = abs(point[0] - 6.2518) < 0.01 and abs(point[1] + 75.5636) < 0.01
                return {"current_kmh": 12.0 if slow else 44.0, "free_kmh": 45.0,
                        "closed": False, "confidence": 1}

        service._traffic_flow = FakeFlow()
        service._refresh_traffic_cells()
        snapshot = service.snapshot()

        zones = snapshot["traffic_zones"]
        self.assertEqual(zones["mode"], "tomtom")
        self.assertEqual(len(zones["zones"]), zones["measured"])
        severities = {zone["severity"] for zone in zones["zones"]}
        self.assertEqual(severities, {"severo", "fluido"})
        self.assertEqual(zones["zones"][0]["severity"], "severo")   # más lentas primero
        self.assertEqual(len(zones["zones"][0]["polygon"]), 6)
        self.assertTrue(any(
            route["ciclo_s"] > free_cycle[route["codigo"]] for route in snapshot["routes"]
        ))

    def test_without_measurements_the_simulated_zone_is_used(self):
        zones = TransitService(self.database).snapshot()["traffic_zones"]

        self.assertEqual(zones["mode"], "simulada")
        self.assertEqual(zones["zones"][0]["id"], "simulada")

    def test_traffic_durations_are_scaled_by_speed_factor(self):
        service = TransitService(self.database)
        route = self.database.list_routes()[0]
        service._traffic_routes[route["codigo"]] = {
            "duraciones_tramos_ida_s": [160.0],
            "duraciones_tramos_regreso_s": [320.0],
        }

        scaled = service._route_with_traffic(route)

        factor = TransitService.TRAFFIC_SPEED_FACTOR
        self.assertEqual(scaled["duraciones_tramos_ida_s"], [160.0 / factor])
        self.assertEqual(scaled["duraciones_tramos_regreso_s"], [320.0 / factor])

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
            [120.0 / TransitService.TRAFFIC_SPEED_FACTOR] * 6,
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

    def test_delete_vehicle_removes_it_from_fleet_and_map(self):
        service = TransitService(self.database)
        service.create_vehicle({
            "placa": "TEST-002",
            "tipo": "Bus urbano",
            "modelo": "Custom",
            "capacidad": 30,
            "ruta": "R1 Centro - Poblado",
            "conductor": "Prueba",
            "estado": "Operativo",
        })
        self.assertIn("TEST-002", [bus["name"] for bus in service.snapshot()["buses"]])

        service.delete_vehicle("test-002")

        snapshot = service.snapshot()
        self.assertNotIn("TEST-002", [bus["name"] for bus in snapshot["buses"]])
        self.assertNotIn("TEST-002", [v["placa"] for v in snapshot["vehicles"]])
        with self.assertRaises(LookupError):
            service.delete_vehicle("TEST-002")

    def test_remove_route_bus_keeps_at_least_one(self):
        service = TransitService(self.database)
        buses = self.database.list_routes()[0]["buses"]

        for _ in range(buses - 1):
            service.remove_route_bus("R1")

        self.assertEqual(self.database.list_routes()[0]["buses"], 1)
        with self.assertRaises(ValueError):
            service.remove_route_bus("R1")
        with self.assertRaises(LookupError):
            service.remove_route_bus("R99")

    def test_service_prevents_deleting_last_route(self):
        service = TransitService(self.database)
        *others, last = [route["codigo"] for route in self.database.list_routes()]
        for code in others:
            service.delete_route(code)

        with self.assertRaises(ValueError):
            service.delete_route(last)

    def _simulate_database_from_before_envigado(self):
        with self.database.connect() as connection:
            connection.execute("DELETE FROM routes WHERE code = 'R5'")
            connection.execute("DROP TABLE applied_seed_routes")
            connection.execute("UPDATE routes SET municipality = ''")

    def test_existing_database_receives_envigado_route_once(self):
        self._simulate_database_from_before_envigado()

        self.database.initialize()
        routes = {route["codigo"]: route for route in self.database.list_routes()}
        self.assertEqual(routes["R5"]["municipio"], "Envigado")
        self.assertEqual(routes["R1"]["municipio"], "Medellín")

        TransitService(self.database).delete_route("R5")
        self.database.initialize()
        self.assertNotIn("R5", [route["codigo"] for route in self.database.list_routes()])

    def test_envigado_route_takes_free_code_when_user_already_has_r5(self):
        self._simulate_database_from_before_envigado()
        user_route = dict(RUTAS[0], codigo="R5", nombre="R5 Bello - Centro")
        self.database.create_route(user_route)

        self.database.initialize()

        names = {route["codigo"]: route["nombre"] for route in self.database.list_routes()}
        self.assertEqual(names["R5"], "R5 Bello - Centro")
        self.assertEqual(names["R6"], "R6 Envigado - El Poblado")

    def test_envigado_route_shares_transfer_stop_with_r1(self):
        stops = {stop["nombre"]: stop for stop in TransitService(self.database).snapshot()["stops"]}

        self.assertEqual(sorted(stops["Parque del Poblado"]["codigos"]), ["R1", "R5"])
        self.assertIn("Parque de Envigado", stops)

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
