"""FastAPI REST interface for the bus simulator."""

from contextlib import asynccontextmanager
import math
from pathlib import Path
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from backend.seguridad import SeguridadMiddleware, cargar_o_crear_token, is_internet_write
from backend.service import TransitService

NombreParada = Annotated[str, StringConstraints(min_length=1, max_length=100)]
MAX_PARADAS = 200
MAX_PUNTOS_TRAZADO = 20_000


class RouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z0-9_-]+$")
    nombre: str = Field(min_length=3, max_length=100)
    municipio: str = Field(min_length=1, max_length=60)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    velocidad_kmh: float = Field(gt=0, le=120)
    buses: int = Field(gt=0, le=100)
    circular: bool
    paradas: list[tuple[NombreParada, float, float]] = Field(min_length=2, max_length=MAX_PARADAS)
    coordenadas: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_PUNTOS_TRAZADO)
    coordenadas_regreso: list[tuple[float, float]] = Field(
        default_factory=list, max_length=MAX_PUNTOS_TRAZADO
    )

    @field_validator("codigo", "nombre", "municipio")
    @classmethod
    def trim_route_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Los campos de texto de la ruta son obligatorios.")
        return value

    @field_validator("paradas")
    @classmethod
    def validate_stops(cls, stops):
        names = set()
        for name, latitude, longitude in stops:
            normalized_name = name.strip().casefold()
            if not normalized_name or normalized_name in names:
                raise ValueError("Las paradas deben tener nombres únicos.")
            if not (
                math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180
            ):
                raise ValueError("Las coordenadas de las paradas no son válidas.")
            names.add(normalized_name)
        return stops

    @field_validator("coordenadas", "coordenadas_regreso")
    @classmethod
    def validate_coordinates(cls, coordinates):
        for latitude, longitude in coordinates:
            if not (
                math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180
            ):
                raise ValueError("Las coordenadas del trazado no son válidas.")
        return coordinates


class VehicleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placa: str = Field(min_length=2, max_length=20)
    tipo: str = Field(min_length=1, max_length=60)
    modelo: str = Field(min_length=1, max_length=60)
    capacidad: int = Field(gt=0, le=500)
    ruta: str = Field(min_length=1, max_length=100)
    conductor: str = Field(min_length=1, max_length=100)
    estado: str = Field(min_length=1, max_length=40)

    @field_validator("placa")
    @classmethod
    def normalize_plate(cls, value):
        value = value.strip().upper()
        if not value:
            raise ValueError("La placa es obligatoria.")
        return value

    @field_validator("tipo", "modelo", "ruta", "conductor", "estado")
    @classmethod
    def trim_vehicle_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Los campos de texto del vehículo son obligatorios.")
        return value


@asynccontextmanager
async def lifespan(app):
    cargar_o_crear_token()  # el dashboard lo lee del mismo archivo
    service = TransitService()
    service.start_traffic_refresh()
    app.state.transit_service = service
    try:
        yield
    finally:
        service.stop_traffic_refresh()


app = FastAPI(title="Visualización de rutas de buses", version="1.0.0", lifespan=lifespan)

# Autenticación, límites, cabeceras y solo lectura desde internet: backend/seguridad.py
app.add_middleware(SeguridadMiddleware)
__all__ = ["app", "is_internet_write", "MOBILE_DIR"]


def get_service(request: Request) -> TransitService:
    return request.app.state.transit_service


ServiceDependency = Annotated[TransitService, Depends(get_service)]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/visitas")
def register_visit(service: ServiceDependency):
    """Ingreso a la app móvil; la app lo envía una vez por sesión."""
    return service.register_visit()


@app.get("/api/dashboard")
def dashboard(service: ServiceDependency, parada: Annotated[str, Query(max_length=100)] = ""):
    return service.snapshot(parada)


@app.post("/api/routes", status_code=status.HTTP_201_CREATED)
def create_route(route: RouteInput, service: ServiceDependency):
    try:
        service.create_route(route.model_dump())
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="El código o nombre de ruta ya existe."
        ) from error
    return {"message": "Ruta creada.", "codigo": route.codigo}


@app.delete("/api/routes/{code}")
def delete_route(code: Annotated[str, PathParam(max_length=12)], service: ServiceDependency):
    try:
        service.delete_route(code)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"message": "Ruta y vehículos asociados eliminados."}


@app.delete("/api/routes/{code}/buses")
def remove_route_bus(code: Annotated[str, PathParam(max_length=12)], service: ServiceDependency):
    try:
        service.remove_route_bus(code)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"message": "Bus retirado de la ruta."}


@app.post("/api/vehicles", status_code=status.HTTP_201_CREATED)
def create_vehicle(vehicle: VehicleInput, service: ServiceDependency):
    try:
        service.create_vehicle(vehicle.model_dump())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="La placa ya está registrada.") from error
    return {"message": "Vehículo registrado.", "placa": vehicle.placa}


@app.delete("/api/vehicles/{plate}")
def delete_vehicle(plate: Annotated[str, PathParam(max_length=20)], service: ServiceDependency):
    try:
        service.delete_vehicle(plate)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"message": "Vehículo eliminado."}


# Mobile web app: same API, opened from the phone's browser at /movil/.
MOBILE_DIR = Path(__file__).resolve().parents[1] / "movil"


@app.get("/", include_in_schema=False)
def mobile_home():
    return RedirectResponse("/movil/")


app.mount("/movil", StaticFiles(directory=MOBILE_DIR, html=True), name="movil")
