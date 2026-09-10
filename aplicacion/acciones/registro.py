"""Definiciones inmutables y validación del catálogo de acciones."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from aplicacion.acciones.errores import ErrorAccionNoAutorizada, ErrorParametrosAccion


class CodigoAccion(StrEnum):
    """Operaciones que pueden llegar al transporte remoto."""

    OBTENER_IDENTIDAD = "obtener_identidad"
    CONSULTAR_PROCESO = "consultar_proceso"
    REINICIAR_SERVIDOR = "reiniciar_servidor"
    OBTENER_DIAGNOSTICO = "obtener_diagnostico"
    CONSULTAR_SERVICIO = "consultar_servicio"
    INICIAR_SERVICIO = "iniciar_servicio"
    DETENER_SERVICIO = "detener_servicio"
    REINICIAR_SERVICIO = "reiniciar_servicio"
    LISTAR_USUARIOS_SISTEMA = "listar_usuarios_sistema"
    CREAR_USUARIO_SISTEMA = "crear_usuario_sistema"
    CAMBIAR_GRUPO_USUARIO_SISTEMA = "cambiar_grupo_usuario_sistema"
    BLOQUEAR_USUARIO_SISTEMA = "bloquear_usuario_sistema"
    DESBLOQUEAR_USUARIO_SISTEMA = "desbloquear_usuario_sistema"
    ELIMINAR_USUARIO_SISTEMA = "eliminar_usuario_sistema"


class ParametrosAccion(BaseModel):
    """Base estricta que impide parámetros no declarados."""

    model_config = ConfigDict(extra="forbid")


class ParametrosSinCampos(ParametrosAccion):
    """Acción que no admite parámetros."""


class ParametrosConsultaProceso(ParametrosAccion):
    """Identificador numérico seguro de un proceso."""

    id_proceso: int = Field(ge=1, le=4_194_304)


class ParametrosServicio(ParametrosAccion):
    """Nombre interno de servicio sin comodines ni metacaracteres de shell."""

    nombre_servicio: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$",
    )


class ParametrosNombreUsuarioSistema(ParametrosAccion):
    """Nombre común, acotado y transportable entre Linux y Windows."""

    nombre_usuario: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,19}$",
    )
    autorizar_cuenta_protegida: bool = Field(default=False, strict=True)

    @field_validator("nombre_usuario")
    @classmethod
    def validar_terminacion(cls, valor: str) -> str:
        if valor.endswith((".", "-")):
            raise ValueError("El nombre de usuario no puede terminar en punto o guion.")
        return valor


class ParametrosCrearUsuarioSistema(ParametrosAccion):
    """Datos no secretos para crear una cuenta inicialmente deshabilitada."""

    nombre_usuario: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,19}$",
    )
    nombre_mostrar: str | None = Field(default=None, max_length=120)

    @field_validator("nombre_usuario")
    @classmethod
    def validar_terminacion(cls, valor: str) -> str:
        if valor.endswith((".", "-")):
            raise ValueError("El nombre de usuario no puede terminar en punto o guion.")
        return valor

    @field_validator("nombre_mostrar")
    @classmethod
    def normalizar_nombre_mostrar(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        normalizado = " ".join(valor.split())
        if not normalizado or not normalizado.isprintable():
            raise ValueError("El nombre para mostrar no es válido.")
        return normalizado


class ParametrosCambioGrupoUsuarioSistema(ParametrosNombreUsuarioSistema):
    """Pertenencia exacta y operación cerrada sobre un grupo."""

    nombre_grupo: str = Field(min_length=1, max_length=128)
    operacion_grupo: Literal["agregar", "quitar"]

    @field_validator("nombre_grupo")
    @classmethod
    def validar_nombre_grupo(cls, valor: str) -> str:
        normalizado = " ".join(valor.split())
        if (
            not normalizado
            or not normalizado[0].isalnum()
            or any(not caracter.isalnum() and caracter not in "_ .-" for caracter in normalizado)
        ):
            raise ValueError("El nombre del grupo no es válido.")
        return normalizado


@dataclass(frozen=True, slots=True)
class DefinicionAccion:
    """Política estática de una acción autorizada."""

    codigo: CodigoAccion
    descripcion: str
    codigo_permiso: str
    requiere_confirmacion: bool
    modelo_parametros: type[ParametrosAccion]
    codigos_permisos_adicionales: tuple[str, ...] = ()
    codigo_permiso_cuenta_protegida: str | None = None

    def validar_parametros(self, parametros: dict[str, object]) -> ParametrosAccion:
        """Aplica el esquema exacto asociado a la acción."""

        try:
            return self.modelo_parametros.model_validate(parametros)
        except ValidationError:
            raise ErrorParametrosAccion() from None

    def obtener_permisos_adicionales(
        self,
        parametros: ParametrosAccion,
    ) -> tuple[str, ...]:
        """Añade la autorización reforzada solo ante una solicitud explícita."""

        permisos = list(self.codigos_permisos_adicionales)
        if (
            self.codigo_permiso_cuenta_protegida is not None
            and isinstance(parametros, ParametrosNombreUsuarioSistema)
            and parametros.autorizar_cuenta_protegida
        ):
            permisos.append(self.codigo_permiso_cuenta_protegida)
        return tuple(permisos)


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
    CodigoAccion.OBTENER_DIAGNOSTICO: DefinicionAccion(
        codigo=CodigoAccion.OBTENER_DIAGNOSTICO,
        descripcion="Consultar disponibilidad, recursos y datos del sistema.",
        codigo_permiso="consultar_diagnostico",
        requiere_confirmacion=False,
        modelo_parametros=ParametrosSinCampos,
    ),
    CodigoAccion.CONSULTAR_SERVICIO: DefinicionAccion(
        codigo=CodigoAccion.CONSULTAR_SERVICIO,
        descripcion="Consultar el estado de un servicio del sistema.",
        codigo_permiso="consultar_servicios",
        requiere_confirmacion=False,
        modelo_parametros=ParametrosServicio,
    ),
    CodigoAccion.INICIAR_SERVICIO: DefinicionAccion(
        codigo=CodigoAccion.INICIAR_SERVICIO,
        descripcion="Iniciar un servicio del sistema.",
        codigo_permiso="gestionar_servicios",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosServicio,
    ),
    CodigoAccion.DETENER_SERVICIO: DefinicionAccion(
        codigo=CodigoAccion.DETENER_SERVICIO,
        descripcion="Detener un servicio del sistema.",
        codigo_permiso="gestionar_servicios",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosServicio,
    ),
    CodigoAccion.REINICIAR_SERVICIO: DefinicionAccion(
        codigo=CodigoAccion.REINICIAR_SERVICIO,
        descripcion="Reiniciar un servicio del sistema.",
        codigo_permiso="gestionar_servicios",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosServicio,
    ),
    CodigoAccion.LISTAR_USUARIOS_SISTEMA: DefinicionAccion(
        codigo=CodigoAccion.LISTAR_USUARIOS_SISTEMA,
        descripcion="Listar cuentas locales y su estado normalizado.",
        codigo_permiso="consultar_usuarios_sistema",
        requiere_confirmacion=False,
        modelo_parametros=ParametrosSinCampos,
    ),
    CodigoAccion.CREAR_USUARIO_SISTEMA: DefinicionAccion(
        codigo=CodigoAccion.CREAR_USUARIO_SISTEMA,
        descripcion="Crear una cuenta local inicialmente deshabilitada.",
        codigo_permiso="gestionar_usuarios_sistema",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosCrearUsuarioSistema,
    ),
    CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA: DefinicionAccion(
        codigo=CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        descripcion="Agregar o quitar una cuenta de un grupo local.",
        codigo_permiso="gestionar_usuarios_sistema",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosCambioGrupoUsuarioSistema,
        codigo_permiso_cuenta_protegida="gestionar_usuarios_protegidos",
    ),
    CodigoAccion.BLOQUEAR_USUARIO_SISTEMA: DefinicionAccion(
        codigo=CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
        descripcion="Bloquear o deshabilitar una cuenta local.",
        codigo_permiso="gestionar_usuarios_sistema",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosNombreUsuarioSistema,
        codigo_permiso_cuenta_protegida="gestionar_usuarios_protegidos",
    ),
    CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA: DefinicionAccion(
        codigo=CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
        descripcion="Desbloquear o habilitar una cuenta local.",
        codigo_permiso="gestionar_usuarios_sistema",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosNombreUsuarioSistema,
        codigo_permiso_cuenta_protegida="gestionar_usuarios_protegidos",
    ),
    CodigoAccion.ELIMINAR_USUARIO_SISTEMA: DefinicionAccion(
        codigo=CodigoAccion.ELIMINAR_USUARIO_SISTEMA,
        descripcion="Eliminar una cuenta local y su directorio de usuario.",
        codigo_permiso="eliminar_usuarios_sistema",
        requiere_confirmacion=True,
        modelo_parametros=ParametrosNombreUsuarioSistema,
        codigos_permisos_adicionales=("gestionar_usuarios_sistema",),
        codigo_permiso_cuenta_protegida="gestionar_usuarios_protegidos",
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
