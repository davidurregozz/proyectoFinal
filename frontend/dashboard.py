"""Tkinter dashboard; all application data is obtained from the REST API."""

import logging
import math
import os
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from PIL import Image, ImageDraw, ImageTk

from backend.seed_data import MODELOS_VEHICULO, MUNICIPIOS, TIPOS_VEHICULO
from frontend.api_client import ApiClient, ApiError
from frontend.map_widget import crear_mapa_con_respaldo, proveedores_mapa


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
    VELOCIDADES = {"x1 (tiempo real)": 1, "x5": 5, "x10": 10, "x30": 30, "x60": 60}

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

        self.title("Simulador de rutas de buses")
        self.geometry("1250x740")

        self._iconos = []                       # Tk necesita que guardemos las imágenes

        # ── Panel derecho ───────────────────────────────────────────────
        panel = ttk.Frame(self, padding=12, width=400)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        self.lbl_reloj = ttk.Label(panel, font=("Helvetica", 26, "bold"))
        self.lbl_reloj.pack(anchor="w")
        ttk.Label(panel, text="Hora simulada").pack(anchor="w")

        controles = ttk.Frame(panel)
        controles.pack(fill="x", pady=10)
        self.btn_pausa = ttk.Button(controles, text="Pausar", command=self.alternar_pausa)
        self.btn_pausa.pack(side="left")
        self.btn_pausa.config(text="Reanudar" if self.pausado else "Pausar")
        ttk.Label(controles, text="  Velocidad:").pack(side="left")
        self.cmb_velocidad = ttk.Combobox(controles, state="readonly", width=15,
                                          values=list(self.VELOCIDADES))
        self.cmb_velocidad.set(f"x{int(self.factor)}")
        self.cmb_velocidad.bind("<<ComboboxSelected>>", self.cambiar_velocidad)
        self.cmb_velocidad.pack(side="left", padx=4)

        self.rutas_panel = ttk.Frame(panel)
        self.rutas_panel.pack(fill="x")
        ttk.Label(panel, text="Agregar Vehículo",
                  font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(10, 2))
        ttk.Button(panel, text="Registrar vehículo o crear ruta",
                   command=self.abrir_ventana_registro).pack(fill="x", pady=(0, 6))
        ttk.Label(panel, text="Vehículos registrados",
                  font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(4, 2))
        self.tabla_vehiculos = self._crear_tabla(panel, 4, [
            ("placa", "Placa", 75), ("tipo", "Tipo", 100), ("modelo", "Modelo", 100),
            ("ruta", "Ruta", 120)])
        self.actualizar_tabla_vehiculos()

        ttk.Label(panel, text="Rutas", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(8, 2))
        self.actualizar_lista_rutas()
        self.lbl_estado_trafico = ttk.Label(
            panel,
            text=self.snapshot["traffic"]["message"],
            wraplength=360,
            foreground="#374151",
        )
        self.lbl_estado_trafico.pack(anchor="w", fill="x", pady=(3, 0))

        ttk.Label(panel, text="Parada (o haz clic en una del mapa)",
                  font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(14, 2))
        self.cmb_parada = ttk.Combobox(panel, state="readonly", values=sorted(self.paradas))
        self.cmb_parada.set(next(iter(self.paradas)))
        self.cmb_parada.bind("<<ComboboxSelected>>", lambda e: self.seleccionar_parada())
        self.cmb_parada.pack(fill="x")

        ttk.Label(panel, text="Próximas llegadas a la parada",
                  font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(12, 2))
        self.tabla_llegadas = self._crear_tabla(panel, 6, [
            ("bus", "Bus", 55), ("hacia", "Hacia", 150),
            ("en", "Llega en", 85), ("hora", "Hora", 55)])

        ttk.Label(panel, text="Todos los buses",
                  font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(12, 2))
        self.tabla_buses = self._crear_tabla(panel, 8, [
            ("bus", "Bus", 55), ("proxima", "Próxima parada", 150),
            ("en", "Llega en", 85), ("hora", "Hora", 55)])

        # ── Mapa ────────────────────────────────────────────────────────
        zona_mapa = ttk.Frame(self)
        zona_mapa.pack(side="left", fill="both", expand=True)
        import tkintermapview
        clase_mapa = crear_mapa_con_respaldo(tkintermapview)
        self.mapa = clase_mapa(
            zona_mapa, corner_radius=0, proveedores=proveedores
        )
        self.mapa.pack(fill="both", expand=True)
        self.marco_estado_mapa = ttk.Frame(zona_mapa, padding=(4, 2))
        self.marco_estado_mapa.place(
            relx=0.01, rely=0.99, anchor="sw", relwidth=0.98
        )
        self.lbl_estado_mapa = ttk.Label(
            self.marco_estado_mapa,
            text="",
            background="white",
            foreground="#222222",
            padding=(6, 3),
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
            background="white",
            foreground="#222222",
            font=("Helvetica", 8),
            takefocus=0,
        )
        self.creditos_mapa.pack(fill="x")
        self._agregar_creditos_mapa()
        self._texto_estado_mapa = ""

        todos = [(lat, lon) for lat, lon, _ in self.paradas.values()]
        self.mapa.set_position(sum(p[0] for p in todos) / len(todos),
                               sum(p[1] for p in todos) / len(todos))
        self.mapa.set_zoom(13)

        self.trazos_rutas = {}
        self.marcadores_paradas = {}
        self._render_route_layers()
        self._route_geometry_drawn = self._route_geometry_signature()

        self.marcador_sel = self.mapa.set_marker(                 # parada elegida
            0, 0, text="", icon=self._icono(22, "#facc15", "#222222"),
            text_color="#111111", font=("Helvetica", 11, "bold"))

        self.marcadores = []                                      # buses
        self._render_bus_markers()

        self.seleccionar_parada()
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
        self.factor = snapshot["factor"]
        self.pausado = snapshot["paused"]
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
        self.btn_pausa.config(text="Reanudar" if self.pausado else "Pausar")
        self.cmb_velocidad.set(f"x{int(self.factor)}")
        self.lbl_estado_trafico.config(
            text=self.snapshot["traffic"]["message"],
            foreground=(
                "#166534" if self.snapshot["traffic"]["available"] else "#92400e"
            ),
        )
        available_stops = sorted(self.paradas)
        self.cmb_parada.configure(values=available_stops)
        if self.cmb_parada.get() not in self.paradas:
            self.cmb_parada.set(available_stops[0])
            snapshot = self.api.dashboard(available_stops[0])
            self._apply_snapshot(snapshot)

        route_codes = {route.codigo for route in self.rutas}
        geometry_signature = self._route_geometry_signature()
        routes_changed = route_codes != set(self._route_geometry_drawn)
        if routes_changed or geometry_signature != self._route_geometry_drawn:
            self._render_route_layers()
            if routes_changed:
                self.actualizar_lista_rutas()
            for route in self.rutas:
                for table in (self.tabla_llegadas, self.tabla_buses):
                    table.tag_configure(route.codigo, foreground=route.color)
            self._route_geometry_drawn = geometry_signature

        bus_names = {
            bus["name"] for bus in self.buses
            if self.rutas_visibles.get(bus["route_code"], True)
        }
        marker_names = {name for name, _ in self.marcadores}
        if bus_names != marker_names:
            self._render_bus_markers()
        else:
            buses_by_name = {
                bus["name"]: bus for bus in self.buses
                if self.rutas_visibles.get(bus["route_code"], True)
            }
            for name, marker in self.marcadores:
                bus = buses_by_name[name]
                marker.set_position(bus["latitude"], bus["longitude"])
        if self.vehiculos != getattr(self, "_displayed_vehicles", None):
            self.actualizar_tabla_vehiculos()
            self._displayed_vehicles = [vehicle.copy() for vehicle in self.vehiculos]
        self._update_selected_marker()
        self.actualizar_tablas()

    def _render_buses(self):
        self._render_bus_markers()

    def _render_bus_markers(self):
        for _, marker in self.marcadores:
            marker.delete()
        self.marcadores = []
        for bus in self.buses:
            if not self.rutas_visibles.get(bus["route_code"], True):
                continue
            marker = self.mapa.set_marker(
                bus["latitude"], bus["longitude"], text=bus["name"],
                icon=self._icono(20, bus["color"], "white"),
                text_color=bus["color"], font=("Helvetica", 9, "bold"),
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
            if self.rutas_visibles.get(route.codigo, True):
                self.trazos_rutas[route.codigo] = self.mapa.set_path(
                    route.trazado(), color=route.color, width=5
                )
        for name, (lat, lon, routes) in self.paradas.items():
            visible_routes = [
                route for route in routes
                if self.rutas_visibles.get(route.codigo, True)
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

    # ── Ayudas para construir la interfaz ──────────────────────────────
    def _icono(self, diametro, relleno, borde):
        """Dibuja un círculo de color para usarlo como marcador en el mapa."""
        Image, ImageDraw, ImageTk = self._pil
        k = 4                                   # se dibuja grande y se reduce (suaviza)
        img = Image.new("RGBA", (diametro * k, diametro * k), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((k, k, diametro * k - k, diametro * k - k),
                                    fill=relleno, outline=borde, width=3 * k)
        icono = ImageTk.PhotoImage(img.resize((diametro, diametro), Image.LANCZOS))
        self._iconos.append(icono)
        return icono

    def _crear_tabla(self, padre, filas, columnas):
        tabla = ttk.Treeview(padre, columns=[c[0] for c in columnas],
                             show="headings", height=filas)
        for clave, titulo, ancho in columnas:
            tabla.heading(clave, text=titulo, anchor="w")
            tabla.column(clave, width=ancho, anchor="w")
        for ruta in self.rutas:                 # cada fila con el color de su ruta
            tabla.tag_configure(ruta.codigo, foreground=ruta.color)
        tabla.pack(fill="x")
        return tabla

    # ── Acciones del usuario ───────────────────────────────────────────
    def alternar_pausa(self):
        try:
            self.api.set_control(not self.pausado, self.factor)
            self._refresh_dashboard()
            self.btn_pausa.config(text="Reanudar" if self.pausado else "Pausar")
        except ApiError as error:
            messagebox.showerror("Error de API", str(error), parent=self)

    def cambiar_velocidad(self, _evento=None):
        try:
            self.factor = self.VELOCIDADES[self.cmb_velocidad.get()]
            self.api.set_control(self.pausado, self.factor)
            self._refresh_dashboard()
        except ApiError as error:
            messagebox.showerror("Error de API", str(error), parent=self)

    def _clic_parada(self, marcador):
        self.cmb_parada.set(marcador.data)
        self.seleccionar_parada()

    def abrir_ventana_registro(self):
        ventana = tk.Toplevel(self)
        ventana.title("Agregar vehículo, bus o ruta")
        ventana.geometry("720x700")
        ventana.minsize(640, 600)
        ventana.transient(self)
        ventana.grab_set()

        contenedor = ttk.Frame(ventana, padding=14)
        contenedor.pack(fill="both", expand=True)
        ttk.Label(
            contenedor,
            text="Registro de flota y recorridos",
            font=("Helvetica", 16, "bold"),
        ).pack(anchor="w", pady=(0, 10))
        pestañas = ttk.Notebook(contenedor)
        pestañas.pack(fill="both", expand=True)
        tab_vehiculo = ttk.Frame(pestañas, padding=14)
        tab_ruta = ttk.Frame(pestañas, padding=14)
        pestañas.add(tab_vehiculo, text="Vehículo / bus")
        pestañas.add(tab_ruta, text="Nueva ruta")

        def agregar_campo(padre, fila, etiqueta, valores=None, valor_inicial=""):
            ttk.Label(padre, text=etiqueta, font=("Helvetica", 10, "bold")).grid(
                row=fila, column=0, sticky="w", padx=(0, 12), pady=7
            )
            if valores is None:
                campo = tk.Entry(
                    padre, relief="solid", bd=1, bg="white", fg="#111111",
                    insertbackground="#111111", font=("Helvetica", 11),
                )
                if valor_inicial:
                    campo.insert(0, valor_inicial)
            else:
                campo = ttk.Combobox(
                    padre, state="readonly", values=valores, font=("Helvetica", 10)
                )
                if valor_inicial:
                    campo.set(valor_inicial)
            campo.grid(row=fila, column=1, sticky="ew", pady=7)
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
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 4))

        botones_vehiculo = ttk.Frame(tab_vehiculo)
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
            botones_vehiculo, text="Registrar vehículo", command=registrar_vehiculo
        ).pack(side="right")

        tab_ruta.columnconfigure(1, weight=1)
        campos_ruta = {
            "destino": agregar_campo(tab_ruta, 0, "Nombre / destino:"),
            "municipio": agregar_campo(
                tab_ruta, 1, "Municipio:", MUNICIPIOS, MUNICIPIOS[0]
            ),
            "velocidad": agregar_campo(
                tab_ruta, 2, "Velocidad (km/h):", valor_inicial="25"
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
            variable=circular,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(
            tab_ruta,
            text="Paradas (una por línea): Nombre; latitud; longitud. "
                 "Usa punto decimal y agrega las paradas en el orden del recorrido.",
            wraplength=570, justify="left",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))
        cuadro_paradas = tk.Text(
            tab_ruta, height=10, wrap="none", relief="solid", bd=1,
            bg="white", fg="#111111", insertbackground="#111111",
            font=("Consolas", 10),
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
            wraplength=560,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(7, 0))
        botones_ruta = ttk.Frame(tab_ruta)
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
            botones_ruta, text="Crear ruta y buses", command=crear_ruta
        ).pack(side="right")

    def actualizar_lista_rutas(self):
        for widget in self.rutas_panel.winfo_children():
            widget.destroy()
        old_menu = getattr(self, "_ruta_menu", None)
        if old_menu is not None:
            old_menu.destroy()

        self._ruta_menu = tk.Menu(self, tearoff=False)
        self._ruta_vars = {}
        for ruta in self.rutas:
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
            self.rutas_panel, text="Seleccionar rutas visibles  ▼"
        )
        selector.configure(menu=self._ruta_menu)
        selector.pack(fill="x", pady=(0, 4))

        for ruta in self.rutas:
            fila = ttk.Frame(self.rutas_panel)
            fila.pack(fill="x", anchor="w")
            tk.Label(fila, bg=ruta.color, width=2).pack(
                side="left", padx=(0, 6), pady=1
            )
            vuelta = round(ruta.ciclo_s / 60)
            ttk.Label(
                fila, text=f"{ruta.nombre}  (vuelta: {vuelta} min)"
            ).pack(side="left", fill="x", expand=True)
            ttk.Button(
                fila,
                text="Eliminar",
                command=lambda r=ruta: self.eliminar_ruta(r),
                state="disabled" if len(self.rutas) == 1 else "normal",
            ).pack(side="right", padx=(4, 0))

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

    def actualizar_tabla_vehiculos(self):
        self.tabla_vehiculos.delete(*self.tabla_vehiculos.get_children())
        for vehiculo in self.vehiculos:
            self.tabla_vehiculos.insert("", "end", values=(
                vehiculo["placa"],
                vehiculo["tipo"],
                vehiculo["modelo"],
                vehiculo["ruta"],
            ))

    def _agregar_creditos_mapa(self):
        def abrir_enlace(evento, destino):
            _ = evento
            if not webbrowser.open(destino):
                logging.error("No se pudo abrir el enlace de atribución.")

        def agregar_enlace(texto, etiqueta, url):
            self.creditos_mapa.tag_configure(
                etiqueta, foreground="#1759a5", underline=True
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
            if self.rutas_visibles.get(arrival["route_code"], True)
        )
        for arrival in visible_arrivals:
            self.tabla_llegadas.insert(
                "", "end", tags=(arrival["route_code"],), values=(
                    arrival["name"], arrival["direction"],
                    arrival["remaining_text"], arrival["arrival_time"],
                )
            )
        self.tabla_buses.delete(*self.tabla_buses.get_children())
        for bus in self.buses:
            if not self.rutas_visibles.get(bus["route_code"], True):
                continue
            self.tabla_buses.insert(
                "", "end", tags=(bus["route_code"],), values=(
                    bus["name"], bus["next_stop"], bus["remaining_text"],
                    bus["arrival_time"],
                )
            )

    def _actualizar_estado_mapa(self):
        if self.mapa.mapa_disponible:
            estado = f"Mapa activo: {self.mapa.nombre_proveedor_activo}"
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
