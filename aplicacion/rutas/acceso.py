"""Rutas protegidas de usuarios, roles y permisos."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status

from aplicacion.dependencias import SesionActual
from aplicacion.esquemas.acceso import (
    ActualizarUsuario,
    CrearUsuario,
    PermisoRespuesta,
    RolRespuesta,
    UsuarioRespuesta,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios import gestor_acceso

enrutador = APIRouter(prefix="/api/v1", tags=["acceso"])
UsuarioGestionAcceso = Annotated[
    Usuario,
    Depends(exigir_permiso("gestionar_acceso")),
]
IdentificadorUsuario = Annotated[int, Path(gt=0)]
IdentificadorRol = Annotated[int, Path(gt=0)]


@enrutador.get("/usuarios", response_model=list[UsuarioRespuesta])
async def consultar_usuarios(
    sesion: SesionActual,
    _: UsuarioGestionAcceso,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[UsuarioRespuesta]:
    """Consulta usuarios autorizados sin devolver hashes."""

    usuarios = await gestor_acceso.listar_usuarios(
        sesion,
        desplazamiento=desplazamiento,
        limite=limite,
    )
    return [UsuarioRespuesta.model_validate(usuario) for usuario in usuarios]


@enrutador.post(
    "/usuarios",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_usuario(
    datos: CrearUsuario,
    solicitud: Request,
    sesion: SesionActual,
    usuario_actor: UsuarioGestionAcceso,
) -> UsuarioRespuesta:
    """Registra un usuario autorizado y asigna roles existentes."""

    usuario = await gestor_acceso.crear_usuario(
        sesion,
        datos,
        usuario_actor,
        solicitud,
    )
    return UsuarioRespuesta.model_validate(usuario)


@enrutador.patch("/usuarios/{id_usuario}", response_model=UsuarioRespuesta)
async def modificar_usuario(
    id_usuario: IdentificadorUsuario,
    datos: ActualizarUsuario,
    solicitud: Request,
    sesion: SesionActual,
    usuario_actor: UsuarioGestionAcceso,
) -> UsuarioRespuesta:
    """Modifica datos o estado de un usuario."""

    usuario = await gestor_acceso.actualizar_usuario(
        sesion,
        id_usuario,
        datos,
        usuario_actor,
        solicitud,
    )
    return UsuarioRespuesta.model_validate(usuario)


@enrutador.get("/roles", response_model=list[RolRespuesta])
async def consultar_roles(
    sesion: SesionActual,
    _: UsuarioGestionAcceso,
) -> list[RolRespuesta]:
    """Consulta roles y permisos concedidos."""

    roles = await gestor_acceso.listar_roles(sesion)
    return [RolRespuesta.model_validate(rol) for rol in roles]


@enrutador.get("/permisos", response_model=list[PermisoRespuesta])
async def consultar_permisos(
    sesion: SesionActual,
    _: UsuarioGestionAcceso,
) -> list[PermisoRespuesta]:
    """Consulta el catálogo persistente de permisos."""

    permisos = await gestor_acceso.listar_permisos(sesion)
    return [PermisoRespuesta.model_validate(permiso) for permiso in permisos]


@enrutador.put(
    "/usuarios/{id_usuario}/roles/{id_rol}",
    response_model=UsuarioRespuesta,
)
async def agregar_rol_al_usuario(
    id_usuario: IdentificadorUsuario,
    id_rol: IdentificadorRol,
    solicitud: Request,
    sesion: SesionActual,
    usuario_actor: UsuarioGestionAcceso,
) -> UsuarioRespuesta:
    """Asigna un rol persistente a un usuario."""

    usuario = await gestor_acceso.asignar_rol(
        sesion,
        id_usuario,
        id_rol,
        usuario_actor,
        solicitud,
    )
    return UsuarioRespuesta.model_validate(usuario)


@enrutador.delete(
    "/usuarios/{id_usuario}/roles/{id_rol}",
    response_model=UsuarioRespuesta,
)
async def quitar_rol_del_usuario(
    id_usuario: IdentificadorUsuario,
    id_rol: IdentificadorRol,
    solicitud: Request,
    sesion: SesionActual,
    usuario_actor: UsuarioGestionAcceso,
) -> UsuarioRespuesta:
    """Retira un rol conservando al menos un administrador activo."""

    usuario = await gestor_acceso.retirar_rol(
        sesion,
        id_usuario,
        id_rol,
        usuario_actor,
        solicitud,
    )
    return UsuarioRespuesta.model_validate(usuario)
