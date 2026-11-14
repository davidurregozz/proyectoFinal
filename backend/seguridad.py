"""Seguridad de la API: autenticación, límites, cabeceras y registro de eventos.

Todo pasa por SeguridadMiddleware, que se aplica a cada petición en este orden:

1. /docs, /redoc y /openapi.json no se muestran desde internet.
2. Límite de peticiones por IP (429), más estricto para el contador de visitas
   y para los intentos con token incorrecto.
3. Tamaño máximo del cuerpo (413) y sin cuerpos "chunked" sin longitud (411).
4. Desde internet (túnel de Cloudflare) solo se permite leer (403).
5. Crear, editar o borrar exige el token de administración (401).
6. Cabeceras de seguridad en todas las respuestas (CSP, anti-clickjacking...).

El token sale de SIMULADOR_API_TOKEN o, si no está, se genera una vez y se
guarda en data/api_token (permisos 600). El dashboard lo lee del mismo sitio.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

log = logging.getLogger("simulador.seguridad")

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
# Contar un ingreso a la app móvil no cambia rutas ni vehículos.
INTERNET_WRITE_ALLOWED = {"/api/visitas"}
RUTAS_DOCUMENTACION = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
LONGITUD_MINIMA_TOKEN = 16

# App móvil: Leaflet desde unpkg y teselas de Esri y OpenStreetMap.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://unpkg.com",
        # Leaflet posiciona el mapa con estilos en línea.
        "style-src 'self' https://unpkg.com 'unsafe-inline'",
        "img-src 'self' data: https://unpkg.com https://server.arcgisonline.com "
        "https://tile.openstreetmap.org",
        "connect-src 'self'",
        "font-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
CABECERAS_BASE = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}


def _entero_env(nombre: str, defecto: int) -> int:
    try:
        return max(1, int(os.environ.get(nombre, defecto)))
    except ValueError:
        return defecto


# --------------------------------------------------------------------------- #
# Token de administración
# --------------------------------------------------------------------------- #
def ruta_token() -> Path:
    """Archivo del token: SIMULADOR_TOKEN_PATH o api_token junto a la base de datos."""
    if os.environ.get("SIMULADOR_TOKEN_PATH"):
        return Path(os.environ["SIMULADOR_TOKEN_PATH"])
    from backend.database import DATABASE_PATH

    return DATABASE_PATH.parent / "api_token"


def leer_token() -> str | None:
    """Token configurado, sin crearlo. Lo usa el cliente del dashboard."""
    token = os.environ.get("SIMULADOR_API_TOKEN", "").strip()
    if token:
        return token
    try:
        return ruta_token().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def cargar_o_crear_token() -> str:
    """Token del servidor; si no hay ninguno se genera uno aleatorio de 256 bits."""
    token = os.environ.get("SIMULADOR_API_TOKEN", "").strip()
    if token:
        if len(token) < LONGITUD_MINIMA_TOKEN:
            raise ValueError(
                f"SIMULADOR_API_TOKEN debe tener al menos {LONGITUD_MINIMA_TOKEN} caracteres."
            )
        return token

    ruta = ruta_token()
    existente = leer_token()
    if existente:
        return existente
    token = secrets.token_urlsafe(32)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
        archivo.write(token + "\n")
    log.warning("Se generó el token de administración de la API en %s", ruta)
    return token


def token_valido(recibido: str | None, esperado: str) -> bool:
    """Comparación en tiempo constante para no filtrar el token por tiempos."""
    if not recibido:
        return False
    return hmac.compare_digest(recibido.encode("utf-8"), esperado.encode("utf-8"))


def token_de_cabeceras(headers: Headers) -> str | None:
    autorizacion = headers.get("authorization", "")
    esquema, _, valor = autorizacion.partition(" ")
    if esquema.lower() == "bearer" and valor.strip():
        return valor.strip()
    return headers.get("x-api-token") or None


# --------------------------------------------------------------------------- #
# Reglas
# --------------------------------------------------------------------------- #
def es_escritura(method: str, path: str) -> bool:
    return method.upper() not in READ_METHODS and path not in INTERNET_WRITE_ALLOWED


def is_internet_write(method, path, headers):
    """
    True para un cambio (crear, editar, borrar) que llega desde internet. Cloudflare
    añade CF-Connecting-IP a todo lo que reenvía y el cliente no puede quitarla;
    el dashboard habla con el backend por la red interna de Docker, sin ella.
    """
    return es_escritura(method, path) and "cf-connecting-ip" in headers


def ip_cliente(scope, headers: Headers) -> str:
    if headers.get("cf-connecting-ip"):
        return headers["cf-connecting-ip"].strip()
    cliente = scope.get("client")
    return cliente[0] if cliente else "desconocida"


class LimitadorFrecuencia:
    """Ventana fija por clave (IP + tipo de petición). Seguro entre hilos."""

    MAX_CLAVES = 10_000

    def __init__(self, reloj=time.monotonic):
        self._reloj = reloj
        self._ventanas: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def _limpiar(self, ahora: float, ventana_s: float):
        vencidas = [k for k, (inicio, _) in self._ventanas.items() if ahora - inicio >= ventana_s]
        for clave in vencidas:
            del self._ventanas[clave]

    def contar(self, clave: str, limite: int, ventana_s: float) -> int:
        """Registra un intento. Devuelve 0 si se permite, o los segundos de espera."""
        ahora = self._reloj()
        with self._lock:
            if len(self._ventanas) > self.MAX_CLAVES:
                self._limpiar(ahora, ventana_s)
            inicio, cuenta = self._ventanas.get(clave, (ahora, 0))
            if ahora - inicio >= ventana_s:
                inicio, cuenta = ahora, 0
            if cuenta >= limite:
                return max(1, int(ventana_s - (ahora - inicio)) + 1)
            self._ventanas[clave] = (inicio, cuenta + 1)
            return 0

    def superado(self, clave: str, limite: int, ventana_s: float) -> int:
        """Como contar, pero sin registrar el intento."""
        ahora = self._reloj()
        with self._lock:
            inicio, cuenta = self._ventanas.get(clave, (ahora, 0))
            if ahora - inicio >= ventana_s or cuenta < limite:
                return 0
            return max(1, int(ventana_s - (ahora - inicio)) + 1)


def cabeceras_seguridad(path: str, https: bool) -> dict[str, str]:
    cabeceras = dict(CABECERAS_BASE)
    # Swagger y ReDoc usan scripts en línea y CDN propios: se dejan sin CSP.
    if path not in RUTAS_DOCUMENTACION:
        cabeceras["content-security-policy"] = CSP
    if path.startswith("/api/"):
        cabeceras["cache-control"] = "no-store"
    if https:
        cabeceras["strict-transport-security"] = "max-age=31536000; includeSubDomains"
    return cabeceras


# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #
class SeguridadMiddleware:
    """Middleware ASGI que aplica todas las reglas de seguridad."""

    def __init__(self, app, obtener_token=None, limitador=None):
        self.app = app
        self._obtener_token = obtener_token or cargar_o_crear_token
        self._token: str | None = None
        self.limitador = limitador or LimitadorFrecuencia()
        self.max_cuerpo = _entero_env("SIMULADOR_MAX_BODY_BYTES", 1_000_000)
        self.limite_api = _entero_env("SIMULADOR_LIMITE_API_MIN", 600)
        self.limite_escrituras = _entero_env("SIMULADOR_LIMITE_ESCRITURAS_MIN", 60)
        self.limite_visitas = _entero_env("SIMULADOR_LIMITE_VISITAS_MIN", 20)
        self.limite_fallos = _entero_env("SIMULADOR_LIMITE_FALLOS_TOKEN", 10)

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = self._obtener_token()
        return self._token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"].upper()
        path = scope["path"]
        headers = Headers(scope=scope)
        ip = ip_cliente(scope, headers)
        desde_internet = "cf-connecting-ip" in headers
        https = desde_internet or headers.get("x-forwarded-proto", "").lower() == "https"
        extra = cabeceras_seguridad(path, https)

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                actuales = Headers(raw=mensaje.get("headers", []))
                raw = list(mensaje.get("headers", []))
                for nombre, valor in extra.items():
                    if nombre not in actuales:
                        raw.append((nombre.encode("latin-1"), valor.encode("latin-1")))
                mensaje = {**mensaje, "headers": raw}
            await send(mensaje)

        async def rechazar(codigo: int, detalle: str, evento: str, cabeceras=None):
            log.warning("%s: %s %s desde %s", evento, method, path, ip)
            respuesta = JSONResponse({"detail": detalle}, status_code=codigo, headers=cabeceras)
            await respuesta(scope, receive, enviar)

        # 1. Documentación de la API oculta desde internet.
        if desde_internet and path in RUTAS_DOCUMENTACION:
            await rechazar(404, "Not Found", "Documentación pedida desde internet")
            return

        # 2. Límites de frecuencia.
        if path.startswith("/api/"):
            escritura = es_escritura(method, path)
            reglas = [(f"api:{ip}", self.limite_api)]
            if path in INTERNET_WRITE_ALLOWED and method not in READ_METHODS:
                reglas.append((f"visitas:{ip}", self.limite_visitas))
            if escritura:
                reglas.append((f"escritura:{ip}", self.limite_escrituras))
            for clave, limite in reglas:
                espera = self.limitador.contar(clave, limite, 60)
                if espera:
                    await rechazar(
                        429,
                        "Demasiadas peticiones; espera un momento.",
                        "Límite de peticiones",
                        {"retry-after": str(espera)},
                    )
                    return

        # 3. Tamaño del cuerpo.
        if method not in READ_METHODS:
            if "chunked" in headers.get("transfer-encoding", "").lower():
                await rechazar(411, "Se requiere Content-Length.", "Cuerpo sin longitud")
                return
            try:
                longitud = int(headers.get("content-length", "0"))
            except ValueError:
                longitud = -1
            if longitud < 0 or longitud > self.max_cuerpo:
                await rechazar(413, "La petición es demasiado grande.", "Cuerpo demasiado grande")
                return

        # 4 y 5. Solo lectura desde internet y token para los cambios.
        if es_escritura(method, path):
            if desde_internet:
                await rechazar(
                    403, "Desde internet la aplicación es de solo lectura.", "Escritura desde internet"
                )
                return
            clave_fallos = f"fallos:{ip}"
            espera = self.limitador.superado(clave_fallos, self.limite_fallos, 300)
            if espera:
                await rechazar(
                    429,
                    "Demasiados intentos con token incorrecto; espera unos minutos.",
                    "IP bloqueada por fallos de token",
                    {"retry-after": str(espera)},
                )
                return
            if not token_valido(token_de_cabeceras(headers), self.token):
                self.limitador.contar(clave_fallos, self.limite_fallos, 300)
                await rechazar(
                    401,
                    "Se requiere el token de administración.",
                    "Token ausente o incorrecto",
                    {"www-authenticate": "Bearer"},
                )
                return

        await self.app(scope, receive, enviar)
