"""Casos de uso persistentes del inventario de servidores."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aplicacion.errores import ErrorConflictoDatos, ErrorRecursoNoEncontrado
from aplicacion.esquemas.inventario import (
    ActualizarGrupo,
    ActualizarServidor,
    CrearGrupo,
    CrearServidor,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import ResultadoAuditoria, TipoRecursoAuditoria
from aplicacion.modelos.grupo_servidor import GrupoServidor
from aplicacion.modelos.servidor import Servidor
from aplicacion.servicios.auditoria import preparar_registro_auditoria
from aplicacion.servicios.persistencia import confirmar_transaccion


async def obtener_servidor(sesion: AsyncSession, id_servidor: int) -> Servidor:
    """Obtiene un servidor con sus grupos o devuelve un error uniforme."""

    consulta = (
        select(Servidor)
        .where(Servidor.id_servidor == id_servidor)
        .options(selectinload(Servidor.grupos))
    )
    servidor = await sesion.scalar(consulta)
    if servidor is None:
        raise ErrorRecursoNoEncontrado("servidor")
    return servidor


async def listar_servidores(
    sesion: AsyncSession,
    *,
    desplazamiento: int,
    limite: int,
    solo_activos: bool = False,
) -> list[Servidor]:
    """Lista servidores sin imponer un máximo fijo al inventario."""

    consulta = select(Servidor).options(selectinload(Servidor.grupos))
    if solo_activos:
        consulta = consulta.where(Servidor.activo.is_(True))
    consulta = consulta.order_by(Servidor.nombre).offset(desplazamiento).limit(limite)
    return list((await sesion.scalars(consulta)).all())


async def crear_servidor(
    sesion: AsyncSession,
    datos: CrearServidor,
    usuario: Usuario,
    solicitud: Request,
) -> Servidor:
    """Registra un servidor sin almacenar el material secreto referenciado."""

    servidor = Servidor(**datos.model_dump(), grupos=[])
    sesion.add(servidor)
    try:
        await sesion.flush()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos("Ya existe un servidor con ese nombre o destino.") from None
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="crear_servidor",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=servidor.id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Servidor incorporado al inventario.",
    )
    await confirmar_transaccion(sesion, "Ya existe un servidor con ese nombre o destino.")
    return servidor


async def actualizar_servidor(
    sesion: AsyncSession,
    id_servidor: int,
    datos: ActualizarServidor,
    usuario: Usuario,
    solicitud: Request,
) -> Servidor:
    """Actualiza únicamente los campos recibidos y validados."""

    servidor = await obtener_servidor(sesion, id_servidor)
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise ErrorConflictoDatos("Debe proporcionar al menos un campo para actualizar.")
    for campo, valor in cambios.items():
        setattr(servidor, campo, valor)

    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="actualizar_servidor",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=servidor.id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Datos del servidor actualizados.",
    )
    await confirmar_transaccion(sesion, "El cambio entra en conflicto con otro servidor.")
    await sesion.refresh(servidor, attribute_names=["actualizado_en"])
    return servidor


async def eliminar_servidor(
    sesion: AsyncSession,
    id_servidor: int,
    usuario: Usuario,
    solicitud: Request,
) -> None:
    """Elimina un servidor y conserva evidencia de la acción."""

    servidor = await obtener_servidor(sesion, id_servidor)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="eliminar_servidor",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=servidor.id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Servidor eliminado del inventario: {servidor.nombre}.",
    )
    await sesion.delete(servidor)
    await confirmar_transaccion(sesion, "No fue posible eliminar el servidor.")


async def obtener_grupo(sesion: AsyncSession, id_grupo: int) -> GrupoServidor:
    """Obtiene un grupo y sus servidores."""

    consulta = (
        select(GrupoServidor)
        .where(GrupoServidor.id_grupo == id_grupo)
        .options(selectinload(GrupoServidor.servidores))
    )
    grupo = await sesion.scalar(consulta)
    if grupo is None:
        raise ErrorRecursoNoEncontrado("grupo")
    return grupo


async def listar_grupos(
    sesion: AsyncSession,
    *,
    desplazamiento: int,
    limite: int,
) -> list[GrupoServidor]:
    """Lista grupos junto con los servidores asociados."""

    consulta = (
        select(GrupoServidor)
        .options(selectinload(GrupoServidor.servidores))
        .order_by(GrupoServidor.nombre)
        .offset(desplazamiento)
        .limit(limite)
    )
    return list((await sesion.scalars(consulta)).all())


async def crear_grupo(
    sesion: AsyncSession,
    datos: CrearGrupo,
    usuario: Usuario,
    solicitud: Request,
) -> GrupoServidor:
    """Registra un grupo vacío."""

    grupo = GrupoServidor(**datos.model_dump(), servidores=[])
    sesion.add(grupo)
    try:
        await sesion.flush()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos("Ya existe un grupo con ese nombre.") from None
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="crear_grupo",
        tipo_recurso=TipoRecursoAuditoria.GRUPO,
        id_recurso=grupo.id_grupo,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Grupo incorporado al inventario.",
    )
    await confirmar_transaccion(sesion, "Ya existe un grupo con ese nombre.")
    return grupo


async def actualizar_grupo(
    sesion: AsyncSession,
    id_grupo: int,
    datos: ActualizarGrupo,
    usuario: Usuario,
    solicitud: Request,
) -> GrupoServidor:
    """Actualiza los campos recibidos de un grupo."""

    grupo = await obtener_grupo(sesion, id_grupo)
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise ErrorConflictoDatos("Debe proporcionar al menos un campo para actualizar.")
    for campo, valor in cambios.items():
        setattr(grupo, campo, valor)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="actualizar_grupo",
        tipo_recurso=TipoRecursoAuditoria.GRUPO,
        id_recurso=grupo.id_grupo,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Datos del grupo actualizados.",
    )
    await confirmar_transaccion(sesion, "El nombre del grupo ya está en uso.")
    await sesion.refresh(grupo, attribute_names=["actualizado_en"])
    return grupo


async def eliminar_grupo(
    sesion: AsyncSession,
    id_grupo: int,
    usuario: Usuario,
    solicitud: Request,
) -> None:
    """Elimina un grupo sin eliminar sus servidores."""

    grupo = await obtener_grupo(sesion, id_grupo)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="eliminar_grupo",
        tipo_recurso=TipoRecursoAuditoria.GRUPO,
        id_recurso=grupo.id_grupo,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Grupo eliminado: {grupo.nombre}.",
    )
    await sesion.delete(grupo)
    await confirmar_transaccion(sesion, "No fue posible eliminar el grupo.")


async def asociar_servidor_grupo(
    sesion: AsyncSession,
    id_grupo: int,
    id_servidor: int,
    usuario: Usuario,
    solicitud: Request,
) -> GrupoServidor:
    """Asocia un servidor y evita duplicados por la clave primaria compuesta."""

    grupo = await obtener_grupo(sesion, id_grupo)
    servidor = await obtener_servidor(sesion, id_servidor)
    if any(item.id_servidor == id_servidor for item in grupo.servidores):
        raise ErrorConflictoDatos("El servidor ya pertenece al grupo.")
    grupo.servidores.append(servidor)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="asociar_servidor_grupo",
        tipo_recurso=TipoRecursoAuditoria.ASOCIACION,
        id_recurso=id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Servidor asociado al grupo con identificador {id_grupo}.",
    )
    await confirmar_transaccion(sesion, "No fue posible asociar el servidor al grupo.")
    return grupo


async def desasociar_servidor_grupo(
    sesion: AsyncSession,
    id_grupo: int,
    id_servidor: int,
    usuario: Usuario,
    solicitud: Request,
) -> None:
    """Elimina exclusivamente la relación entre servidor y grupo."""

    grupo = await obtener_grupo(sesion, id_grupo)
    servidor = next(
        (item for item in grupo.servidores if item.id_servidor == id_servidor),
        None,
    )
    if servidor is None:
        raise ErrorRecursoNoEncontrado("asociación de servidor y grupo")
    grupo.servidores.remove(servidor)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="desasociar_servidor_grupo",
        tipo_recurso=TipoRecursoAuditoria.ASOCIACION,
        id_recurso=id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Servidor retirado del grupo con identificador {id_grupo}.",
    )
    await confirmar_transaccion(sesion, "No fue posible retirar el servidor del grupo.")
