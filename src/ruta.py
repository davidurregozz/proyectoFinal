import math
from bisect import bisect_right
from config import ESPERA_EN_PARADA_S


def distancia_coordenadas_m(p1, p2):
    lat1, lon1 = p1
    lat2, lon2 = p2
    r = 6_371_000
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df, dl = f2 - f1, math.radians(lon2 - lon1)
    a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Ruta:
    def __init__(self, datos: dict):
        self.nombre = datos["nombre"]
        self.codigo = self.nombre.split()[0]
        self.color = datos["color"]
        self.circular = datos["circular"]
        self.paradas = datos["paradas"]
        self.n_buses = datos["buses"]
        self.velocidad_kmh = datos["velocidad_kmh"]
        self.velocidad_ms = self.velocidad_kmh / 3.6

        self._inicializar_trazado(datos)
        self._calcular_horario()

    def _inicializar_trazado(self, datos):
        coordenadas_paradas = [(lat, lon) for _, lat, lon in self.paradas]
        coordenadas = datos.get("coordenadas", coordenadas_paradas)
        if self.circular and "coordenadas" not in datos:
            coordenadas = [*coordenadas, coordenadas_paradas[0]]
        self.coordenadas = list(coordenadas)
        
        if not self.coordenadas:
            raise ValueError(f"El trazado de {self.nombre} no tiene coordenadas.")

        indices_paradas = []
        desde = 0
        for coordenada in coordenadas_paradas:
            try:
                indice = self.coordenadas.index(coordenada, desde)
            except ValueError as error:
                raise ValueError(f"El trazado de {self.nombre} debe incluir las paradas en orden.") from error
            indices_paradas.append(indice)
            desde = indice + 1

        self._tramos_ida = [
            self.coordenadas[inicio:fin + 1]
            for inicio, fin in zip(indices_paradas, indices_paradas[1:])
        ]
        if self.circular:
            self._tramos_ida.append(self.coordenadas[indices_paradas[-1]:])

    def _calcular_horario(self):
        n = len(self.paradas)
        if self.circular:
            orden = list(range(n)) + [0]
        else:
            orden = list(range(n)) + list(range(n - 2, -1, -1))

        self.horario = []
        self._tramos_horario = []
        t = 0.0
        for k, idx in enumerate(orden):
            if k > 0:
                tramo = self._tramo_entre(orden[k - 1], idx)
                distancia = sum(distancia_coordenadas_m(a, b) for a, b in zip(tramo, tramo[1:]))
                t += distancia / self.velocidad_ms
            if k == len(orden) - 1:
                break
            
            if self.circular:
                sentido = "Circular"
            elif k < n - 1:
                sentido = self.paradas[-1][0]
            else:
                sentido = self.paradas[0][0]

            self.horario.append((t, t + ESPERA_EN_PARADA_S, idx, sentido))
            self._tramos_horario.append(self._tramo_entre(idx, orden[k + 1]))
            t += ESPERA_EN_PARADA_S

        self.ciclo_s = t
        self._llegadas = [h[0] for h in self.horario]

    def _tramo_entre(self, origen, destino):
        if destino == origen + 1:
            return self._tramos_ida[origen]
        if self.circular and origen == len(self.paradas) - 1 and destino == 0:
            return self._tramos_ida[-1]
        if destino == origen - 1:
            return list(reversed(self._tramos_ida[destino]))
        raise ValueError(f"Las paradas {origen} y {destino} no son consecutivas.")

    @staticmethod
    def _posicion_en_tramo(tramo, distancia):
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

    def obtener_estado_bus(self, fase):
        i = bisect_right(self._llegadas, fase) - 1
        _, t_salida, idx, _ = self.horario[i]
        nombre, lat, lon = self.paradas[idx]
        if fase <= t_salida:
            return lat, lon, nombre, 0.0

        j = (i + 1) % len(self.horario)
        t_siguiente = self.horario[j][0] if j else self.ciclo_s
        nombre2 = self.paradas[self.horario[j][2]][0]
        distancia = (fase - t_salida) * self.velocidad_ms
        posicion = self._posicion_en_tramo(self._tramos_horario[i], distancia)
        return (*posicion, nombre2, t_siguiente - fase)

    def calcular_segundos_hasta_parada(self, fase, nombre_parada):
        mejor = None
        for t_llegada, t_salida, idx, sentido in self.horario:
            if self.paradas[idx][0] != nombre_parada:
                continue
            if t_llegada <= fase <= t_salida:
                falta = 0.0
            else:
                falta = (t_llegada - fase) % self.ciclo_s
            if mejor is None or falta < mejor[0]:
                mejor = (falta, sentido)
        return mejor