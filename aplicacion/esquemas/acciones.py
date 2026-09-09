"""Solicitudes y respuestas del motor de acciones."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aplicacion.acciones.registro import CodigoAccion
from aplicacion.modelos.enumeraciones import SistemaOperativo


class SolicitudEjecucionAccion(BaseModel):
    """Entrada genérica que el registro vuelve a validar por acción."""

    model_config = ConfigDict(extra="forbid")

    parametros: dict[str, object] = Field(default_factory=dict)
    confirmar: bool = False


class ResultadoAccionRespuesta(BaseModel):
    """Resultado normalizado sin devolver el comando ni stderr interno."""

    id_servidor: int
    nombre_servidor: str
    sistema_operativo: SistemaOperativo
    accion: CodigoAccion
    estado: Literal["completada"] = "completada"
    datos: dict[str, str | int | bool]
    duracion_ms: float


class AccionDisponibleRespuesta(BaseModel):
    """Metadatos seguros que facilitan futuras interfaces de mensajería."""

    codigo: CodigoAccion
    descripcion: str
    requiere_confirmacion: bool
