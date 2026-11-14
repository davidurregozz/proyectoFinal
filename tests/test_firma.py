"""Firma digital del código: firmar, verificar y detectar alteraciones."""

import base64
import json
import tempfile
import unittest
from pathlib import Path

from firma.firma_digital import (
    FIRMA,
    MANIFIESTO,
    ErrorFirma,
    firmar,
    generar_claves,
    hash_archivo,
    verificar,
)


class FirmaDigitalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp.name)
        (self.raiz / "app.py").write_text("print('hola')\n", encoding="utf-8")
        (self.raiz / "datos.bin").write_bytes(b"\x00\x01\r\n\x02")
        generar_claves(self.raiz, contrasena="secreta")
        firmar(self.raiz, contrasena="secreta", firmante="Pruebas")

    def tearDown(self):
        self.temp.cleanup()

    def test_codigo_sin_cambios_verifica(self):
        resultado = verificar(self.raiz)
        self.assertTrue(resultado["valida"])
        self.assertIn("app.py", resultado["manifiesto"]["archivos"])
        self.assertNotIn("firma/clave_privada.pem", resultado["manifiesto"]["archivos"])

    def test_detecta_archivo_modificado_faltante_y_nuevo(self):
        (self.raiz / "app.py").write_text("print('alterado')\n", encoding="utf-8")
        (self.raiz / "datos.bin").unlink()
        (self.raiz / "extra.py").write_text("x = 1\n", encoding="utf-8")

        resultado = verificar(self.raiz)

        self.assertFalse(resultado["valida"])
        self.assertEqual(resultado["modificados"], ["app.py"])
        self.assertEqual(resultado["faltantes"], ["datos.bin"])
        self.assertEqual(resultado["nuevos"], ["extra.py"])

    def test_manifiesto_alterado_invalida_la_firma(self):
        ruta = self.raiz / MANIFIESTO
        manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
        manifiesto["archivos"]["app.py"] = "0" * 64
        ruta.write_text(json.dumps(manifiesto), encoding="utf-8")

        with self.assertRaises(ErrorFirma):
            verificar(self.raiz)

    def test_firma_de_otra_clave_no_verifica(self):
        otra = Path(self.temp.name) / "otra"
        otra.mkdir()
        generar_claves(otra)
        with self.assertRaises(ErrorFirma):
            verificar(self.raiz, clave_publica=otra / "firma" / "clave_publica.pem")

    def test_firma_tiene_64_bytes_ed25519(self):
        firma = base64.b64decode((self.raiz / FIRMA).read_text(encoding="ascii"))
        self.assertEqual(len(firma), 64)

    def test_contrasena_incorrecta_no_firma(self):
        with self.assertRaises(ErrorFirma):
            firmar(self.raiz, contrasena="otra")

    def test_crlf_y_lf_dan_el_mismo_hash_en_texto(self):
        lf, crlf = self.raiz / "lf.txt", self.raiz / "crlf.txt"
        lf.write_bytes(b"a\nb\n")
        crlf.write_bytes(b"a\r\nb\r\n")
        self.assertEqual(hash_archivo(lf), hash_archivo(crlf))


if __name__ == "__main__":
    unittest.main()
