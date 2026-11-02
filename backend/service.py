"""Application services and server-side simulation state."""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from backend.congestion import (
    REDUCCION_MAX,
    REDUCCION_MIN,
    ZONA_CONGESTION,
    punto_en_zona,
)
from backend.database import Database
from backend.hexagons import celdas_sobre_trazados
from backend.seed_data import emoji_vehiculo
from backend.simulation import Bus, Ruta, distancia_coordenadas_m, texto_espera
from backend.traffic import (
    TrafficRoutingError,
    create_traffic_flow,
    create_traffic_router,
    log_traffic_failure,
)

# Colombia no cambia de horario: UTC-5 todo el año. Se fija aquí porque el
# contenedor de Docker corre en UTC.
ZONA_HORARIA = timezone(timedelta(hours=-5), "COT")

# Un hexágono es "lento" cuando su vía va por debajo del 80 % de la velocidad libre.
UMBRAL_LENTO = 0.8
REDUCCION_MAX_TRAFICO = 0.85


def clasificar_trafico(current_kmh, free_kmh, closed=False):
    """Devuelve (reducción de velocidad, severidad o None si el tráfico fluye)."""
    if closed:
        return REDUCCION_MAX_TRAFICO, "severo"
    ratio = min(1.0, current_kmh / free_kmh)
    reduccion = min(REDUCCION_MAX_TRAFICO, 1 - ratio)
    if ratio >= UMBRAL_LENTO:
        return reduccion, None
    if ratio >= 0.6:
        return reduccion, "moderado"
    if ratio >= 0.4:
        return reduccion, "alto"
    return reduccion, "severo"


