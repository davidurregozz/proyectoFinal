"""Start the local API and desktop dashboard together."""

import json
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


HEALTH_URL = "http://127.0.0.1:8000/api/health"


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
    server = None
    if not backend_is_ready():
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.api:app",
                "--host",
                "127.0.0.1",
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

    try:
        from frontend.run import main as run_dashboard

        run_dashboard()
    finally:
        if server is not None:
            stop_server(server)


if __name__ == "__main__":
    main()
