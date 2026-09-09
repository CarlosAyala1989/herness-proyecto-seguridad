"""Errores seguros del transporte remoto."""

from http import HTTPStatus

from aplicacion.errores import ErrorHermes


class ErrorConfiguracionSSH(ErrorHermes):
    """Indica que falta material local necesario para conectar."""

    def __init__(
        self, mensaje: str = "La configuración SSH del servidor no está completa."
    ) -> None:
        super().__init__(
            mensaje,
            codigo="configuracion_ssh_no_valida",
            estado_http=HTTPStatus.CONFLICT,
        )


class ErrorIdentidadServidorSSH(ErrorHermes):
    """Impide continuar cuando no se puede verificar la clave del host."""

    def __init__(self) -> None:
        super().__init__(
            "No fue posible verificar de forma segura la identidad del servidor.",
            codigo="identidad_servidor_no_verificada",
            estado_http=HTTPStatus.BAD_GATEWAY,
        )


class ErrorAutenticacionSSH(ErrorHermes):
    """Oculta los detalles de un rechazo de autenticación remota."""

    def __init__(self) -> None:
        super().__init__(
            "El servidor rechazó la credencial SSH configurada.",
            codigo="autenticacion_ssh_rechazada",
            estado_http=HTTPStatus.BAD_GATEWAY,
        )


class ErrorServidorSSHNoDisponible(ErrorHermes):
    """Representa un fallo de red o protocolo aislado a un servidor."""

    def __init__(self) -> None:
        super().__init__(
            "El servidor no está disponible mediante SSH.",
            codigo="servidor_ssh_no_disponible",
            estado_http=HTTPStatus.SERVICE_UNAVAILABLE,
        )


class ErrorTiempoEsperaSSH(ErrorHermes):
    """Indica que una conexión u operación superó su plazo."""

    def __init__(self) -> None:
        super().__init__(
            "La operación SSH superó el tiempo de espera permitido.",
            codigo="tiempo_espera_ssh_superado",
            estado_http=HTTPStatus.GATEWAY_TIMEOUT,
        )


class ErrorSalidaSSHExcedida(ErrorHermes):
    """Detiene procesos que generan más datos de los permitidos."""

    def __init__(self) -> None:
        super().__init__(
            "La salida remota superó el límite permitido.",
            codigo="limite_salida_ssh_superado",
            estado_http=HTTPStatus.BAD_GATEWAY,
        )


class ErrorSistemaOperativoNoCoincide(ErrorHermes):
    """Impide usar un adaptador distinto del sistema registrado."""

    def __init__(self) -> None:
        super().__init__(
            "El sistema operativo detectado no coincide con el inventario.",
            codigo="sistema_operativo_no_coincide",
            estado_http=HTTPStatus.CONFLICT,
        )
