"""TomTom bus routes over the real road network and live road speeds (Traffic Flow)."""

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backend.simulation import distancia_coordenadas_m

# A leg is a detour when it is twice the straight line and at least 800 m longer:
# TomTom goes to a far U-turn just to touch a stop placed on the opposite
# carriageway or on a metro station. Going around one downtown block is normal.
DETOUR_FACTOR = 2.0
DETOUR_EXTRA_M = 800
# Farthest a direction's bus stop may be from the stop drawn on the map.
MAX_STOP_OFFSET_M = 300
# Two stops closer than this would give TomTom a zero-length leg.
MIN_STOP_GAP_M = 60


class TrafficRoutingError(RuntimeError):
    """The live traffic provider could not produce a usable route."""


class TomTomTrafficRouter:
    BASE_URL = "https://api.tomtom.com/routing/1/calculateRoute"

    def __init__(self, api_key=None, timeout=8):
        self.api_key = (
            api_key if api_key is not None
            else os.environ.get("TOMTOM_API_KEY", "").strip()
        )
        self.timeout = timeout
        # Bus stop points per direction; the road network does not change with
        # traffic, so they are located once per route and reused.
        self._stop_points = {}
        # Like a real bus line, a route keeps its path whatever the traffic: it is
        # drawn once and reused; live traffic only slows buses down (hexagons).
        self._routes = {}
        self.calls = 0                                 # HTTP calls made, for the quota

    @property
    def available(self):
        return bool(self.api_key)

    def optimize(self, route):
        if not self.available:
            raise TrafficRoutingError("Falta configurar TOMTOM_API_KEY.")
        key = (tuple(tuple(stop) for stop in route["paradas"]), route["circular"])
        if key not in self._routes:
            self._routes[key] = self._draw(route)
        return self._routes[key]

    def _draw(self, route):
        stops = [(lat, lon) for _, lat, lon in route["paradas"]]
        circular = route["circular"]
        forward_points = self._direction_stop_points(stops, circular)
        forward, forward_times, forward_free = self._calculate(
            forward_points + [forward_points[0]] if circular else forward_points
        )

        if circular:
            reverse, reverse_times, reverse_free = [], [], []
            reverse_points = forward_points
        else:
            reverse_points = self._direction_stop_points(stops[::-1], False)[::-1]
            reverse, reverse_times, reverse_free = self._calculate(reverse_points[::-1])

        return {
            "coordenadas": forward,
            "coordenadas_regreso": reverse,
            # Where the bus actually stops in each direction, in stop order.
            "paraderos_ida": forward_points,
            "paraderos_regreso": reverse_points,
            "duraciones_tramos_ida_s": forward_times,
            "duraciones_tramos_regreso_s": reverse_times,
            # Same legs without traffic; used when traffic is applied per hexagon.
            "duraciones_libres_ida_s": forward_free,
            "duraciones_libres_regreso_s": reverse_free,
        }

    def _direction_stop_points(self, stops, circular):
        key = (tuple(stops), circular)
        if key not in self._stop_points:
            self._stop_points[key] = self._locate_stop_points(stops, circular)
        return self._stop_points[key]

    def _locate_stop_points(self, stops, circular):
        """
        Moves each stop that causes a detour onto the road the bus naturally takes
        in this direction, like a real bus stop on its side of the street: the
        point, at most MAX_STOP_OFFSET_M away, of the route that skips that stop.
        A route end has no "skip" route, so it keeps the closest point the leg
        reaches before (or after) looping around it.
        """
        points = list(stops)
        count = len(points)
        for _ in range(2):                              # a second pass catches knock-on loops
            visit = points + [points[0]] if circular else points
            geometry, _, _ = self._calculate(visit)
            indices = [0]
            for point in visit[1:]:
                indices.append(geometry.index(point, indices[-1] + 1))
            legs = [geometry[a:b + 1] for a, b in zip(indices, indices[1:])]
            culprits = sorted({
                index % count
                for leg_index, leg in enumerate(legs) if _is_detour(leg)
                for index in (leg_index, leg_index + 1)
            })
            changed = False
            for index in culprits:
                if not circular and index in (0, count - 1):
                    leg = legs[0] if index == 0 else legs[-1]
                    near = [p for p in leg if distancia_coordenadas_m(p, stops[index]) <= MAX_STOP_OFFSET_M]
                    candidate = near[-1] if index == 0 else near[0]
                else:
                    before, after = points[(index - 1) % count], points[(index + 1) % count]
                    if before == after:
                        continue
                    direct, _, _ = self._calculate([before, after])
                    candidate = min(direct, key=lambda p: distancia_coordenadas_m(p, stops[index]))
                    if distancia_coordenadas_m(candidate, stops[index]) > MAX_STOP_OFFSET_M:
                        continue                        # the stop really is off the road
                neighbours = [points[(index - 1) % count], points[(index + 1) % count]]
                if any(distancia_coordenadas_m(candidate, n) < MIN_STOP_GAP_M for n in neighbours):
                    continue                            # would merge with the next stop
                if tuple(candidate) != points[index]:
                    points[index] = tuple(candidate)
                    changed = True
            if not changed:
                break
        return points

    def _calculate(self, stops):
        locations = ":".join(
            f"{latitude:.6f},{longitude:.6f}"
            for latitude, longitude in stops
        )
        query = urlencode({
            "key": self.api_key,
            # Fixed path, not "fastest right now": traffic would make it change.
            "traffic": "false",
            "routeType": "fastest",
            "travelMode": "bus",
            "computeTravelTimeFor": "all",
        })
        url = f"{self.BASE_URL}/{quote(locations, safe=',:.-')}/json?{query}"
        request = Request(url, headers={"Accept": "application/json"})
        self.calls += 1
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError) as error:
            raise TrafficRoutingError(
                f"TomTom Routing no respondió ({type(error).__name__})."
            ) from error
        except json.JSONDecodeError as error:
            raise TrafficRoutingError("TomTom devolvió una respuesta JSON inválida.") from error

        try:
            route = payload["routes"][0]
            legs = route["legs"]
            if len(legs) != len(stops) - 1:
                raise ValueError("Número de tramos inesperado.")
            geometry = []
            durations = []
            free_durations = []
            for index, leg in enumerate(legs):
                points = [
                    (point["latitude"], point["longitude"])
                    for point in leg["points"]
                ]
                if len(points) < 2:
                    raise ValueError("Tramo sin geometría suficiente.")
                points[0] = stops[index]
                points[-1] = stops[index + 1]
                geometry.extend(points if not geometry else points[1:])
                duration = leg["summary"]["travelTimeInSeconds"]
                if not isinstance(duration, (int, float)) or duration <= 0:
                    raise ValueError("Duración de tramo inválida.")
                durations.append(float(duration))
                free_duration = leg["summary"].get("noTrafficTravelTimeInSeconds", duration)
                if not isinstance(free_duration, (int, float)) or free_duration <= 0:
                    free_duration = duration
                free_durations.append(float(free_duration))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise TrafficRoutingError(
                "La respuesta de TomTom no contiene una ruta compatible."
            ) from error

        return geometry, durations, free_durations


