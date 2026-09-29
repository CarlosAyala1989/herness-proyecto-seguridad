"""Autenticación HTTP local y comprobación persistente de permisos."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aplicacion.dependencias import obtener_sesion
from aplicacion.errores import ErrorNoAutenticado, ErrorPermisoDenegado
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import ResultadoAuditoria, TipoRecursoAuditoria
from aplicacion.seguridad.contrasenas import (
    ejecutar_verificacion_simulada,
    verificar_contrasena,
)
from aplicacion.servicios.auditoria import ContextoAuditoria, preparar_registro_auditoria

esquema_basico = HTTPBasic(auto_error=False)


async def obtener_usuario_actual(
    solicitud: Request,
    credenciales: Annotated[HTTPBasicCredentials | None, Depends(esquema_basico)],
    sesion: Annotated[AsyncSession, Depends(obtener_sesion)],
) -> Usuario:
    """Autentica al usuario sin distinguir entre nombre y contraseña incorrectos."""

    origen = solicitud.client.host if solicitud.client is not None else "origen_desconocido"
    limitador = solicitud.app.state.limitador_autenticacion
    limitador.comprobar(origen)
    usuario = None
    if credenciales is not None:
        consulta = (
            select(Usuario)
            .where(Usuario.nombre_usuario == credenciales.username.lower())
            .options(selectinload(Usuario.roles).selectinload(Rol.permisos))
        )
        usuario = await sesion.scalar(consulta)

    if credenciales is None:
        ejecutar_verificacion_simulada("")
    elif usuario is None:
        ejecutar_verificacion_simulada(credenciales.password)
    elif usuario.activo and verificar_contrasena(
        credenciales.password,
        usuario.hash_contrasena,
    ):
        limitador.registrar_exito(origen)
        return usuario

    limitador.registrar_fallo(origen)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="autenticar_usuario",
        tipo_recurso=TipoRecursoAuditoria.AUTENTICACION,
        resultado=ResultadoAuditoria.DENEGADO,
        solicitud=solicitud,
        detalle="Intento de autenticación rechazado.",
    )
    await sesion.commit()
    raise ErrorNoAutenticado()


UsuarioActual = Annotated[Usuario, Depends(obtener_usuario_actual)]


async def comprobar_permiso_usuario(
    sesion: AsyncSession,
    solicitud: Request | None,
    usuario: Usuario,
    codigo_permiso: str,
    contexto_auditoria: ContextoAuditoria | None = None,
) -> None:
    """Comprueba un permiso conocido y audita cualquier denegación."""

    permisos = {permiso.codigo for rol in usuario.roles for permiso in rol.permisos}
    if codigo_permiso in permisos:
        return

    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="comprobar_permiso",
        tipo_recurso=TipoRecursoAuditoria.PERMISO,
        resultado=ResultadoAuditoria.DENEGADO,
        solicitud=solicitud,
        detalle=f"Permiso requerido: {codigo_permiso}.",
        contexto=contexto_auditoria,
    )
    await sesion.commit()
    raise ErrorPermisoDenegado(codigo_permiso)


def exigir_permiso(
    codigo_permiso: str,
) -> Callable[..., Awaitable[Usuario]]:
    """Crea una dependencia que exige un permiso persistente concreto."""

    async def comprobar_permiso(
        solicitud: Request,
        usuario: UsuarioActual,
        sesion: Annotated[AsyncSession, Depends(obtener_sesion)],
    ) -> Usuario:
        await comprobar_permiso_usuario(
            sesion,
            solicitud,
            usuario,
            codigo_permiso,
        )
        return usuario

    return comprobar_permiso
