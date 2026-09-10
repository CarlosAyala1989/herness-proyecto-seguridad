"""Contratos públicos para plantillas y despliegues controlados."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aplicacion.modelos.enumeraciones import (
    EstadoDespliegue,
    SistemaOperativo,
    TipoPlantillaDespliegue,
)

PATRON_NOMBRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$")
PATRON_SERVICIO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
PATRON_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")


def _limpiar_texto(valor: str | None) -> str | None:
    if valor is None:
        return None
    limpio = " ".join(valor.split())
    if not limpio or not limpio.isprintable():
        raise ValueError("El texto no es válido.")
    return limpio


class CrearPlantillaDespliegue(BaseModel):
    """Procedimiento cerrado de archivo único para una plataforma."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=2, max_length=100)
    descripcion: str | None = Field(default=None, max_length=500)
    sistema_operativo: SistemaOperativo
    tipo: TipoPlantillaDespliegue = TipoPlantillaDespliegue.ARCHIVO_UNICO
    ruta_destino: str = Field(min_length=2, max_length=900)
    nombre_servicio: str | None = Field(default=None, max_length=128)
    activo: bool = True

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        if not PATRON_NOMBRE.fullmatch(valor):
            raise ValueError("El nombre de plantilla no tiene un formato válido.")
        return valor

    @field_validator("descripcion")
    @classmethod
    def limpiar_descripcion(cls, valor: str | None) -> str | None:
        return _limpiar_texto(valor)

    @field_validator("nombre_servicio")
    @classmethod
    def validar_servicio(cls, valor: str | None) -> str | None:
        if valor is not None and not PATRON_SERVICIO.fullmatch(valor):
            raise ValueError("El nombre del servicio no tiene un formato válido.")
        return valor


class PlantillaDespliegueRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_plantilla_despliegue: int
    nombre: str
    descripcion: str | None
    sistema_operativo: SistemaOperativo
    tipo: TipoPlantillaDespliegue
    ruta_destino: str
    nombre_servicio: str | None
    activo: bool
    creado_en: datetime
    actualizado_en: datetime


class CrearAplicacionAdministrada(BaseModel):
    """Asocia una plantilla compatible con un servidor."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=2, max_length=100)
    descripcion: str | None = Field(default=None, max_length=500)
    id_servidor: int = Field(strict=True, gt=0)
    id_plantilla_despliegue: int = Field(strict=True, gt=0)
    activo: bool = True

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        if not PATRON_NOMBRE.fullmatch(valor):
            raise ValueError("El nombre de aplicación no tiene un formato válido.")
        return valor

    @field_validator("descripcion")
    @classmethod
    def limpiar_descripcion(cls, valor: str | None) -> str | None:
        return _limpiar_texto(valor)


class AplicacionAdministradaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_aplicacion_administrada: int
    id_servidor: int
    id_plantilla_despliegue: int
    nombre: str
    descripcion: str | None
    version_actual: str | None
    activo: bool
    creado_en: datetime
    actualizado_en: datetime


class SolicitudDespliegue(BaseModel):
    """Versión y artefacto remoto ya cargado mediante el hito 13."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=64)
    ruta_artefacto: str = Field(min_length=2, max_length=1024)
    confirmar: bool = False

    @field_validator("version")
    @classmethod
    def validar_version(cls, valor: str) -> str:
        if not PATRON_VERSION.fullmatch(valor):
            raise ValueError("La versión no tiene un formato válido.")
        return valor


class SolicitudReversion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmar: bool = False


class DespliegueAplicacionRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_despliegue_aplicacion: int
    id_aplicacion_administrada: int
    nombre_usuario: str
    version: str
    version_anterior: str | None
    hash_sha256: str | None
    estado: EstadoDespliegue
    detalle_resultado: str | None
    iniciado_en: datetime
    finalizado_en: datetime | None
    revertido_en: datetime | None


class EstadoAplicacionRespuesta(BaseModel):
    """Estado normalizado del archivo instalado y servicio opcional."""

    id_aplicacion_administrada: int
    nombre_aplicacion: str
    nombre_servidor: str
    sistema_operativo: SistemaOperativo
    version_actual: str | None
    estado: str
    archivo_disponible: bool
    integridad_verificada: bool | None
    servicio: str | None
    estado_servicio: str | None
