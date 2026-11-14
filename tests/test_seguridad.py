"""Autenticación, límites, cabeceras y validación de la API."""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import RouteInput, app as app_real
from backend.seguridad import (
    CSP,
    LimitadorFrecuencia,
    SeguridadMiddleware,
    cargar_o_crear_token,
    token_valido,
)

TOKEN = "token-de-pruebas-1234567890"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
INTERNET = {"CF-Connecting-IP": "203.0.113.7"}

# Los rechazos se registran como avisos; en las pruebas no hacen falta.
logging.getLogger("simulador.seguridad").setLevel(logging.CRITICAL)


def crear_app(**limites):
    app = FastAPI()

    @app.get("/api/dashboard")
    def leer():
        return {"ok": True}

    @app.post("/api/routes")
    def crear(datos: dict):
        return {"creado": datos}

    @app.delete("/api/vehicles/{placa}")
    def borrar(placa: str):
        return {"borrado": placa}

    @app.post("/api/visitas")
    def visita():
        return {"total": 1}

    @app.get("/movil/")
    def movil():
        return {"html": True}

    with mock.patch.dict(os.environ, {k: str(v) for k, v in limites.items()}):
        app.add_middleware(SeguridadMiddleware, obtener_token=lambda: TOKEN)
        cliente = TestClient(app)
        cliente.get("/movil/")  # construye el middleware con estos límites
    return cliente


class AutenticacionTests(unittest.TestCase):
    def setUp(self):
        self.cliente = crear_app()

    def test_lectura_no_requiere_token(self):
        self.assertEqual(self.cliente.get("/api/dashboard").status_code, 200)

    def test_escritura_sin_token_o_con_token_incorrecto_se_rechaza(self):
        respuesta = self.cliente.post("/api/routes", json={"a": 1})
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(respuesta.headers["www-authenticate"], "Bearer")
        mala = {"Authorization": "Bearer otro-token-cualquiera"}
        self.assertEqual(self.cliente.delete("/api/vehicles/ABC", headers=mala).status_code, 401)

    def test_escritura_con_token_se_permite(self):
        self.assertEqual(self.cliente.post("/api/routes", json={"a": 1}, headers=AUTH).status_code, 200)
        self.assertEqual(
            self.cliente.delete("/api/vehicles/ABC", headers={"X-API-Token": TOKEN}).status_code, 200
        )

    def test_desde_internet_solo_lectura_aunque_tenga_token(self):
        respuesta = self.cliente.post("/api/routes", json={}, headers={**AUTH, **INTERNET})
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.cliente.get("/api/dashboard", headers=INTERNET).status_code, 200)

    def test_visitas_no_requieren_token_ni_desde_internet(self):
        self.assertEqual(self.cliente.post("/api/visitas", headers=INTERNET).status_code, 200)

    def test_comparacion_de_token(self):
        self.assertTrue(token_valido(TOKEN, TOKEN))
        self.assertFalse(token_valido(TOKEN[:-1], TOKEN))
        self.assertFalse(token_valido(None, TOKEN))


class LimitesTests(unittest.TestCase):
    def test_limite_de_visitas_por_ip(self):
        cliente = crear_app(SIMULADOR_LIMITE_VISITAS_MIN=3)
        codigos = [cliente.post("/api/visitas").status_code for _ in range(4)]
        self.assertEqual(codigos, [200, 200, 200, 429])

    def test_limite_por_ip_separa_clientes(self):
        cliente = crear_app(SIMULADOR_LIMITE_API_MIN=2)
        for _ in range(2):
            cliente.get("/api/dashboard", headers=INTERNET)
        bloqueada = cliente.get("/api/dashboard", headers=INTERNET)
        self.assertEqual(bloqueada.status_code, 429)
        self.assertIn("retry-after", bloqueada.headers)
        otra = cliente.get("/api/dashboard", headers={"CF-Connecting-IP": "198.51.100.1"})
        self.assertEqual(otra.status_code, 200)

    def test_bloqueo_tras_fallos_de_token(self):
        cliente = crear_app(SIMULADOR_LIMITE_FALLOS_TOKEN=3)
        for _ in range(3):
            self.assertEqual(cliente.post("/api/routes", json={}).status_code, 401)
        # Ni siquiera el token correcto pasa mientras dura el bloqueo.
        self.assertEqual(cliente.post("/api/routes", json={}, headers=AUTH).status_code, 429)

    def test_cuerpo_demasiado_grande(self):
        cliente = crear_app(SIMULADOR_MAX_BODY_BYTES=100)
        respuesta = cliente.post("/api/routes", json={"x": "a" * 200}, headers=AUTH)
        self.assertEqual(respuesta.status_code, 413)

    def test_ventana_del_limitador_se_reinicia(self):
        ahora = [0.0]
        limitador = LimitadorFrecuencia(reloj=lambda: ahora[0])
        self.assertEqual(limitador.contar("k", 1, 60), 0)
        self.assertGreater(limitador.contar("k", 1, 60), 0)
        ahora[0] = 61
        self.assertEqual(limitador.contar("k", 1, 60), 0)


