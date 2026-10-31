"""Widget de mapa con conmutaci?n autom?tica entre proveedores XYZ."""

import io
import logging
import os
import threading
import time
import tkinter as tk
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def proveedores_mapa():
    """Devuelve los proveedores XYZ y añade sus claves solo desde el entorno."""
    proveedores = []
    clave_stadia = os.environ.get("STADIA_MAPS_API_KEY", "").strip()
    clave_carto = os.environ.get("CARTO_API_KEY", "").strip()
    clave_esri = os.environ.get("ARCGIS_API_KEY", "").strip()

    if clave_stadia:
        proveedores.append({
            "nombre": "Stadia Maps - Alidade Smooth",
            "url": (
                "https://tiles.stadiamaps.com/tiles/alidade_smooth/"
                "{z}/{x}/{y}.png?" + urlencode({"api_key": clave_stadia})
            ),
        })
    if clave_carto:
        proveedores.append({
            "nombre": "CARTO - Voyager",
            "url": (
                "https://basemaps.cartocdn.com/rastertiles/voyager/"
                "{z}/{x}/{y}.png?" + urlencode({"key": clave_carto})
            ),
        })

    url_esri = (
        "https://services.arcgisonline.com/ArcGIS/rest/services/"
        "World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
    )
    if clave_esri:
        url_esri += "?" + urlencode({"token": clave_esri})
    proveedores.append({"nombre": "Esri - World Topographic Map", "url": url_esri})
    return proveedores


def crear_mapa_con_respaldo(tkintermapview):
    """Crea un widget de mapa XYZ que conmuta entre proveedores ante fallos."""
    from PIL import Image, ImageTk

    class MapaConRespaldo(tkintermapview.TkinterMapView):
        TIEMPO_REINTENTO_S = 30

        def __init__(self, *args, proveedores, **kwargs):
            if not proveedores:
                raise ValueError("No hay proveedores de mapas configurados.")
            self.proveedores = proveedores
            self._proveedor_activo = 0
            self._proveedores_fallidos = {}
            self._fallos_reportados = set()
            self._estado_mapa_lock = threading.Lock()
            self.mapa_disponible = True
            self._ultimo_aviso_fallo = 0.0
            super().__init__(*args, **kwargs)
            self.set_tile_server(proveedores[0]["url"], max_zoom=19)

        @property
        def nombre_proveedor_activo(self):
            with self._estado_mapa_lock:
                return self.proveedores[self._proveedor_activo]["nombre"]

        def request_image(self, zoom, x, y, db_cursor=None):
            _ = db_cursor
            cache_key = f"{zoom}{x}{y}"
            if cache_key in self.tile_image_cache:
                return self.tile_image_cache[cache_key]

            ahora = time.monotonic()
            with self._estado_mapa_lock:
                orden = [
                    (self._proveedor_activo + offset) % len(self.proveedores)
                    for offset in range(len(self.proveedores))
                ]
                candidatos = [
                    indice for indice in orden
                    if self._proveedores_fallidos.get(indice, 0) <= ahora
                ]

            if not candidatos:
                return self.empty_tile_image

            for indice in candidatos:
                proveedor = self.proveedores[indice]
                url = (
                    proveedor["url"]
                    .replace("{z}", str(zoom))
                    .replace("{x}", str(x))
                    .replace("{y}", str(y))
                )
                try:
                    solicitud = Request(
                        url,
                        headers={"User-Agent": "SimuladorBuses/1.0"},
                    )
                    with urlopen(solicitud, timeout=8) as respuesta:
                        contenido = respuesta.read()
                    with Image.open(io.BytesIO(contenido)) as mosaico:
                        imagen = mosaico.convert("RGB")
                except (OSError, URLError, ValueError) as error:
                    with self._estado_mapa_lock:
                        self._proveedores_fallidos[indice] = (
                            time.monotonic() + self.TIEMPO_REINTENTO_S
                        )
                        if indice not in self._fallos_reportados:
                            logging.warning(
                                "Falló el proveedor de mapas %s (%s); "
                                "se probará el siguiente.",
                                proveedor["nombre"], type(error).__name__,
                            )
                            self._fallos_reportados.add(indice)
                    continue

                try:
                    imagen_tk = ImageTk.PhotoImage(imagen)
                except tk.TclError as error:
                    logging.error(
                        "No se pudo preparar la imagen del mapa (%s).",
                        type(error).__name__,
                    )
                    return self.empty_tile_image

                with self._estado_mapa_lock:
                    self._proveedor_activo = indice
                    self._proveedores_fallidos.pop(indice, None)
                    if indice in self._fallos_reportados:
                        logging.info(
                            "Se restableció el proveedor de mapas %s.",
                            proveedor["nombre"],
                        )
                        self._fallos_reportados.remove(indice)
                    self.mapa_disponible = True
                self.tile_image_cache[cache_key] = imagen_tk
                return imagen_tk

            with self._estado_mapa_lock:
                self.mapa_disponible = False
                if time.monotonic() - self._ultimo_aviso_fallo >= self.TIEMPO_REINTENTO_S:
                    logging.error(
                        "No se pudo cargar un mosaico con ninguno de los "
                        "proveedores de mapas configurados."
                    )
                    self._ultimo_aviso_fallo = time.monotonic()
            return self.empty_tile_image

    return MapaConRespaldo
