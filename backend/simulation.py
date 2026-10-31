"""C?lculo de geometr?as, horarios y posiciones de los buses."""

import math
from bisect import bisect_right

from backend.seed_data import ESPERA_EN_PARADA_S


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
        self.codigo = datos.get("codigo", self.nombre.split()[0])
        self.municipio = datos.get("municipio", "")
        self.color = datos["color"]
        self.circular = datos["circular"]
        self.paradas = datos["paradas"]
        self.n_buses = datos["buses"]
        self.velocidad_kmh = datos["velocidad_kmh"]
        velocidad_ms = self.velocidad_kmh / 3.6
        self.duraciones_tramos_ida_s = list(
            datos.get("duraciones_tramos_ida_s", [])
        )
        self.duraciones_tramos_regreso_s = list(
            datos.get("duraciones_tramos_regreso_s", [])
        )

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

        self.coordenadas_regreso = list(datos.get("coordenadas_regreso", []))
        self._tramos_regreso = []
        if self.coordenadas_regreso:
            if self.circular:
                raise ValueError(
                    f"La ruta circular {self.nombre} no puede tener un trazado "
                    "de regreso separado."
                )
            paradas_regreso = list(reversed(coordenadas_paradas))
            if self.coordenadas_regreso[0] != paradas_regreso[0]:
                raise ValueError(
                    f"El trazado de regreso de {self.nombre} debe iniciar en "
                    "la última parada."
                )
            indices_regreso = []
            desde = 0
            for coordenada in paradas_regreso:
                try:
                    indice = self.coordenadas_regreso.index(coordenada, desde)
                except ValueError as error:
                    raise ValueError(
                        f"El trazado de regreso de {self.nombre} debe incluir "
                        "las paradas en orden inverso."
                    ) from error
                indices_regreso.append(indice)
                desde = indice + 1
            if self.coordenadas_regreso[-1] != coordenadas_paradas[0]:
                raise ValueError(
                    f"El trazado de regreso de {self.nombre} debe terminar "
                    "en la primera parada."
                )
            self._tramos_regreso = [
                self.coordenadas_regreso[inicio:fin + 1]
                for inicio, fin in zip(indices_regreso, indices_regreso[1:])
            ]

        expected_forward = len(self.paradas) if self.circular else len(self.paradas) - 1
        expected_return = 0 if self.circular else len(self.paradas) - 1
        for durations, expected, direction in (
            (self.duraciones_tramos_ida_s, expected_forward, "ida"),
            (self.duraciones_tramos_regreso_s, expected_return, "regreso"),
        ):
            if durations and (
                len(durations) != expected
                or any(not math.isfinite(value) or value <= 0 for value in durations)
            ):
                raise ValueError(
                    f"Las duraciones de {direction} de {self.nombre} son inválidas."
                )

        # Orden en que se visitan las paradas durante un ciclo completo
        n = len(self.paradas)
        if self.circular:
            orden = list(range(n)) + [0]                           # 0,1,2,...,0
        else:
            orden = list(range(n)) + list(range(n - 2, -1, -1))    # ida y vuelta

        # horario = lista de (t_llegada, t_salida, indice_parada, sentido)
        self.horario = []
        self._tramos_horario = []
        self._duraciones_tramos_horario = []
        t = 0.0
        for k, idx in enumerate(orden):
            if k > 0:
                tramo = self._tramo_entre(orden[k - 1], idx)
                distancia = sum(
                    distancia_coordenadas_m(a, b)
                    for a, b in zip(tramo, tramo[1:])
                )
                duracion = self._duracion_tramo(orden[k - 1], idx, distancia / velocidad_ms)
                t += duracion
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
            self._duraciones_tramos_horario.append(
                self._duracion_tramo(
                    idx,
                    orden[k + 1],
                    self._distancia_tramo(self._tramo_entre(idx, orden[k + 1]))
                    / velocidad_ms,
                )
            )
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
            if self._tramos_regreso:
                return self._tramos_regreso[len(self.paradas) - 1 - origen]
            return list(reversed(self._tramos_ida[destino]))
        raise ValueError(
            f"Las paradas {origen} y {destino} no son consecutivas en "
            f"el trazado de {self.nombre}."
        )

    def _duracion_tramo(self, origen, destino, duracion_predeterminada):
        if destino == origen + 1:
            duraciones = self.duraciones_tramos_ida_s
            indice = origen
        elif self.circular and origen == len(self.paradas) - 1 and destino == 0:
            duraciones = self.duraciones_tramos_ida_s
            indice = origen
        elif destino == origen - 1:
            duraciones = self.duraciones_tramos_regreso_s
            indice = len(self.paradas) - 1 - origen
        else:
            return duracion_predeterminada
        if indice < len(duraciones):
            return duraciones[indice]
        return duracion_predeterminada

    @staticmethod
    def _distancia_tramo(tramo):
        return sum(
            distancia_coordenadas_m(start, end)
            for start, end in zip(tramo, tramo[1:])
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
        if self.coordenadas_regreso:
            return self.coordenadas + self.coordenadas_regreso[1:]
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
        duracion_tramo = self._duraciones_tramos_horario[i]
        distancia_tramo = self._distancia_tramo(self._tramos_horario[i])
        fraccion_recorrida = min(
            1.0, max(0.0, (fase - t_salida) / duracion_tramo)
        )
        distancia = distancia_tramo * fraccion_recorrida
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