class CabecerasTests(unittest.TestCase):
    def test_cabeceras_de_seguridad(self):
        respuesta = crear_app().get("/movil/")
        self.assertEqual(respuesta.headers["content-security-policy"], CSP)
        self.assertEqual(respuesta.headers["x-frame-options"], "DENY")
        self.assertEqual(respuesta.headers["x-content-type-options"], "nosniff")
        self.assertEqual(respuesta.headers["referrer-policy"], "no-referrer")
        self.assertNotIn("strict-transport-security", respuesta.headers)

    def test_hsts_y_no_store_por_https(self):
        respuesta = crear_app().get("/api/dashboard", headers=INTERNET)
        self.assertIn("max-age=", respuesta.headers["strict-transport-security"])
        self.assertEqual(respuesta.headers["cache-control"], "no-store")

    def test_csp_no_permite_scripts_en_linea_ni_iframes(self):
        self.assertNotIn("'unsafe-inline'", CSP.split("script-src")[1].split(";")[0])
        self.assertIn("frame-ancestors 'none'", CSP)


class AppRealTests(unittest.TestCase):
    def setUp(self):
        parche = mock.patch.dict(os.environ, {"SIMULADOR_API_TOKEN": TOKEN})
        parche.start()
        self.addCleanup(parche.stop)
        self.cliente = TestClient(app_real)

    def test_app_real_exige_token_para_cambios(self):
        self.assertEqual(self.cliente.delete("/api/vehicles/ABC123").status_code, 401)
        self.assertEqual(self.cliente.post("/api/routes", json={}).status_code, 401)

    def test_documentacion_oculta_desde_internet(self):
        self.assertEqual(self.cliente.get("/openapi.json").status_code, 200)
        self.assertEqual(self.cliente.get("/docs", headers=INTERNET).status_code, 404)
        self.assertEqual(self.cliente.get("/openapi.json", headers=INTERNET).status_code, 404)


class ValidacionTests(unittest.TestCase):
    BASE = {
        "codigo": "R9",
        "nombre": "Ruta de prueba",
        "municipio": "Medellín",
        "color": "#112233",
        "velocidad_kmh": 20,
        "buses": 1,
        "circular": False,
        "paradas": [["A", 6.2, -75.5], ["B", 6.3, -75.6]],
        "coordenadas": [[6.2, -75.5], [6.3, -75.6]],
    }

    def test_ruta_valida(self):
        RouteInput(**self.BASE)

    def test_rechaza_codigo_con_caracteres_especiales(self):
        with self.assertRaises(ValidationError):
            RouteInput(**{**self.BASE, "codigo": "R1/../x"})

    def test_rechaza_nombre_de_parada_enorme_y_trazados_gigantes(self):
        with self.assertRaises(ValidationError):
            RouteInput(**{**self.BASE, "paradas": [["A" * 500, 6.2, -75.5], ["B", 6.3, -75.6]]})
        with self.assertRaises(ValidationError):
            RouteInput(**{**self.BASE, "coordenadas": [[6.2, -75.5]] * 20_001})


class TokenTests(unittest.TestCase):
    def test_token_generado_es_aleatorio_persistente_y_privado(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "api_token"
            entorno = {"SIMULADOR_TOKEN_PATH": str(ruta), "SIMULADOR_API_TOKEN": ""}
            with mock.patch.dict(os.environ, entorno):
                primero = cargar_o_crear_token()
                self.assertGreaterEqual(len(primero), 40)
                self.assertEqual(cargar_o_crear_token(), primero)
                if os.name == "posix":
                    self.assertEqual(ruta.stat().st_mode & 0o777, 0o600)

    def test_token_corto_en_entorno_se_rechaza(self):
        with mock.patch.dict(os.environ, {"SIMULADOR_API_TOKEN": "corto"}):
            with self.assertRaises(ValueError):
                cargar_o_crear_token()


if __name__ == "__main__":
    unittest.main()
