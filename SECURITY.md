# Seguridad

Este documento describe qué se protege en el simulador de rutas de buses, frente
a qué amenazas y con qué controles. También explica cómo revisar la
configuración y cómo reportar una vulnerabilidad.

## Qué se protege

| Activo | Riesgo si se compromete |
|---|---|
| Rutas y vehículos (SQLite) | Alguien borra o falsea la flota que ven los usuarios. |
| App móvil (`/movil/`) | Un script malicioso se ejecuta en el celular de los usuarios (XSS). |
| Panel de administración (noVNC, puerto 6080) | Control total del dashboard. |
| Claves de TomTom y de los mapas | Uso de la cuota gratuita o cobros a nombre del dueño. |
| Código fuente | Alguien distribuye una versión alterada. |

## Modelo de amenazas

| Atacante | Puede llegar a | Control principal |
|---|---|---|
| Cualquiera en internet | La app a través del túnel de Cloudflare | Solo lectura, sin `/docs`, límites por IP |
| Alguien en la misma Wi-Fi | El puerto 8000 y el 6080 si se abren con `0.0.0.0` | Token de la API y `VNC_PASSWORD` |
| Una página web maliciosa abierta en el PC | Peticiones desde el navegador al backend | Token en cabecera (no hay cookies que robar) y CSP |
| Quien recibe una copia del código | El repositorio | Firma digital Ed25519 |

## Controles

### API (`backend/seguridad.py`)

- **Autenticación para cambios.** `POST` y `DELETE` sobre rutas y vehículos
  exigen `Authorization: Bearer <token>` (o `X-API-Token`). El token se compara
  en tiempo constante. Si `SIMULADOR_API_TOKEN` está vacío, el backend genera
  uno aleatorio de 256 bits en `data/api_token` (permisos 600) y el dashboard lo
  lee de ahí. El contador de visitas es la única escritura pública.
- **Solo lectura desde internet.** Toda petición que llega con `CF-Connecting-IP`
  (túnel de Cloudflare) no puede modificar datos, ni siquiera con el token.
- **Límites por IP**, configurables en `.env`:

  | Qué | Por defecto |
  |---|---|
  | Peticiones a `/api/` | 600 por minuto |
  | Escrituras | 60 por minuto |
  | Visitas registradas | 20 por minuto |
  | Token incorrecto | 10 fallos bloquean la IP 5 minutos |

- **Tamaño de las peticiones.** Máximo 1 MB, y no se aceptan cuerpos *chunked*
  sin longitud. Pydantic limita además cada campo: códigos `[A-Za-z0-9_-]`,
  nombres de hasta 100 caracteres, 200 paradas y 20.000 puntos por trazado.
- **Cabeceras de seguridad** en todas las respuestas: `Content-Security-Policy`
  (sin scripts en línea, solo Leaflet de unpkg y las teselas de Esri y OSM),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `Permissions-Policy`, y `Strict-Transport-Security`
  cuando la conexión es HTTPS. Las respuestas de la API llevan `Cache-Control: no-store`.
- **Menos información expuesta.** `/docs`, `/redoc` y `/openapi.json` devuelven
  404 desde internet, y el servidor no envía la cabecera `server: uvicorn`.
- **Registro de eventos.** Cada rechazo (401, 403, 404 de documentación, 411,
  413 y 429) queda en el log `simulador.seguridad` con el método, la ruta y la IP.
  El token nunca se escribe en el log.

### Datos

- Todas las consultas SQL usan parámetros (`?`): no hay inyección SQL.
- La app móvil pinta los textos con `textContent`, y lo que va como HTML a
  Leaflet (tooltips e iconos) pasa por `escapar()`.
- Leaflet se carga con *Subresource Integrity* (`integrity="sha256-…"`).

### Contenedores (`docker-compose.yml`, `Dockerfile`)

- Todos los procesos corren con el usuario `app` (uid 1000), no como root.
- `no-new-privileges` y `cap_drop: ALL` en todos los servicios.
- El backend tiene el sistema de archivos de solo lectura: solo escribe en el
  volumen de datos y en `/tmp`.
- Por defecto los puertos solo escuchan en `127.0.0.1`.
- El dashboard monta el volumen de datos en solo lectura, únicamente para leer el token.
- `.env`, `data/` y `firma/clave_privada.pem` no entran en la imagen.

### Secretos

- `.env`, `data/api_token` y `firma/clave_privada.pem` están en `.gitignore`.
- Las claves de TomTom no aparecen en los mensajes de error ni en los logs.

### Integridad del código (`firma/`)

El código se firma con Ed25519: `py -m firma.firma_digital firmar` y
`py -m firma.firma_digital verificar`. Más detalles en el README.

## Auditoría

```powershell
py -m pip install -r requirements-dev.txt
py -m backend.auditoria_seguridad
```

Comprueba que los secretos no estén en git, busca claves escritas en los
archivos, revisa `VNC_PASSWORD` y el token cuando la app se abre a la red,
verifica la firma del código y busca vulnerabilidades conocidas en las
dependencias con `pip-audit`. Termina con código 1 si hay algún problema grave.

## Antes de abrir la app a la red o a internet

1. `VNC_PASSWORD` con 8 caracteres. VNC ignora los que pasen de 8.
2. Opcional: un `SIMULADOR_API_TOKEN` propio de 32 caracteres o más.
3. Firmar el código y pasar la auditoría sin problemas graves.
4. Publicar el panel (`--profile internet-panel`) solo mientras haga falta.

## Limitaciones conocidas

- Fuera de Cloudflare no hay HTTPS. En la red local el token viaja en texto
  plano, así que solo se debe usar en redes de confianza.
- Con Docker Desktop, todos los celulares de la Wi-Fi pueden aparecer con la
  misma IP. En ese caso los límites por IP se comparten entre ellos.
- Un cliente de la red local podría enviar `CF-Connecting-IP` falsa para
  cambiar la IP con la que se cuentan sus límites. Con eso no gana permisos de
  escritura: al contrario, queda tratado como petición de internet.
- La contraseña de VNC usa el esquema de VNC, que es débil. Por internet el
  túnel de Cloudflare añade el cifrado HTTPS.
- Los límites se guardan en memoria y se reinician cuando se reinicia el backend.

## Reportar una vulnerabilidad

No abras un *issue* público. Escribe a los mantenedores del proyecto con los
pasos para reproducir el problema y su impacto. Se responderá en un plazo
máximo de 7 días.
