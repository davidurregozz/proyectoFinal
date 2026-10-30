import time
import tkinter as tk
from datetime import timedelta
from tkinter import ttk
import tkintermapview
from PIL import Image, ImageDraw, ImageTk

from simulador import SimuladorCore


class SimuladorGUI(tk.Tk):
    VELOCIDADES = {"x1 (tiempo real)": 1, "x5": 5, "x10": 10, "x30": 30, "x60": 60}

    def __init__(self, core: SimuladorCore):
        super().__init__()
        self.core = core
        self.title("Simulador de rutas de buses - POO")
        self.geometry("1250x740")

        self._ultimo_tick = time.monotonic()
        self._iconos = []
        self.paradas = self.core.obtener_paradas_unicas()

        self._construir_interfaz()
        self._ciclos = 0
        self.tick()

    def _construir_interfaz(self):
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
        ttk.Label(controles, text="  Velocidad:").pack(side="left")
        
        self.cmb_velocidad = ttk.Combobox(controles, state="readonly", width=15, values=list(self.VELOCIDADES))
        self.cmb_velocidad.set("x10")
        self.cmb_velocidad.bind("<<ComboboxSelected>>", self.cambiar_velocidad)
        self.cmb_velocidad.pack(side="left", padx=4)

        ttk.Label(panel, text="Rutas", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(8, 2))
        for ruta in self.core.rutas:
            fila = ttk.Frame(panel)
            fila.pack(anchor="w")
            tk.Label(fila, bg=ruta.color, width=2).pack(side="left", padx=(0, 6), pady=1)
            vuelta = round(ruta.ciclo_s / 60)
            ttk.Label(fila, text=f"{ruta.nombre}  (vuelta: {vuelta} min)").pack(side="left")

        ttk.Label(panel, text="Parada seleccionada", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(14, 2))
        self.cmb_parada = ttk.Combobox(panel, state="readonly", values=sorted(self.paradas))
        self.cmb_parada.set(self.core.rutas[0].paradas[1][0])
        self.cmb_parada.bind("<<ComboboxSelected>>", lambda e: self.seleccionar_parada())
        self.cmb_parada.pack(fill="x")

        ttk.Label(panel, text="Próximas llegadas", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(12, 2))
        self.tabla_llegadas = self._crear_tabla(panel, 6, [("bus", "Bus", 55), ("hacia", "Hacia", 150), ("en", "Llega en", 85), ("hora", "Hora", 55)])

        ttk.Label(panel, text="Todos los buses", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(12, 2))
        self.tabla_buses = self._crear_tabla(panel, 8, [("bus", "Bus", 55), ("proxima", "Próxima parada", 150), ("en", "Llega en", 85), ("hora", "Hora", 55)])

        self.mapa = tkintermapview.TkinterMapView(self, corner_radius=0)
        self.mapa.pack(side="left", fill="both", expand=True)

        todos = [(lat, lon) for lat, lon, _ in self.paradas.values()]
        self.mapa.set_position(sum(p[0] for p in todos) / len(todos), sum(p[1] for p in todos) / len(todos))
        self.mapa.set_zoom(13)

        for ruta in self.core.rutas:
            self.mapa.set_path(ruta.coordenadas, color=ruta.color, width=5)

        for nombre, (lat, lon, rutas) in self.paradas.items():
            borde = rutas[0].color if len(rutas) == 1 else "#222222"
            self.mapa.set_marker(lat, lon, icon=self._icono(14, "white", borde), data=nombre, command=self._clic_parada)

        self.marcador_sel = self.mapa.set_marker(0, 0, text="", icon=self._icono(22, "#facc15", "#222222"), text_color="#111111", font=("Helvetica", 11, "bold"))

        self.marcadores_buses = []
        for bus in self.core.buses:
            lat, lon, _, _ = bus.obtener_ubicacion(0)
            m = self.mapa.set_marker(lat, lon, text=bus.nombre, icon=self._icono(20, bus.ruta.color, "white"), text_color=bus.ruta.color, font=("Helvetica", 9, "bold"))
            self.marcadores_buses.append((bus, m))

        self.seleccionar_parada()

    def _icono(self, diametro, relleno, borde):
        k = 4
        img = Image.new("RGBA", (diametro * k, diametro * k), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((k, k, diametro * k - k, diametro * k - k), fill=relleno, outline=borde, width=3 * k)
        icono = ImageTk.PhotoImage(img.resize((diametro, diametro), Image.LANCZOS))
        self._iconos.append(icono)
        return icono

    def _crear_tabla(self, padre, filas, columnas):
        tabla = ttk.Treeview(padre, columns=[c[0] for c in columnas], show="headings", height=filas)
        for clave, titulo, ancho in columnas:
            tabla.heading(clave, text=titulo, anchor="w")
            tabla.column(clave, width=ancho, anchor="w")
        for ruta in self.core.rutas:
            tabla.tag_configure(ruta.codigo, foreground=ruta.color)
        tabla.pack(fill="x")
        return tabla

    def alternar_pausa(self):
        self.core.pausado = not self.core.pausado
        self.btn_pausa.config(text="Reanudar" if self.core.pausado else "Pausar")

    def cambiar_velocidad(self, _evento=None):
        self.core.factor = self.VELOCIDADES[self.cmb_velocidad.get()]

    def _clic_parada(self, marcador):
        self.cmb_parada.set(marcador.data)
        self.seleccionar_parada()

    def seleccionar_parada(self):
        nombre = self.cmb_parada.get()
        lat, lon, _ = self.paradas[nombre]
        self.marcador_sel.set_position(lat, lon)
        self.marcador_sel.set_text(nombre)
        self.actualizar_tablas()

    def _texto_espera(self, segundos):
        if segundos <= 0:
            return "En la parada"
        if segundos < 60:
            return "< 1 min"
        return f"{round(segundos / 60)} min"

    def tick(self):
        ahora = time.monotonic()
        delta = ahora - self._ultimo_tick
        self._ultimo_tick = ahora
        
        self.core.avanzar_tiempo(delta)

        for bus, marcador in self.marcadores_buses:
            lat, lon, _, _ = bus.obtener_ubicacion(self.core.t_sim)
            marcador.set_position(lat, lon)

        self.lbl_reloj.config(text=self.core.obtener_hora_simulada().strftime("%H:%M:%S"))
        self._ciclos += 1
        if self._ciclos % 6 == 0:
            self.actualizar_tablas()
            
        self.after(80, self.tick)

    def actualizar_tablas(self):
        ahora = self.core.obtener_hora_simulada()

        def hora_en(segundos):
            return (ahora + timedelta(seconds=segundos)).strftime("%H:%M")

        parada = self.cmb_parada.get()
        llegadas = []
        for bus in self.core.buses:
            resultado = bus.consultar_tiempo_parada(self.core.t_sim, parada)
            if resultado:
                llegadas.append((resultado[0], bus, resultado[1]))
        llegadas.sort(key=lambda fila: fila[0])

        self.tabla_llegadas.delete(*self.tabla_llegadas.get_children())
        for falta, bus, sentido in llegadas:
            self.tabla_llegadas.insert("", "end", tags=(bus.ruta.codigo,), values=(bus.nombre, sentido, self._texto_espera(falta), hora_en(falta)))

        self.tabla_buses.delete(*self.tabla_buses.get_children())
        for bus in self.core.buses:
            _, _, proxima, falta = bus.obtener_ubicacion(self.core.t_sim)
            self.tabla_buses.insert("", "end", tags=(bus.ruta.codigo,), values=(bus.nombre, proxima, self._texto_espera(falta), hora_en(falta)))