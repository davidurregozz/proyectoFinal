"""
Simulador de rutas de buses con mapa en vivo
============================================

Muestra un mapa (OpenStreetMap) con varias rutas, los buses moviéndose por
ellas y un tablero con la hora aproximada de llegada a la parada que elijas.

Requisitos:   pip install tkintermapview pillow
Ejecutar:     python simulador_buses.py
(Necesita internet para descargar las imágenes del mapa.)

El archivo está dividido en tres partes:
  1. DATOS    -> las rutas y paradas (edita aquí para poner las tuyas)
  2. LÓGICA   -> cálculo de posiciones y tiempos de llegada (sin interfaz)
  3. INTERFAZ -> ventana con el mapa y las tablas
"""

import math
import time
import tkinter as tk
from bisect import bisect_right
from datetime import datetime, timedelta
from tkinter import ttk

# ════════════════════════════════════════════════════════════════════════
# 1. DATOS
# ════════════════════════════════════════════════════════════════════════
# Rutas de EJEMPLO en Medellín: las coordenadas son aproximadas y no
# representan recorridos reales.
# Cada parada es (nombre, latitud, longitud). Si dos rutas tienen una parada
# con el mismo nombre, el tablero muestra los buses de ambas.
# "coordenadas" define el trazado en orden; agrega puntos (latitud, longitud)
# entre las paradas para seguir las calles. Incluye las coordenadas exactas
# de las paradas; en rutas circulares, repite la primera coordenada al final.

ESPERA_EN_PARADA_S = 25          # segundos que el bus se detiene en cada parada

RUTAS = [
    {
        "nombre": "R1 Centro - Poblado",
        "color": "#d62828",
        "velocidad_kmh": 22,
        "buses": 2,
        "circular": False,       # False = va y vuelve por el mismo camino
        "paradas": [
            ("Parque Berrío",      6.2502, -75.5682),
            ("San Antonio",        6.2472, -75.5697),
            ("Alpujarra",          6.2449, -75.5735),
            ("Exposiciones",       6.2383, -75.5732),
            ("Industriales",       6.2300, -75.5756),
            ("Estación Poblado",   6.2126, -75.5779),
            ("Parque del Poblado", 6.2104, -75.5707),
        ],
        "coordenadas": [
            (6.2502, -75.5682), (6.2472, -75.5697), (6.2449, -75.5735),
            (6.2383, -75.5732), (6.2300, -75.5756), (6.2126, -75.5779),
            (6.2104, -75.5707),
        ],
    },
    {
        "nombre": "R2 Centro - San Javier",
        "color": "#1d4ed8",
        "velocidad_kmh": 20,
        "buses": 2,
        "circular": False,
        "paradas": [
            ("San Antonio",  6.2472, -75.5697),
            ("Cisneros",     6.2491, -75.5749),
            ("Suramericana", 6.2530, -75.5829),
            ("Estadio",      6.2533, -75.5883),
            ("Floresta",     6.2587, -75.5977),
            ("San Javier",   6.2567, -75.6134),
        ],
        "coordenadas": [
            (6.2472, -75.5697), (6.2491, -75.5749), (6.2530, -75.5829),
            (6.2533, -75.5883), (6.2587, -75.5977), (6.2567, -75.6134),
        ],
    },
    {
        "nombre": "R3 Circular Norte",
        "color": "#15803d",
        "velocidad_kmh": 24,
        "buses": 2,
        "circular": True,        # True = del último punto regresa al primero
        "paradas": [
            ("Parque Berrío",            6.2502, -75.5682),
            ("Prado",                    6.2570, -75.5661),
            ("Hospital",                 6.2639, -75.5633),
            ("Universidad de Antioquia", 6.264789, -75.569457),
            ("Terminal del Norte",       6.2779, -75.5694),
            ("Universidad Nacional",     6.2617, -75.5773),
        ],
        "coordenadas": [
            (6.2502, -75.5682), (6.2570, -75.5661), (6.2639, -75.5633),
            (6.264789, -75.569457), (6.265128, -75.571600), (6.2779, -75.5694), (6.2617, -75.5773),
            (6.2502, -75.5682),
        ],
    },
]


