from ruta import Ruta


class Bus:
    def __init__(self, ruta: Ruta, numero: int, desfase_s: float):
        self.ruta = ruta
        self.numero = numero
        self.nombre = f"{ruta.codigo}-{numero}"
        self.desfase_s = desfase_s

    def calcular_fase(self, t_sim: float) -> float:
        return (t_sim + self.desfase_s) % self.ruta.ciclo_s

    def obtener_ubicacion(self, t_sim: float):
        fase = self.calcular_fase(t_sim)
        return self.ruta.obtener_estado_bus(fase)

    def consultar_tiempo_parada(self, t_sim: float, nombre_parada: str):
        fase = self.calcular_fase(t_sim)
        return self.ruta.calcular_segundos_hasta_parada(fase, nombre_parada)