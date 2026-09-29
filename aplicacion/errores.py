"""Errores de dominio y respuestas HTTP centralizadas."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as ExcepcionHTTP

registrador = logging.getLogger(__name__)


class ErrorHermes(Exception):
    """Error controlado que puede convertirse en una respuesta segura."""

    def __init__(
        self,
        mensaje: str,
        *,
        codigo: str,
        estado_http: int,
        detalles: list[dict[str, Any]] | None = None,
        cabeceras: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.estado_http = estado_http
        self.detalles = detalles
        self.cabeceras = cabeceras


class ErrorBaseDatosNoDisponible(ErrorHermes):
    """Indica que MariaDB no respondió a una comprobación."""

    def __init__(self) -> None:
        super().__init__(
            "La base de datos no está disponible temporalmente.",
            codigo="base_datos_no_disponible",
            estado_http=HTTPStatus.SERVICE_UNAVAILABLE,
        )


class ErrorNoAutenticado(ErrorHermes):
    """Indica que las credenciales de acceso no son válidas."""

    def __init__(self) -> None:
        super().__init__(
            "Las credenciales proporcionadas no son válidas.",
            codigo="credenciales_no_validas",
            estado_http=HTTPStatus.UNAUTHORIZED,
            cabeceras={"WWW-Authenticate": 'Basic realm="Hermes"'},
        )


class ErrorDemasiadosIntentosAutenticacion(ErrorHermes):
    """Frena rechazos repetidos antes de cargar Argon2 y MariaDB."""

    def __init__(self, espera_segundos: int) -> None:
        super().__init__(
            "Hay demasiados intentos de acceso. Inténtelo más tarde.",
            codigo="demasiados_intentos_autenticacion",
            estado_http=HTTPStatus.TOO_MANY_REQUESTS,
            cabeceras={"Retry-After": str(espera_segundos)},
        )


class ErrorIdentidadMensajeriaNoAutorizada(ErrorHermes):
    """Rechaza identidades externas que no estén vinculadas y activas."""

    def __init__(self) -> None:
        super().__init__(
            "Esta identidad no está autorizada para utilizar Hermes.",
            codigo="identidad_mensajeria_no_autorizada",
            estado_http=HTTPStatus.FORBIDDEN,
        )


class ErrorPermisoDenegado(ErrorHermes):
    """Indica que un usuario autenticado no tiene el permiso requerido."""

    def __init__(self, codigo_permiso: str) -> None:
        super().__init__(
            "No tiene permiso para realizar esta operación.",
            codigo="permiso_denegado",
            estado_http=HTTPStatus.FORBIDDEN,
            detalles=[{"permiso_requerido": codigo_permiso}],
        )


class ErrorRecursoNoEncontrado(ErrorHermes):
    """Indica que una entidad solicitada no existe."""

    def __init__(self, tipo_recurso: str) -> None:
        super().__init__(
            f"No se encontró el recurso de tipo {tipo_recurso}.",
            codigo="recurso_no_encontrado",
            estado_http=HTTPStatus.NOT_FOUND,
        )


class ErrorServidorInactivo(ErrorHermes):
    """Impide operar un servidor deshabilitado en el inventario."""

    def __init__(self) -> None:
        super().__init__(
            "El servidor está inactivo en el inventario.",
            codigo="servidor_inactivo",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorConflictoDatos(ErrorHermes):
    """Indica una colisión con restricciones de integridad."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(
            mensaje,
            codigo="conflicto_de_datos",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorConfirmacionRequerida(ErrorHermes):
    """Impide una eliminación que no fue confirmada explícitamente."""

    def __init__(self) -> None:
        super().__init__(
            "La operación requiere confirmación explícita.",
            codigo="confirmacion_requerida",
            estado_http=HTTPStatus.BAD_REQUEST,
        )


