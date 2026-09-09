"""Ruta de comprobación de salud de Hermes."""

import logging

from fastapi import APIRouter, Request

from aplicacion.base_datos import comprobar_conexion_base_datos
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorBaseDatosNoDisponible
from aplicacion.esquemas.salud import EstadoBaseDatos, RespuestaSalud

registrador = logging.getLogger(__name__)
enrutador = APIRouter(tags=["salud"])


@enrutador.get(
    "/salud",
    response_model=RespuestaSalud,
    summary="Comprobar la salud del backend y de MariaDB",
)
async def obtener_salud(solicitud: Request) -> RespuestaSalud:
    """Comprueba que el proceso y su base de datos pueden atender solicitudes."""

    configuracion: Configuracion = solicitud.app.state.configuracion
    try:
        duracion = await comprobar_conexion_base_datos(solicitud.app.state.motor_base_datos)
    except Exception:
        registrador.warning(
            "Falló la comprobación de MariaDB. identificador_solicitud=%s",
            solicitud.state.identificador_solicitud,
        )
        raise ErrorBaseDatosNoDisponible() from None

    return RespuestaSalud(
        aplicacion=configuracion.nombre_aplicacion,
        version=configuracion.version_aplicacion,
        estado="saludable",
        base_datos=EstadoBaseDatos(
            estado="disponible",
            tiempo_respuesta_ms=duracion,
        ),
    )
