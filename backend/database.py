"""SQLite persistence for routes and vehicles."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.seed_data import RUTAS, RUTAS_ORIGINALES, VEHICULOS_INICIALES


DATABASE_PATH = Path(
    os.environ.get(
        "SIMULADOR_DB_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "simulador.sqlite3"),
    )
)


class Database:
    def __init__(self, path=DATABASE_PATH):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    municipality TEXT NOT NULL,
                    color TEXT NOT NULL,
                    speed_kmh REAL NOT NULL CHECK (speed_kmh > 0),
                    bus_count INTEGER NOT NULL CHECK (bus_count > 0),
                    circular INTEGER NOT NULL CHECK (circular IN (0, 1)),
                    stops_json TEXT NOT NULL,
                    coordinates_json TEXT NOT NULL,
                    return_coordinates_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vehicles (
                    plate TEXT PRIMARY KEY COLLATE NOCASE,
                    kind TEXT NOT NULL,
                    model TEXT NOT NULL,
                    capacity INTEGER NOT NULL CHECK (capacity > 0),
                    route_code TEXT NOT NULL REFERENCES routes(code) ON DELETE CASCADE,
                    driver TEXT NOT NULL,
                    status TEXT NOT NULL,
                    active_bus INTEGER NOT NULL DEFAULT 0 CHECK (active_bus IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS applied_seed_routes (
                    seed_code TEXT PRIMARY KEY
                );
                """
            )
            has_routes = connection.execute(
                "SELECT 1 FROM routes LIMIT 1"
            ).fetchone()
            if has_routes:
                self._migrate_seed_routes(connection)
                return

            for route in RUTAS:
                self._insert_route(connection, route)
            connection.executemany(
                "INSERT INTO applied_seed_routes (seed_code) VALUES (?)",
                [(self._seed_code(route),) for route in RUTAS],
            )
            route_codes = {
                row["name"]: row["code"]
                for row in connection.execute("SELECT code, name FROM routes")
            }
            for vehicle in VEHICULOS_INICIALES:
                connection.execute(
                    """
                    INSERT INTO vehicles
                        (plate, kind, model, capacity, route_code, driver, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        vehicle["placa"],
                        vehicle["tipo"],
                        vehicle["modelo"],
                        vehicle["capacidad"],
                        route_codes[vehicle["ruta"]],
                        vehicle["conductor"],
                        vehicle["estado"],
                    ),
                )

    @staticmethod
    def _seed_code(route):
        return route.get("codigo", route["nombre"].split()[0])

    def _migrate_seed_routes(self, connection):
        """
        Pone al día una base existente: agrega una sola vez las rutas de la
        semilla que no tenía (si el usuario la borra después, no vuelve) y
        completa el municipio que las rutas originales guardaban vacío.
        """
        applied = {
            row["seed_code"]
            for row in connection.execute("SELECT seed_code FROM applied_seed_routes")
        }
        if not applied:
            applied = set(RUTAS_ORIGINALES)
            connection.executemany(
                "INSERT INTO applied_seed_routes (seed_code) VALUES (?)",
                [(code,) for code in applied],
            )
        for route in RUTAS:
            seed_code = self._seed_code(route)
            if route.get("municipio"):
                connection.execute(
                    "UPDATE routes SET municipality = ? "
                    "WHERE code = ? AND name = ? AND municipality = ''",
                    (route["municipio"], seed_code, route["nombre"]),
                )
            if seed_code in applied:
                continue
            existing = connection.execute("SELECT code, name FROM routes").fetchall()
            codes = {row["code"] for row in existing}
            destination = route["nombre"].split(" ", 1)[1]
            # Si ya hay una ruta con el mismo recorrido (con cualquier código) no se duplica.
            if not any(row["name"].split(" ", 1)[-1] == destination for row in existing):
                if seed_code in codes:
                    # El usuario ya creó una ruta con ese código: se usa el siguiente libre.
                    number = max(
                        (int(code[1:]) for code in codes
                         if code[:1] == "R" and code[1:].isdigit()),
                        default=0,
                    ) + 1
                    route = {
                        **route,
                        "codigo": f"R{number}",
                        "nombre": f"R{number} {destination}",
                    }
                self._insert_route(connection, route)
            connection.execute(
                "INSERT INTO applied_seed_routes (seed_code) VALUES (?)", (seed_code,)
            )

    @staticmethod
    def _insert_route(connection, route):
        code = Database._seed_code(route)
        connection.execute(
            """
            INSERT INTO routes
                (code, name, municipality, color, speed_kmh, bus_count, circular,
                 stops_json, coordinates_json, return_coordinates_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                route["nombre"],
                route.get("municipio", ""),
                route["color"],
                route["velocidad_kmh"],
                route["buses"],
                int(route["circular"]),
                json.dumps(route["paradas"], ensure_ascii=False),
                json.dumps(route.get("coordenadas", [])),
                json.dumps(route.get("coordenadas_regreso", [])),
            ),
        )

    @staticmethod
    def route_from_row(row):
        return {
            "codigo": row["code"],
            "nombre": row["name"],
            "municipio": row["municipality"],
            "color": row["color"],
            "velocidad_kmh": row["speed_kmh"],
            "buses": row["bus_count"],
            "circular": bool(row["circular"]),
            "paradas": [tuple(stop) for stop in json.loads(row["stops_json"])],
            "coordenadas": [
                tuple(point) for point in json.loads(row["coordinates_json"])
            ],
            "coordenadas_regreso": [
                tuple(point)
                for point in json.loads(row["return_coordinates_json"])
            ],
        }

    def list_routes(self):
        with self.connect() as connection:
            return [
                self.route_from_row(row)
                for row in connection.execute("SELECT * FROM routes ORDER BY rowid")
            ]

    def create_route(self, route):
        with self.connect() as connection:
            self._insert_route(connection, route)

    def delete_route(self, code):
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM routes WHERE code = ?", (code,))
            return cursor.rowcount > 0

    def remove_route_bus(self, code):
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE routes SET bus_count = bus_count - 1 WHERE code = ? AND bus_count > 1",
                (code,),
            )
            return cursor.rowcount > 0

    def list_vehicles(self):
        with self.connect() as connection:
            return [
                {
                    "placa": row["plate"],
                    "tipo": row["kind"],
                    "modelo": row["model"],
                    "capacidad": row["capacity"],
                    "ruta": row["route_name"],
                    "conductor": row["driver"],
                    "estado": row["status"],
                }
                for row in connection.execute(
                    """
                    SELECT vehicles.*, routes.name AS route_name
                    FROM vehicles JOIN routes ON routes.code = vehicles.route_code
                    ORDER BY vehicles.plate
                    """
                )
            ]

    def list_bus_vehicles(self):
        with self.connect() as connection:
            return [
                {"placa": row["plate"], "ruta": row["route_name"]}
                for row in connection.execute(
                    """
                    SELECT vehicles.plate, routes.name AS route_name
                    FROM vehicles JOIN routes ON routes.code = vehicles.route_code
                    WHERE vehicles.active_bus = 1
                    """
                )
            ]

    def create_vehicle(self, vehicle):
        with self.connect() as connection:
            route = connection.execute(
                "SELECT code FROM routes WHERE name = ?", (vehicle["ruta"],)
            ).fetchone()
            if route is None:
                raise LookupError("La ruta seleccionada ya no existe.")
            connection.execute(
                """
                INSERT INTO vehicles
                    (plate, kind, model, capacity, route_code, driver, status, active_bus)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle["placa"],
                    vehicle["tipo"],
                    vehicle["modelo"],
                    vehicle["capacidad"],
                    route["code"],
                    vehicle["conductor"],
                    vehicle["estado"],
                    int(vehicle["estado"] == "Operativo"),
                ),
            )

    def delete_vehicle(self, plate):
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM vehicles WHERE plate = ?", (plate,))
            return cursor.rowcount > 0
