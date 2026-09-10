"""Contratos de administración segura de archivos remotos."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from aplicacion.esquemas.comunes import EsquemaDesdeAtributos


class CrearRutaArchivoPermitida(BaseModel):
    """Raíz declarada para un servidor; la plataforma determina su sintaxis."""

    ruta: str = Field(min_length=2, max_length=1024)
    descripcion: str | None = Field(default=None, max_length=255)
    permite_lectura: bool = True
    permite_escritura: bool = False
    activo: bool = True

    @model_validator(mode="after")
    def validar_operaciones(self) -> "CrearRutaArchivoPermitida":
        if not self.permite_lectura and not self.permite_escritura:
            raise ValueError("Debe habilitar lectura o escritura para la ruta.")
        return self


class RutaArchivoPermitidaDetalle(EsquemaDesdeAtributos):
    """Configuración persistente visible sin datos secretos."""

    id_ruta_archivo_permitida: int
    id_servidor: int
    ruta: str
    descripcion: str | None
    permite_lectura: bool
    permite_escritura: bool
    activo: bool
    creado_en: datetime
    actualizado_en: datetime


class InformacionArchivoRespuesta(BaseModel):
    """Metadatos normalizados obtenidos mediante SFTP."""

    id_servidor: int
    nombre_servidor: str
    ruta_remota: str
    nombre_archivo: str
    tipo: str
    tamano_bytes: int | None
    modificado_en: datetime | None


class CargaArchivoRespuesta(BaseModel):
    """Confirmación acotada de una carga remota."""

    id_servidor: int
    nombre_servidor: str
    ruta_remota: str
    tamano_bytes: int
    sobrescrito: bool


class DescargaArchivo:
    """Contenido interno no serializable entregado por API o mensajería."""

    def __init__(self, nombre_archivo: str, contenido: bytes, ruta_remota: str) -> None:
        self.nombre_archivo = nombre_archivo
        self.contenido = contenido
        self.ruta_remota = ruta_remota
