"""The backend serves the mobile web app next to the REST API."""

import unittest

from backend.api import MOBILE_DIR, app


class MobileAppTests(unittest.TestCase):
    def test_mobile_app_is_mounted_and_root_redirects_to_it(self):
        paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/movil", paths)
        self.assertIn("/", paths)

    def test_mobile_files_exist_and_use_the_dashboard_api(self):
        for name in ("index.html", "app.js", "estilos.css", "manifest.webmanifest", "icono.svg"):
            self.assertTrue((MOBILE_DIR / name).is_file(), name)
        self.assertIn('"/api/dashboard"', (MOBILE_DIR / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
