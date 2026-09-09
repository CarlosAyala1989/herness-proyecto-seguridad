"""Casos de uso para usuarios, roles y permisos persistentes."""

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aplicacion.errores import ErrorConflictoDatos, ErrorRecursoNoEncontrado
from aplicacion.esquemas.acceso import ActualizarUsuario, CrearUsuario
from aplicacion.modelos.acceso import Permiso, Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    ResultadoAuditoria,
    TipoRecursoAuditoria,
)
from aplicacion.seguridad.contrasenas import generar_hash_contrasena
from aplicacion.servicios.auditoria import preparar_registro_auditoria
from aplicacion.servicios.persistencia import confirmar_transaccion


def _consulta_usuario():
    return select(Usuario).options(selectinload(Usuario.roles).selectinload(Rol.permisos))


async def obtener_usuario(sesion: AsyncSession, id_usuario: int) -> Usuario:
    """Obtiene un usuario con todos sus roles y permisos."""

    usuario = await sesion.scalar(_consulta_usuario().where(Usuario.id_usuario == id_usuario))
    if usuario is None:
        raise ErrorRecursoNoEncontrado("usuario")
    return usuario


async def listar_usuarios(
    sesion: AsyncSession,
    *,
    desplazamiento: int,
    limite: int,
) -> list[Usuario]:
    """Lista usuarios sin exponer hashes de contraseña."""

    consulta = (
        _consulta_usuario().order_by(Usuario.nombre_usuario).offset(desplazamiento).limit(limite)
    )
    return list((await sesion.scalars(consulta)).all())


async def crear_usuario(
    sesion: AsyncSession,
    datos: CrearUsuario,
    usuario_actor: Usuario | None,
    solicitud: Request | None,
    canal: CanalAuditoria = CanalAuditoria.API,
) -> Usuario:
    """Crea un usuario y transforma inmediatamente su contraseña en Argon2."""

    roles = list(
        (
            await sesion.scalars(
                select(Rol)
                .where(Rol.id_rol.in_(datos.ids_roles))
                .options(selectinload(Rol.permisos))
            )
        ).all()
    )
    if len(roles) != len(datos.ids_roles):
        raise ErrorRecursoNoEncontrado("rol")

    usuario = Usuario(
        nombre_usuario=datos.nombre_usuario,
        nombre_mostrar=datos.nombre_mostrar.strip(),
        hash_contrasena=generar_hash_contrasena(datos.contrasena.get_secret_value()),
        activo=True,
        roles=roles,
    )
    sesion.add(usuario)
    try:
        await sesion.flush()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos("El nombre de usuario ya está registrado.") from None
    preparar_registro_auditoria(
        sesion,
        usuario=usuario_actor,
        accion="crear_usuario",
        tipo_recurso=TipoRecursoAuditoria.USUARIO,
        id_recurso=usuario.id_usuario,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Usuario autorizado creado: {usuario.nombre_usuario}.",
        canal=canal,
    )
    await confirmar_transaccion(sesion, "El nombre de usuario ya está registrado.")
    return usuario


async def actualizar_usuario(
    sesion: AsyncSession,
    id_usuario: int,
    datos: ActualizarUsuario,
    usuario_actor: Usuario,
    solicitud: Request,
) -> Usuario:
    """Actualiza un usuario y evita que el actor se desactive a sí mismo."""

    usuario = await obtener_usuario(sesion, id_usuario)
    cambios = datos.model_dump(exclude_unset=True)
    if not cambios:
        raise ErrorConflictoDatos("Debe proporcionar al menos un campo para actualizar.")
    if id_usuario == usuario_actor.id_usuario and cambios.get("activo") is False:
        raise ErrorConflictoDatos("No puede desactivar su propio usuario.")

    contrasena = cambios.pop("contrasena", None)
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor.strip() if isinstance(valor, str) else valor)
    if contrasena is not None:
        usuario.hash_contrasena = generar_hash_contrasena(contrasena.get_secret_value())

    preparar_registro_auditoria(
        sesion,
        usuario=usuario_actor,
        accion="actualizar_usuario",
        tipo_recurso=TipoRecursoAuditoria.USUARIO,
        id_recurso=usuario.id_usuario,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Datos del usuario actualizados.",
    )
    await confirmar_transaccion(sesion, "No fue posible actualizar el usuario.")
    await sesion.refresh(usuario, attribute_names=["actualizado_en"])
    return usuario


async def listar_roles(sesion: AsyncSession) -> list[Rol]:
    """Lista los roles y sus permisos persistentes."""

    consulta = select(Rol).options(selectinload(Rol.permisos)).order_by(Rol.nombre)
    return list((await sesion.scalars(consulta)).all())


async def listar_permisos(sesion: AsyncSession) -> list[Permiso]:
    """Lista las capacidades atómicas disponibles."""

    return list((await sesion.scalars(select(Permiso).order_by(Permiso.codigo))).all())


async def asignar_rol(
    sesion: AsyncSession,
    id_usuario: int,
    id_rol: int,
    usuario_actor: Usuario,
    solicitud: Request,
) -> Usuario:
    """Asigna un rol evitando relaciones duplicadas."""

    usuario = await obtener_usuario(sesion, id_usuario)
    rol = await sesion.get(Rol, id_rol, options=[selectinload(Rol.permisos)])
    if rol is None:
        raise ErrorRecursoNoEncontrado("rol")
    if any(item.id_rol == id_rol for item in usuario.roles):
        raise ErrorConflictoDatos("El usuario ya tiene asignado ese rol.")
    usuario.roles.append(rol)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario_actor,
        accion="asignar_rol_usuario",
        tipo_recurso=TipoRecursoAuditoria.ROL,
        id_recurso=id_rol,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Rol asignado al usuario con identificador {id_usuario}.",
    )
    await confirmar_transaccion(sesion, "No fue posible asignar el rol.")
    return usuario


async def retirar_rol(
    sesion: AsyncSession,
    id_usuario: int,
    id_rol: int,
    usuario_actor: Usuario,
    solicitud: Request,
) -> Usuario:
    """Retira un rol sin dejar el sistema sin administradores activos."""

    usuario = await obtener_usuario(sesion, id_usuario)
    rol = next((item for item in usuario.roles if item.id_rol == id_rol), None)
    if rol is None:
        raise ErrorRecursoNoEncontrado("asignación de rol")

    if rol.nombre == "administrador" and usuario.activo:
        consulta = (
            select(func.count(Usuario.id_usuario))
            .join(Usuario.roles)
            .where(Usuario.activo.is_(True), Rol.nombre == "administrador")
        )
        cantidad_administradores = await sesion.scalar(consulta)
        if cantidad_administradores is not None and cantidad_administradores <= 1:
            raise ErrorConflictoDatos("No se puede retirar el último administrador activo.")

    usuario.roles.remove(rol)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario_actor,
        accion="retirar_rol_usuario",
        tipo_recurso=TipoRecursoAuditoria.ROL,
        id_recurso=id_rol,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle=f"Rol retirado del usuario con identificador {id_usuario}.",
    )
    await confirmar_transaccion(sesion, "No fue posible retirar el rol.")
    return usuario
