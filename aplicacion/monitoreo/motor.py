"""Orquestación concurrente de un ciclo completo de monitoreo."""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from aplicacion.configuracion import Configuracion
from aplicacion.esquemas.monitoreo import ResumenCicloMonitoreo
from aplicacion.modelos.enumeraciones import FaseNotificacionAlerta, TipoCanalMensajeria
from aplicacion.modelos.monitoreo import ConfiguracionMonitoreoServidor
from aplicacion.monitoreo.evaluador import (
    cerrar_alertas_por_monitoreo_inactivo,
    evaluar_resultado_sondeo,
)
from aplicacion.monitoreo.notificaciones import (
    NotificadorMensajeria,
    enviar_notificaciones_pendientes,
    preparar_notificaciones,
)
from aplicacion.monitoreo.sondeador import (
    ErrorInternoSondeo,
    ObjetivoMonitoreo,
    ResultadoSondeo,
    sondear_objetivo,
)
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto

registrador = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoObjetivo:
    """Resultado mínimo necesario para consolidar un ciclo."""

    disponible: bool | None
    aperturas: int
    recuperaciones: int
    error_interno: bool = False


async def cargar_objetivos_monitoreo(
    sesion: AsyncSession,
) -> list[ObjetivoMonitoreo]:
    """Copia todas las políticas sin imponer un límite fijo al inventario."""

    consulta = (
        select(ConfiguracionMonitoreoServidor)
        .options(
            selectinload(ConfiguracionMonitoreoServidor.servidor),
            selectinload(ConfiguracionMonitoreoServidor.servicios_criticos),
        )
        .order_by(ConfiguracionMonitoreoServidor.id_servidor)
    )
    configuraciones = list((await sesion.scalars(consulta)).all())
    return [
        ObjetivoMonitoreo(
            servidor=configuracion.servidor,
            activo=configuracion.activo and configuracion.servidor.activo,
            umbral_cpu=configuracion.umbral_cpu,
            umbral_memoria=configuracion.umbral_memoria,
            umbral_disco=configuracion.umbral_disco,
            servicios_criticos=tuple(configuracion.nombres_servicios_criticos),
        )
        for configuracion in configuraciones
    ]


async def _persistir_resultado(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    objetivo: ObjetivoMonitoreo,
    resultado: ResultadoSondeo | None,
) -> ResultadoObjetivo:
    async with fabrica_sesiones() as sesion:
        if resultado is None:
            transiciones = await cerrar_alertas_por_monitoreo_inactivo(sesion, objetivo)
            disponible: bool | None = None
        else:
            transiciones = await evaluar_resultado_sondeo(sesion, objetivo, resultado)
            disponible = resultado.disponible
        await sesion.flush()
        await preparar_notificaciones(sesion, transiciones)
        await sesion.commit()
    return ResultadoObjetivo(
        disponible=disponible,
        aperturas=sum(
            transicion.fase is FaseNotificacionAlerta.APERTURA for transicion in transiciones
        ),
        recuperaciones=sum(
            transicion.fase is FaseNotificacionAlerta.RECUPERACION for transicion in transiciones
        ),
    )


async def _procesar_objetivo(
    objetivo: ObjetivoMonitoreo,
    semaforo: asyncio.Semaphore,
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
) -> ResultadoObjetivo:
    try:
        if not objetivo.activo:
            return await _persistir_resultado(fabrica_sesiones, objetivo, None)
        async with semaforo:
            resultado = await sondear_objetivo(objetivo, fabrica_transporte, configuracion)
        return await _persistir_resultado(fabrica_sesiones, objetivo, resultado)
    except ErrorInternoSondeo:
        return ResultadoObjetivo(None, 0, 0, error_interno=True)
    except Exception as error:
        registrador.exception(
            "Falló un objetivo de monitoreo sin afectar a los demás. id_servidor=%s",
            objetivo.servidor.id_servidor,
            exc_info=error,
        )
        return ResultadoObjetivo(None, 0, 0, error_interno=True)


async def ejecutar_ciclo_monitoreo(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
    notificadores: dict[TipoCanalMensajeria, NotificadorMensajeria],
) -> ResumenCicloMonitoreo:
    """Evalúa destinos aisladamente y luego entrega eventos pendientes."""

    async with fabrica_sesiones() as sesion:
        objetivos = await cargar_objetivos_monitoreo(sesion)
    semaforo = asyncio.Semaphore(configuracion.max_concurrencia_monitoreo)
    resultados = await asyncio.gather(
        *(
            _procesar_objetivo(
                objetivo,
                semaforo,
                fabrica_sesiones,
                fabrica_transporte,
                configuracion,
            )
            for objetivo in objetivos
        )
    )
    resumen_notificaciones = await enviar_notificaciones_pendientes(
        fabrica_sesiones,
        notificadores,
        configuracion.max_intentos_notificacion_alerta,
    )
    resumen = ResumenCicloMonitoreo(
        servidores_evaluados=sum(objetivo.activo for objetivo in objetivos),
        servidores_disponibles=sum(resultado.disponible is True for resultado in resultados),
        servidores_no_disponibles=sum(resultado.disponible is False for resultado in resultados),
        alertas_abiertas=sum(resultado.aperturas for resultado in resultados),
        alertas_recuperadas=sum(resultado.recuperaciones for resultado in resultados),
        sondeos_con_error_interno=sum(resultado.error_interno for resultado in resultados),
        notificaciones_enviadas=resumen_notificaciones.enviadas,
        notificaciones_fallidas=resumen_notificaciones.fallidas,
    )
    registrador.info(
        "Ciclo de monitoreo completado. evaluados=%s disponibles=%s no_disponibles=%s "
        "alertas_abiertas=%s alertas_recuperadas=%s notificaciones_enviadas=%s "
        "notificaciones_fallidas=%s errores_internos=%s",
        resumen.servidores_evaluados,
        resumen.servidores_disponibles,
        resumen.servidores_no_disponibles,
        resumen.alertas_abiertas,
        resumen.alertas_recuperadas,
        resumen.notificaciones_enviadas,
        resumen.notificaciones_fallidas,
        resumen.sondeos_con_error_interno,
    )
    return resumen
