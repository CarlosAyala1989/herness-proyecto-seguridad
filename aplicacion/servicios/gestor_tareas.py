"""Creación, consulta y cancelación segura de tareas programadas."""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.acciones.registro import obtener_definicion_accion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import (
    ErrorConfirmacionRequerida,
    ErrorConflictoDatos,
    ErrorRecursoNoEncontrado,
)
from aplicacion.esquemas.tareas import CrearTareaProgramada
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import (
    EstadoTareaProgramada,
    ResultadoAuditoria,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.servidor import Servidor
from aplicacion.modelos.tarea_programada import EjecucionTarea, TareaProgramada
from aplicacion.seguridad.autenticacion import comprobar_permiso_usuario
from aplicacion.servicios.auditoria import preparar_registro_auditoria
from aplicacion.servicios.gestor_acciones import comprobar_permisos_adicionales_accion
from aplicacion.servicios.gestor_acciones_multiples import resolver_objetivos_accion_multiple


def _fecha_utc_sin_zona(fecha: datetime) -> datetime:
    return fecha.astimezone(UTC).replace(tzinfo=None)


async def crear_tarea_programada(
    sesion: AsyncSession,
    datos: CrearTareaProgramada,
    usuario: Usuario,
    solicitud: Request,
    configuracion: Configuracion,
) -> TareaProgramada:
    """Valida permisos y congela destinos antes de persistir la tarea."""

    definicion = obtener_definicion_accion(datos.codigo_accion.value)
    await comprobar_permiso_usuario(
        sesion,
        solicitud,
        usuario,
        definicion.codigo_permiso,
    )
    parametros = definicion.validar_parametros(datos.parametros)
    await comprobar_permisos_adicionales_accion(
        sesion,
        solicitud,
        usuario,
        definicion,
        parametros,
    )
    if definicion.requiere_confirmacion and not datos.confirmar:
        raise ErrorConfirmacionRequerida()

    programada_para = _fecha_utc_sin_zona(datos.programada_para)
    if programada_para < datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5):
        raise ErrorConflictoDatos("La fecha programada ya ha transcurrido.")

    objetivos = await resolver_objetivos_accion_multiple(
        sesion,
        datos.seleccion,
        configuracion.max_servidores_accion_multiple,
    )
    if any(not objetivo.existe for objetivo in objetivos):
        raise ErrorConflictoDatos("La selección contiene servidores que no existen.")
    ids_servidores = [objetivo.id_servidor for objetivo in objetivos]
    servidores_activos = set(
        await sesion.scalars(
            select(Servidor.id_servidor).where(
                Servidor.id_servidor.in_(ids_servidores),
                Servidor.activo.is_(True),
            )
        )
    )
    if servidores_activos != set(ids_servidores):
        raise ErrorConflictoDatos("La selección contiene servidores inactivos.")

    tarea = TareaProgramada(
        id_usuario_creador=usuario.id_usuario,
        nombre_usuario_creador=usuario.nombre_usuario,
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        codigo_accion=definicion.codigo.value,
        parametros=parametros.model_dump(mode="json"),
        ids_servidores=ids_servidores,
        tipo_programacion=datos.tipo_programacion,
        estado=EstadoTareaProgramada.ACTIVA,
        programada_inicialmente_para=programada_para,
        proxima_ejecucion_en=programada_para,
        intervalo_segundos=datos.intervalo_segundos,
        confirmacion_otorgada=datos.confirmar,
        notificar_resultado=datos.notificar_resultado,
    )
    sesion.add(tarea)
    await sesion.flush()
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="crear_tarea_programada",
        tipo_recurso=TipoRecursoAuditoria.TAREA,
        id_recurso=tarea.id_tarea_programada,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=(
            f"Tarea creada para {len(ids_servidores)} servidor(es); "
            f"acción {definicion.codigo.value}."
        ),
    )
    await sesion.commit()
    await sesion.refresh(tarea)
    return tarea


async def obtener_tarea_programada(
    sesion: AsyncSession,
    id_tarea_programada: int,
) -> TareaProgramada:
    tarea = await sesion.get(TareaProgramada, id_tarea_programada)
    if tarea is None:
        raise ErrorRecursoNoEncontrado("tarea_programada")
    return tarea


async def listar_tareas_programadas(
    sesion: AsyncSession,
    *,
    estado: EstadoTareaProgramada | None,
    desplazamiento: int,
    limite: int,
) -> list[TareaProgramada]:
    consulta = select(TareaProgramada)
    if estado is not None:
        consulta = consulta.where(TareaProgramada.estado == estado)
    consulta = consulta.order_by(TareaProgramada.id_tarea_programada.desc())
    return list(await sesion.scalars(consulta.offset(desplazamiento).limit(limite)))


async def listar_ejecuciones_tarea(
    sesion: AsyncSession,
    id_tarea_programada: int,
    *,
    desplazamiento: int,
    limite: int,
) -> list[EjecucionTarea]:
    await obtener_tarea_programada(sesion, id_tarea_programada)
    consulta = (
        select(EjecucionTarea)
        .where(EjecucionTarea.id_tarea_programada == id_tarea_programada)
        .order_by(EjecucionTarea.id_ejecucion_tarea.desc())
        .offset(desplazamiento)
        .limit(limite)
    )
    return list(await sesion.scalars(consulta))


async def cancelar_tarea_programada(
    sesion: AsyncSession,
    id_tarea_programada: int,
    usuario: Usuario,
    solicitud: Request,
) -> TareaProgramada:
    """Cancela solo ocurrencias no iniciadas; una ejecución en curso finaliza."""

    tarea = await sesion.scalar(
        select(TareaProgramada)
        .where(TareaProgramada.id_tarea_programada == id_tarea_programada)
        .with_for_update()
    )
    if tarea is None:
        raise ErrorRecursoNoEncontrado("tarea_programada")
    if tarea.estado is not EstadoTareaProgramada.ACTIVA:
        raise ErrorConflictoDatos("La tarea ya no está activa y no puede cancelarse.")

    ahora = datetime.now(UTC).replace(tzinfo=None)
    tarea.estado = EstadoTareaProgramada.CANCELADA
    tarea.proxima_ejecucion_en = None
    tarea.cancelada_en = ahora
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="cancelar_tarea_programada",
        tipo_recurso=TipoRecursoAuditoria.TAREA,
        id_recurso=tarea.id_tarea_programada,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Se cancelaron las ocurrencias futuras de la tarea.",
    )
    await sesion.commit()
    await sesion.refresh(tarea)
    return tarea
