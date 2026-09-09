"""Punto de entrada ASGI del backend de Hermes."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.transporte_ssh import crear_transporte_ssh
from aplicacion.configuracion import Configuracion, obtener_configuracion
from aplicacion.errores import registrar_manejadores_errores
from aplicacion.registro_logs import configurar_logs
from aplicacion.rutas.acceso import enrutador as enrutador_acceso
from aplicacion.rutas.acciones import enrutador as enrutador_acciones
from aplicacion.rutas.auditoria import enrutador as enrutador_auditoria
from aplicacion.rutas.conexiones import enrutador as enrutador_conexiones
from aplicacion.rutas.inventario import enrutador as enrutador_inventario
from aplicacion.rutas.salud import enrutador as enrutador_salud

registrador = logging.getLogger(__name__)


def crear_aplicacion(
    configuracion: Configuracion | None = None,
    motor_base_datos: AsyncEngine | None = None,
) -> FastAPI:
    """Construye la aplicación permitiendo sustituir dependencias en pruebas."""

    configuracion = configuracion or obtener_configuracion()
    configurar_logs(configuracion.nivel_log)
    motor_base_datos = motor_base_datos or crear_motor_base_datos(configuracion)

    @asynccontextmanager
    async def ciclo_vida(aplicacion: FastAPI) -> AsyncIterator[None]:
        registrador.info(
            "Iniciando %s versión %s en entorno %s.",
            configuracion.nombre_aplicacion,
            configuracion.version_aplicacion,
            configuracion.entorno,
        )
        yield
        await aplicacion.state.motor_base_datos.dispose()
        registrador.info("Hermes se detuvo y liberó las conexiones de base de datos.")

    aplicacion = FastAPI(
        title=configuracion.nombre_aplicacion,
        description="Backend central de administración segura de servidores.",
        version=configuracion.version_aplicacion,
        docs_url="/documentacion",
        redoc_url=None,
        openapi_url="/esquema_api.json",
        lifespan=ciclo_vida,
    )
    aplicacion.state.configuracion = configuracion
    aplicacion.state.motor_base_datos = motor_base_datos
    aplicacion.state.fabrica_sesiones = crear_fabrica_sesiones(motor_base_datos)
    aplicacion.state.fabrica_transporte_remoto = lambda servidor: crear_transporte_ssh(
        servidor, configuracion
    )

    @aplicacion.middleware("http")
    async def registrar_solicitud(
        solicitud: Request,
        continuar: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        identificador = str(uuid4())
        solicitud.state.identificador_solicitud = identificador
        inicio = perf_counter()

        respuesta = await continuar(solicitud)
        respuesta.headers["X-Identificador-Solicitud"] = identificador
        duracion_ms = round((perf_counter() - inicio) * 1000, 2)
        registrador.info(
            "Solicitud atendida. metodo=%s ruta=%s estado=%s duracion_ms=%s "
            "identificador_solicitud=%s",
            solicitud.method,
            solicitud.url.path,
            respuesta.status_code,
            duracion_ms,
            identificador,
        )
        return respuesta

    registrar_manejadores_errores(aplicacion)
    aplicacion.include_router(enrutador_salud)
    aplicacion.include_router(enrutador_inventario)
    aplicacion.include_router(enrutador_acceso)
    aplicacion.include_router(enrutador_acciones)
    aplicacion.include_router(enrutador_auditoria)
    aplicacion.include_router(enrutador_conexiones)
    return aplicacion


aplicacion = crear_aplicacion()
