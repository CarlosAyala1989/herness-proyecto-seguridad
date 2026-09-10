"""Errores controlados del motor de acciones."""

from http import HTTPStatus

from aplicacion.errores import ErrorHermes


class ErrorAccionNoAutorizada(ErrorHermes):
    """Rechaza códigos que no pertenecen al catálogo cerrado."""

    def __init__(self) -> None:
        super().__init__(
            "La acción solicitada no está autorizada en Hermes.",
            codigo="accion_no_autorizada",
            estado_http=HTTPStatus.NOT_FOUND,
        )


class ErrorParametrosAccion(ErrorHermes):
    """Rechaza parámetros desconocidos o fuera de rango."""

    def __init__(self) -> None:
        super().__init__(
            "Los parámetros de la acción no son válidos.",
            codigo="parametros_accion_no_validos",
            estado_http=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class ErrorEjecucionAccion(ErrorHermes):
    """Normaliza un código de salida remoto fallido sin revelar stderr."""

    def __init__(self, codigo_salida: int) -> None:
        super().__init__(
            "El servidor no pudo completar la acción autorizada.",
            codigo="ejecucion_accion_fallida",
            estado_http=HTTPStatus.BAD_GATEWAY,
            detalles=[{"codigo_salida": str(codigo_salida)}],
        )


class ErrorRespuestaAccionNoValida(ErrorHermes):
    """Impide devolver una respuesta remota que no tenga el marcador esperado."""

    def __init__(self) -> None:
        super().__init__(
            "El servidor devolvió una respuesta no válida para la acción.",
            codigo="respuesta_accion_no_valida",
            estado_http=HTTPStatus.BAD_GATEWAY,
        )


class ErrorServicioNoEncontrado(ErrorHermes):
    """Informa que el nombre validado no corresponde a un servicio remoto."""

    def __init__(self) -> None:
        super().__init__(
            "El servicio solicitado no existe en el servidor.",
            codigo="servicio_no_encontrado",
            estado_http=HTTPStatus.NOT_FOUND,
        )


class ErrorGestorServiciosNoDisponible(ErrorHermes):
    """Evita usar órdenes incompatibles en un sistema sin gestor admitido."""

    def __init__(self) -> None:
        super().__init__(
            "La administración de servicios no está disponible en este sistema.",
            codigo="gestor_servicios_no_disponible",
            estado_http=HTTPStatus.NOT_IMPLEMENTED,
        )


class ErrorUsuarioSistemaNoEncontrado(ErrorHermes):
    """Informa que la cuenta local exacta no existe."""

    def __init__(self) -> None:
        super().__init__(
            "El usuario del sistema solicitado no existe en el servidor.",
            codigo="usuario_sistema_no_encontrado",
            estado_http=HTTPStatus.NOT_FOUND,
        )


class ErrorUsuarioSistemaYaExiste(ErrorHermes):
    """Impide sustituir accidentalmente una cuenta existente."""

    def __init__(self) -> None:
        super().__init__(
            "El usuario del sistema ya existe en el servidor.",
            codigo="usuario_sistema_ya_existe",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorGrupoSistemaNoEncontrado(ErrorHermes):
    """Informa que el grupo local exacto no existe."""

    def __init__(self) -> None:
        super().__init__(
            "El grupo del sistema solicitado no existe en el servidor.",
            codigo="grupo_sistema_no_encontrado",
            estado_http=HTTPStatus.NOT_FOUND,
        )


class ErrorGestorUsuariosNoDisponible(ErrorHermes):
    """Evita improvisar órdenes en plataformas sin herramientas compatibles."""

    def __init__(self) -> None:
        super().__init__(
            "La administración de usuarios no está disponible en este sistema.",
            codigo="gestor_usuarios_no_disponible",
            estado_http=HTTPStatus.NOT_IMPLEMENTED,
        )


class ErrorCuentaSistemaProtegida(ErrorHermes):
    """Exige autorización reforzada para cuentas o grupos privilegiados."""

    def __init__(self) -> None:
        super().__init__(
            "La operación afecta una cuenta o grupo protegido y requiere autorización explícita.",
            codigo="cuenta_sistema_protegida",
            estado_http=HTTPStatus.FORBIDDEN,
        )


class ErrorCuentaOperadorSSH(ErrorHermes):
    """Impide bloquear o eliminar la sesión usada por Hermes."""

    def __init__(self) -> None:
        super().__init__(
            "No se puede bloquear ni eliminar la cuenta utilizada por la conexión de Hermes.",
            codigo="cuenta_operador_ssh",
            estado_http=HTTPStatus.CONFLICT,
        )
