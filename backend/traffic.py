"""TomTom route calculations using current traffic conditions."""

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


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

    @property
    def available(self):
        return bool(self.api_key)

    def optimize(self, route):
        if not self.available:
            raise TrafficRoutingError("Falta configurar TOMTOM_API_KEY.")

        stops = [(lat, lon) for _, lat, lon in route["paradas"]]
        forward_stops = stops + [stops[0]] if route["circular"] else stops
        forward, forward_times = self._calculate(forward_stops)

        if route["circular"]:
            reverse = []
            reverse_times = []
        else:
            reverse, reverse_times = self._calculate(list(reversed(stops)))

        return {
            "coordenadas": forward,
            "coordenadas_regreso": reverse,
            "duraciones_tramos_ida_s": forward_times,
            "duraciones_tramos_regreso_s": reverse_times,
        }

    def _calculate(self, stops):
        locations = ":".join(
            f"{latitude:.6f},{longitude:.6f}"
            for latitude, longitude in stops
        )
        query = urlencode({
            "key": self.api_key,
            "traffic": "true",
            "routeType": "fastest",
            "departAt": "now",
            "travelMode": "bus",
        })
        url = f"{self.BASE_URL}/{quote(locations, safe=',:.-')}/json?{query}"
        request = Request(url, headers={"Accept": "application/json"})
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
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise TrafficRoutingError(
                "La respuesta de TomTom no contiene una ruta compatible."
            ) from error

        return geometry, durations


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
