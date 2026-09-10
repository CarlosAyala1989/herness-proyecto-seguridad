"""Entrega persistente de resultados de tareas por mensajería."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import EstadoNotificacionTarea, TipoCanalMensajeria
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.tarea_programada import EjecucionTarea, NotificacionTarea
from aplicacion.monitoreo.notificaciones import NotificadorMensajeria, ResumenNotificaciones

registrador = logging.getLogger(__name__)
LIMITE_NOTIFICACIONES_POR_CICLO = 500


@dataclass(frozen=True, slots=True)
class TrabajoNotificacionTarea:
    """Datos separados de la sesión para una entrega externa."""

    id_notificacion: int
    canal: TipoCanalMensajeria
    identificador_destino: str
    mensaje: str


def _formatear_mensaje(notificacion: NotificacionTarea) -> str:
    ejecucion = notificacion.ejecucion
    tarea = ejecucion.tarea
    resumen = ejecucion.resumen_resultado or {}
    return (
        "RESULTADO DE TAREA HERMES\n"
        f"Tarea: {tarea.nombre}\n"
        f"Acción: {tarea.codigo_accion}\n"
        f"Estado: {ejecucion.estado.value}\n"
        f"Servidores completados: {resumen.get('servidores_completados', 0)}\n"
        f"Servidores fallidos: {resumen.get('servidores_fallidos', 0)}"
    )


async def _cargar_trabajos(
    sesion: AsyncSession,
    max_intentos: int,
) -> list[TrabajoNotificacionTarea]:
    consulta = (
        select(NotificacionTarea)
        .join(NotificacionTarea.identidad)
        .join(IdentidadMensajeria.usuario)
        .join(NotificacionTarea.ejecucion)
        .join(EjecucionTarea.tarea)
        .where(
            or_(
                NotificacionTarea.estado == EstadoNotificacionTarea.PENDIENTE,
                NotificacionTarea.estado == EstadoNotificacionTarea.FALLIDA,
            ),
            NotificacionTarea.intentos < max_intentos,
            IdentidadMensajeria.activo.is_(True),
            Usuario.activo.is_(True),
        )
        .options(
            selectinload(NotificacionTarea.identidad),
            selectinload(NotificacionTarea.ejecucion).selectinload(EjecucionTarea.tarea),
        )
        .order_by(NotificacionTarea.id_notificacion_tarea)
        .limit(LIMITE_NOTIFICACIONES_POR_CICLO)
    )
    notificaciones = list((await sesion.scalars(consulta)).all())
    return [
        TrabajoNotificacionTarea(
            id_notificacion=notificacion.id_notificacion_tarea,
            canal=notificacion.canal,
            identificador_destino=notificacion.identidad.identificador_externo,
            mensaje=_formatear_mensaje(notificacion),
        )
        for notificacion in notificaciones
        if notificacion.identidad is not None
        and notificacion.identidad.id_usuario == notificacion.ejecucion.tarea.id_usuario_creador
    ]


async def _registrar_resultado(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    id_notificacion: int,
    enviada: bool,
    tipo_error: str | None,
) -> None:
    async with fabrica_sesiones() as sesion:
        notificacion = await sesion.get(NotificacionTarea, id_notificacion)
        if notificacion is None or notificacion.estado is EstadoNotificacionTarea.ENVIADA:
            return
        ahora = datetime.now(UTC).replace(tzinfo=None)
        notificacion.intentos += 1
        notificacion.ultimo_intento_en = ahora
        if enviada:
            notificacion.estado = EstadoNotificacionTarea.ENVIADA
            notificacion.enviada_en = ahora
            notificacion.ultimo_error = None
        else:
            notificacion.estado = EstadoNotificacionTarea.FALLIDA
            notificacion.ultimo_error = f"Fallo de entrega de tipo {tipo_error or 'desconocido'}."
        await sesion.commit()


async def enviar_notificaciones_tareas_pendientes(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    notificadores: Mapping[TipoCanalMensajeria, NotificadorMensajeria],
    max_intentos: int,
) -> ResumenNotificaciones:
    """Entrega cada resultado y conserva fallos para reintentos acotados."""

    async with fabrica_sesiones() as sesion:
        trabajos = await _cargar_trabajos(sesion, max_intentos)
    enviadas = 0
    fallidas = 0
    for trabajo in trabajos:
        notificador = notificadores.get(trabajo.canal)
        if notificador is None:
            continue
        try:
            await notificador.enviar_mensaje(trabajo.identificador_destino, trabajo.mensaje)
        except Exception as error:
            fallidas += 1
            await _registrar_resultado(
                fabrica_sesiones,
                trabajo.id_notificacion,
                False,
                type(error).__name__,
            )
            registrador.warning(
                "Falló una notificación de tarea. id_notificacion=%s canal=%s tipo=%s",
                trabajo.id_notificacion,
                trabajo.canal.value,
                type(error).__name__,
            )
        else:
            enviadas += 1
            await _registrar_resultado(
                fabrica_sesiones,
                trabajo.id_notificacion,
                True,
                None,
            )
    return ResumenNotificaciones(enviadas=enviadas, fallidas=fallidas)
