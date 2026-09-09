"""Definiciones inmutables y validación del catálogo de acciones."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aplicacion.acciones.errores import ErrorAccionNoAutorizada, ErrorParametrosAccion


class CodigoAccion(StrEnum):
    """Operaciones que pueden llegar al transporte remoto."""

    OBTENER_IDENTIDAD = "obtener_identidad"
    CONSULTAR_PROCESO = "consultar_proceso"
    REINICIAR_SERVIDOR = "reiniciar_servidor"


class ParametrosAccion(BaseModel):
    """Base estricta que impide parámetros no declarados."""

    model_config = ConfigDict(extra="forbid")


class ParametrosSinCampos(ParametrosAccion):
    """Acción que no admite parámetros."""


class ParametrosConsultaProceso(ParametrosAccion):
    """Identificador numérico seguro de un proceso."""

    id_proceso: int = Field(ge=1, le=4_194_304)


@dataclass(frozen=True, slots=True)
class DefinicionAccion:
    """Política estática de una acción autorizada."""

    codigo: CodigoAccion
    descripcion: str
    codigo_permiso: str
    requiere_confirmacion: bool
    modelo_parametros: type[ParametrosAccion]

    def validar_parametros(self, parametros: dict[str, object]) -> ParametrosAccion:
        """Aplica el esquema exacto asociado a la acción."""

        try:
            return self.modelo_parametros.model_validate(parametros)
        except ValidationError:
            raise ErrorParametrosAccion() from None


_ACCIONES = {
    CodigoAccion.OBTENER_IDENTIDAD: DefinicionAccion(
        codigo=CodigoAccion.OBTENER_IDENTIDAD,
        descripcion="Obtener el usuario remoto y el nombre del equipo.",
        codigo_permiso="ejecutar_acciones_lectura",
        requiere_confirmacion=False,
        modelo_parametros=ParametrosSinCampos,
    ),
    CodigoAccion.CONSULTAR_PROCESO: DefinicionAccion(
        codigo=CodigoAccion.CONSULTAR_PROCESO,
        descripcion="Consultar un proceso mediante su identificador numérico.",
        codigo_permiso="ejecutar_acciones_lectura",
        requiere_confirmacion=False,
        modelo_parametros=ParametrosConsultaProceso,
    ),
    CodigoAccion.REINICIAR_SERVIDOR: DefinicionAccion(
        codigo=CodigoAccion.REINICIAR_SERVIDOR,
        descripcion="Programar el reinicio del servidor con un minuto de margen.",
        codigo_permiso="reiniciar_servidor",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosSinCampos,
    ),
}


def obtener_definicion_accion(codigo: str) -> DefinicionAccion:
    """Busca una acción sin convertir texto desconocido en un comando."""

    try:
        codigo_normalizado = CodigoAccion(codigo)
        return _ACCIONES[codigo_normalizado]
    except (ValueError, KeyError):
        raise ErrorAccionNoAutorizada() from None


def listar_definiciones_acciones() -> tuple[DefinicionAccion, ...]:
    """Expone el catálogo para ayuda y pruebas sin permitir mutaciones."""

    return tuple(_ACCIONES.values())