class ErrorSeleccionServidoresVacia(ErrorHermes):
    """Impide iniciar una operación múltiple sin destinos resolubles."""

    def __init__(self) -> None:
        super().__init__(
            "La selección no contiene servidores sobre los que se pueda operar.",
            codigo="seleccion_servidores_vacia",
            estado_http=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class ErrorLimiteSeleccionServidores(ErrorHermes):
    """Acota la cantidad de destinos aceptados en una sola solicitud."""

    def __init__(self, maximo: int) -> None:
        super().__init__(
            "La selección supera el máximo de servidores permitido por solicitud.",
            codigo="limite_seleccion_servidores_superado",
            estado_http=HTTPStatus.UNPROCESSABLE_ENTITY,
            detalles=[{"maximo_servidores": maximo}],
        )


class ErrorRutaRemotaNoValida(ErrorHermes):
    """Rechaza rutas ambiguas, relativas o propias de otra plataforma."""

    def __init__(
        self, mensaje: str = "La ruta remota no tiene un formato seguro y válido."
    ) -> None:
        super().__init__(
            mensaje,
            codigo="ruta_remota_no_valida",
            estado_http=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class ErrorRutaRemotaNoPermitida(ErrorHermes):
    """Impide acceder fuera de las raíces autorizadas del servidor."""

    def __init__(self) -> None:
        super().__init__(
            "La ruta remota no está autorizada para esta operación.",
            codigo="ruta_remota_no_permitida",
            estado_http=HTTPStatus.FORBIDDEN,
        )


class ErrorLimiteArchivoExcedido(ErrorHermes):
    """Detiene una transferencia que supera el presupuesto configurado."""

    def __init__(self, maximo_bytes: int) -> None:
        super().__init__(
            "El archivo supera el tamaño máximo permitido.",
            codigo="limite_archivo_superado",
            estado_http=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            detalles=[{"maximo_bytes": maximo_bytes}],
        )


class ErrorArchivoRemotoNoCompatible(ErrorHermes):
    """Representa tipos de archivo u operaciones no admitidas."""

    def __init__(
        self, mensaje: str = "La operación no es compatible con el archivo remoto."
    ) -> None:
        super().__init__(
            mensaje,
            codigo="archivo_remoto_no_compatible",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorPlantillaDespliegueIncompatible(ErrorHermes):
    """Impide asociar procedimientos propios de otra plataforma o ruta."""

    def __init__(self, mensaje: str = "La plantilla no es compatible con el servidor.") -> None:
        super().__init__(
            mensaje,
            codigo="plantilla_despliegue_incompatible",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorDespliegueNoRevertible(ErrorHermes):
    """Indica que el despliegue no representa el estado vigente recuperable."""

    def __init__(self) -> None:
        super().__init__(
            "El despliegue no puede revertirse desde el estado actual.",
            codigo="despliegue_no_revertible",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorAplicacionNoOperativa(ErrorHermes):
    """Señala que la verificación posterior no confirmó un estado saludable."""

    def __init__(self) -> None:
        super().__init__(
            "La aplicación no superó la verificación operativa.",
            codigo="aplicacion_no_operativa",
            estado_http=HTTPStatus.BAD_GATEWAY,
        )


def _identificador_solicitud(solicitud: Request) -> str:
    return getattr(solicitud.state, "identificador_solicitud", "no_disponible")


def _crear_respuesta_error(
    solicitud: Request,
    *,
    estado_http: int,
    codigo: str,
    mensaje: str,
    detalles: list[dict[str, Any]] | None = None,
    cabeceras: dict[str, str] | None = None,
) -> JSONResponse:
    contenido: dict[str, Any] = {
        "codigo": codigo,
        "mensaje": mensaje,
        "identificador_solicitud": _identificador_solicitud(solicitud),
    }
    if detalles:
        contenido["detalles"] = detalles
    return JSONResponse(status_code=estado_http, content=contenido, headers=cabeceras)


def _normalizar_errores_validacion(
    error: RequestValidationError,
) -> list[dict[str, str]]:
    mensajes = {
        "missing": "El campo es obligatorio.",
        "string_too_short": "El texto es demasiado corto.",
        "string_pattern_mismatch": "El formato del texto no es válido.",
        "int_parsing": "El valor debe ser un número entero.",
        "greater_than": "El valor debe ser mayor que el mínimo permitido.",
        "less_than_equal": "El valor supera el máximo permitido.",
    }
    return [
        {
            "ubicacion": ".".join(str(parte) for parte in detalle["loc"]),
            "mensaje": mensajes.get(detalle["type"], "El valor proporcionado no es válido."),
        }
        for detalle in error.errors()
    ]


def registrar_manejadores_errores(aplicacion: FastAPI) -> None:
    """Registra todos los transformadores de excepciones en un único lugar."""

    @aplicacion.exception_handler(ErrorHermes)
    async def manejar_error_hermes(solicitud: Request, error: ErrorHermes) -> JSONResponse:
        return _crear_respuesta_error(
            solicitud,
            estado_http=error.estado_http,
            codigo=error.codigo,
            mensaje=error.mensaje,
            detalles=error.detalles,
            cabeceras=error.cabeceras,
        )

    @aplicacion.exception_handler(RequestValidationError)
    async def manejar_error_validacion(
        solicitud: Request, error: RequestValidationError
    ) -> JSONResponse:
        return _crear_respuesta_error(
            solicitud,
            estado_http=HTTPStatus.UNPROCESSABLE_ENTITY,
            codigo="solicitud_no_valida",
            mensaje="La solicitud contiene datos no válidos.",
            detalles=_normalizar_errores_validacion(error),
        )

    @aplicacion.exception_handler(ExcepcionHTTP)
    async def manejar_error_http(solicitud: Request, error: ExcepcionHTTP) -> JSONResponse:
        mensajes = {
            HTTPStatus.NOT_FOUND: "El recurso solicitado no existe.",
            HTTPStatus.METHOD_NOT_ALLOWED: "El método solicitado no está permitido.",
        }
        return _crear_respuesta_error(
            solicitud,
            estado_http=error.status_code,
            codigo=f"error_http_{error.status_code}",
            mensaje=mensajes.get(error.status_code, "No fue posible procesar la solicitud."),
        )

    @aplicacion.exception_handler(Exception)
    async def manejar_error_inesperado(solicitud: Request, error: Exception) -> JSONResponse:
        registrador.exception(
            "Ocurrió un error interno no controlado. identificador_solicitud=%s",
            _identificador_solicitud(solicitud),
            exc_info=error,
        )
        return _crear_respuesta_error(
            solicitud,
            estado_http=HTTPStatus.INTERNAL_SERVER_ERROR,
            codigo="error_interno",
            mensaje=(
                "Ocurrió un error interno. Consulte los registros con el identificador indicado."
            ),
        )
