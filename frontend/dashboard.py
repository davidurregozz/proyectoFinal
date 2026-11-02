"""Tkinter dashboard; all application data is obtained from the REST API."""

import logging
import math
import os
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from PIL import Image, ImageDraw, ImageTk

from backend.congestion import dividir_segmento_zonas
from backend.seed_data import MODELOS_VEHICULO, MUNICIPIOS, TIPOS_VEHICULO
from frontend.api_client import ApiClient, ApiError
from frontend.map_widget import crear_mapa_con_respaldo, proveedores_mapa
from frontend.theme import aclarar, aplicar_tema


class RouteView:
    def __init__(self, data):
        self.codigo = data["codigo"]
        self.nombre = data["nombre"]
        self.municipio = data["municipio"]
        self.color = data["color"]
        self.velocidad_kmh = data["velocidad_kmh"]
        self.n_buses = data["buses"]
        self.circular = data["circular"]
        self.paradas = [tuple(stop) for stop in data["paradas"]]
        self.coordenadas = [tuple(point) for point in data["coordenadas"]]
        self.coordenadas_regreso = [tuple(point) for point in data["coordenadas_regreso"]]
        self.ciclo_s = data["ciclo_s"]

    def trazado(self):
        if self.coordenadas_regreso:
            return self.coordenadas + self.coordenadas_regreso[1:]
        return self.coordenadas


