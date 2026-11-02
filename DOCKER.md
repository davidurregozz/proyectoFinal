# Ejecutar con Docker

Toda la aplicación corre en contenedores: la API REST (FastAPI + SQLite) y el
dashboard Tkinter, que se ve desde el navegador mediante noVNC. No hace falta
instalar Python ni un servidor X en el equipo.

| Servicio   | Qué hace                                   | Dirección                      |
|------------|--------------------------------------------|--------------------------------|
| `backend`  | API REST y simulación; datos en un volumen | http://localhost:8000/docs     |
| `frontend` | Dashboard Tkinter en el navegador          | http://localhost:6080          |
| `dashboard`| Dashboard como ventana nativa (perfil `gui`) | requiere servidor X          |
| `tests`    | Pruebas unitarias (perfil `test`)          | —                              |

## Requisitos

- Docker Desktop con WSL2 (Windows) o Docker Engine con el plugin `compose`.

## Arrancar

Desde la carpeta del proyecto:

```powershell
docker compose up -d --build
```

Luego abre **http://localhost:6080** en el navegador. El dashboard aparece en
cuanto el backend pasa su health check (unos segundos la primera vez).

Si cierras la ventana del dashboard, el contenedor se reinicia solo; recarga la
página para volver a verlo.

## Claves opcionales

```powershell
copy .env.example .env
```

Completa en `.env` las claves que tengas (`TOMTOM_API_KEY`,
`STADIA_MAPS_API_KEY`, `CARTO_API_KEY`, `ARCGIS_API_KEY`) y vuelve a ejecutar
`docker compose up -d`. Sin claves, el mapa usa Esri World Topo y la
optimización con tráfico queda desactivada.

Con `TOMTOM_API_KEY`, cada 10 minutos el backend cubre los recorridos con
hexágonos de 600 m y mide en cada uno la velocidad real de la vía (TomTom
Traffic Flow). Los hexágonos que van por debajo del 80 % de su velocidad libre
se dibujan en el mapa y los buses frenan dentro de ellos. Se ajusta con
`TOMTOM_REFRESCO_S`, `TRAFICO_HEX_RADIO_M` y `TRAFICO_HEX_MAX`; cada
actualización consume unas 2 consultas por ruta más 1 por hexágono (la cuota
gratuita es de 2.500 al día). El reloj del dashboard es la hora real de Colombia.

## Comandos habituales

| Para qué                              | Comando                                          |
|---------------------------------------|--------------------------------------------------|
| Ver el estado de los servicios        | `docker compose ps`                              |
| Ver los logs                          | `docker compose logs -f`                         |
| Comprobar la API                      | `curl http://localhost:8000/api/health`          |
| Ejecutar las pruebas                  | `docker compose --profile test run --rm tests`   |
| Reconstruir tras cambiar código       | `docker compose up -d --build`                   |
| Detener                               | `docker compose down`                            |
| Detener y borrar la base de datos     | `docker compose down -v`                         |

## Alternativas para el dashboard

**Ventana nativa con servidor X.** Instala VcXsrv (Windows) o XQuartz (macOS),
inícialo con el control de acceso desactivado y ejecuta:

```powershell
docker compose up -d backend
docker compose --profile gui up --build dashboard
```

**Dashboard sin Docker.** Con el backend en el contenedor:

```powershell
docker compose up -d backend
py -m pip install -r requirements.txt
py -m frontend.run
```

## Problemas comunes

- **La página de noVNC dice "Failed to connect"**: el dashboard todavía está
  arrancando o se reinició; espera unos segundos y recarga.
- **"Backend no disponible" en el dashboard**: revisa `docker compose logs backend`.
- **El puerto 8000 o 6080 ya está en uso**: detén el otro proceso (por ejemplo
  `py start.py`) o cambia el puerto de la izquierda en `docker-compose.yml`.
- **`exec ... no such file or directory` en `frontend`**: el script quedó con
  finales de línea CRLF; el Dockerfile los corrige al construir, así que
  reconstruye con `--build`.
