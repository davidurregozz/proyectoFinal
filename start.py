"""Start the local API and desktop dashboard together."""

import json
import os
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from backend.env import load_env_file


HEALTH_URL = "http://127.0.0.1:8000/api/health"


def lan_address():
    """IP of this computer on the local network (the UDP connect sends no packets)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def stop_server(server):
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()


def backend_is_ready():
    try:
        with urlopen(HEALTH_URL, timeout=1) as response:
            return json.loads(response.read().decode("utf-8")).get("status") == "ok"
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False


def main():
    load_env_file()                 # the backend subprocess inherits these variables
    # 0.0.0.0 makes the API and the mobile app reachable from phones on the same Wi-Fi.
    host = os.environ.get("SIMULADOR_HOST") or "127.0.0.1"
    server = None
    if not backend_is_ready():
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.api:app",
                "--host",
                host,
                "--port",
                "8000",
            ]
        )
        for _ in range(40):
            if backend_is_ready():
                break
            if server.poll() is not None:
                raise RuntimeError("El servidor REST terminó antes de iniciar.")
            time.sleep(0.25)
        else:
            stop_server(server)
            raise RuntimeError("El servidor REST no respondió en el tiempo esperado.")

    if host == "0.0.0.0":
        print(f"App móvil: abre http://{lan_address()}:8000/movil/ en el celular (misma red Wi-Fi).")
    else:
        print("App móvil en este equipo: http://127.0.0.1:8000/movil/ "
              "(para el celular inicia con SIMULADOR_HOST=0.0.0.0).")

    try:
        from frontend.run import main as run_dashboard

        run_dashboard()
    finally:
        if server is not None:
            stop_server(server)


if __name__ == "__main__":
    main()
