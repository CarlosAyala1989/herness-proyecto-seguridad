"""Contratos públicos de tareas administrativas programadas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aplicacion.acciones.registro import CodigoAccion
from aplicacion.esquemas.acciones import SeleccionServidores
from aplicacion.modelos.enumeraciones import (
    EstadoEjecucionTarea,
    EstadoTareaProgramada,
    TipoProgramacionTarea,
)


class CrearTareaProgramada(BaseModel):
    """Acción cerrada, selección y calendario solicitados."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=3, max_length=120)
    descripcion: str | None = Field(default=None, max_length=500)
    codigo_accion: CodigoAccion
    seleccion: SeleccionServidores
    parametros: dict[str, object] = Field(default_factory=dict)
    confirmar: bool = False
    tipo_programacion: TipoProgramacionTarea
    programada_para: datetime
    intervalo_segundos: int | None = Field(default=None, ge=60, le=31_536_000)
    notificar_resultado: bool = False

    @field_validator("nombre", "descripcion")
    @classmethod
    def limpiar_texto(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        limpio = " ".join(valor.split())
        if not limpio or not limpio.isprintable():
            raise ValueError("El texto no es válido.")
        return limpio

    @field_validator("programada_para")
    @classmethod
    def exigir_zona_horaria(cls, valor: datetime) -> datetime:
        if valor.tzinfo is None or valor.utcoffset() is None:
            raise ValueError("La fecha programada debe incluir una zona horaria.")
        return valor

    @model_validator(mode="after")
    def validar_intervalo(self) -> "CrearTareaProgramada":
        if self.tipo_programacion is TipoProgramacionTarea.UNA_VEZ:
            if self.intervalo_segundos is not None:
                raise ValueError("Una tarea de una vez no admite intervalo_segundos.")
        elif self.intervalo_segundos is None:
            raise ValueError("Una tarea por intervalo requiere intervalo_segundos.")
        return self


class CancelarTareaProgramada(BaseModel):
    """Confirmación explícita para detener ocurrencias futuras."""

    model_config = ConfigDict(extra="forbid")

    confirmar: bool = False


class TareaProgramadaRespuesta(BaseModel):
    """Definición persistida sin exponer datos internos del bloqueo."""

    model_config = ConfigDict(from_attributes=True)

    id_tarea_programada: int
    nombre: str
    descripcion: str | None
    nombre_usuario_creador: str
    codigo_accion: CodigoAccion
    parametros: dict[str, object]
    ids_servidores: list[int]
    tipo_programacion: TipoProgramacionTarea
    estado: EstadoTareaProgramada
    programada_inicialmente_para: datetime
    proxima_ejecucion_en: datetime | None
    intervalo_segundos: int | None
    confirmacion_otorgada: bool
    notificar_resultado: bool
    cancelada_en: datetime | None
    creado_en: datetime
    actualizado_en: datetime


class EjecucionTareaRespuesta(BaseModel):
    """Resultado seguro y resumido de una ocurrencia."""

    model_config = ConfigDict(from_attributes=True)

    id_ejecucion_tarea: int
    id_tarea_programada: int
    programada_para: datetime
    iniciada_en: datetime
    finalizada_en: datetime | None
    estado: EstadoEjecucionTarea
    resumen_resultado: dict[str, object] | None
    detalle_error: str | None
