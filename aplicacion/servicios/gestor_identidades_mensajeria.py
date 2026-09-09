"""Vinculación y autenticación de identidades de mensajería."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aplicacion.errores import (
    ErrorConflictoDatos,
    ErrorIdentidadMensajeriaNoAutorizada,
    ErrorRecursoNoEncontrado,
)
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    ResultadoAuditoria,
    TipoCanalMensajeria,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.servicios.auditoria import ContextoAuditoria, preparar_registro_auditoria


async def obtener_usuario_por_identidad(
    sesion: AsyncSession,
    canal: TipoCanalMensajeria,
    identificador_externo: str,
    contexto_auditoria: ContextoAuditoria,
) -> Usuario:
    """Resuelve siempre la identidad persistente y rechaza cuentas inactivas."""

    consulta = (
        select(IdentidadMensajeria)
        .where(
            IdentidadMensajeria.canal == canal,
            IdentidadMensajeria.identificador_externo == identificador_externo,
        )
        .options(
            selectinload(IdentidadMensajeria.usuario)
            .selectinload(Usuario.roles)
            .selectinload(Rol.permisos)
        )
    )
    identidad = await sesion.scalar(consulta)
    usuario = identidad.usuario if identidad is not None else None
    if identidad is not None and identidad.activo and usuario is not None and usuario.activo:
        return usuario

    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="autenticar_identidad_mensajeria",
        tipo_recurso=TipoRecursoAuditoria.AUTENTICACION,
        resultado=ResultadoAuditoria.DENEGADO,
        detalle="Intento de acceso desde una identidad de mensajería no autorizada.",
        contexto=contexto_auditoria,
    )
    await sesion.commit()
    raise ErrorIdentidadMensajeriaNoAutorizada()


async def vincular_identidad_telegram(
    sesion: AsyncSession,
    nombre_usuario: str,
    identificador_telegram: int,
    nombre_telegram: str | None = None,
) -> IdentidadMensajeria:
    """Crea o actualiza el único vínculo Telegram de un usuario Hermes."""

    if identificador_telegram <= 0:
        raise ErrorConflictoDatos("El identificador de Telegram debe ser un entero positivo.")
    usuario = await sesion.scalar(
        select(Usuario).where(Usuario.nombre_usuario == nombre_usuario.strip().lower())
    )
    if usuario is None:
        raise ErrorRecursoNoEncontrado("usuario")

    identificador = str(identificador_telegram)
    identidad_en_uso = await sesion.scalar(
        select(IdentidadMensajeria).where(
            IdentidadMensajeria.canal == TipoCanalMensajeria.TELEGRAM,
            IdentidadMensajeria.identificador_externo == identificador,
        )
    )
    if identidad_en_uso is not None and identidad_en_uso.id_usuario != usuario.id_usuario:
        raise ErrorConflictoDatos("El identificador de Telegram ya está vinculado.")

    identidad = await sesion.scalar(
        select(IdentidadMensajeria).where(
            IdentidadMensajeria.id_usuario == usuario.id_usuario,
            IdentidadMensajeria.canal == TipoCanalMensajeria.TELEGRAM,
        )
    )
    if identidad is None:
        identidad = IdentidadMensajeria(
            usuario=usuario,
            canal=TipoCanalMensajeria.TELEGRAM,
            identificador_externo=identificador,
            nombre_externo=nombre_telegram,
            activo=True,
        )
        sesion.add(identidad)
    else:
        identidad.identificador_externo = identificador
        identidad.nombre_externo = nombre_telegram
        identidad.activo = True

    preparar_registro_auditoria(
        sesion,
        usuario=None,
        accion="vincular_identidad_telegram",
        tipo_recurso=TipoRecursoAuditoria.USUARIO,
        id_recurso=usuario.id_usuario,
        resultado=ResultadoAuditoria.EXITO,
        detalle="Identidad de Telegram vinculada mediante administración local.",
        canal=CanalAuditoria.SISTEMA,
    )

    try:
        await sesion.commit()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos("No fue posible vincular la identidad de Telegram.") from None
    await sesion.refresh(identidad)
    return identidad


async def desactivar_identidad_telegram(
    sesion: AsyncSession,
    nombre_usuario: str,
) -> None:
    """Revoca el acceso de Telegram sin desactivar el usuario local."""

    consulta = (
        select(IdentidadMensajeria)
        .join(IdentidadMensajeria.usuario)
        .where(
            Usuario.nombre_usuario == nombre_usuario.strip().lower(),
            IdentidadMensajeria.canal == TipoCanalMensajeria.TELEGRAM,
        )
    )
    identidad = await sesion.scalar(consulta)
    if identidad is None:
        raise ErrorRecursoNoEncontrado("identidad de Telegram")
    identidad.activo = False
    preparar_registro_auditoria(
        sesion,
        usuario=None,
        accion="desactivar_identidad_telegram",
        tipo_recurso=TipoRecursoAuditoria.USUARIO,
        id_recurso=identidad.id_usuario,
        resultado=ResultadoAuditoria.EXITO,
        detalle="Identidad de Telegram desactivada mediante administración local.",
        canal=CanalAuditoria.SISTEMA,
    )
    await sesion.commit()