class Simulador(tk.Tk):
    VELOCIDAD_LENTA_KMH = 15        # por debajo, el bus se marca con un banderín rojo
    TODOS_MUNICIPIOS = "Todos"
    # (relleno pastel, borde, texto de la leyenda) de cada nivel de tráfico
    NIVELES_TRAFICO = {
        "fluido": ("#b9f6ca", "#4caf7d", "Tráfico fluido"),
        "moderado": ("#fff3a3", "#e0b100", "Tráfico moderado"),
        "alto": ("#ffcc99", "#f08a3c", "Tráfico alto"),
        "severo": ("#ffaaaa", "#e05555", "Tráfico severo"),
        "simulada": ("#FFCC99", "#F4A261", "Zona de congestión simulada"),
    }

    def __init__(self):
        super().__init__()
        self._pil = (Image, ImageDraw, ImageTk)
        self.api = ApiClient()
        try:
            snapshot = self.api.dashboard()
        except ApiError as error:
            messagebox.showerror("Backend no disponible", str(error), parent=self)
            self.destroy()
            return
        self._apply_snapshot(snapshot)
        self._last_poll = 0.0
        self._backend_error_reported = False
        proveedores = proveedores_mapa()
        self.colores, self.fuentes = aplicar_tema(self)
        C, F = self.colores, self.fuentes

        self.title("Simulador de rutas de buses · Medellín")
        self.geometry("1366x800")
        self.minsize(1180, 700)

        self._iconos = []                       # Tk necesita que guardemos las imágenes
        self._iconos_bus = {}                   # (color, lento) -> icono

        # ── Barra superior ──────────────────────────────────────────────
        barra = ttk.Frame(self, style="Header.TFrame", padding=(16, 10))
        barra.pack(side="top", fill="x")
        tk.Frame(self, bg=C["borde"], height=1).pack(side="top", fill="x")

        ttk.Label(barra, image=self._icono_logo(), style="Header.TLabel").pack(
            side="left", padx=(0, 10))
        titulos = ttk.Frame(barra, style="Header.TFrame")
        titulos.pack(side="left")
        ttk.Label(titulos, text="Simulador de Rutas", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titulos, text="Transporte público · Valle de Aburrá",
                  style="HeaderMuted.TLabel").pack(anchor="w")

        reloj = ttk.Frame(barra, style="Header.TFrame")
        reloj.pack(side="right", padx=(18, 0))
        self.lbl_reloj = ttk.Label(reloj, style="Clock.TLabel")
        self.lbl_reloj.pack(anchor="e")
        ttk.Label(reloj, text="HORA REAL · MEDELLÍN", style="HeaderMuted.TLabel").pack(
            anchor="e")
        self.lbl_pill_trafico = ttk.Label(barra, style="PillWarn.TLabel")
        self.lbl_pill_trafico.pack(side="right", padx=(18, 0))

        controles = ttk.Frame(barra, style="Header.TFrame")
        controles.pack(side="right")
        self.municipio = self.TODOS_MUNICIPIOS
        ttk.Label(controles, text="Municipio", style="HeaderMuted.TLabel").pack(
            side="left", padx=(0, 6))
        self.cmb_municipio = ttk.Combobox(controles, state="readonly", width=13,
                                          values=self._opciones_municipio())
        self.cmb_municipio.set(self.municipio)
        self.cmb_municipio.bind("<<ComboboxSelected>>", self.cambiar_municipio)
        self.cmb_municipio.pack(side="left")
        ttk.Label(controles, text="Mapa", style="HeaderMuted.TLabel").pack(
            side="left", padx=(14, 6))
        self.cmb_mapa = ttk.Combobox(
            controles, state="readonly", width=29,
            values=[proveedor["nombre"] for proveedor in proveedores],
        )
        self.cmb_mapa.current(0)
        self.cmb_mapa.bind("<<ComboboxSelected>>", self.cambiar_mapa)
        self.cmb_mapa.pack(side="left")
        ttk.Button(controles, text="+  Nuevo registro", style="Accent.TButton",
                   command=self.abrir_ventana_registro).pack(side="left", padx=(14, 0))

        cuerpo = ttk.Frame(self)
        cuerpo.pack(side="top", fill="both", expand=True)

        # ── Panel derecho ───────────────────────────────────────────────
        panel = ttk.Frame(cuerpo, padding=(12, 12, 12, 12), width=450)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        kpis = ttk.Frame(panel)
        kpis.pack(fill="x", pady=(0, 10))
        self.kpi_valores = {}
        for columna, (clave, titulo) in enumerate((
            ("activos", "BUSES EN SERVICIO"),
            ("media", "VELOCIDAD MEDIA"),
            ("lentos", f"BAJO {self.VELOCIDAD_LENTA_KMH} KM/H"),
        )):
            kpis.columnconfigure(columna, weight=1, uniform="kpi")
            tarjeta = ttk.Frame(kpis, style="Card.TFrame", padding=(12, 8))
            tarjeta.grid(row=0, column=columna, sticky="nsew",
                         padx=(0 if columna == 0 else 8, 0))
            self.kpi_valores[clave] = ttk.Label(tarjeta, text="–", style="KpiValue.TLabel")
            self.kpi_valores[clave].pack(anchor="w")
            ttk.Label(tarjeta, text=titulo, style="KpiCaption.TLabel").pack(anchor="w")

        llegadas = self._tarjeta(panel, "Próximas llegadas",
                                 "Elige una parada o haz clic en una del mapa")
        llegadas.master.pack(fill="x", pady=(0, 10))
        self.cmb_parada = ttk.Combobox(llegadas, state="readonly",
                                       values=self._paradas_filtradas())
        self.cmb_parada.set(next(iter(self.paradas)))
        self.cmb_parada.bind("<<ComboboxSelected>>", lambda e: self.seleccionar_parada())
        self.cmb_parada.pack(fill="x", pady=(0, 8))
        self.tabla_llegadas = self._crear_tabla(llegadas, 5, [
            ("bus", "BUS", 60), ("hacia", "HACIA", 125),
            ("en", "LLEGA EN", 85), ("hora", "HORA", 50),
            ("velocidad", "VELOCIDAD", 80)])

        self.pestañas = pestañas = ttk.Notebook(panel)
        pestañas.pack(fill="both", expand=True)
        tab_buses = ttk.Frame(pestañas, style="Card.TFrame", padding=10)
        tab_rutas = ttk.Frame(pestañas, style="Card.TFrame", padding=10)
        tab_vehiculos = ttk.Frame(pestañas, style="Card.TFrame", padding=10)
        self.tab_trafico = tab_trafico = ttk.Frame(pestañas, style="Card.TFrame", padding=10)
        pestañas.add(tab_buses, text="Flota en vivo")
        pestañas.add(tab_trafico, text="Tráfico")
        pestañas.add(tab_rutas, text="Rutas")
        pestañas.add(tab_vehiculos, text="Vehículos")

        self.lbl_resumen_trafico = ttk.Label(tab_trafico, style="CardMuted.TLabel",
                                             wraplength=400, justify="left")
        self.lbl_resumen_trafico.pack(anchor="w", fill="x", pady=(0, 8))
        self.tabla_trafico = self._crear_tabla(tab_trafico, 6, [
            ("zona", "ZONA", 135), ("actual", "ACTUAL", 70), ("libre", "LIBRE", 65),
            ("reduccion", "FRENA", 55), ("buses", "BUSES", 50)], expandir=True)
        self.tabla_trafico.bind("<<TreeviewSelect>>", self._centrar_zona_seleccionada)

        self.tabla_buses = self._crear_tabla(tab_buses, 8, [
            ("bus", "BUS", 60), ("proxima", "PRÓXIMA PARADA", 135),
            ("en", "LLEGA EN", 75), ("hora", "HORA", 50),
            ("velocidad", "VELOCIDAD", 80)], expandir=True)

        acciones_rutas = ttk.Frame(tab_rutas, style="Card.TFrame")
        acciones_rutas.pack(fill="x", pady=(0, 8))
        ttk.Button(acciones_rutas, text="+  Agregar ruta", style="Accent.TButton",
                   command=lambda: self.abrir_ventana_registro("ruta")).pack(side="left")
        self.rutas_panel = ttk.Frame(tab_rutas, style="Card.TFrame")
        self.rutas_panel.pack(fill="x")
        self.actualizar_lista_rutas()
        self.lbl_estado_trafico = ttk.Label(
            tab_rutas,
            text=self.snapshot["traffic"]["message"],
            wraplength=390,
            style="CardMuted.TLabel",
        )
        self.lbl_estado_trafico.pack(anchor="w", fill="x", pady=(10, 0))

        acciones_vehiculos = ttk.Frame(tab_vehiculos, style="Card.TFrame")
        acciones_vehiculos.pack(fill="x", pady=(0, 8))
        ttk.Button(acciones_vehiculos, text="+  Agregar vehículo", style="Accent.TButton",
                   command=lambda: self.abrir_ventana_registro("vehiculo")).pack(side="left")
        self.btn_eliminar_vehiculo = ttk.Button(
            acciones_vehiculos, text="Eliminar seleccionado", style="Danger.TButton",
            command=self.eliminar_vehiculo, state="disabled",
        )
        self.btn_eliminar_vehiculo.pack(side="right")
        self.lbl_resumen_flota = ttk.Label(tab_vehiculos, style="CardMuted.TLabel")
        self.lbl_resumen_flota.pack(anchor="w", pady=(0, 6))
        self.tabla_vehiculos = self._crear_tabla(tab_vehiculos, 6, [
            ("placa", "BUS / PLACA", 75), ("tipo", "TIPO", 90),
            ("ruta", "RUTA", 125), ("estado", "ESTADO", 85)], expandir=True)
        self.tabla_vehiculos.bind(
            "<<TreeviewSelect>>",
            lambda e: self.btn_eliminar_vehiculo.config(
                state="normal" if self.tabla_vehiculos.selection() else "disabled"),
        )
        self.actualizar_tabla_vehiculos()

        # ── Mapa ────────────────────────────────────────────────────────
        zona_mapa = ttk.Frame(cuerpo)
        zona_mapa.pack(side="left", fill="both", expand=True)
        import tkintermapview
        clase_mapa = crear_mapa_con_respaldo(tkintermapview)
        self.mapa = clase_mapa(
            zona_mapa, corner_radius=0, proveedores=proveedores, bg_color=C["fondo"]
        )
        self.mapa.pack(fill="both", expand=True)
        self._crear_leyenda(zona_mapa)
        self.marco_estado_mapa = ttk.Frame(zona_mapa, style="Header.TFrame", padding=(8, 4))
        self.marco_estado_mapa.place(
            relx=0.01, rely=0.99, anchor="sw", relwidth=0.98
        )
        self.lbl_estado_mapa = ttk.Label(
            self.marco_estado_mapa,
            text="",
            style="Header.TLabel",
            font=F["pequena"],
            wraplength=780,
        )
        self.lbl_estado_mapa.pack(anchor="w", fill="x")
        self.creditos_mapa = tk.Text(
            self.marco_estado_mapa,
            height=2,
            width=100,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            background=C["superficie"],
            foreground=C["tenue"],
            font=(F["pequena"][0], 8),
            takefocus=0,
        )
        self.creditos_mapa.pack(fill="x")
        self._agregar_creditos_mapa()
        self._texto_estado_mapa = ""

        todos = [(lat, lon) for lat, lon, _ in self.paradas.values()]
        self.mapa.set_position(sum(p[0] for p in todos) / len(todos),
                               sum(p[1] for p in todos) / len(todos))
        self.mapa.set_zoom(13)

        self.poligonos_trafico = []
        self._zonas_dibujadas = None
        self._dibujar_zonas_trafico()

        self.trazos_rutas = {}
        self.marcadores_paradas = {}
        self._render_route_layers()
        self._route_geometry_drawn = self._route_geometry_signature()

        self.marcador_sel = self.mapa.set_marker(                 # parada elegida
            0, 0, text="", icon=self._icono(22, "#facc15", "#222222"),
            text_color="#111111", font=self.fuentes["parada"])

        self.marcadores = []                                      # buses
        self._render_bus_markers()

        self.seleccionar_parada()
        self._actualizar_estado_trafico()
        self._actualizar_kpis()
        self._actualizar_tabla_trafico()
        self._actualizar_estado_mapa()
        self.tick()

    def _apply_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.rutas = [RouteView(route) for route in snapshot["routes"]]
        self.rutas_por_codigo = {route.codigo: route for route in self.rutas}
        route_codes = set(self.rutas_por_codigo)
        if not hasattr(self, "rutas_visibles"):
            self.rutas_visibles = {code: True for code in route_codes}
        else:
            self.rutas_visibles = {
                code: self.rutas_visibles.get(code, True)
                for code in route_codes
            }
        self.vehiculos = snapshot["vehicles"]
        self.buses = snapshot["buses"]
        self.paradas = {}
        for stop in snapshot["stops"]:
            rutas = [self.rutas_por_codigo[code] for code in stop["codigos"]]
            self.paradas[stop["nombre"]] = (
                stop["latitud"], stop["longitud"], rutas
            )

    def _refresh_dashboard(self):
        selected_stop = self.cmb_parada.get() if hasattr(self, "cmb_parada") else ""
        snapshot = self.api.dashboard(selected_stop)
        self._apply_snapshot(snapshot)
        if not hasattr(self, "mapa"):
            return
        self._actualizar_estado_trafico()
        self._dibujar_zonas_trafico()
        self._actualizar_tabla_trafico()
        self.cmb_municipio.configure(values=self._opciones_municipio())
        if self.municipio not in self.cmb_municipio["values"]:     # se borró su última ruta
            self.municipio = self.TODOS_MUNICIPIOS
            self.cmb_municipio.set(self.municipio)
        available_stops = self._paradas_filtradas()
        self.cmb_parada.configure(values=available_stops)
        if self.cmb_parada.get() not in available_stops:
            self.cmb_parada.set(available_stops[0])
            snapshot = self.api.dashboard(available_stops[0])
            self._apply_snapshot(snapshot)

        route_codes = {route.codigo for route in self.rutas}
        geometry_signature = self._route_geometry_signature()
        routes_changed = route_codes != set(self._route_geometry_drawn)
        conteo_buses = [(route.codigo, route.n_buses) for route in self.rutas]
        if conteo_buses != getattr(self, "_conteo_buses", None):
            self.actualizar_lista_rutas()
            self._conteo_buses = conteo_buses
        if routes_changed or geometry_signature != self._route_geometry_drawn:
            self._render_route_layers()
            for table in (self.tabla_llegadas, self.tabla_buses):
                self._colorear_tabla(table)
            self._route_geometry_drawn = geometry_signature

        bus_names = {
            bus["name"] for bus in self.buses
            if self._ruta_visible(bus["route_code"])
        }
        marker_names = {name for name, _ in self.marcadores}
        if bus_names != marker_names:
            self._render_bus_markers()
        else:
            buses_by_name = {
                bus["name"]: bus for bus in self.buses
                if self._ruta_visible(bus["route_code"])
            }
            for name, marker in self.marcadores:
                bus = buses_by_name[name]
                marker.set_position(bus["latitude"], bus["longitude"])
                icono = self._icono_bus(bus)
                if marker.icon is not icono:                # cambió a lento/normal
                    marker.change_icon(icono)
        self.actualizar_tabla_vehiculos()
        self._update_selected_marker()
        self.actualizar_tablas()
        self._actualizar_kpis()

    def _render_buses(self):
        self._render_bus_markers()

    def _render_bus_markers(self):
        for _, marker in self.marcadores:
            marker.delete()
        self.marcadores = []
        for bus in self.buses:
            if not self._ruta_visible(bus["route_code"]):
                continue
            marker = self.mapa.set_marker(
                bus["latitude"], bus["longitude"], text=bus["name"],
                icon=self._icono_bus(bus),
                text_color=bus["color"], font=self.fuentes["marcador"],
            )
            self.marcadores.append((bus["name"], marker))

    def _render_route_layers(self):
        for path in self.trazos_rutas.values():
            path.delete()
        self.trazos_rutas.clear()
        for marker in self.marcadores_paradas.values():
            marker.delete()
        self.marcadores_paradas.clear()

        for route in self.rutas:
            if self._ruta_visible(route.codigo):
                self.trazos_rutas[route.codigo] = self.mapa.set_path(
                    route.trazado(), color=route.color, width=5
                )
        for name, (lat, lon, routes) in self.paradas.items():
            visible_routes = [
                route for route in routes
                if self._ruta_visible(route.codigo)
            ]
            if not visible_routes:
                continue
            border = visible_routes[0].color if len(visible_routes) == 1 else "#222222"
            self.marcadores_paradas[name] = self.mapa.set_marker(
                lat, lon, icon=self._icono(14, "white", border),
                data=name, command=self._clic_parada,
            )

    def _route_geometry_signature(self):
        return {
            route.codigo: (
                tuple(route.coordenadas),
                tuple(route.coordenadas_regreso),
            )
            for route in self.rutas
        }

    def _cambiar_visibilidad_ruta(self, codigo, visible):
        self.rutas_visibles[codigo] = visible
        self._render_route_layers()
        self._render_bus_markers()
        self.actualizar_tablas()

    # ── Filtro por municipio ───────────────────────────────────────────
    def _opciones_municipio(self):
        return [self.TODOS_MUNICIPIOS] + sorted(
            {ruta.municipio for ruta in self.rutas if ruta.municipio}
        )

    def _en_municipio(self, codigo):
        ruta = self.rutas_por_codigo.get(codigo)
        return self.municipio == self.TODOS_MUNICIPIOS or (
            ruta is not None and ruta.municipio == self.municipio
        )

    def _ruta_visible(self, codigo):
        """Visible si su casilla está marcada y pertenece al municipio elegido."""
        return self.rutas_visibles.get(codigo, True) and self._en_municipio(codigo)

    def _paradas_filtradas(self):
        return sorted(
            nombre for nombre, (_, _, rutas) in self.paradas.items()
            if any(self._en_municipio(ruta.codigo) for ruta in rutas)
        )

    def cambiar_municipio(self, _evento=None):
        self.municipio = self.cmb_municipio.get()
        paradas = self._paradas_filtradas()
        self.cmb_parada.configure(values=paradas)
        if self.cmb_parada.get() not in paradas:
            self.cmb_parada.set(paradas[0])
        self._render_route_layers()
        self._render_bus_markers()
        self.actualizar_lista_rutas()
        self.actualizar_tabla_vehiculos()
        self.seleccionar_parada()
        self._actualizar_kpis()
        self._dibujar_zonas_trafico()
        self._actualizar_tabla_trafico()
        self._encuadrar_rutas_visibles()

    def _encuadrar_rutas_visibles(self):
        puntos = [
            punto for ruta in self.rutas if self._en_municipio(ruta.codigo)
            for punto in ruta.trazado()
        ]
        if not puntos:
            return
        lats = [lat for lat, _ in puntos]
        lons = [lon for _, lon in puntos]
        margen = 0.004                          # unos 400 m alrededor de las rutas
        self.mapa.fit_bounding_box(
            (max(lats) + margen, min(lons) - margen),
            (min(lats) - margen, max(lons) + margen),
        )

    # ── Ayudas para construir la interfaz ──────────────────────────────
    def _icono(self, diametro, relleno, borde, banderin=False):
        """
        Dibuja un círculo de color para usarlo como marcador en el mapa.
        Con 'banderin' agrega un banderín rojo arriba a la derecha; el lienzo
        crece por igual en todos los lados para que el círculo siga centrado.
        """
        Image, ImageDraw, ImageTk = self._pil
        k = 4                                   # se dibuja grande y se reduce (suaviza)
        margen = 9 if banderin else 0
        lado = diametro + 2 * margen
        img = Image.new("RGBA", (lado * k, lado * k), (0, 0, 0, 0))
        dibujo = ImageDraw.Draw(img)
        dibujo.ellipse(
            ((margen + 1) * k, (margen + 1) * k,
             (margen + diametro - 1) * k, (margen + diametro - 1) * k),
            fill=relleno, outline=borde, width=3 * k)
        if banderin:
            asta = (lado - 10) * k
            dibujo.line((asta, 1 * k, asta, (margen + 7) * k),
                        fill="#1f2937", width=2 * k)
            dibujo.polygon([(asta, 1 * k), (lado * k - k, 5 * k), (asta, 9 * k)],
                           fill="#dc2626", outline="#7f1d1d")
        icono = ImageTk.PhotoImage(img.resize((lado, lado), Image.LANCZOS))
        self._iconos.append(icono)
        return icono

    def _icono_bus(self, bus):
        """Icono del bus; lleva banderín rojo si va a menos de 15 km/h."""
        clave = (bus["color"], bus["speed_kmh"] < self.VELOCIDAD_LENTA_KMH)
        if clave not in self._iconos_bus:
            self._iconos_bus[clave] = self._icono(20, clave[0], "white", banderin=clave[1])
        return self._iconos_bus[clave]

    def _icono_logo(self, lado=36):
        """Logo de la barra superior: un bus sobre un cuadrado redondeado."""
        Image, ImageDraw, ImageTk = self._pil
        C, k = self.colores, 4
        img = Image.new("RGBA", (lado * k, lado * k), (0, 0, 0, 0))
        dibujo = ImageDraw.Draw(img)
        dibujo.rounded_rectangle((0, 0, lado * k - 1, lado * k - 1), radius=10 * k,
                                 fill=C["acento"])
        dibujo.rounded_rectangle((8 * k, 7 * k, 28 * k, 26 * k), radius=4 * k,
                                 fill=C["fondo"])
        dibujo.rounded_rectangle((10 * k, 10 * k, 26 * k, 17 * k), radius=k,
                                 fill=C["acento"])
        for x in (11, 22):                                  # faros
            dibujo.ellipse((x * k, 20 * k, (x + 3) * k, 23 * k), fill=C["acento"])
        for x in (10, 22):                                  # ruedas
            dibujo.rectangle((x * k, 26 * k, (x + 4) * k, 29 * k), fill=C["fondo"])
        icono = ImageTk.PhotoImage(img.resize((lado, lado), Image.LANCZOS))
        self._iconos.append(icono)
        return icono

    def _tarjeta(self, padre, titulo, subtitulo=None):
        """Crea una tarjeta con título; devuelve el marco interior (su master es la tarjeta)."""
        tarjeta = ttk.Frame(padre, style="Card.TFrame", padding=12)
        ttk.Label(tarjeta, text=titulo, style="Section.TLabel").pack(anchor="w")
        if subtitulo:
            ttk.Label(tarjeta, text=subtitulo, style="CardMuted.TLabel").pack(anchor="w")
        interior = ttk.Frame(tarjeta, style="Card.TFrame")
        interior.pack(fill="both", expand=True, pady=(8, 0))
        return interior

    def _crear_leyenda(self, zona_mapa):
        C = self.colores
        leyenda = ttk.Frame(zona_mapa, style="Header.TFrame", padding=(10, 8))
        leyenda.place(relx=0.01, rely=0.015, anchor="nw")
        ttk.Label(leyenda, text="LEYENDA", style="HeaderMuted.TLabel").pack(anchor="w")
        self.leyenda_zonas = ttk.Frame(leyenda, style="Header.TFrame")
        self.leyenda_zonas.pack(anchor="w")
        fila = ttk.Frame(leyenda, style="Header.TFrame")
        fila.pack(anchor="w", pady=(4, 0))
        ttk.Label(fila, image=self._icono(16, C["acento"], "white", banderin=True),
                  style="Header.TLabel").pack(side="left", padx=(0, 4))
        ttk.Label(fila, text=f"Bus a menos de {self.VELOCIDAD_LENTA_KMH} km/h",
                  style="Header.TLabel").pack(side="left")

    def _actualizar_leyenda(self, modo):
        for widget in self.leyenda_zonas.winfo_children():
            widget.destroy()
        niveles = (
            ("fluido", "moderado", "alto", "severo") if modo == "tomtom" else ("simulada",)
        )
        for nivel in niveles:
            relleno, _, texto = self.NIVELES_TRAFICO[nivel]
            fila = ttk.Frame(self.leyenda_zonas, style="Header.TFrame")
            fila.pack(anchor="w", pady=(4, 0))
            tk.Label(fila, bg=relleno, width=2, height=1, bd=0).pack(side="left", padx=(0, 6))
            ttk.Label(fila, text=texto + (" (TomTom)" if modo == "tomtom" else ""),
                      style="Header.TLabel").pack(side="left")

    def _actualizar_kpis(self):
        buses = [
            bus for bus in self.buses
            if self._ruta_visible(bus["route_code"])
        ]
        en_marcha = [bus["speed_kmh"] for bus in buses if bus["speed_kmh"] > 0]
        lentos = sum(velocidad < self.VELOCIDAD_LENTA_KMH for velocidad in en_marcha)
        media = sum(en_marcha) / len(en_marcha) if en_marcha else 0.0
        self.kpi_valores["activos"].config(text=str(len(buses)))
        self.kpi_valores["media"].config(text=f"{media:.0f} km/h")
        self.kpi_valores["lentos"].config(
            text=str(lentos),
            foreground=self.colores["peligro"] if lentos else self.colores["exito"],
        )

    def _actualizar_estado_trafico(self):
        trafico = self.snapshot["traffic"]
        C = self.colores
        self.lbl_estado_trafico.config(
            text=trafico["message"],
            foreground=C["exito"] if trafico["available"] else C["alerta"],
        )
        if trafico["available"]:
            self.lbl_pill_trafico.config(text="●  Tráfico en vivo", style="PillOk.TLabel")
        else:
            self.lbl_pill_trafico.config(text="●  Trazados guardados",
                                         style="PillWarn.TLabel")

    def _colorear_tabla(self, tabla):
        for ruta in self.rutas:                 # cada fila con el color de su ruta
            tabla.tag_configure(ruta.codigo, foreground=aclarar(ruta.color))
        tabla.tag_configure("alterna", background=self.colores["fila_alterna"])

    def _crear_tabla(self, padre, filas, columnas, expandir=False):
        contenedor = ttk.Frame(padre, style="Card.TFrame")
        contenedor.pack(fill="both" if expandir else "x", expand=expandir)
        tabla = ttk.Treeview(contenedor, columns=[c[0] for c in columnas],
                             show="headings", height=filas, selectmode="browse")
        for clave, titulo, ancho in columnas:
            tabla.heading(clave, text=titulo, anchor="w")
            tabla.column(clave, width=ancho, minwidth=40, anchor="w")
        self._colorear_tabla(tabla)
        if expandir:                            # las tablas largas necesitan desplazarse
            barra = ttk.Scrollbar(contenedor, orient="vertical", command=tabla.yview)
            tabla.configure(yscrollcommand=barra.set)
            barra.pack(side="right", fill="y")
        tabla.pack(side="left", fill="both", expand=True)
        return tabla

    # ── Zonas de tráfico ───────────────────────────────────────────────
    def _dibujar_zonas_trafico(self):
        """Pinta cada hexágono de TomTom (o la zona simulada) con el pastel de su nivel."""
        datos = self.snapshot["traffic_zones"]
        zonas = self._zonas_filtradas()
        firma = (datos["mode"], [(zona["id"], zona["severity"]) for zona in zonas])
        if firma == self._zonas_dibujadas:
            return
        for poligono in self.poligonos_trafico:
            poligono.delete()
        self.poligonos_trafico = []
        # De menos a más tráfico, para que los bordes de las zonas lentas queden encima.
        for zona in reversed(zonas):
            relleno, borde, _ = self.NIVELES_TRAFICO[zona["severity"]]
            poligono = self.mapa.set_polygon(
                [tuple(punto) for punto in zona["polygon"]],
                fill_color=relleno, outline_color=borde,
                border_width=1 if zona["severity"] == "fluido" else 2,
                name=zona["label"], data=zona["id"], command=self._clic_zona,
            )
            # Trama más densa que la de tkintermapview para resaltar las zonas con tráfico.
            if zona["severity"] != "fluido":
                self.mapa.canvas.itemconfig(poligono.canvas_polygon, stipple="gray50")
            self.poligonos_trafico.append(poligono)
        self.mapa.manage_z_order()              # rutas y buses por encima de las zonas
        self._zonas_dibujadas = firma
        self._actualizar_leyenda(datos["mode"])

    def _zonas_filtradas(self):
        """Hexágonos que cruzan alguna ruta del municipio elegido."""
        datos = self.snapshot["traffic_zones"]
        if self.municipio == self.TODOS_MUNICIPIOS or datos["mode"] != "tomtom":
            return datos["zones"]
        rutas = [ruta for ruta in self.rutas if self._en_municipio(ruta.codigo)]
        clave = (
            self.municipio,
            tuple(zona["id"] for zona in datos["zones"]),
            tuple((ruta.codigo, len(ruta.trazado())) for ruta in rutas),
        )
        if clave != getattr(self, "_clave_zonas_filtradas", None):
            poligonos = [zona["polygon"] for zona in datos["zones"]]
            cruzadas = {
                indice
                for ruta in rutas
                for a, b in zip(ruta.trazado(), ruta.trazado()[1:])
                for _, _, indice in dividir_segmento_zonas(a, b, poligonos)
                if indice is not None
            }
            self._ids_zonas_filtradas = {datos["zones"][i]["id"] for i in cruzadas}
            self._clave_zonas_filtradas = clave
        return [zona for zona in datos["zones"] if zona["id"] in self._ids_zonas_filtradas]

    def _actualizar_tabla_trafico(self):
        datos = self.snapshot["traffic_zones"]
        zonas = self._zonas_filtradas()
        if datos["mode"] == "tomtom":
            lentas = sum(zona["severity"] != "fluido" for zona in zonas)
            donde = (
                "los recorridos" if self.municipio == self.TODOS_MUNICIPIOS
                else f"las rutas de {self.municipio}"
            )
            self.lbl_resumen_trafico.config(text=(
                f"TomTom midió {len(zonas)} hexágonos sobre {donde} "
                f"({datos['updated_at']}). "
                + (f"{lentas} con tráfico lento: ahí los buses frenan según la "
                   "velocidad real de la vía. Toca una fila para ubicarla."
                   if lentas else
                   "Ninguno tiene tráfico lento; los buses circulan a velocidad libre.")
            ))
            filas = [
                (zona["id"], zona["severity"], (
                    zona["label"],
                    "Cerrada" if zona["closed"] else f"{zona['current_kmh']:.0f} km/h",
                    f"{zona['free_kmh']:.0f} km/h",
                    f"-{zona['slowdown'] * 100:.0f} %",
                    zona["buses"],
                ))
                for zona in zonas
            ]
        else:
            self.lbl_resumen_trafico.config(text=(
                "Sin medición de TomTom todavía (revisa TOMTOM_API_KEY). Se usa la "
                "zona de congestión simulada, donde cada bus frena entre "
                f"{datos['min_slowdown'] * 100:.0f} % y {datos['max_slowdown'] * 100:.0f} %."
            ))
            rango = f"{datos['min_slowdown'] * 100:.0f}-{datos['max_slowdown'] * 100:.0f} %"
            filas = [
                (zona["id"], zona["severity"], (zona["label"], "—", "—", rango, zona["buses"]))
                for zona in zonas
            ]
        if filas == getattr(self, "_filas_trafico", None):
            return
        self._filas_trafico = filas
        seleccion = self.tabla_trafico.selection()
        self.tabla_trafico.delete(*self.tabla_trafico.get_children())
        for numero, (iid, severidad, valores) in enumerate(filas):
            self.tabla_trafico.insert(
                "", "end", iid=iid, values=valores,
                tags=(severidad, "alterna") if numero % 2 else (severidad,),
            )
        for severidad, (relleno, _, _) in self.NIVELES_TRAFICO.items():
            self.tabla_trafico.tag_configure(severidad, foreground=relleno)
        self.tabla_trafico.selection_set(
            [iid for iid in seleccion if self.tabla_trafico.exists(iid)]
        )

    def _zona(self, iid):
        return next(
            (zona for zona in self.snapshot["traffic_zones"]["zones"] if zona["id"] == iid),
            None,
        )

    def _centrar_zona_seleccionada(self, _evento=None):
        seleccion = self.tabla_trafico.selection()
        zona = self._zona(seleccion[0]) if seleccion else None
        if zona is None:
            return
        poligono = zona["polygon"]
        lat, lon = zona.get("center") or (
            sum(p[0] for p in poligono) / len(poligono),
            sum(p[1] for p in poligono) / len(poligono),
        )
        self.mapa.set_position(lat, lon)

    def _clic_zona(self, poligono):
        if self.tabla_trafico.exists(poligono.data):
            self.pestañas.select(self.tab_trafico)
            self.tabla_trafico.selection_set(poligono.data)
            self.tabla_trafico.see(poligono.data)

    # ── Acciones del usuario ───────────────────────────────────────────
    def _clic_parada(self, marcador):
        self.cmb_parada.set(marcador.data)
        self.seleccionar_parada()

    def abrir_ventana_registro(self, pestaña_inicial="vehiculo"):
        ventana = tk.Toplevel(self)
        ventana.title("Agregar vehículo, bus o ruta")
        ventana.geometry("720x700")
        ventana.minsize(640, 600)
        ventana.transient(self)
        ventana.grab_set()
        C, F = self.colores, self.fuentes
        ventana.configure(background=C["fondo"])
        estilo_entrada = dict(
            relief="flat", bd=0, bg=C["superficie"], fg=C["texto"],
            insertbackground=C["texto"], highlightthickness=1,
            highlightbackground=C["borde"], highlightcolor=C["acento"],
            selectbackground=C["acento"], selectforeground=C["texto_acento"],
        )

        contenedor = ttk.Frame(ventana, padding=18)
        contenedor.pack(fill="both", expand=True)
        ttk.Label(
            contenedor,
            text="Registro de flota y recorridos",
            font=F["titulo"],
        ).pack(anchor="w")
        ttk.Label(
            contenedor,
            text="Agrega vehículos a una ruta existente o crea una ruta nueva con sus paradas.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        pestañas = ttk.Notebook(contenedor)
        pestañas.pack(fill="both", expand=True)
        tab_vehiculo = ttk.Frame(pestañas, padding=16, style="Card.TFrame")
        tab_ruta = ttk.Frame(pestañas, padding=16, style="Card.TFrame")
        pestañas.add(tab_vehiculo, text="Vehículo / bus")
        pestañas.add(tab_ruta, text="Nueva ruta")

        def agregar_campo(padre, fila, etiqueta, valores=None, valor_inicial=""):
            ttk.Label(padre, text=etiqueta, style="Field.TLabel").grid(
                row=fila, column=0, sticky="w", padx=(0, 12), pady=7
            )
            if valores is None:
                campo = tk.Entry(padre, font=(F["base"][0], 11), **estilo_entrada)
                if valor_inicial:
                    campo.insert(0, valor_inicial)
            else:
                campo = ttk.Combobox(
                    padre, state="readonly", values=valores, font=F["base"]
                )
                if valor_inicial:
                    campo.set(valor_inicial)
            campo.grid(row=fila, column=1, sticky="ew", pady=7, ipady=3)
            return campo

        tab_vehiculo.columnconfigure(1, weight=1)
        campos_vehiculo = {
            "placa": agregar_campo(tab_vehiculo, 0, "Placa:"),
            "tipo": agregar_campo(
                tab_vehiculo, 1, "Tipo de vehículo:", TIPOS_VEHICULO,
                TIPOS_VEHICULO[0],
            ),
            "modelo": agregar_campo(
                tab_vehiculo, 2, "Marca / modelo:", MODELOS_VEHICULO,
                MODELOS_VEHICULO[0],
            ),
            "capacidad": agregar_campo(
                tab_vehiculo, 3, "Capacidad de pasajeros:", valor_inicial="40"
            ),
            "ruta": agregar_campo(
                tab_vehiculo, 4, "Ruta asignada:",
                [ruta.nombre for ruta in self.rutas], self.rutas[0].nombre,
            ),
            "conductor": agregar_campo(tab_vehiculo, 5, "Conductor:"),
            "estado": agregar_campo(
                tab_vehiculo, 6, "Estado:",
                ["Operativo", "Mantenimiento", "Inactivo", "En revisión"],
                "Operativo",
            ),
        }
        ttk.Label(
            tab_vehiculo,
            text="Los vehículos en estado Operativo también se agregarán como buses al mapa.",
            wraplength=560,
            style="CardMuted.TLabel",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 4))

        botones_vehiculo = ttk.Frame(tab_vehiculo, style="Card.TFrame")
        botones_vehiculo.grid(row=8, column=0, columnspan=2, sticky="e", pady=(14, 0))

        def registrar_vehiculo():
            datos = {clave: campo.get().strip() for clave, campo in campos_vehiculo.items()}
            if any(not datos[clave] for clave in ("placa", "conductor")):
                messagebox.showerror(
                    "Datos incompletos", "La placa y el nombre del conductor son obligatorios.",
                    parent=ventana,
                )
                return
            if any(
                vehiculo["placa"].casefold() == datos["placa"].casefold()
                for vehiculo in self.vehiculos
            ):
                messagebox.showerror(
                    "Placa duplicada", "Ya existe un vehículo con esa placa.",
                    parent=ventana,
                )
                return
            try:
                capacidad = int(datos["capacidad"])
                if capacidad <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Capacidad inválida",
                    "La capacidad debe ser un entero mayor que cero.",
                    parent=ventana,
                )
                return
            ruta = next((r for r in self.rutas if r.nombre == datos["ruta"]), None)
            if ruta is None:
                messagebox.showerror(
                    "Ruta inválida", "Selecciona una ruta existente.", parent=ventana
                )
                return

            vehiculo = {
                "placa": datos["placa"].upper(),
                "tipo": datos["tipo"],
                "modelo": datos["modelo"],
                "capacidad": capacidad,
                "ruta": ruta.nombre,
                "conductor": datos["conductor"],
                "estado": datos["estado"],
            }
            try:
                self.api.create_vehicle(vehiculo)
                self._refresh_dashboard()
            except ApiError as error:
                messagebox.showerror("No se pudo registrar", str(error), parent=ventana)
                return
            ventana.destroy()
            messagebox.showinfo(
                "Registro exitoso",
                f"Vehículo {vehiculo['placa']} registrado correctamente.",
                parent=self,
            )

        ttk.Button(
            botones_vehiculo, text="Cancelar", command=ventana.destroy
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            botones_vehiculo, text="Registrar vehículo", command=registrar_vehiculo,
            style="Accent.TButton",
        ).pack(side="right")

        tab_ruta.columnconfigure(1, weight=1)
        campos_ruta = {
            "destino": agregar_campo(tab_ruta, 0, "Nombre / destino:"),
            "municipio": agregar_campo(
                tab_ruta, 1, "Municipio:", MUNICIPIOS, MUNICIPIOS[0]
            ),
            "velocidad": agregar_campo(
                tab_ruta, 2, "Velocidad (km/h):", valor_inicial="51"
            ),
            "buses": agregar_campo(
                tab_ruta, 3, "Cantidad de buses:", valor_inicial="1"
            ),
            "color": agregar_campo(
                tab_ruta, 4, "Color de ruta:",
                ["#d62828", "#1d4ed8", "#15803d", "#7e22ce", "#ea580c",
                 "#0891b2", "#be123c", "#475569"],
                "#7e22ce",
            ),
        }
        circular = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tab_ruta, text="Ruta circular (la última parada conecta con la primera)",
            variable=circular, style="Card.TCheckbutton",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(
            tab_ruta,
            text="Paradas (una por línea): Nombre; latitud; longitud. "
                 "Usa punto decimal y agrega las paradas en el orden del recorrido.",
            wraplength=570, justify="left", style="CardMuted.TLabel",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))
        cuadro_paradas = tk.Text(
            tab_ruta, height=10, wrap="none", font=F["mono"], padx=8, pady=6,
            **estilo_entrada,
        )
        cuadro_paradas.grid(row=7, column=0, columnspan=2, sticky="nsew")
        cuadro_paradas.insert(
            "1.0",
            "Terminal del Norte; 6.2779; -75.5694\n"
            "Parque de Bello; 6.3370; -75.5580\n"
            "Centro de Bello; 6.3350; -75.5570",
        )
        tab_ruta.rowconfigure(7, weight=1)
        ttk.Label(
            tab_ruta,
            text="La ruta nueva se dibujará usando estas coordenadas como trazado.",
            wraplength=560, style="CardMuted.TLabel",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(7, 0))
        botones_ruta = ttk.Frame(tab_ruta, style="Card.TFrame")
        botones_ruta.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def crear_ruta():
            destino = campos_ruta["destino"].get().strip()
            municipio = campos_ruta["municipio"].get().strip()
            try:
                velocidad = float(campos_ruta["velocidad"].get().strip())
                cantidad_buses = int(campos_ruta["buses"].get().strip())
                if not math.isfinite(velocidad) or velocidad <= 0:
                    raise ValueError
                if cantidad_buses <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Datos inválidos",
                    "La velocidad y la cantidad de buses deben ser valores positivos.",
                    parent=ventana,
                )
                return
            if not destino or not municipio:
                messagebox.showerror(
                    "Datos incompletos", "Indica el destino y el municipio.",
                    parent=ventana,
                )
                return

            paradas = []
            nombres = set()
            for numero_linea, linea in enumerate(
                cuadro_paradas.get("1.0", "end").splitlines(), start=1
            ):
                if not linea.strip():
                    continue
                partes = [parte.strip() for parte in linea.split(";")]
                if len(partes) != 3 or not partes[0]:
                    messagebox.showerror(
                        "Formato de parada inválido",
                        f"La línea {numero_linea} debe tener el formato "
                        "'Nombre; latitud; longitud'.",
                        parent=ventana,
                    )
                    return
                try:
                    latitud, longitud = float(partes[1]), float(partes[2])
                    if not (
                        math.isfinite(latitud) and math.isfinite(longitud)
                        and -90 <= latitud <= 90 and -180 <= longitud <= 180
                    ):
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Coordenada inválida",
                        f"Revisa la latitud y longitud de la línea {numero_linea}.",
                        parent=ventana,
                    )
                    return
                nombre = partes[0]
                if nombre.casefold() in nombres:
                    messagebox.showerror(
                        "Parada repetida",
                        f"La parada '{nombre}' aparece más de una vez en esta ruta.",
                        parent=ventana,
                    )
                    return
                nombres.add(nombre.casefold())
                existente = self.paradas.get(nombre)
                if existente and (
                    abs(existente[0] - latitud) > 1e-6
                    or abs(existente[1] - longitud) > 1e-6
                ):
                    messagebox.showerror(
                        "Nombre de parada en uso",
                        f"Ya existe una parada llamada '{nombre}' en otra ubicación. "
                        "Usa un nombre más específico.",
                        parent=ventana,
                    )
                    return
                paradas.append((nombre, latitud, longitud))
            if len(paradas) < 2:
                messagebox.showerror(
                    "Ruta incompleta", "Agrega al menos dos paradas con coordenadas.",
                    parent=ventana,
                )
                return

            siguiente_codigo = max(
                (
                    int(ruta.codigo[1:])
                    for ruta in self.rutas
                    if ruta.codigo.startswith("R") and ruta.codigo[1:].isdigit()
                ),
                default=0,
            ) + 1
            codigo = f"R{siguiente_codigo}"
            nombre_ruta = f"{codigo} {municipio} - {destino}"
            coordenadas = [(lat, lon) for _, lat, lon in paradas]
            if circular.get():
                coordenadas.append(coordenadas[0])
            datos_ruta = {
                "codigo": codigo,
                "nombre": nombre_ruta,
                "municipio": municipio,
                "color": campos_ruta["color"].get(),
                "velocidad_kmh": velocidad,
                "buses": cantidad_buses,
                "circular": circular.get(),
                "paradas": paradas,
                "coordenadas": coordenadas,
            }
            try:
                self.api.create_route(datos_ruta)
                self._refresh_dashboard()
            except ApiError as error:
                messagebox.showerror(
                    "No se pudo crear la ruta", str(error), parent=ventana
                )
                return

            pestañas.select(tab_vehiculo)
            campos_vehiculo["ruta"].configure(
                values=[ruta_existente.nombre for ruta_existente in self.rutas]
            )
            campos_vehiculo["ruta"].set(nombre_ruta)
            messagebox.showinfo(
                "Ruta creada",
                f"{nombre_ruta} fue agregada con {cantidad_buses} bus(es).",
                parent=ventana,
            )

        ttk.Button(
            botones_ruta, text="Cancelar", command=ventana.destroy
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            botones_ruta, text="Crear ruta y buses", command=crear_ruta,
            style="Accent.TButton",
        ).pack(side="right")
        if pestaña_inicial == "ruta":
            pestañas.select(tab_ruta)

    def actualizar_lista_rutas(self):
        for widget in self.rutas_panel.winfo_children():
            widget.destroy()
        old_menu = getattr(self, "_ruta_menu", None)
        if old_menu is not None:
            old_menu.destroy()

        rutas_municipio = [ruta for ruta in self.rutas if self._en_municipio(ruta.codigo)]
        self._ruta_menu = tk.Menu(self, tearoff=False)
        self._ruta_vars = {}
        for ruta in rutas_municipio:
            variable = tk.BooleanVar(
                self, value=self.rutas_visibles.get(ruta.codigo, True)
            )
            self._ruta_vars[ruta.codigo] = variable
            self._ruta_menu.add_checkbutton(
                label=ruta.nombre,
                variable=variable,
                command=lambda code=ruta.codigo, var=variable:
                    self._cambiar_visibilidad_ruta(code, var.get()),
            )
        selector = ttk.Menubutton(
            self.rutas_panel, text="Seleccionar rutas visibles"
        )
        selector.configure(menu=self._ruta_menu)
        selector.pack(fill="x", pady=(0, 8))

        for ruta in rutas_municipio:
            fila = ttk.Frame(self.rutas_panel, style="Card.TFrame")
            fila.pack(fill="x", anchor="w", pady=2)
            tk.Frame(fila, bg=ruta.color, width=4, height=34).pack(
                side="left", padx=(0, 10)
            )
            # El botón se empaqueta antes que los textos para que un nombre
            # largo no lo deje sin espacio.
            ttk.Button(
                fila,
                text="Eliminar",
                style="Danger.TButton",
                command=lambda r=ruta: self.eliminar_ruta(r),
                state="disabled" if len(self.rutas) == 1 else "normal",
            ).pack(side="right", padx=(4, 0))
            textos = ttk.Frame(fila, style="Card.TFrame")
            textos.pack(side="left", fill="x", expand=True)
            vuelta = round(ruta.ciclo_s / 60)
            ttk.Label(textos, text=ruta.nombre, style="Card.TLabel",
                      font=self.fuentes["negrita"]).pack(anchor="w")
            ttk.Label(
                textos,
                text=f"{ruta.n_buses} bus(es) · vuelta de {vuelta} min · "
                     f"{ruta.velocidad_kmh:.0f} km/h",
                style="CardMuted.TLabel",
            ).pack(anchor="w")

    def eliminar_ruta(self, ruta):
        ruta = next(
            (actual for actual in self.rutas if actual.codigo == ruta.codigo),
            None,
        )
        if ruta is None:
            return
        if len(self.rutas) <= 1:
            messagebox.showwarning(
                "No se puede eliminar",
                "Debe quedar al menos una ruta en la simulación.",
                parent=self,
            )
            return

        vehiculos_asociados = sum(
            vehiculo["ruta"] == ruta.nombre for vehiculo in self.vehiculos
        )
        detalle_vehiculos = (
            f"\nTambién se eliminarán {vehiculos_asociados} vehículo(s) "
            "asociado(s)."
            if vehiculos_asociados else ""
        )
        confirmar = messagebox.askyesno(
            "Eliminar ruta",
            f"¿Eliminar la ruta «{ruta.nombre}» y sus buses?"
            f"{detalle_vehiculos}",
            parent=self,
        )
        if not confirmar:
            return

        try:
            self.api.delete_route(ruta.codigo)
            self._refresh_dashboard()
        except ApiError as error:
            messagebox.showerror("No se pudo eliminar la ruta", str(error), parent=self)

    def registrar_vehiculo(self):
        self.abrir_ventana_registro()

    def _filas_flota(self):
        """Toda la flota: los buses del mapa más los vehículos registrados fuera de servicio.

        Cada fila es (iid, placa, tipo, ruta, estado, codigo_ruta). El iid indica cómo
        se elimina: 'vehiculo|PLACA' borra el registro y 'ruta|CODIGO|BUS' retira
        uno de los buses propios de la ruta.
        """
        vehiculos = {v["placa"].casefold(): v for v in self.vehiculos}
        codigos = {ruta.nombre: ruta.codigo for ruta in self.rutas}
        filas, en_mapa = [], set()
        for bus in self.buses:
            vehiculo = vehiculos.get(bus["name"].casefold())
            if vehiculo:
                en_mapa.add(bus["name"].casefold())
                filas.append((f"vehiculo|{vehiculo['placa']}", vehiculo["placa"],
                              vehiculo["tipo"], vehiculo["ruta"], "En servicio",
                              bus["route_code"]))
            else:
                ruta = self.rutas_por_codigo[bus["route_code"]]
                filas.append((f"ruta|{ruta.codigo}|{bus['name']}", bus["name"],
                              "Bus de ruta", ruta.nombre, "En servicio", ruta.codigo))
        for clave, vehiculo in vehiculos.items():
            if clave not in en_mapa:
                filas.append((f"vehiculo|{vehiculo['placa']}", vehiculo["placa"],
                              vehiculo["tipo"], vehiculo["ruta"], vehiculo["estado"],
                              codigos.get(vehiculo["ruta"], "")))
        return [fila for fila in filas if self._en_municipio(fila[5])]

    def actualizar_tabla_vehiculos(self):
        filas = self._filas_flota()
        if filas == getattr(self, "_filas_vehiculos", None):
            return
        self._filas_vehiculos = filas
        seleccion = self.tabla_vehiculos.selection()
        self.tabla_vehiculos.delete(*self.tabla_vehiculos.get_children())
        for numero, (iid, placa, tipo, ruta, estado, codigo) in enumerate(filas):
            self.tabla_vehiculos.insert(
                "", "end", iid=iid, values=(placa, tipo, ruta, estado),
                tags=(codigo, "alterna") if numero % 2 else (codigo,),
            )
        self._colorear_tabla(self.tabla_vehiculos)
        seleccion = [iid for iid in seleccion if self.tabla_vehiculos.exists(iid)]
        self.tabla_vehiculos.selection_set(seleccion)
        self.btn_eliminar_vehiculo.config(state="normal" if seleccion else "disabled")
        en_servicio = sum(fila[4] == "En servicio" for fila in filas)
        self.lbl_resumen_flota.config(
            text=f"{len(filas)} vehículo(s) · {en_servicio} en el mapa · "
                 "selecciona uno para eliminarlo"
        )

    def eliminar_vehiculo(self):
        seleccion = self.tabla_vehiculos.selection()
        if not seleccion:
            return
        tipo, *partes = seleccion[0].split("|")
        try:
            if tipo == "ruta":
                codigo, nombre_bus = partes
                ruta = self.rutas_por_codigo.get(codigo)
                if ruta is None:
                    return
                if ruta.n_buses <= 1:
                    messagebox.showwarning(
                        "No se puede eliminar",
                        f"{nombre_bus} es el único bus propio de «{ruta.nombre}». "
                        "Para quitarlo elimina la ruta desde la pestaña Rutas.",
                        parent=self,
                    )
                    return
                if not messagebox.askyesno(
                    "Eliminar bus",
                    f"¿Retirar un bus de «{ruta.nombre}»?\n"
                    f"La ruta pasará de {ruta.n_buses} a {ruta.n_buses - 1} bus(es).",
                    parent=self,
                ):
                    return
                self.api.remove_route_bus(codigo)
            else:
                placa = partes[0]
                if not messagebox.askyesno(
                    "Eliminar vehículo", f"¿Eliminar el vehículo {placa}?", parent=self
                ):
                    return
                self.api.delete_vehicle(placa)
            self._refresh_dashboard()
        except ApiError as error:
            messagebox.showerror("No se pudo eliminar", str(error), parent=self)

    def _agregar_creditos_mapa(self):
        def abrir_enlace(evento, destino):
            _ = evento
            if not webbrowser.open(destino):
                logging.error("No se pudo abrir el enlace de atribución.")

        def agregar_enlace(texto, etiqueta, url):
            self.creditos_mapa.tag_configure(
                etiqueta, foreground=self.colores["acento"], underline=True
            )
            self.creditos_mapa.tag_bind(
                etiqueta,
                "<Button-1>",
                lambda evento, destino=url: abrir_enlace(evento, destino),
            )
            self.creditos_mapa.tag_bind(
                etiqueta,
                "<Enter>",
                lambda _evento: self.creditos_mapa.configure(cursor="hand2"),
            )
            self.creditos_mapa.tag_bind(
                etiqueta,
                "<Leave>",
                lambda _evento: self.creditos_mapa.configure(cursor=""),
            )
            self.creditos_mapa.insert("end", texto, etiqueta)

        texto = self.creditos_mapa
        texto.insert("end", "© ")
        agregar_enlace(
            "OpenStreetMap contributors", "osm",
            "https://www.openstreetmap.org/copyright",
        )
        texto.insert("end", " · © ")
        agregar_enlace("Stadia Maps", "stadia", "https://stadiamaps.com/attribution/")
        texto.insert("end", " · © ")
        agregar_enlace("OpenMapTiles", "openmaptiles", "https://openmaptiles.org/")
        texto.insert("end", " · © ")
        agregar_enlace("CARTO", "carto", "https://carto.com/attribution/")
        texto.insert("end", " · Sources: ")
        agregar_enlace(
            "Esri", "esri", "https://goto.arcgisonline.com/maps/World_Topo_Map"
        )
        texto.insert(
            "end",
            ", HERE, Garmin, Intermap, increment P Corp., GEBCO, USGS, FAO, NPS, "
            "NRCAN, GeoBase, IGN, Kadaster NL, Ordnance Survey, Esri Japan, METI, "
            "Esri China (Hong Kong), © OpenStreetMap contributors, and the GIS "
            "User Community",
        )
        texto.configure(state="disabled")

    def seleccionar_parada(self):
        nombre = self.cmb_parada.get()
        if nombre not in self.paradas:
            return
        try:
            self._apply_snapshot(self.api.dashboard(nombre))
        except ApiError as error:
            messagebox.showerror("Error de API", str(error), parent=self)
            return
        self._update_selected_marker()
        self.actualizar_tablas()

    def _update_selected_marker(self):
        nombre = self.cmb_parada.get()
        if nombre not in self.paradas:
            return
        lat, lon, _ = self.paradas[nombre]
        self.marcador_sel.set_position(lat, lon)
        self.marcador_sel.set_text(nombre)

    # ── Bucle principal ────────────────────────────────────────────────
    def tick(self):
        """Polls the backend for simulation positions and arrival estimates."""
        ahora = time.monotonic()
        polled = False
        if ahora - self._last_poll >= 0.5:
            try:
                self._refresh_dashboard()
                self._last_poll = ahora
                self._backend_error_reported = False
                polled = True
            except ApiError as error:
                if not self._backend_error_reported:
                    messagebox.showerror("Backend no disponible", str(error), parent=self)
                    self._backend_error_reported = True
        self.lbl_reloj.config(text=self.snapshot["clock"])
        for name, marker in self.marcadores:
            bus = next((item for item in self.buses if item["name"] == name), None)
            if bus:
                marker.set_position(bus["latitude"], bus["longitude"])
        if polled:
            self._actualizar_estado_mapa()
        self.after(80, self.tick)

    def actualizar_tablas(self):
        self.tabla_llegadas.delete(*self.tabla_llegadas.get_children())
        visible_arrivals = (
            arrival for arrival in self.snapshot["arrivals"]
            if self._ruta_visible(arrival["route_code"])
        )
        for fila, arrival in enumerate(visible_arrivals):
            self.tabla_llegadas.insert(
                "", "end", tags=(arrival["route_code"], "alterna" if fila % 2 else ""),
                values=(
                    arrival["name"], arrival["direction"],
                    arrival["remaining_text"], arrival["arrival_time"],
                    f"{arrival['speed_kmh']:.1f} km/h",
                )
            )
        self.tabla_buses.delete(*self.tabla_buses.get_children())
        buses_visibles = [
            bus for bus in self.buses
            if self._ruta_visible(bus["route_code"])
        ]
        for fila, bus in enumerate(buses_visibles):
            self.tabla_buses.insert(
                "", "end", tags=(bus["route_code"], "alterna" if fila % 2 else ""),
                values=(
                    bus["name"], bus["next_stop"], bus["remaining_text"],
                    bus["arrival_time"], f"{bus['speed_kmh']:.1f} km/h",
                )
            )

    def cambiar_mapa(self, _evento=None):
        self.mapa.usar_proveedor(self.cmb_mapa.current())
        self._actualizar_estado_mapa()

    def _actualizar_estado_mapa(self):
        if self.mapa.mapa_disponible:
            estado = f"Mapa activo: {self.mapa.nombre_proveedor_activo}"
            if self.cmb_mapa.get() != self.mapa.nombre_proveedor_activo:
                self.cmb_mapa.set(self.mapa.nombre_proveedor_activo)   # cambió por respaldo
        else:
            estado = "Mapa sin conexión; probando los proveedores de respaldo..."

        faltantes = []
        if not os.environ.get("STADIA_MAPS_API_KEY", "").strip():
            faltantes.append("STADIA_MAPS_API_KEY")
        if not os.environ.get("CARTO_API_KEY", "").strip():
            faltantes.append("CARTO_API_KEY")
        if faltantes:
            estado += " | Faltan claves para habilitar todos los mapas: " + ", ".join(faltantes)

        texto = estado
        if texto != self._texto_estado_mapa:
            self.lbl_estado_mapa.config(text=texto)
            self._texto_estado_mapa = texto
