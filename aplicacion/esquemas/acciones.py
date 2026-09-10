"""Solicitudes y respuestas del motor de acciones."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    datos: dict[str, object]
    duracion_ms: float


class AccionDisponibleRespuesta(BaseModel):
    """Metadatos seguros que facilitan futuras interfaces de mensajería."""

    codigo: CodigoAccion
    descripcion: str
    requiere_confirmacion: bool


IdentificadorServidorPositivo = Annotated[int, Field(strict=True, gt=0)]


class SeleccionServidores(BaseModel):
    """Selecciona destinos mediante una única estrategia explícita."""

    model_config = ConfigDict(extra="forbid")

    ids_servidores: list[IdentificadorServidorPositivo] | None = Field(
        default=None,
        min_length=1,
        max_length=500,
    )
    id_grupo: IdentificadorServidorPositivo | None = None
    todos: bool = False

    @field_validator("ids_servidores")
    @classmethod
    def validar_ids_sin_duplicados(
        cls,
        ids_servidores: list[int] | None,
    ) -> list[int] | None:
        if ids_servidores is not None and len(ids_servidores) != len(set(ids_servidores)):
            raise ValueError("Los identificadores de servidores no pueden repetirse.")
        return ids_servidores

    @model_validator(mode="after")
    def validar_una_sola_estrategia(self) -> "SeleccionServidores":
        estrategias = sum(
            (
                self.ids_servidores is not None,
                self.id_grupo is not None,
                self.todos,
            )
        )
        if estrategias != 1:
            raise ValueError(
                "Debe indicar exactamente una selección: ids_servidores, id_grupo o todos."
            )
        return self


class SolicitudEjecucionMultiple(BaseModel):
    """Entrada para ejecutar una misma acción sobre varios destinos."""

    model_config = ConfigDict(extra="forbid")

    seleccion: SeleccionServidores
    parametros: dict[str, object] = Field(default_factory=dict)
    confirmar: bool = False

    def como_solicitud_individual(self) -> SolicitudEjecucionAccion:
        """Reutiliza el contrato validado del motor de una sola acción."""

        return SolicitudEjecucionAccion(
            parametros=self.parametros,
            confirmar=self.confirmar,
        )


class ResultadoServidorAccionMultiple(BaseModel):
    """Resultado aislado de un destino, sea satisfactorio o fallido."""

    id_servidor: int
    nombre_servidor: str | None
    sistema_operativo: SistemaOperativo | None
    estado: Literal["completada", "error"]
    datos: dict[str, object] | None = None
    duracion_ms: float
    codigo_error: str | None = None
    mensaje_error: str | None = None


class ResultadoAccionMultipleRespuesta(BaseModel):
    """Resumen consolidado que no oculta los fallos individuales."""

    accion: CodigoAccion
    estado: Literal["completada", "completada_con_errores", "fallida"]
    total_servidores: int
    servidores_completados: int
    servidores_fallidos: int
    duracion_ms: float
    resultados: list[ResultadoServidorAccionMultiple]
