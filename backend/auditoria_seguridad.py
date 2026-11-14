"""Auditoría de seguridad del proyecto: py -m backend.auditoria_seguridad

Revisa antes de publicar o abrir la app a la red:
- que .env, las claves privadas y el token no estén en git;
- que no haya secretos escritos en los archivos del repositorio;
- que el panel tenga contraseña si se abre a la red;
- la firma digital del código;
- vulnerabilidades conocidas en las dependencias (si pip-audit está instalado).

Termina con código 1 si encuentra algún problema grave.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from backend.env import load_env_file

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVOS_PROHIBIDOS = (".env", "firma/clave_privada.pem", "data/api_token")
VARIABLES_SECRETAS = (
    "TOMTOM_API_KEY",
    "VNC_PASSWORD",
    "SIMULADOR_API_TOKEN",
    "STADIA_MAPS_API_KEY",
    "CARTO_API_KEY",
    "ARCGIS_API_KEY",
    "FIRMA_CONTRASENA",
)
PATRONES_SECRETOS = [
    (re.compile(r"-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----"), "clave privada"),
    (
        re.compile(r"(?im)^\s*(?:" + "|".join(VARIABLES_SECRETAS) + r")\s*=\s*['\"]?[^\s'\"#]{6,}"),
        "variable secreta con valor",
    ),
    (re.compile(r"[?&]key=[A-Za-z0-9]{20,}"), "clave de API en una URL"),
]


class Informe:
    def __init__(self):
        self.graves = 0
        self.avisos = 0

    def ok(self, texto):
        print(f"[OK] {texto}")

    def aviso(self, texto):
        self.avisos += 1
        print(f"[!]  {texto}")

    def grave(self, texto):
        self.graves += 1
        print(f"[X]  {texto}")


def _git(*args) -> list[str] | None:
    try:
        salida = subprocess.run(
            ["git", *args], cwd=RAIZ, capture_output=True, check=True
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError):
        return None
    return [linea for linea in salida.split("\0") if linea]


def revisar_git(informe: Informe):
    rastreados = _git("ls-files", "-z")
    if rastreados is None:
        informe.aviso("No hay git: no se pudo comprobar qué archivos se suben.")
        return
    subidos = [r for r in ARCHIVOS_PROHIBIDOS if r in rastreados]
    for ruta in subidos:
        informe.grave(f"{ruta} está en git. Quítalo con 'git rm --cached {ruta}' y cambia sus secretos.")
    if not subidos:
        informe.ok(".env, la clave privada de la firma y el token de la API no están en git.")

    for ruta in ARCHIVOS_PROHIBIDOS:
        ignorado = subprocess.run(
            ["git", "check-ignore", "-q", ruta], cwd=RAIZ, capture_output=True
        ).returncode == 0
        if (RAIZ / ruta).exists() and not ignorado:
            informe.grave(f"{ruta} existe y no está en .gitignore.")

    copias = [r for r in rastreados if r.startswith("data/")]
    if copias:
        informe.aviso(
            "Hay copias de la base de datos en git (" + ", ".join(copias) + "). "
            "Revisa que no tengan datos que no quieras publicar."
        )


def revisar_secretos(informe: Informe):
    rastreados = _git("ls-files", "-z") or []
    valores = {
        os.environ[n] for n in VARIABLES_SECRETAS if len(os.environ.get(n, "")) >= 6
    }
    hallazgos = []
    for ruta in rastreados:
        archivo = RAIZ / ruta
        if ruta == ".env.example" or not archivo.is_file() or archivo.stat().st_size > 2_000_000:
            continue
        try:
            texto = archivo.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for patron, tipo in PATRONES_SECRETOS:
            if patron.search(texto):
                hallazgos.append(f"{ruta}: {tipo}")
        if any(valor in texto for valor in valores):
            hallazgos.append(f"{ruta}: contiene el valor de un secreto de .env")
    for hallazgo in hallazgos:
        informe.grave(f"Posible secreto en el repositorio: {hallazgo}")
    if not hallazgos:
        informe.ok(f"Sin secretos visibles en los {len(rastreados)} archivos del repositorio.")


def revisar_exposicion(informe: Informe):
    abierto = "0.0.0.0" in (
        os.environ.get("SIMULADOR_HOST", ""),
        os.environ.get("SIMULADOR_IP_PUBLICA", ""),
    )
    contrasena = os.environ.get("VNC_PASSWORD", "")
    if abierto and not contrasena:
        informe.grave("La app está abierta a la red (0.0.0.0) y VNC_PASSWORD está vacía.")
    elif contrasena and len(contrasena) < 8:
        informe.grave("VNC_PASSWORD tiene menos de 8 caracteres.")
    elif contrasena:
        informe.ok("El panel web tiene contraseña (VNC solo usa los primeros 8 caracteres).")
    else:
        informe.ok("La app solo escucha en este equipo (127.0.0.1).")

    token = os.environ.get("SIMULADOR_API_TOKEN", "")
    if token and len(token) < 16:
        informe.grave("SIMULADOR_API_TOKEN tiene menos de 16 caracteres.")
    elif token:
        informe.ok("SIMULADOR_API_TOKEN configurado.")
    else:
        informe.ok("Token de la API automático (se genera en data/api_token).")


def revisar_firma(informe: Informe):
    try:
        from firma.firma_digital import ErrorFirma, verificar
    except ImportError:
        informe.aviso("No se pudo cargar la firma digital (¿falta 'cryptography'?).")
        return
    if not (RAIZ / "firma" / "manifiesto.json").exists():
        informe.aviso("El código no está firmado: py -m firma.firma_digital firmar")
        return
    try:
        resultado = verificar(RAIZ)
    except ErrorFirma as error:
        informe.grave(str(error))
        return
    if resultado["valida"]:
        informe.ok("La firma digital del código es válida.")
    else:
        cambios = len(resultado["modificados"]) + len(resultado["faltantes"]) + len(resultado["nuevos"])
        informe.aviso(f"La firma es auténtica pero hay {cambios} archivos cambiados: vuelve a firmar.")


def revisar_dependencias(informe: Informe):
    ejecutable = shutil.which("pip-audit")
    if not ejecutable:
        informe.aviso("pip-audit no está instalado: py -m pip install pip-audit")
        return
    proceso = subprocess.run(
        [ejecutable, "-r", str(RAIZ / "requirements.txt"), "--progress-spinner", "off"],
        capture_output=True,
        text=True,
    )
    if proceso.returncode == 0:
        informe.ok("Sin vulnerabilidades conocidas en las dependencias.")
    else:
        print(proceso.stdout.strip() or proceso.stderr.strip())
        informe.grave("pip-audit encontró dependencias vulnerables o falló.")


def main() -> int:
    load_env_file()
    informe = Informe()
    print("Auditoría de seguridad\n")
    revisar_git(informe)
    revisar_secretos(informe)
    revisar_exposicion(informe)
    revisar_firma(informe)
    revisar_dependencias(informe)
    print(f"\n{informe.graves} problemas graves, {informe.avisos} avisos.")
    return 1 if informe.graves else 0


if __name__ == "__main__":
    sys.exit(main())
