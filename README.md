# Visualización de Rutas de Buses

Sistema para seguir en tiempo real los buses de rutas urbanas del Valle de Aburrá
(Medellín y Envigado). Las rutas se trazan sobre las vías reales y el tráfico
real de TomTom frena a los buses en las zonas congestionadas.

Tiene tres partes que comparten la misma API:

| Parte | Para quién | Tecnología |
|---|---|---|
| **Backend** | API REST, simulación y base de datos | FastAPI + SQLite |
| **Dashboard técnico** | Administrar rutas, vehículos y ver el tráfico | Tkinter + tkintermapview (también en el navegador con noVNC) |
| **App móvil** | Consultar buses y llegadas desde el celular | Web app con Leaflet servida en `/movil/` |

## Funcionalidades

- **Hora real de Colombia (UTC-5).** La posición de cada bus se calcula a partir
  de la hora actual y del horario de su ruta.
- **Rutas sobre vías reales.** Con una clave de TomTom, cada ruta se traza una vez
  como una línea de bus de verdad: no hay giros raros ni pasadas repetidas, y el
  recorrido no cambia con el tráfico. Si una parada obligaría a desviarse, su
  paradero se acomoda sobre la vía, a un máximo de 300 m.
- **Tráfico en hexágonos.** Los recorridos se cubren con hexágonos de 600 m y en
  cada uno se mide la velocidad real con TomTom Traffic Flow. Se pintan en
  colores pastel según el nivel de tráfico: fluido, moderado, alto, severo o sin
  dato. En las zonas lentas los buses van más despacio y sus llegadas se retrasan.
- **Filtro por municipio** en el dashboard y en la app móvil.
- **Gestión de la flota.** Se pueden agregar y eliminar rutas y vehículos (bus urbano,
  articulado, microbús, minibús, BRT, carro, taxi o moto), cada uno con su emoji en el mapa.
- **Contador de ingresos** a la app móvil, con el total y los ingresos de hoy.
- **Acceso por red local e internet.** Desde internet la app es de solo lectura.

### Rutas incluidas

| Código | Ruta | Municipio |
|---|---|---|
| R1 | Centro - Poblado (circular) | Medellín |
| R2 | Centro - San Javier (circular) | Medellín |
| R3 | Circular Norte | Medellín |
| R5 | Envigado - El Poblado (circular) | Envigado |

## Estructura del proyecto

```
backend/
  api.py           API REST, app móvil en /movil/ y bloqueo de escrituras desde internet
  service.py       Estado en vivo: buses, llegadas, tráfico y contador de ingresos
  simulation.py    Movimiento de los buses sobre su ruta según la hora
  traffic.py       TomTom: trazado de rutas (Routing) y velocidad real (Traffic Flow)
  hexagons.py      Hexágonos que cubren los recorridos
  congestion.py    División de cada tramo por zonas de tráfico
  database.py      SQLite: rutas, vehículos, migraciones y visitas
  seed_data.py     Rutas iniciales y tipos de vehículo
  check_tomtom.py  Comprueba que la clave de TomTom funcione
  env.py, run.py   Carga de .env y arranque del servidor
frontend/
  dashboard.py     Dashboard técnico (pestañas Flota en vivo, Tráfico, Rutas y Vehículos)
  map_widget.py    Mapa y proveedores de teselas
  api_client.py    Cliente de la API
  theme.py         Tema oscuro
  run.py           Arranque del dashboard
movil/             App web para celular (index.html, app.js, estilos.css, manifest)
docker/            Scripts de noVNC, red local (Windows) y enlaces de internet
tests/             Pruebas unitarias
start.py           Arranca backend y dashboard juntos, sin Docker
Dockerfile, docker-compose.yml
```

## Puesta en marcha

### 1. Configuración

```powershell
copy .env.example .env
```

Todas las claves son opcionales. Las principales:

