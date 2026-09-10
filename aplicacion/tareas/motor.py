"""Reclamación idempotente y ejecución aislada de ocurrencias vencidas."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorHermes, ErrorNoAutenticado
from aplicacion.esquemas.acciones import SeleccionServidores, SolicitudEjecucionMultiple
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    EstadoEjecucionTarea,
    EstadoNotificacionTarea,
    EstadoTareaProgramada,
    TipoProgramacionTarea,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.tarea_programada import (
    EjecucionTarea,
    NotificacionTarea,
    TareaProgramada,
)
from aplicacion.servicios.auditoria import ContextoAuditoria
from aplicacion.servicios.gestor_acciones_multiples import ejecutar_accion_multiple
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto

registrador = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrabajoTarea:
    """Copia inmutable que puede ejecutarse fuera de la transacción de reclamo."""

    id_tarea: int
    id_ejecucion: int
    id_usuario: int | None
    codigo_accion: str
    parametros: dict[str, object]
    ids_servidores: list[int]
    confirmacion_otorgada: bool
    token_bloqueo: str


@dataclass(frozen=True, slots=True)
class ResumenCicloTareas:
    """Contadores observables de una vuelta del trabajador."""

    reclamadas: int
    completadas: int
    completadas_con_errores: int
    fallidas: int
    interrumpidas_marcadas: int
    notificaciones_enviadas: int
    notificaciones_fallidas: int


def _ahora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _calcular_siguiente(tarea: TareaProgramada, ahora: datetime) -> datetime | None:
    if tarea.tipo_programacion is TipoProgramacionTarea.UNA_VEZ:
        return None
    intervalo = tarea.intervalo_segundos
    programada_para = tarea.proxima_ejecucion_en
    if intervalo is None or programada_para is None:
        return None
    siguiente = programada_para + timedelta(seconds=intervalo)
    if siguiente <= ahora:
        saltos = ((ahora - siguiente).total_seconds() // intervalo) + 1
        siguiente += timedelta(seconds=intervalo * saltos)
    return siguiente


async def marcar_ejecuciones_interrumpidas(
    sesion: AsyncSession,
    antiguedad_segundos: int,
) -> int:
    """Cierra evidencia abandonada sin repetir la acción remota."""

    limite = _ahora() - timedelta(seconds=antiguedad_segundos)
    resultado = await sesion.execute(
        update(EjecucionTarea)
        .where(
            EjecucionTarea.estado == EstadoEjecucionTarea.EN_EJECUCION,
            EjecucionTarea.iniciada_en <= limite,
        )
        .values(
            estado=EstadoEjecucionTarea.INTERRUMPIDA,
            finalizada_en=_ahora(),
            detalle_error=(
                "El trabajador anterior no finalizó esta ocurrencia; no se reintentó para "
                "evitar duplicar una acción remota."
            ),
        )
    )
    await sesion.commit()
    return int(resultado.rowcount or 0)


async def reclamar_tareas_vencidas(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    configuracion: Configuracion,
) -> list[TrabajoTarea]:
    """Reserva ocurrencias mediante actualización condicional y clave única."""

    ahora = _ahora()
    async with fabrica_sesiones() as sesion:
        candidatas = list(
            await sesion.scalars(
                select(TareaProgramada)
                .where(
                    TareaProgramada.estado == EstadoTareaProgramada.ACTIVA,
                    TareaProgramada.proxima_ejecucion_en.is_not(None),
                    TareaProgramada.proxima_ejecucion_en <= ahora,
                    or_(
                        TareaProgramada.bloqueada_hasta.is_(None),
                        TareaProgramada.bloqueada_hasta < ahora,
                    ),
                )
                .order_by(TareaProgramada.proxima_ejecucion_en)
                .limit(configuracion.max_tareas_por_ciclo * 3)
            )
        )

    trabajos: list[TrabajoTarea] = []
    for tarea in candidatas:
        if len(trabajos) >= configuracion.max_tareas_por_ciclo:
            break
        programada_para = tarea.proxima_ejecucion_en
        if programada_para is None:
            continue
        token = str(uuid4())
        siguiente = _calcular_siguiente(tarea, ahora)
        valores: dict[str, object] = {
            "token_bloqueo": token,
            "bloqueada_hasta": ahora
            + timedelta(seconds=configuracion.duracion_bloqueo_tarea_segundos),
            "proxima_ejecucion_en": siguiente,
        }
        if siguiente is None:
            valores["estado"] = EstadoTareaProgramada.COMPLETADA
        async with fabrica_sesiones() as sesion:
            resultado = await sesion.execute(
                update(TareaProgramada)
                .where(
                    TareaProgramada.id_tarea_programada == tarea.id_tarea_programada,
                    TareaProgramada.estado == EstadoTareaProgramada.ACTIVA,
                    TareaProgramada.proxima_ejecucion_en == programada_para,
                    or_(
                        TareaProgramada.bloqueada_hasta.is_(None),
                        TareaProgramada.bloqueada_hasta < ahora,
                    ),
                )
                .values(**valores)
            )
            if resultado.rowcount != 1:
                await sesion.rollback()
                continue
            ejecucion = EjecucionTarea(
                id_tarea_programada=tarea.id_tarea_programada,
                programada_para=programada_para,
                iniciada_en=ahora,
                estado=EstadoEjecucionTarea.EN_EJECUCION,
            )
            sesion.add(ejecucion)
            await sesion.flush()
            trabajo = TrabajoTarea(
                id_tarea=tarea.id_tarea_programada,
                id_ejecucion=ejecucion.id_ejecucion_tarea,
                id_usuario=tarea.id_usuario_creador,
                codigo_accion=tarea.codigo_accion,
                parametros=dict(tarea.parametros),
                ids_servidores=list(tarea.ids_servidores),
                confirmacion_otorgada=tarea.confirmacion_otorgada,
                token_bloqueo=token,
            )
            await sesion.commit()
            trabajos.append(trabajo)
    return trabajos


async def _cargar_usuario(sesion: AsyncSession, id_usuario: int | None) -> Usuario:
    if id_usuario is None:
        raise ErrorNoAutenticado()
    usuario = await sesion.scalar(
        select(Usuario)
        .where(Usuario.id_usuario == id_usuario)
        .options(selectinload(Usuario.roles).selectinload(Rol.permisos))
    )
    if usuario is None or not usuario.activo:
        raise ErrorNoAutenticado()
    return usuario


def _resumen_seguro(resultado) -> dict[str, object]:
    return {
        "accion": resultado.accion.value,
        "estado": resultado.estado,
        "total_servidores": resultado.total_servidores,
        "servidores_completados": resultado.servidores_completados,
        "servidores_fallidos": resultado.servidores_fallidos,
        "duracion_ms": resultado.duracion_ms,
        "resultados": [
            {
                "id_servidor": elemento.id_servidor,
                "nombre_servidor": elemento.nombre_servidor,
                "estado": elemento.estado,
                "datos": elemento.datos,
                "codigo_error": elemento.codigo_error,
                "mensaje_error": elemento.mensaje_error,
                "duracion_ms": elemento.duracion_ms,
            }
            for elemento in resultado.resultados
        ],
    }


async def _finalizar_trabajo(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    trabajo: TrabajoTarea,
    estado: EstadoEjecucionTarea,
    resumen: dict[str, object] | None,
    detalle_error: str | None,
) -> None:
    async with fabrica_sesiones() as sesion:
        ejecucion = await sesion.get(EjecucionTarea, trabajo.id_ejecucion)
        if ejecucion is not None and ejecucion.estado is EstadoEjecucionTarea.EN_EJECUCION:
            ejecucion.estado = estado
            ejecucion.finalizada_en = _ahora()
            ejecucion.resumen_resultado = resumen
            ejecucion.detalle_error = detalle_error
            tarea = await sesion.get(TareaProgramada, trabajo.id_tarea)
            if tarea is not None and tarea.notificar_resultado:
                identidades = list(
                    await sesion.scalars(
                        select(IdentidadMensajeria).where(
                            IdentidadMensajeria.id_usuario == trabajo.id_usuario,
                            IdentidadMensajeria.activo.is_(True),
                        )
                    )
                )
                for identidad in identidades:
                    sesion.add(
                        NotificacionTarea(
                            id_ejecucion_tarea=ejecucion.id_ejecucion_tarea,
                            id_identidad_mensajeria=identidad.id_identidad_mensajeria,
                            canal=identidad.canal,
                            estado=EstadoNotificacionTarea.PENDIENTE,
                        )
                    )
        await sesion.execute(
            update(TareaProgramada)
            .where(
                TareaProgramada.id_tarea_programada == trabajo.id_tarea,
                TareaProgramada.token_bloqueo == trabajo.token_bloqueo,
            )
            .values(token_bloqueo=None, bloqueada_hasta=None)
        )
        await sesion.commit()


async def ejecutar_trabajo(
    trabajo: TrabajoTarea,
    semaforo: asyncio.Semaphore,
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
) -> EstadoEjecucionTarea:
    """Reautoriza al creador y delega en el motor común."""

    try:
        async with semaforo:
            async with fabrica_sesiones() as sesion:
                usuario = await _cargar_usuario(sesion, trabajo.id_usuario)
                resultado = await ejecutar_accion_multiple(
                    sesion,
                    fabrica_sesiones,
                    trabajo.codigo_accion,
                    SolicitudEjecucionMultiple(
                        seleccion=SeleccionServidores(ids_servidores=trabajo.ids_servidores),
                        parametros=trabajo.parametros,
                        confirmar=trabajo.confirmacion_otorgada,
                    ),
                    usuario,
                    None,
                    fabrica_transporte,
                    configuracion,
                    ContextoAuditoria(
                        canal=CanalAuditoria.SISTEMA,
                        direccion_origen=None,
                        identificador_solicitud=trabajo.token_bloqueo,
                    ),
                )
        estado = EstadoEjecucionTarea(resultado.estado)
        await _finalizar_trabajo(
            fabrica_sesiones,
            trabajo,
            estado,
            _resumen_seguro(resultado),
            None,
        )
        return estado
    except ErrorHermes as error:
        await _finalizar_trabajo(
            fabrica_sesiones,
            trabajo,
            EstadoEjecucionTarea.FALLIDA,
            None,
            f"La ejecución fue rechazada con código {error.codigo}: {error.mensaje}",
        )
        return EstadoEjecucionTarea.FALLIDA
    except Exception as error:
        registrador.exception(
            "Falló una tarea programada. id_tarea=%s tipo=%s",
            trabajo.id_tarea,
            type(error).__name__,
        )
        await _finalizar_trabajo(
            fabrica_sesiones,
            trabajo,
            EstadoEjecucionTarea.FALLIDA,
            None,
            "La ejecución produjo un error interno controlado.",
        )
        return EstadoEjecucionTarea.FALLIDA


async def ejecutar_ciclo_tareas(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
    enviar_notificaciones,
) -> ResumenCicloTareas:
    """Recupera evidencia antigua, ejecuta vencimientos y entrega resultados."""

    async with fabrica_sesiones() as sesion:
        interrumpidas = await marcar_ejecuciones_interrumpidas(
            sesion,
            configuracion.duracion_bloqueo_tarea_segundos,
        )
    trabajos = await reclamar_tareas_vencidas(fabrica_sesiones, configuracion)
    semaforo = asyncio.Semaphore(configuracion.max_concurrencia_tareas)
    estados = await asyncio.gather(
        *(
            ejecutar_trabajo(
                trabajo,
                semaforo,
                fabrica_sesiones,
                fabrica_transporte,
                configuracion,
            )
            for trabajo in trabajos
        )
    )
    notificaciones = await enviar_notificaciones()
    resumen = ResumenCicloTareas(
        reclamadas=len(trabajos),
        completadas=estados.count(EstadoEjecucionTarea.COMPLETADA),
        completadas_con_errores=estados.count(EstadoEjecucionTarea.COMPLETADA_CON_ERRORES),
        fallidas=estados.count(EstadoEjecucionTarea.FALLIDA),
        interrumpidas_marcadas=interrumpidas,
        notificaciones_enviadas=notificaciones.enviadas,
        notificaciones_fallidas=notificaciones.fallidas,
    )
    registrador.info(
        "Ciclo de tareas completado. reclamadas=%s completadas=%s parciales=%s "
        "fallidas=%s interrumpidas=%s notificaciones_enviadas=%s "
        "notificaciones_fallidas=%s",
        resumen.reclamadas,
        resumen.completadas,
        resumen.completadas_con_errores,
        resumen.fallidas,
        resumen.interrumpidas_marcadas,
        resumen.notificaciones_enviadas,
        resumen.notificaciones_fallidas,
    )
    return resumen
