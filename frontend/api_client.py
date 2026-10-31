"""HTTP client used by the desktop dashboard to access the REST backend."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    """A network failure or explicit error response from the backend."""


class ApiClient:
    def __init__(self, base_url="http://127.0.0.1:8000", timeout=2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
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
        return self._request("DELETE", f"/api/routes/{code}")

    def create_vehicle(self, vehicle):
        return self._request("POST", "/api/vehicles", vehicle)

    def set_control(self, paused, factor):
        return self._request(
            "PUT",
            "/api/simulation/control",
            {"paused": paused, "factor": factor},
        )
