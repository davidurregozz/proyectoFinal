"""Firma digital del código fuente con Ed25519.

Se calcula el SHA-256 de cada archivo del proyecto, se guardan todos en un
manifiesto y el manifiesto se firma con la clave privada. Con la clave pública
cualquiera puede comprobar quién firmó el código y que ningún archivo cambió.

Uso:
    py -m firma.firma_digital generar-claves   # una sola vez
    py -m firma.firma_digital firmar           # después de cada cambio
    py -m firma.firma_digital verificar        # en cualquier equipo

La contraseña de la clave privada se pide por teclado, o se toma de la
variable de entorno FIRMA_CONTRASENA.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = "firma"
CLAVE_PRIVADA = f"{CARPETA}/clave_privada.pem"
CLAVE_PUBLICA = f"{CARPETA}/clave_publica.pem"
MANIFIESTO = f"{CARPETA}/manifiesto.json"
FIRMA = f"{CARPETA}/manifiesto.sig"

# Archivos que nunca entran en el manifiesto: la propia firma y la clave privada.
EXCLUIDOS = {CLAVE_PRIVADA, MANIFIESTO, FIRMA}
# Si no hay git, se recorren las carpetas saltando estas.
CARPETAS_IGNORADAS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
ARCHIVOS_IGNORADOS = {".env"}


class ErrorFirma(Exception):
    """Fallo al generar claves, firmar o verificar."""


# --------------------------------------------------------------------------- #
# Hash de archivos
# --------------------------------------------------------------------------- #
def hash_archivo(ruta: Path) -> str:
    """SHA-256 del archivo.

    En los archivos de texto los saltos de línea CRLF se cuentan como LF, para
    que la firma sea la misma en Windows (git con autocrlf) y en Linux/Docker.
    """
    datos = ruta.read_bytes()
    if b"\0" not in datos:  # texto
        datos = datos.replace(b"\r\n", b"\n")
    return hashlib.sha256(datos).hexdigest()


def listar_archivos(raiz: Path = RAIZ) -> list[str]:
    """Archivos del proyecto (rutas relativas con '/'), sin los excluidos.

    Usa git para respetar .gitignore. Incluye archivos nuevos aún sin commit.
    """
    try:
        salida = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=raiz,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        rutas = [r for r in salida.split("\0") if r]
    except (OSError, subprocess.CalledProcessError):
        rutas = []
        for carpeta, subcarpetas, archivos in os.walk(raiz):
            subcarpetas[:] = [c for c in subcarpetas if c not in CARPETAS_IGNORADAS]
            for nombre in archivos:
                if nombre in ARCHIVOS_IGNORADOS or nombre.endswith((".pyc", ".pyo")):
                    continue
                rutas.append((Path(carpeta) / nombre).relative_to(raiz).as_posix())

    return sorted(
        {r for r in rutas if r not in EXCLUIDOS and (raiz / r).is_file()}
    )


def _commit_actual(raiz: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=raiz, capture_output=True, check=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _bytes_canonicos(manifiesto: dict) -> bytes:
    """Serialización fija del manifiesto: es lo que realmente se firma."""
    return json.dumps(
        manifiesto, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# --------------------------------------------------------------------------- #
# Claves
# --------------------------------------------------------------------------- #
def huella(clave_publica: Ed25519PublicKey) -> str:
    """Huella SHA-256 de la clave pública, para compararla por otro medio."""
    crudo = clave_publica.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    digest = hashlib.sha256(crudo).hexdigest()
    return ":".join(digest[i : i + 4] for i in range(0, 32, 4))


def generar_claves(raiz: Path = RAIZ, contrasena: str | None = None, forzar: bool = False):
    privada_ruta, publica_ruta = raiz / CLAVE_PRIVADA, raiz / CLAVE_PUBLICA
    if privada_ruta.exists() and not forzar:
        raise ErrorFirma(
            f"Ya existe {CLAVE_PRIVADA}. Usa --forzar para reemplazarla "
            "(las firmas anteriores dejarán de verificarse)."
        )

    privada = Ed25519PrivateKey.generate()
    cifrado = (
        serialization.BestAvailableEncryption(contrasena.encode("utf-8"))
        if contrasena
        else serialization.NoEncryption()
    )
    privada_ruta.parent.mkdir(parents=True, exist_ok=True)
    privada_ruta.write_bytes(
        privada.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, cifrado
        )
    )
    try:
        os.chmod(privada_ruta, 0o600)
    except OSError:
        pass
    publica_ruta.write_bytes(
        privada.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return privada.public_key()


def cargar_clave_privada(raiz: Path = RAIZ, contrasena: str | None = None) -> Ed25519PrivateKey:
    ruta = raiz / CLAVE_PRIVADA
    if not ruta.exists():
        raise ErrorFirma(f"No existe {CLAVE_PRIVADA}. Ejecuta primero 'generar-claves'.")
    try:
        clave = serialization.load_pem_private_key(
            ruta.read_bytes(), password=contrasena.encode("utf-8") if contrasena else None
        )
    except (TypeError, ValueError) as exc:
        raise ErrorFirma("No se pudo abrir la clave privada: contraseña incorrecta o faltante.") from exc
    if not isinstance(clave, Ed25519PrivateKey):
        raise ErrorFirma("La clave privada no es Ed25519.")
    return clave


def cargar_clave_publica(raiz: Path = RAIZ, ruta: Path | None = None) -> Ed25519PublicKey:
    ruta = ruta or raiz / CLAVE_PUBLICA
    if not ruta.exists():
        raise ErrorFirma(f"No existe la clave pública {ruta}.")
    clave = serialization.load_pem_public_key(ruta.read_bytes())
    if not isinstance(clave, Ed25519PublicKey):
        raise ErrorFirma("La clave pública no es Ed25519.")
    return clave


# --------------------------------------------------------------------------- #
# Firmar y verificar
# --------------------------------------------------------------------------- #
def firmar(raiz: Path = RAIZ, contrasena: str | None = None, firmante: str | None = None) -> dict:
    """Crea firma/manifiesto.json y firma/manifiesto.sig. Devuelve el manifiesto."""
    privada = cargar_clave_privada(raiz, contrasena)
    archivos = {ruta: hash_archivo(raiz / ruta) for ruta in listar_archivos(raiz)}
    manifiesto = {
        "version": 1,
        "algoritmo_firma": "Ed25519",
        "algoritmo_hash": "SHA-256",
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "firmante": firmante,
        "commit": _commit_actual(raiz),
        "huella_clave": huella(privada.public_key()),
        "archivos": archivos,
    }
    firma = privada.sign(_bytes_canonicos(manifiesto))

    (raiz / MANIFIESTO).write_text(
        json.dumps(manifiesto, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (raiz / FIRMA).write_text(base64.b64encode(firma).decode("ascii") + "\n", encoding="ascii")
    return manifiesto


def verificar(raiz: Path = RAIZ, clave_publica: Path | None = None) -> dict:
    """Comprueba la firma y los archivos.

    Devuelve un dict con 'valida', 'modificados', 'faltantes', 'nuevos' y el
    manifiesto. Lanza ErrorFirma si la firma no corresponde a la clave.
    """
    publica = cargar_clave_publica(raiz, clave_publica)
    try:
        manifiesto = json.loads((raiz / MANIFIESTO).read_text(encoding="utf-8"))
        firma = base64.b64decode((raiz / FIRMA).read_text(encoding="ascii").strip())
    except FileNotFoundError as exc:
        raise ErrorFirma("El código no está firmado: falta el manifiesto o la firma.") from exc
    except ValueError as exc:
        raise ErrorFirma("El manifiesto o la firma están dañados.") from exc

    try:
        publica.verify(firma, _bytes_canonicos(manifiesto))
    except InvalidSignature as exc:
        raise ErrorFirma(
            "FIRMA INVÁLIDA: el manifiesto fue alterado o no lo firmó esta clave."
        ) from exc

    firmados: dict[str, str] = manifiesto["archivos"]
    actuales = set(listar_archivos(raiz))
    modificados = sorted(
        r for r in firmados if r in actuales and hash_archivo(raiz / r) != firmados[r]
    )
    faltantes = sorted(r for r in firmados if r not in actuales)
    nuevos = sorted(actuales - firmados.keys())
    return {
        "valida": not (modificados or faltantes or nuevos),
        "modificados": modificados,
        "faltantes": faltantes,
        "nuevos": nuevos,
        "manifiesto": manifiesto,
    }


# --------------------------------------------------------------------------- #
# Línea de comandos
# --------------------------------------------------------------------------- #
def _pedir_contrasena(confirmar: bool = False) -> str | None:
    if "FIRMA_CONTRASENA" in os.environ:
        return os.environ["FIRMA_CONTRASENA"] or None
    if not sys.stdin.isatty():
        return None
    contrasena = getpass.getpass("Contraseña de la clave privada (vacía = sin contraseña): ")
    if confirmar and contrasena and getpass.getpass("Repite la contraseña: ") != contrasena:
        raise ErrorFirma("Las contraseñas no coinciden.")
    return contrasena or None


def _nombre_git(raiz: Path) -> str | None:
    try:
        nombre = subprocess.run(
            ["git", "config", "user.name"], cwd=raiz, capture_output=True, text=True, check=True
        ).stdout.strip()
        return nombre or None
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Firma digital del código del proyecto (Ed25519).")
    sub = parser.add_subparsers(dest="comando", required=True)
    gen = sub.add_parser("generar-claves", help="Crea el par de claves Ed25519.")
    gen.add_argument("--forzar", action="store_true", help="Reemplaza las claves existentes.")
    fir = sub.add_parser("firmar", help="Firma el estado actual del código.")
    fir.add_argument("--firmante", help="Nombre del firmante (por defecto, git user.name).")
    ver = sub.add_parser("verificar", help="Verifica la firma y los archivos.")
    ver.add_argument("--clave", type=Path, help="Clave pública de confianza (por defecto la del repo).")
    args = parser.parse_args(argv)

    try:
        if args.comando == "generar-claves":
            publica = generar_claves(contrasena=_pedir_contrasena(confirmar=True), forzar=args.forzar)
            print(f"Clave privada: {CLAVE_PRIVADA}  (NO la compartas ni la subas)")
            print(f"Clave pública: {CLAVE_PUBLICA}")
            print(f"Huella:        {huella(publica)}")
        elif args.comando == "firmar":
            manifiesto = firmar(
                contrasena=_pedir_contrasena(), firmante=args.firmante or _nombre_git(RAIZ)
            )
            print(f"Firmados {len(manifiesto['archivos'])} archivos.")
            print(f"Manifiesto: {MANIFIESTO}\nFirma:      {FIRMA}")
            print(f"Huella:     {manifiesto['huella_clave']}")
        else:
            resultado = verificar(clave_publica=args.clave)
            m = resultado["manifiesto"]
            print("Firma auténtica: el manifiesto lo firmó esta clave y no fue alterado.")
            print(f"  Firmante: {m.get('firmante') or '-'}   Fecha: {m['fecha']}")
            print(f"  Commit:   {m.get('commit') or '-'}")
            print(f"  Huella:   {m['huella_clave']}")
            for titulo, clave in (
                ("Modificados", "modificados"),
                ("Faltantes", "faltantes"),
                ("Nuevos sin firmar", "nuevos"),
            ):
                for ruta in resultado[clave]:
                    print(f"  [{titulo}] {ruta}")
            if not resultado["valida"]:
                print("El código NO coincide con lo firmado.")
                return 1
            print(f"Los {len(m['archivos'])} archivos coinciden con lo firmado.")
    except ErrorFirma as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
