"""Sondeo controlado de diagnóstico y servicios críticos."""

import asyncio
import logging
from dataclasses import dataclass

from aplicacion.acciones.registro import CodigoAccion, obtener_definicion_accion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorHermes
from aplicacion.modelos.servidor import Servidor
from aplicacion.servicios.gestor_conexiones import (
    FabricaTransporteRemoto,
    obtener_adaptador,
)

registrador = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ObjetivoMonitoreo:
    """Copia inmutable de una política lista para abandonar la sesión ORM."""

    servidor: Servidor
    activo: bool
    umbral_cpu: float | None
    umbral_memoria: float | None
    umbral_disco: float | None
    servicios_criticos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResultadoSondeo:
    """Datos normalizados o fallo controlado de disponibilidad."""

    id_servidor: int
    nombre_servidor: str
    disponible: bool
    diagnostico: dict[str, str | int | float | bool | None]
    estados_servicios: dict[str, str]
    codigo_error: str | None = None


class ErrorInternoSondeo(Exception):
    """Aísla un fallo inesperado sin convertirlo en indisponibilidad remota."""


async def sondear_objetivo(
    objetivo: ObjetivoMonitoreo,
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
) -> ResultadoSondeo:
    """Reutiliza catálogo, adaptador y una conexión SSH con un plazo total."""

    servidor = objetivo.servidor
    transporte = fabrica_transporte(servidor)
    diagnostico: dict[str, str | int | float | bool | None] | None = None
    estados_servicios: dict[str, str] = {}
    servicio_actual: str | None = None
    try:
        async with asyncio.timeout(configuracion.tiempo_limite_sondeo_segundos):
            adaptador = obtener_adaptador(servidor.sistema_operativo)
            definicion_diagnostico = obtener_definicion_accion(
                CodigoAccion.OBTENER_DIAGNOSTICO.value
            )
            parametros_diagnostico = definicion_diagnostico.validar_parametros({})
            accion_diagnostico = adaptador.preparar_accion(
                CodigoAccion.OBTENER_DIAGNOSTICO,
                parametros_diagnostico,
            )
            resultado_remoto = await transporte.ejecutar_comando_controlado(
                accion_diagnostico.comando,
                configuracion.tiempo_operacion_ssh_segundos,
                configuracion.limite_salida_ssh_bytes,
            )
            diagnostico = adaptador.interpretar_accion(
                CodigoAccion.OBTENER_DIAGNOSTICO,
                resultado_remoto,
            )

            definicion_servicio = obtener_definicion_accion(CodigoAccion.CONSULTAR_SERVICIO.value)
            for servicio_actual in objetivo.servicios_criticos:
                try:
                    parametros_servicio = definicion_servicio.validar_parametros(
                        {"nombre_servicio": servicio_actual}
                    )
                    accion_servicio = adaptador.preparar_accion(
                        CodigoAccion.CONSULTAR_SERVICIO,
                        parametros_servicio,
                    )
                    resultado_servicio = await transporte.ejecutar_comando_controlado(
                        accion_servicio.comando,
                        configuracion.tiempo_operacion_ssh_segundos,
                        configuracion.limite_salida_ssh_bytes,
                    )
                    datos_servicio = adaptador.interpretar_accion(
                        CodigoAccion.CONSULTAR_SERVICIO,
                        resultado_servicio,
                    )
                    estados_servicios[servicio_actual] = str(datos_servicio["estado"])
                except ErrorHermes as error:
                    estados_servicios[servicio_actual] = f"no_consultable:{error.codigo}"
                finally:
                    servicio_actual = None
    except TimeoutError:
        if diagnostico is None:
            return ResultadoSondeo(
                id_servidor=servidor.id_servidor,
                nombre_servidor=servidor.nombre,
                disponible=False,
                diagnostico={},
                estados_servicios={},
                codigo_error="tiempo_limite_sondeo",
            )
        if servicio_actual is not None:
            estados_servicios[servicio_actual] = "no_consultable:tiempo_limite_sondeo"
        for nombre in objetivo.servicios_criticos:
            estados_servicios.setdefault(nombre, "no_consultable:tiempo_limite_sondeo")
    except ErrorHermes as error:
        return ResultadoSondeo(
            id_servidor=servidor.id_servidor,
            nombre_servidor=servidor.nombre,
            disponible=False,
            diagnostico={},
            estados_servicios={},
            codigo_error=error.codigo,
        )
    except Exception as error:
        registrador.exception(
            "El sondeo produjo un error interno aislado. id_servidor=%s",
            servidor.id_servidor,
            exc_info=error,
        )
        raise ErrorInternoSondeo() from None
    finally:
        try:
            await transporte.cerrar()
        except Exception as error:
            registrador.warning(
                "No se pudo confirmar el cierre de un transporte de monitoreo. "
                "id_servidor=%s tipo=%s",
                servidor.id_servidor,
                type(error).__name__,
            )

    return ResultadoSondeo(
        id_servidor=servidor.id_servidor,
        nombre_servidor=servidor.nombre,
        disponible=True,
        diagnostico=diagnostico or {},
        estados_servicios=estados_servicios,
    )
