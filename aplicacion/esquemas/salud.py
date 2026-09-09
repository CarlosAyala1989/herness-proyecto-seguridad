"""Esquemas de respuesta para el estado del backend."""

from typing import Literal

from pydantic import BaseModel, Field


class EstadoBaseDatos(BaseModel):
    """Estado normalizado de la dependencia MariaDB."""

    estado: Literal["disponible"]
    tiempo_respuesta_ms: float = Field(ge=0)


class RespuestaSalud(BaseModel):
    """Estado general del backend de Hermes."""

    aplicacion: str
    version: str
    estado: Literal["saludable"]
    base_datos: EstadoBaseDatos
