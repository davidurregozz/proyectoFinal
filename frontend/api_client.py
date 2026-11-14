"""HTTP client used by the desktop dashboard to access the REST backend."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backend.seguridad import leer_token


class ApiError(RuntimeError):
    """A network failure or explicit error response from the backend."""


class ApiClient:
    def __init__(self, base_url=None, timeout=2, token=None):
        if base_url is None:
            base_url = os.environ.get("SIMULADOR_API_URL", "http://127.0.0.1:8000")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token

    @property
    def token(self):
        # Se lee en cada cambio: el backend puede crear el archivo después de abrir el dashboard.
        return self._token or leer_token()

    def _request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if method != "GET" and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                details = json.loads(error.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                details = {}
            message = details.get("detail", error.reason)
            raise ApiError(str(message)) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ApiError(
                "No se pudo conectar con el backend. Inicia el servidor REST "
                "y vuelve a intentarlo."
            ) from error

    def dashboard(self, selected_stop=""):
        query = urlencode({"parada": selected_stop}) if selected_stop else ""
        path = "/api/dashboard" + (f"?{query}" if query else "")
        return self._request("GET", path)

    def create_route(self, route):
        return self._request("POST", "/api/routes", route)

    def delete_route(self, code):
        return self._request("DELETE", f"/api/routes/{quote(code, safe='')}")

    def remove_route_bus(self, code):
        return self._request("DELETE", f"/api/routes/{quote(code, safe='')}/buses")

    def create_vehicle(self, vehicle):
        return self._request("POST", "/api/vehicles", vehicle)

    def delete_vehicle(self, plate):
        return self._request("DELETE", f"/api/vehicles/{quote(plate, safe='')}")