# ════════════════════════════════════════════════════════════════════════
# 2. LÓGICA DE LA SIMULACIÓN
# ════════════════════════════════════════════════════════════════════════

def distancia_coordenadas_m(p1, p2):
    """Distancia en metros entre dos pares (latitud, longitud)."""
    lat1, lon1 = p1
    lat2, lon2 = p2
    r = 6_371_000
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = f2 - f1, math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distancia_m(p1, p2):
    """Distancia en metros entre dos paradas (fórmula de Haversine)."""
    return distancia_coordenadas_m(p1[1:], p2[1:])


class Ruta:
    """
    Una ruta se recorre en un CICLO que se repite sin fin.
    Al crearla se calcula su 'horario': para cada parada del ciclo, en qué
    segundo llega el bus y en qué segundo sale. Con eso, saber dónde está un
    bus o cuánto le falta para una parada es solo consultar esa tabla.
    """

    def __init__(self, datos):
        self.nombre = datos["nombre"]
        self.codigo = self.nombre.split()[0]          # "R1", "R2", ...
        self.color = datos["color"]
        self.circular = datos["circular"]
        self.paradas = datos["paradas"]
        self.n_buses = datos["buses"]
        self.velocidad_kmh = datos["velocidad_kmh"]
        velocidad_ms = self.velocidad_kmh / 3.6

        # Cada parada debe aparecer en orden en el trazado para poder dividirlo
        # en tramos y calcular correctamente la posición y el tiempo del bus.
        coordenadas_paradas = [(lat, lon) for _, lat, lon in self.paradas]
        coordenadas = datos.get("coordenadas", coordenadas_paradas)
        if self.circular and "coordenadas" not in datos:
            coordenadas = [*coordenadas, coordenadas_paradas[0]]
        self.coordenadas = list(coordenadas)
        if not self.coordenadas:
            raise ValueError(f"El trazado de {self.nombre} no tiene coordenadas.")
        if self.coordenadas[0] != coordenadas_paradas[0]:
            raise ValueError(
                f"El trazado de {self.nombre} debe iniciar en la coordenada "
                "de su primera parada."
            )
        indices_paradas = []
        desde = 0
        for coordenada in coordenadas_paradas:
            try:
                indice = self.coordenadas.index(coordenada, desde)
            except ValueError as error:
                raise ValueError(
                    f"El trazado de {self.nombre} debe incluir las coordenadas "
                    "de todas sus paradas en orden."
                ) from error
            indices_paradas.append(indice)
            desde = indice + 1
        coordenada_final = coordenadas_paradas[0] if self.circular else coordenadas_paradas[-1]
        if self.coordenadas[-1] != coordenada_final:
            raise ValueError(
                f"El trazado de {self.nombre} debe terminar en la coordenada "
                "de su última parada del recorrido."
            )

        self._tramos_ida = [
            self.coordenadas[inicio:fin + 1]
            for inicio, fin in zip(indices_paradas, indices_paradas[1:])
        ]
        if self.circular:
            self._tramos_ida.append(self.coordenadas[indices_paradas[-1]:])

        # Orden en que se visitan las paradas durante un ciclo completo
        n = len(self.paradas)
        if self.circular:
            orden = list(range(n)) + [0]                           # 0,1,2,...,0
        else:
            orden = list(range(n)) + list(range(n - 2, -1, -1))    # ida y vuelta

        # horario = lista de (t_llegada, t_salida, indice_parada, sentido)
        self.horario = []
        self._tramos_horario = []
        t = 0.0
        for k, idx in enumerate(orden):
            if k > 0:
                tramo = self._tramo_entre(orden[k - 1], idx)
                distancia = sum(
                    distancia_coordenadas_m(a, b)
                    for a, b in zip(tramo, tramo[1:])
                )
                t += distancia / velocidad_ms
            if k == len(orden) - 1:
                break                 # regresó al inicio: aquí se cierra el ciclo
            if self.circular:
                sentido = "Circular"
            elif k < n - 1:
                sentido = self.paradas[-1][0]     # va hacia la última parada
            else:
                sentido = self.paradas[0][0]      # viene de regreso
            self.horario.append((t, t + ESPERA_EN_PARADA_S, idx, sentido))
            self._tramos_horario.append(
                self._tramo_entre(idx, orden[k + 1]))
            t += ESPERA_EN_PARADA_S

        self.ciclo_s = t                                   # duración del ciclo
        self._llegadas = [h[0] for h in self.horario]      # para búsqueda rápida

    def _tramo_entre(self, origen, destino):
        """Devuelve los puntos del trazado entre dos paradas consecutivas."""
        if destino == origen + 1:
            return self._tramos_ida[origen]
        if self.circular and origen == len(self.paradas) - 1 and destino == 0:
            return self._tramos_ida[-1]
        if destino == origen - 1:
            return list(reversed(self._tramos_ida[destino]))
        raise ValueError(
            f"Las paradas {origen} y {destino} no son consecutivas en "
            f"el trazado de {self.nombre}."
        )

    @staticmethod
    def _posicion_en_tramo(tramo, distancia):
        """Interpola la posición a una distancia recorrida sobre el trazado."""
        for inicio, fin in zip(tramo, tramo[1:]):
            largo = distancia_coordenadas_m(inicio, fin)
            if distancia <= largo:
                avance = distancia / largo if largo else 0.0
                return (
                    inicio[0] + (fin[0] - inicio[0]) * avance,
                    inicio[1] + (fin[1] - inicio[1]) * avance,
                )
            distancia -= largo
        return tramo[-1]

    def trazado(self):
        """Lista de (lat, lon) para dibujar la línea de la ruta."""
        return self.coordenadas

    def estado(self, fase):
        """
        Dónde está un bus cuando lleva 'fase' segundos dentro del ciclo.
        Devuelve (lat, lon, próxima_parada, segundos_que_faltan).
        Si está detenido en una parada, segundos_que_faltan = 0.
        """
        i = bisect_right(self._llegadas, fase) - 1
        _, t_salida, idx, _ = self.horario[i]
        nombre, lat, lon = self.paradas[idx]
        if fase <= t_salida:                               # detenido en la parada
            return lat, lon, nombre, 0.0

        j = (i + 1) % len(self.horario)                    # siguiente parada
        t_siguiente = self.horario[j][0] if j else self.ciclo_s
        nombre2 = self.paradas[self.horario[j][2]][0]
        distancia = (fase - t_salida) * (self.velocidad_kmh / 3.6)
        posicion = self._posicion_en_tramo(self._tramos_horario[i], distancia)
        return (*posicion, nombre2, t_siguiente - fase)

    def segundos_hasta(self, fase, nombre_parada):
        """
        Segundos que faltan para que el bus pase por 'nombre_parada'.
        Devuelve (segundos, sentido) o None si la ruta no pasa por ahí.
        """
        mejor = None
        for t_llegada, t_salida, idx, sentido in self.horario:
            if self.paradas[idx][0] != nombre_parada:
                continue
            if t_llegada <= fase <= t_salida:
                falta = 0.0                                 # ya está ahí
            else:
                falta = (t_llegada - fase) % self.ciclo_s
            if mejor is None or falta < mejor[0]:
                mejor = (falta, sentido)
        return mejor