| Variable | Para qué |
|---|---|
| `TOMTOM_API_KEY` | Rutas sobre vías reales y tráfico real. Sin ella se usa la geometría guardada de cada ruta y no hay hexágonos de tráfico. |
| `VNC_PASSWORD` | Contraseña del dashboard en el navegador. Es obligatoria si se abre a la red o a internet. |
| `SIMULADOR_IP_PUBLICA=0.0.0.0` | Con Docker, abre los puertos a la red local. |
| `SIMULADOR_HOST=0.0.0.0` | Lo mismo, sin Docker. |
| `TOMTOM_CUOTA_DIARIA`, `TOMTOM_HORAS_USO`, `TOMTOM_REFRESCO_S` | Regulan cada cuánto se consulta el tráfico para no pasar la cuota gratuita de 2.500 consultas al día. |
| `MAPA_PROVEEDOR`, `STADIA_MAPS_API_KEY`, `CARTO_API_KEY`, `ARCGIS_API_KEY` | Mapa base. Esri y OpenStreetMap no requieren clave. |

`.env` no se sube al repositorio ni entra en la imagen de Docker. Para comprobar
la clave de TomTom: `py -m backend.check_tomtom`.

### 2a. Con Docker (recomendado)

Requiere Docker Desktop con WSL2, o Docker Engine con `compose`.

```bash
docker compose up -d --build
```

| Qué | Dirección |
|---|---|
| Dashboard técnico | http://localhost:6080 |
| App móvil | http://localhost:8000/movil/ |
| Documentación de la API | http://localhost:8000/docs |

### 2b. Sin Docker

Requiere Python 3 con Tkinter (la imagen de Docker usa Python 3.14).

```powershell
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
py start.py
```

`start.py` levanta el backend, abre el dashboard y muestra la dirección de la
app móvil. En macOS o Linux se activa el entorno con `source .venv/bin/activate`.

## Acceso desde otros dispositivos

### Misma red Wi-Fi

Con Docker, en `.env` pon `SIMULADOR_IP_PUBLICA=0.0.0.0` y `VNC_PASSWORD`, y luego
ejecuta en PowerShell **como administrador**:

```powershell
powershell -ExecutionPolicy Bypass -File docker\abrir-en-red.ps1
```

El script redirige los puertos de WSL, abre el firewall y muestra las
direcciones, por ejemplo:

- App móvil: `http://192.168.1.4:8080/movil/`
- Dashboard: `http://192.168.1.4:6081/vnc.html` (pide `VNC_PASSWORD`)

Hay que repetirlo después de reiniciar el PC, porque la IP interna de WSL cambia.
Para deshacerlo, ejecuta el mismo comando con `-Cerrar`.

### Internet

Se usan túneles rápidos de Cloudflare: son gratuitos, tienen HTTPS y no hay que
abrir puertos en el router. La dirección `https://….trycloudflare.com` cambia
cada vez que se encienden los túneles.

```bash
docker compose --profile internet up -d --build                     # app móvil
docker compose --profile internet --profile internet-panel up -d    # + dashboard
sh docker/enlaces-internet.sh                                       # muestra las direcciones
```

Desde internet la API solo acepta lecturas. La única excepción es el registro
de ingresos de la app. El dashboard publicado sí puede editar, por eso exige
contraseña.

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio |
| GET | `/api/dashboard` | Estado completo: rutas, buses, llegadas, paradas, reloj, tráfico, hexágonos e ingresos |
| POST | `/api/routes` | Crear una ruta |
| DELETE | `/api/routes/{code}` | Eliminar una ruta |
| DELETE | `/api/routes/{code}/buses` | Quitar un bus de una ruta |
| POST | `/api/vehicles` | Registrar un vehículo |
| DELETE | `/api/vehicles/{plate}` | Eliminar un vehículo |
| POST | `/api/visitas` | Registrar un ingreso a la app móvil |
| GET | `/movil/` | App móvil (`/` redirige aquí) |

La documentación interactiva está en `/docs`.

## Pruebas

```bash
docker compose --profile test run --rm tests
# o sin Docker
py -m unittest discover tests
```

## Comandos útiles

| Para qué | Comando |
|---|---|
| Ver el estado | `docker compose ps` |
| Ver los logs | `docker compose logs -f` |
| Reconstruir tras cambiar código | `docker compose up -d --build` |
| Detener | `docker compose down` |
| Detener y borrar la base de datos | `docker compose down -v` |

Más detalles de Docker, alternativas para el dashboard y problemas comunes en
[DOCKER.md](DOCKER.md).
