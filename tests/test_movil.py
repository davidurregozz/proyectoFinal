"""The backend serves the mobile web app next to the REST API."""

import unittest

from starlette.datastructures import Headers

from backend.api import MOBILE_DIR, app, is_internet_write


class MobileAppTests(unittest.TestCase):
    def test_mobile_app_is_mounted_and_root_redirects_to_it(self):
        paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/movil", paths)
        self.assertIn("/", paths)

    def test_mobile_files_exist_and_use_the_dashboard_api(self):
        for name in ("index.html", "app.js", "estilos.css", "manifest.webmanifest", "icono.svg"):
            self.assertTrue((MOBILE_DIR / name).is_file(), name)
        self.assertIn('"/api/dashboard"', (MOBILE_DIR / "app.js").read_text(encoding="utf-8"))

    def test_changes_from_the_internet_are_blocked_but_reads_are_not(self):
        from_internet = Headers({"CF-Connecting-IP": "203.0.113.7"})
        from_docker = Headers({"host": "backend:8000"})

        self.assertTrue(is_internet_write("DELETE", "/api/vehicles/ABC", from_internet))
        self.assertTrue(is_internet_write("post", "/api/routes", from_internet))
        self.assertFalse(is_internet_write("GET", "/api/dashboard", from_internet))  # la app lee
        self.assertFalse(is_internet_write("DELETE", "/api/vehicles/ABC", from_docker))  # el panel
        self.assertFalse(is_internet_write("POST", "/api/visitas", from_internet))   # contador


if __name__ == "__main__":
    unittest.main()