class Bus:
    """Un bus es una ruta + un desfase, para que no salgan todos a la vez."""

    def __init__(self, ruta, numero, desfase_s):
        self.ruta = ruta
        self.nombre = f"{ruta.codigo}-{numero}"
        self.desfase_s = desfase_s

    def fase(self, t_sim):
        return (t_sim + self.desfase_s) % self.ruta.ciclo_s


def crear_flota(datos_rutas):
    """Crea las rutas y reparte sus buses de forma pareja a lo largo del ciclo."""
    rutas = [Ruta(d) for d in datos_rutas]
    buses = []
    for ruta in rutas:
        for k in range(ruta.n_buses):
            buses.append(Bus(ruta, k + 1, k * ruta.ciclo_s / ruta.n_buses))
    return rutas, buses


def texto_espera(segundos):
    if segundos <= 0:
        return "En la parada"
    if segundos < 60:
        return "< 1 min"
    return f"{round(segundos / 60)} min"


# ════════════════════════════════════════════════════════════════════════
# 3. INTERFAZ GRÁFICA
# ════════════════════════════════════════════════════════════════════════

class Simulador(tk.Tk):
    VELOCIDADES = {"x1 (tiempo real)": 1, "x5": 5, "x10": 10, "x30": 30, "x60": 60}

    def __init__(self):
        super().__init__()
        # Se importan aquí para que la LÓGICA de arriba se pueda usar sin interfaz
        import tkintermapview
        from PIL import Image, ImageDraw, ImageTk
        self._pil = (Image, ImageDraw, ImageTk)

        self.title("Simulador de rutas de buses")
        self.geometry("1250x740")

        self.rutas, self.buses = crear_flota(RUTAS)
        self.t_sim = 0.0                        # segundos simulados transcurridos
        self.hora_inicio = datetime.now()
        self.factor = 10
        self.pausado = False
        self._ultimo_tick = time.monotonic()
        self._iconos = []                       # Tk necesita que guardemos las imágenes

        # Paradas únicas: nombre -> (lat, lon, [rutas que pasan])
        self.paradas = {}
        for ruta in self.rutas:
            for nombre, lat, lon in ruta.paradas:
                self.paradas.setdefault(nombre, (lat, lon, []))[2].append(ruta)

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
        ttk.Label(controles, text="  Velocidad:").pack(side="left")
        self.cmb_velocidad = ttk.Combobox(controles, state="readonly", width=15,
                                          values=list(self.VELOCIDADES))
        self.cmb_velocidad.set("x10")
        self.cmb_velocidad.bind("<<ComboboxSelected>>", self.cambiar_velocidad)
        self.cmb_velocidad.pack(side="left", padx=4)

        ttk.Label(panel, text="Rutas", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(8, 2))
        for ruta in self.rutas:
            fila = ttk.Frame(panel)
            fila.pack(anchor="w")
            tk.Label(fila, bg=ruta.color, width=2).pack(side="left", padx=(0, 6), pady=1)
            vuelta = round(ruta.ciclo_s / 60)
            ttk.Label(fila, text=f"{ruta.nombre}  (vuelta: {vuelta} min)").pack(side="left")

        ttk.Label(panel, text="Parada (o haz clic en una del mapa)",
                  font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(14, 2))
        self.cmb_parada = ttk.Combobox(panel, state="readonly", values=sorted(self.paradas))
        self.cmb_parada.set(self.rutas[0].paradas[1][0])
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
        self.mapa = tkintermapview.TkinterMapView(self, corner_radius=0)
        self.mapa.pack(side="left", fill="both", expand=True)

        todos = [(lat, lon) for lat, lon, _ in self.paradas.values()]
        self.mapa.set_position(sum(p[0] for p in todos) / len(todos),
                               sum(p[1] for p in todos) / len(todos))
        self.mapa.set_zoom(13)

        for ruta in self.rutas:                                   # líneas
            self.mapa.set_path(ruta.trazado(), color=ruta.color, width=5)

        for nombre, (lat, lon, rutas) in self.paradas.items():    # paradas
            borde = rutas[0].color if len(rutas) == 1 else "#222222"
            self.mapa.set_marker(lat, lon, icon=self._icono(14, "white", borde),
                                 data=nombre, command=self._clic_parada)

        self.marcador_sel = self.mapa.set_marker(                 # parada elegida
            0, 0, text="", icon=self._icono(22, "#facc15", "#222222"),
            text_color="#111111", font=("Helvetica", 11, "bold"))

        self.marcadores = []                                      # buses
        for bus in self.buses:
            lat, lon, _, _ = bus.ruta.estado(bus.fase(0))
            m = self.mapa.set_marker(lat, lon, text=bus.nombre,
                                     icon=self._icono(20, bus.ruta.color, "white"),
                                     text_color=bus.ruta.color,
                                     font=("Helvetica", 9, "bold"))
            self.marcadores.append((bus, m))

        self.seleccionar_parada()
        self._ciclos = 0
        self.tick()

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
        self.pausado = not self.pausado
        self.btn_pausa.config(text="Reanudar" if self.pausado else "Pausar")

    def cambiar_velocidad(self, _evento=None):
        self.factor = self.VELOCIDADES[self.cmb_velocidad.get()]

    def _clic_parada(self, marcador):
        self.cmb_parada.set(marcador.data)
        self.seleccionar_parada()

    def seleccionar_parada(self):
        nombre = self.cmb_parada.get()
        lat, lon, _ = self.paradas[nombre]
        self.marcador_sel.set_position(lat, lon)
        self.marcador_sel.set_text(nombre)
        self.actualizar_tablas()

    # ── Bucle principal ────────────────────────────────────────────────
    def hora_simulada(self):
        return self.hora_inicio + timedelta(seconds=self.t_sim)

    def tick(self):
        """Se ejecuta ~12 veces por segundo: avanza el reloj y mueve los buses."""
        ahora = time.monotonic()
        if not self.pausado:
            self.t_sim += (ahora - self._ultimo_tick) * self.factor
        self._ultimo_tick = ahora

        for bus, marcador in self.marcadores:
            lat, lon, _, _ = bus.ruta.estado(bus.fase(self.t_sim))
            marcador.set_position(lat, lon)

        self.lbl_reloj.config(text=self.hora_simulada().strftime("%H:%M:%S"))
        self._ciclos += 1
        if self._ciclos % 6 == 0:               # las tablas, 2 veces por segundo
            self.actualizar_tablas()
        self.after(80, self.tick)

    def actualizar_tablas(self):
        ahora = self.hora_simulada()

        def hora_en(segundos):
            return (ahora + timedelta(seconds=segundos)).strftime("%H:%M")

        # Tabla 1: buses que pasan por la parada elegida, del más cercano al más lejano
        parada = self.cmb_parada.get()
        llegadas = []
        for bus in self.buses:
            resultado = bus.ruta.segundos_hasta(bus.fase(self.t_sim), parada)
            if resultado:
                llegadas.append((resultado[0], bus, resultado[1]))
        llegadas.sort(key=lambda fila: fila[0])

        self.tabla_llegadas.delete(*self.tabla_llegadas.get_children())
        for falta, bus, sentido in llegadas:
            self.tabla_llegadas.insert("", "end", tags=(bus.ruta.codigo,), values=(
                bus.nombre, sentido, texto_espera(falta), hora_en(falta)))

        # Tabla 2: próxima parada de cada bus
        self.tabla_buses.delete(*self.tabla_buses.get_children())
        for bus in self.buses:
            _, _, proxima, falta = bus.ruta.estado(bus.fase(self.t_sim))
            self.tabla_buses.insert("", "end", tags=(bus.ruta.codigo,), values=(
                bus.nombre, proxima, texto_espera(falta), hora_en(falta)))


if __name__ == "__main__":
    Simulador().mainloop()
