# Simulador de rutas de buses

El proyecto está dividido en una API REST con almacenamiento SQLite y un
dashboard de escritorio Tkinter. El dashboard obtiene las rutas, vehículos y
posiciones de buses exclusivamente a través de la API local.

## Instalar y ejecutar en Windows

Desde PowerShell, en la carpeta del proyecto:

```powershell
py -m pip install -r requirements.txt
py .\simulador_buses.py
```

El comando anterior inicia el backend REST y el dashboard. También se pueden
ejecutar por separado en dos terminales:

```powershell
py -m backend.run
py -m frontend.run
```

La API escucha solo en `127.0.0.1:8000`. Su documentación interactiva está en
`http://127.0.0.1:8000/docs`. La base de datos se crea automáticamente en
`data\simulador.sqlite3`; las rutas y vehículos de muestra se cargan solo
cuando la base de datos todavía no contiene rutas.

## Estructura

- `backend\seed_data.py`: datos iniciales y opciones de formularios.
- `backend\simulation.py`: geometrías, horarios y posiciones de los buses.
- `backend\database.py`: esquema y acceso a SQLite.
- `backend\service.py`: casos de uso y estado de la simulación del servidor.
- `backend\api.py`: endpoints FastAPI.
- `frontend\api_client.py`: cliente HTTP del dashboard.
- `frontend\dashboard.py`: interfaz gráfica.
- `frontend\map_widget.py`: proveedores de mapas y conmutación de respaldo.
- `tests\test_backend.py`: pruebas de persistencia y simulación.

Para cambiar la ubicación de la base de datos, define `SIMULADOR_DB_PATH` antes
de iniciar el backend. Las claves opcionales de Stadia Maps y CARTO se siguen
configurando con `STADIA_MAPS_API_KEY` y `CARTO_API_KEY`.

## Tráfico en tiempo real

La optimización opcional usa TomTom Routing API con `traffic=true`, hora de
salida actual y modo de viaje de bus. TomTom documenta cobertura de cálculo
de rutas y tráfico en Colombia; el acceso y sus cuotas dependen de la cuenta
del proveedor. Consulta sus términos antes de usarlo.

Obtén una clave desde tu cuenta de desarrollador de TomTom. No la compartas
por el chat ni la guardes en el código. En PowerShell, ingrésala de forma
oculta y ejecuta el simulador desde esa misma ventana:

```powershell
$secureKey = Read-Host "Pega tu clave de TomTom" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:TOMTOM_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    Remove-Variable secureKey, keyPointer
}
py .\simulador_buses.py
```

La clave queda solo en el entorno de esa ventana de PowerShell y se hereda
por el backend que inicia el simulador; al cerrar la ventana tendrás que
ingresarla nuevamente. Si ya hay una instancia abierta, ciérrala antes de
iniciar otra. La clave no se guarda en el repositorio ni en SQLite. El backend actualiza
los trazados y duraciones cada cinco minutos y conserva las geometrías
guardadas cuando falta la clave, el proveedor falla o una ruta no se puede
calcular. El dashboard muestra el estado de la conexión; sin clave configurada
no se debe interpretar el trazado guardado como una ruta optimizada en vivo.
