"""Respuestas normalizadas de conexión remota."""

from typing import Literal

from pydantic import BaseModel

from aplicacion.modelos.enumeraciones import SistemaOperativo


class ComprobacionConexionRespuesta(BaseModel):
    """Estado seguro de una conexión y detección de plataforma."""

    id_servidor: int
    nombre_servidor: str
    estado: Literal["disponible"] = "disponible"
    sistema_registrado: SistemaOperativo
    sistema_detectado: SistemaOperativo
    version_detectada: str
    nombre_equipo: str
    duracion_ms: float
