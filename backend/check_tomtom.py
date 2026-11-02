"""Check TOMTOM_API_KEY against TomTom Routing: python -m backend.check_tomtom"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from backend.env import ENV_PATH, load_env_file
from backend.seed_data import RUTAS
from backend.traffic import TomTomTrafficRouter, TrafficRoutingError


CAUSAS = {
    400: "Petición inválida; revisa que la clave esté completa.",
    401: "Clave inválida o incompleta (una clave real tiene unos 32 caracteres).",
    403: "Clave rechazada: incorrecta, deshabilitada o sin el producto Routing API.",
    429: "Se agotó la cuota de solicitudes de la cuenta; espera o revisa el plan.",
}


def main():
    load_env_file()
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if not key:
        print(f"[X] TOMTOM_API_KEY está vacía. Pégala en {ENV_PATH} y guarda el archivo.")
        return 1
    print(f"[OK] Clave encontrada ({len(key)} caracteres, termina en ...{key[-4:]}).")

    url = (
        "https://api.tomtom.com/routing/1/calculateRoute/"
        "6.244200,-75.581200:6.251800,-75.563600/json?" + urlencode({"key": key})
    )
    try:
        with urlopen(url, timeout=10) as response:
            json.loads(response.read().decode("utf-8"))
        print("[OK] TomTom Routing API respondió correctamente.")
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8"))
            detail = detail.get("detailedError", {}).get("message") or detail
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = error.reason
        print(f"[X] TomTom respondió HTTP {error.code}: {detail}")
        print("    " + CAUSAS.get(error.code, "Revisa la clave en developer.tomtom.com."))
        return 1
    except (URLError, TimeoutError, OSError) as error:
        print(f"[X] Sin conexión con api.tomtom.com ({type(error).__name__}).")
        print("    Revisa internet, el firewall o el proxy de la red.")
        return 1

    try:
        TomTomTrafficRouter(key).optimize(RUTAS[0])
        print(f"[OK] Ruta '{RUTAS[0]['nombre']}' optimizada con tráfico en vivo.")
    except TrafficRoutingError as error:
        print(f"[X] La prueba simple funcionó pero la ruta del simulador falló: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
