"""FastAPI REST interface for the bus simulator."""

from contextlib import asynccontextmanager
import math
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.service import TransitService


class RouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=2, max_length=12) 

    
    nombre: str = Field(min_length=3, max_length=100)
    municipio: str = Field(min_length=1, max_length=60)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    velocidad_kmh: float = Field(gt=0, le=120)
    buses: int = Field(gt=0, le=100)
    circular: bool
    paradas: list[tuple[str, float, float]] = Field(min_length=2)
    coordenadas: list[tuple[float, float]] = Field(min_length=2)
    coordenadas_regreso: list[tuple[float, float]] = Field(default_factory=list)

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


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool
    factor: float


@asynccontextmanager
async def lifespan(app):
    service = TransitService()
    service.start_traffic_refresh()
    app.state.transit_service = service
    try:
        yield
    finally:
        service.stop_traffic_refresh()


app = FastAPI(title="Simulador de rutas de buses", version="1.0.0", lifespan=lifespan)


def get_service(request: Request) -> TransitService:
    return request.app.state.transit_service


ServiceDependency = Annotated[TransitService, Depends(get_service)]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(service: ServiceDependency, parada: str = ""):
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
def delete_route(code: str, service: ServiceDependency):
    try:
        service.delete_route(code)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"message": "Ruta y vehículos asociados eliminados."}


@app.post("/api/vehicles", status_code=status.HTTP_201_CREATED)
def create_vehicle(vehicle: VehicleInput, service: ServiceDependency):
    try:
        service.create_vehicle(vehicle.model_dump())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="La placa ya está registrada.") from error
    return {"message": "Vehículo registrado.", "placa": vehicle.placa}


@app.put("/api/simulation/control")
def update_control(control: ControlInput, service: ServiceDependency):
    if control.factor not in {1, 5, 10, 30, 60}:
        raise HTTPException(status_code=422, detail="Velocidad de simulación inválida.")
    service.set_control(control.paused, control.factor)
    return {"paused": control.paused, "factor": control.factor}
