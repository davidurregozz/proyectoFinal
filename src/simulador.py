from datetime import datetime, timedelta
from ruta import Ruta
from bus import Bus
from config import RUTAS


class SimuladorCore:
    def __init__(self):
        self.rutas = [Ruta(d) for d in RUTAS]
        self.buses = []
        self._inicializar_buses()
        
        self.t_sim = 0.0
        self.hora_inicio = datetime.now()
        self.factor = 10
        self.pausado = False

    def _inicializar_buses(self):
        for ruta in self.rutas:
            for k in range(ruta.n_buses):
                desfase = k * ruta.ciclo_s / ruta.n_buses
                self.buses.append(Bus(ruta, k + 1, desfase))

    def avanzar_tiempo(self, delta_segundos: float):
        if not self.pausado:
            self.t_sim += delta_segundos * self.factor

    def obtener_hora_simulada(self) -> datetime:
        return self.hora_inicio + timedelta(seconds=self.t_sim)

    def obtener_paradas_unicas(self) -> dict:
        paradas = {}
        for ruta in self.rutas:
            for nombre, lat, lon in ruta.paradas:
                paradas.setdefault(nombre, (lat, lon, []))[2].append(ruta)
        return paradas