class TransitService:
    # Routing (about 2 calls per route) plus one Traffic Flow call per hexagon each
    # refresh; 600 s keeps a normal working day inside TomTom's free daily quota.
    TRAFFIC_REFRESH_SECONDS = int(os.environ.get("TOMTOM_REFRESCO_S", "600"))
    # The real wait grows with the number of calls so a day of use fits the free quota.
    TOMTOM_DAILY_QUOTA = int(os.environ.get("TOMTOM_CUOTA_DIARIA", "2500"))
    TOMTOM_USAGE_HOURS = float(os.environ.get("TOMTOM_HORAS_USO", "10"))
    # TomTom durations are divided by this so buses run 60 % faster than live traffic.
    TRAFFIC_SPEED_FACTOR = float(os.environ.get("SIMULADOR_FACTOR_VELOCIDAD", "1.6"))
    HEX_RADIUS_M = float(os.environ.get("TRAFICO_HEX_RADIO_M", "600"))
    # Safety cap only: every hexagon the routes cross is measured, so none is left out.
    HEX_MAX = int(os.environ.get("TRAFICO_HEX_MAX", "150"))

    def __init__(self, database=None):
        self.database = database or Database()
        self.database.initialize()
        self._lock = threading.RLock()
        self._traffic_router = create_traffic_router()
        self._traffic_flow = create_traffic_flow()
        self._traffic_routes = {}
        self._traffic_cells = None          # None: sin medición, se usa la zona simulada
        self._traffic_interval_s = self.TRAFFIC_REFRESH_SECONDS
        self._route_cache = {}
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
            calls = self._refresh_traffic_routes() + self._refresh_traffic_cells()
            self._traffic_interval_s = self._refresh_interval(calls)
            self._traffic_refresh_requested.wait(self._traffic_interval_s)
            self._traffic_refresh_requested.clear()

    def _refresh_interval(self, calls):
        """Seconds to wait so TOMTOM_USAGE_HOURS of use stay inside the daily quota."""
        budget = calls * self.TOMTOM_USAGE_HOURS * 3600 / self.TOMTOM_DAILY_QUOTA
        return max(self.TRAFFIC_REFRESH_SECONDS, budget)

    def _refresh_traffic_routes(self):
        """Recalcula las rutas con TomTom; devuelve cuántas consultas hizo."""
        if self._traffic_router is None:
            return 0
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
        # Una consulta por sentido: las circulares solo tienen ida.
        return sum(1 if route["circular"] else 2 for route in routes)

    def _refresh_traffic_cells(self):
        """
        Mide con TomTom Traffic Flow la velocidad real en cada hexágono de los
        recorridos; devuelve cuántas consultas hizo. Si un hexágono no responde
        se reintenta, luego se usa su medición anterior y, si no hay, queda
        "sin_dato": así ningún tramo de ruta se queda sin su hexágono.
        """
        if self._traffic_flow is None:
            return 0
        with self._lock:
            routes = [self._route_with_traffic(route) for route in self.database.list_routes()]
        trazados = [route["coordenadas"] for route in routes] + [
            route["coordenadas_regreso"] for route in routes if route["coordenadas_regreso"]
        ]
        previous = {
            cell["id"]: cell for cell in (self._traffic_cells or {}).get("cells", [])
            if cell["severidad"] != "sin_dato"
        }
        cells = []
        calls = measured = failures = 0
        for cell in celdas_sobre_trazados(trazados, self.HEX_RADIUS_M, self.HEX_MAX):
            speed = None
            for attempt in range(2):
                if attempt:
                    self._traffic_stop.wait(1)      # un respiro antes de reintentar
                calls += 1
                try:
                    speed = self._traffic_flow.speed(cell["consulta"])
                    break
                except TrafficRoutingError as error:
                    last_error = error
            if speed is None:
                failures += 1
                if not measured and failures >= 3:  # clave sin Traffic API o sin conexión
                    logging.warning("TomTom Traffic Flow no disponible: %s", last_error)
                    break
                old = previous.get(cell["id"])
                cells.append({**old, **cell} if old else {
                    **cell, "current_kmh": None, "free_kmh": None, "closed": False,
                    "confidence": None, "reduccion": 0.0, "severidad": "sin_dato",
                })
                continue
            measured += 1
            reduccion, severidad = clasificar_trafico(
                speed["current_kmh"], speed["free_kmh"], speed["closed"]
            )
            cells.append({**cell, **speed, "reduccion": reduccion, "severidad": severidad})

        with self._lock:
            if measured:                            # si todo falla se conserva la medición anterior
                self._traffic_cells = {
                    "cells": cells,
                    "updated_at": datetime.now(ZONA_HORARIA).strftime("%H:%M"),
                }
        return calls

    def _zones(self):
        """Zonas lentas medidas por TomTom, o None para usar la zona simulada."""
        if self._traffic_cells is None:
            return None
        return [
            {"poligono": cell["poligono"], "reduccion": cell["reduccion"]}
            for cell in self._traffic_cells["cells"]
            if cell["severidad"] in ("moderado", "alto", "severo")
        ]

    def _build_route(self, route_data, zones):
        # Ruta precalcula geometría y horarios; se reutiliza mientras nada cambie.
        key = json.dumps([route_data, zones], sort_keys=True)
        cached = self._route_cache.get(route_data["codigo"])
        if cached and cached[0] == key:
            return cached[1]
        route = Ruta(route_data, zones)
        self._route_cache[route_data["codigo"]] = (key, route)
        return route

    def snapshot(self, selected_stop=""):
        with self._lock:
            # Tiempo real: los buses se ubican según los segundos transcurridos hoy.
            clock = datetime.now(ZONA_HORARIA)
            elapsed = (
                clock - clock.replace(hour=0, minute=0, second=0, microsecond=0)
            ).total_seconds()
            zones = self._zones()
            routes = [
                self._build_route(
                    self._route_with_traffic(route_data, free_flow=zones is not None),
                    zones,
                )
                for route_data in self.database.list_routes()
            ]
            self._route_cache = {
                route.codigo: self._route_cache[route.codigo] for route in routes
            }
            route_data = [self._serialize_route(route) for route in routes]
            routes_by_name = {route.nombre: route for route in routes}
            buses = []
            for route in routes:
                for number in range(1, route.n_buses + 1):
                    bus = Bus(route, number, (number - 1) * route.ciclo_s / route.n_buses)
                    buses.append(bus)

            # Los buses propios de cada ruta son buses urbanos; los registrados usan su tipo.
            vehicle_types = {}
            for vehicle in self.database.list_bus_vehicles():
                route = routes_by_name[vehicle["ruta"]]
                bus = Bus(route, len([b for b in buses if b.ruta is route]) + 1, 0)
                bus.nombre = vehicle["placa"]
                buses.append(bus)
                vehicle_types[bus.nombre] = vehicle["tipo"]

            bus_states = []
            arrivals = []
            for bus in buses:
                lat, lon, next_stop, remaining = bus.estado(elapsed)
                speed_kmh = round(bus.velocidad_actual_kmh(elapsed), 1)
                vehicle_type = vehicle_types.get(bus.nombre, "Bus urbano")
                bus_states.append({
                    "name": bus.nombre,
                    "route_code": bus.ruta.codigo,
                    "color": bus.ruta.color,
                    "vehicle_type": vehicle_type,
                    "emoji": emoji_vehiculo(vehicle_type),
                    "latitude": lat,
                    "longitude": lon,
                    "next_stop": next_stop,
                    "seconds_remaining": remaining,
                    "remaining_text": texto_espera(remaining),
                    "arrival_time": (clock + timedelta(seconds=remaining)).strftime("%H:%M"),
                    "speed_kmh": speed_kmh,
                })
                if selected_stop:
                    result = bus.segundos_hasta(elapsed, selected_stop)
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
            stops = self._stops(route_data)
            return {
                "routes": route_data,
                "vehicles": self.database.list_vehicles(),
                "buses": bus_states,
                "arrivals": arrivals,
                "stops": stops,
                "clock": clock.strftime("%H:%M:%S"),
                "traffic": dict(self._traffic_status),
                "traffic_zones": self._serialize_zones(bus_states, stops),
            }

    def _serialize_zones(self, bus_states, stops):
        def buses_in(polygon):
            return sum(
                punto_en_zona((bus["latitude"], bus["longitude"]), polygon)
                for bus in bus_states
            )

        if self._traffic_cells is None:
            return {
                "mode": "simulada",
                "updated_at": None,
                "measured": 0,
                "min_slowdown": REDUCCION_MIN,
                "max_slowdown": REDUCCION_MAX,
                "zones": [{
                    "id": "simulada",
                    "polygon": ZONA_CONGESTION,
                    "label": "Zona de congestión simulada",
                    "severity": "simulada",
                    "current_kmh": None,
                    "free_kmh": None,
                    "slowdown": None,
                    "closed": False,
                    "buses": buses_in(ZONA_CONGESTION),
                }],
            }

        zones = []
        for cell in self._traffic_cells["cells"]:
            nearest = min(
                stops,
                key=lambda stop: distancia_coordenadas_m(
                    cell["centro"], (stop["latitud"], stop["longitud"])
                ),
                default=None,
            )
            zones.append({
                "id": cell["id"],
                "polygon": cell["poligono"],
                "center": cell["centro"],
                "label": f"Cerca de {nearest['nombre']}" if nearest else cell["id"],
                # Los hexágonos fluidos también se envían para pintarlos en el mapa.
                "severity": cell["severidad"] or "fluido",
                "current_kmh": cell["current_kmh"],
                "free_kmh": cell["free_kmh"],
                "slowdown": round(cell["reduccion"], 2),
                "closed": cell["closed"],
                "buses": buses_in(cell["poligono"]),
            })
        zones.sort(key=lambda zone: zone["slowdown"], reverse=True)
        return {
            "mode": "tomtom",
            "updated_at": self._traffic_cells["updated_at"],
            "measured": len(self._traffic_cells["cells"]),
            "refresh_minutes": round(self._traffic_interval_s / 60),
            "zones": zones,
        }

    def _route_with_traffic(self, route_data, free_flow=False):
        """
        Aplica el trazado y los tiempos de TomTom. Con free_flow se usan los
        tiempos sin tráfico tal cual, porque el tráfico real lo ponen los
        hexágonos; si no, los tiempos con tráfico se aceleran con el factor.
        """
        traffic_route = self._traffic_routes.get(route_data["codigo"])
        if traffic_route is None:
            return route_data
        durations = {}
        for direction in ("ida", "regreso"):
            seconds = [
                value / self.TRAFFIC_SPEED_FACTOR
                for value in traffic_route[f"duraciones_tramos_{direction}_s"]
            ]
            if free_flow:
                seconds = traffic_route.get(f"duraciones_libres_{direction}_s") or seconds
            durations[f"duraciones_tramos_{direction}_s"] = seconds
        return {**route_data, **traffic_route, **durations}

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

    def remove_route_bus(self, code):
        with self._lock:
            route = next(
                (route for route in self.database.list_routes() if route["codigo"] == code),
                None,
            )
            if route is None:
                raise LookupError("La ruta solicitada no existe.")
            if not self.database.remove_route_bus(code):
                raise ValueError(
                    "La ruta debe conservar al menos un bus; elimina la ruta completa."
                )

    def create_vehicle(self, vehicle):
        with self._lock:
            self.database.create_vehicle(vehicle)

    def delete_vehicle(self, plate):
        with self._lock:
            if not self.database.delete_vehicle(plate):
                raise LookupError("El vehículo solicitado no existe.")
