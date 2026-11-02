"""Application services and server-side simulation state."""

import os
import threading
import time
from datetime import datetime, timedelta, timezone

from backend.congestion import REDUCCION_MAX, REDUCCION_MIN, ZONA_CONGESTION
from backend.database import Database
from backend.simulation import Bus, Ruta, texto_espera
from backend.traffic import (
    TrafficRoutingError,
    create_traffic_router,
    log_traffic_failure,
)


class TransitService:
    TRAFFIC_REFRESH_SECONDS = 300
    # TomTom durations are divided by this so buses run 60 % faster than live traffic.
    TRAFFIC_SPEED_FACTOR = float(os.environ.get("SIMULADOR_FACTOR_VELOCIDAD", "1.6"))

    def __init__(self, database=None):
        self.database = database or Database()
        self.database.initialize()
        self._lock = threading.RLock()
        self._elapsed = 0.0
        self._last_tick = time.monotonic()
        self._traffic_router = create_traffic_router()
        self._traffic_routes = {}
        self._traffic_stop = threading.Event()
        self._traffic_refresh_requested = threading.Event()
        self._traffic_thread = None
        self._traffic_status = {
            "provider": "TomTom",
            "available": False,
            "message": (
                "Tráfico en vivo desactivado; configura TOMTOM_API_KEY. "
                "Se usan los trazados guardados."
            ),
            "updated_at": None,
        }

    def start_traffic_refresh(self):
        if self._traffic_router is None or self._traffic_thread is not None:
            return
        self._traffic_thread = threading.Thread(
            target=self._traffic_refresh_loop,
            name="tomtom-traffic-refresh",
            daemon=True,
        )
        self._traffic_thread.start()

    def stop_traffic_refresh(self):
        self._traffic_stop.set()
        self._traffic_refresh_requested.set()
        if self._traffic_thread is not None:
            self._traffic_thread.join(timeout=3)

    def _traffic_refresh_loop(self):
        while not self._traffic_stop.is_set():
            self._refresh_traffic_routes()
            self._traffic_refresh_requested.wait(self.TRAFFIC_REFRESH_SECONDS)
            self._traffic_refresh_requested.clear()

    def _refresh_traffic_routes(self):
        if self._traffic_router is None:
            return
        with self._lock:
            self._traffic_status = {
                **self._traffic_status,
                "message": "Consultando rutas con el tráfico actual de TomTom...",
            }

        updated = {}
        failures = []
        routes = self.database.list_routes()
        for route in routes:
            try:
                updated[route["codigo"]] = self._traffic_router.optimize(route)
            except TrafficRoutingError as error:
                log_traffic_failure(route["codigo"], error)
                failures.append(route["codigo"])
                with self._lock:
                    if route["codigo"] in self._traffic_routes:
                        updated[route["codigo"]] = self._traffic_routes[route["codigo"]]

        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        successes = len(routes) - len(failures)
        with self._lock:
            self._traffic_routes = updated
            previous_update = self._traffic_status["updated_at"]
            if successes:
                self._traffic_status = {
                    "provider": "TomTom",
                    "available": successes == len(routes),
                    "message": (
                        "Rutas optimizadas con tráfico actual de TomTom."
                        if not failures else
                        "Tráfico TomTom parcial; las rutas fallidas conservan su trazado guardado."
                    ),
                    "updated_at": updated_at,
                }
            else:
                self._traffic_status = {
                    "provider": "TomTom",
                    "available": False,
                    "message": (
                        "No se pudo consultar el tráfico; se usan trazados guardados."
                    ),
                    "updated_at": previous_update,
                }

    def set_control(self, paused, factor):
        with self._lock:
            self._advance()
            self.database.update_control(paused, factor)
            self._last_tick = time.monotonic()

    def _advance(self):
        now = time.monotonic()
        control = self.database.get_control()
        if not control["paused"]:
            self._elapsed += (now - self._last_tick) * control["factor"]
        self._last_tick = now

    def snapshot(self, selected_stop=""):
        with self._lock:
            self._advance()
            control = self.database.get_control()
            routes = [
                Ruta(self._route_with_traffic(route_data))
                for route_data in self.database.list_routes()
            ]
            route_data = [self._serialize_route(route) for route in routes]
            routes_by_name = {route.nombre: route for route in routes}
            buses = []
            for route in routes:
                for number in range(1, route.n_buses + 1):
                    bus = Bus(route, number, (number - 1) * route.ciclo_s / route.n_buses)
                    buses.append(bus)

            for vehicle in self.database.list_bus_vehicles():
                route = routes_by_name[vehicle["ruta"]]
                bus = Bus(route, len([b for b in buses if b.ruta is route]) + 1, 0)
                bus.nombre = vehicle["placa"]
                buses.append(bus)

            clock = datetime.now() + timedelta(seconds=self._elapsed)
            bus_states = []
            arrivals = []
            for bus in buses:
                lat, lon, next_stop, remaining = bus.estado(self._elapsed)
                speed_kmh = round(bus.velocidad_actual_kmh(self._elapsed), 1)
                bus_states.append({
                    "name": bus.nombre,
                    "route_code": bus.ruta.codigo,
                    "color": bus.ruta.color,
                    "latitude": lat,
                    "longitude": lon,
                    "next_stop": next_stop,
                    "seconds_remaining": remaining,
                    "remaining_text": texto_espera(remaining),
                    "arrival_time": (clock + timedelta(seconds=remaining)).strftime("%H:%M"),
                    "speed_kmh": speed_kmh,
                })
                if selected_stop:
                    result = bus.segundos_hasta(self._elapsed, selected_stop)
                    if result:
                        seconds, direction = result
                        arrivals.append({
                            "name": bus.nombre,
                            "route_code": bus.ruta.codigo,
                            "direction": direction,
                            "seconds_remaining": seconds,
                            "remaining_text": texto_espera(seconds),
                            "arrival_time": (
                                clock + timedelta(seconds=seconds)
                            ).strftime("%H:%M"),
                            "speed_kmh": speed_kmh,
                        })
            arrivals.sort(key=lambda arrival: arrival["seconds_remaining"])
            return {
                "routes": route_data,
                "vehicles": self.database.list_vehicles(),
                "buses": bus_states,
                "arrivals": arrivals,
                "stops": self._stops(route_data),
                "clock": clock.strftime("%H:%M:%S"),
                "paused": control["paused"],
                "factor": control["factor"],
                "traffic": dict(self._traffic_status),
                "congestion_zone": {
                    "polygon": ZONA_CONGESTION,
                    "min_slowdown": REDUCCION_MIN,
                    "max_slowdown": REDUCCION_MAX,
                },
            }

    def _route_with_traffic(self, route_data):
        traffic_route = self._traffic_routes.get(route_data["codigo"])
        if traffic_route is None:
            return route_data
        traffic_route = {
            **traffic_route,
            **{
                key: [seconds / self.TRAFFIC_SPEED_FACTOR for seconds in traffic_route[key]]
                for key in ("duraciones_tramos_ida_s", "duraciones_tramos_regreso_s")
            },
        }
        return {**route_data, **traffic_route}

    @staticmethod
    def _serialize_route(route):
        return {
            "codigo": route.codigo,
            "nombre": route.nombre,
            "municipio": route.municipio,
            "color": route.color,
            "velocidad_kmh": route.velocidad_kmh,
            "buses": route.n_buses,
            "circular": route.circular,
            "paradas": route.paradas,
            "coordenadas": route.coordenadas,
            "coordenadas_regreso": route.coordenadas_regreso,
            "duraciones_tramos_ida_s": route.duraciones_tramos_ida_s,
            "duraciones_tramos_regreso_s": route.duraciones_tramos_regreso_s,
            "traffic_applied": bool(route.duraciones_tramos_ida_s),
            "ciclo_s": route.ciclo_s,
        }

    @staticmethod
    def _stops(routes):
        stops = {}
        for route in routes:
            for name, latitude, longitude in route["paradas"]:
                stops.setdefault(name, {
                    "nombre": name,
                    "latitud": latitude,
                    "longitud": longitude,
                    "colores": [],
                    "codigos": [],
                })
                stops[name]["colores"].append(route["color"])
                stops[name]["codigos"].append(route["codigo"])
        return list(stops.values())

    def create_route(self, route):
        with self._lock:
            Ruta(route)
            self.database.create_route(route)
            self._traffic_refresh_requested.set()

    def delete_route(self, code):
        with self._lock:
            routes = self.database.list_routes()
            if not any(route["codigo"] == code for route in routes):
                raise LookupError("La ruta solicitada no existe.")
            if len(routes) <= 1:
                raise ValueError("Debe quedar al menos una ruta en la simulación.")
            if not self.database.delete_route(code):
                raise LookupError("La ruta solicitada no existe.")
            self._traffic_routes.pop(code, None)

    def create_vehicle(self, vehicle):
        with self._lock:
            self.database.create_vehicle(vehicle)
