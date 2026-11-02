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

Con `TOMTOM_API_KEY`, cada ruta se traza una sola vez sobre las vías reales,
como una línea de bus de verdad: no cambia de recorrido con el tráfico. Si una
parada obliga a dar un rodeo (por ejemplo, queda en la calzada contraria de una
autopista), su paradero en ese sentido se ubica sobre la vía por donde pasa el
bus, a máximo 300 m.

Además, el backend cubre los recorridos con hexágonos de 600 m
y mide en **todos** la velocidad real de la vía (TomTom Traffic Flow). Los que
van por debajo del 80 % de su velocidad libre frenan a los buses. Si un
hexágono no responde se reintenta, se usa su medición anterior o se dibuja en
gris como "Sin dato", así ninguna ruta queda con huecos.

Cada actualización consume 1 consulta por hexágono (unas 50); las rutas solo
se consultan la primera vez. La espera entre actualizaciones crece sola para que
`TOMTOM_HORAS_USO` horas de uso (10 por defecto) quepan en la cuota gratuita
de 2.500 consultas al día: hoy son unos 14 minutos. Se ajusta con
`TOMTOM_REFRESCO_S` (espera mínima), `TOMTOM_CUOTA_DIARIA`, `TOMTOM_HORAS_USO`
y `TRAFICO_HEX_RADIO_M`. El reloj del dashboard es la hora real de Colombia.

## App para celular

El backend sirve una app web para celular en `/movil/`: mapa con los buses en
vivo, hexágonos de tráfico, próximas llegadas, flota y filtro por municipio.
En el computador se abre en http://localhost:8000/movil/.

Para usarla desde el celular, conectado a la misma red Wi-Fi que el PC:

**Sin Docker (lo más simple).** En `.env` pon `SIMULADOR_HOST=0.0.0.0` y ejecuta
`py start.py`. La consola muestra la dirección, por ejemplo
`http://192.168.1.20:8000/movil/`. Windows pedirá permitir Python en el
firewall: acepta solo para redes privadas.

**Con Docker (corre dentro de WSL).** En `.env` pon `SIMULADOR_IP_PUBLICA=0.0.0.0`
y una contraseña en `VNC_PASSWORD` (el dashboard del puerto 6080 permite crear y
borrar rutas; VNC usa solo 8 caracteres) y ejecuta `docker compose up -d`. WSL tiene su propia red, así que además hay
que redirigir el puerto desde Windows, permitirlo en el firewall y tener la
Wi-Fi marcada como red Privada (en una red Pública Windows bloquea todo lo
entrante). El script lo hace; ejecútalo en PowerShell **como administrador**
desde la carpeta del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File docker\abrir-en-red.ps1
```

Al final muestra las direcciones para los otros dispositivos, por ejemplo
`http://192.168.1.4:8080/movil/` (app móvil) y `http://192.168.1.4:6081`
(dashboard de escritorio, pide la contraseña de `VNC_PASSWORD`). Repítelo después de reiniciar el PC, porque
la IP interna de WSL cambia. Para deshacerlo: el mismo comando con `-Cerrar`.

En el navegador del celular, "Agregar a la pantalla de inicio" la deja como un
ícono más. La app solo consulta datos; aun así, con la red abierta cualquiera
en ese Wi-Fi puede usar la API (también crear o borrar rutas), así que úsala en
redes de confianza.

## Acceso desde internet

Para ver la aplicación desde cualquier computador o celular, sin abrir puertos
del router, se usan túneles rápidos de Cloudflare: gratis, con HTTPS y sin
cuenta ni dominio. La dirección (`https://...trycloudflare.com`) **cambia cada
vez que se encienden**.

```bash
docker compose --profile internet up -d --build      # app para celular
sh docker/enlaces-internet.sh                        # muestra la dirección
```

Desde internet la app es **de solo lectura**: se ven el mapa, las llegadas y el
tráfico, pero no se pueden crear ni borrar rutas o vehículos.

El panel de administración se publica aparte y solo cuando haga falta. Antes,
pon una contraseña en `VNC_PASSWORD` dentro de `.env`:

```bash
docker compose --profile internet --profile internet-panel up -d
sh docker/enlaces-internet.sh
```

Para dejar de publicar (el resto sigue funcionando en el equipo):

```bash
docker compose --profile internet --profile internet-panel stop tunel-app tunel-panel
```

Para una dirección fija (por ejemplo `buses.midominio.com`) hace falta un
dominio propio y un túnel con nombre de Cloudflare.

## Comandos habituales

| Para qué                              | Comando                                          |
|---------------------------------------|--------------------------------------------------|
| Ver el estado de los servicios        | `docker compose ps`                              |
| Ver los logs                          | `docker compose logs -f`                         |
| Comprobar la API                      | `curl http://localhost:8000/api/health`          |
| Abrir la app para celular             | http://localhost:8000/movil/                     |
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