def _is_detour(leg):
    length = sum(distancia_coordenadas_m(a, b) for a, b in zip(leg, leg[1:]))
    straight = distancia_coordenadas_m(leg[0], leg[-1])
    return length > DETOUR_FACTOR * straight and length - straight > DETOUR_EXTRA_M


class TomTomTrafficFlow:
    """Current and free-flow speed of the road nearest to a point."""

    BASE_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/16/json"

    def __init__(self, api_key=None, timeout=8):
        self.api_key = (
            api_key if api_key is not None
            else os.environ.get("TOMTOM_API_KEY", "").strip()
        )
        self.timeout = timeout

    def speed(self, point):
        query = urlencode({
            "key": self.api_key,
            "point": f"{point[0]:.6f},{point[1]:.6f}",
            "unit": "KMPH",
        })
        request = Request(f"{self.BASE_URL}?{query}", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))["flowSegmentData"]
            current = float(data["currentSpeed"])
            free = float(data["freeFlowSpeed"])
            if free <= 0 or current < 0:
                raise ValueError("Velocidades inválidas.")
        except HTTPError as error:
            raise TrafficRoutingError(f"TomTom Traffic Flow respondió HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError, UnicodeDecodeError) as error:
            raise TrafficRoutingError(
                f"TomTom Traffic Flow no respondió ({type(error).__name__})."
            ) from error
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise TrafficRoutingError("TomTom Traffic Flow devolvió datos incompatibles.") from error
        return {
            "current_kmh": current,
            "free_kmh": free,
            "closed": bool(data.get("roadClosure", False)),
            "confidence": data.get("confidence"),
        }


def create_traffic_flow():
    flow = TomTomTrafficFlow()
    return flow if flow.api_key else None


def create_traffic_router():
    router = TomTomTrafficRouter()
    return router if router.available else None


def log_traffic_failure(route_code, error):
    logging.warning(
        "No se pudo actualizar la ruta %s con tráfico TomTom (%s). "
        "Se conserva la geometría guardada.",
        route_code,
        error,
    )
