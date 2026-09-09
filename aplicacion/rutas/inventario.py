"""Rutas protegidas del inventario de servidores y grupos."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from aplicacion.dependencias import SesionActual
from aplicacion.errores import ErrorConfirmacionRequerida
from aplicacion.esquemas.inventario import (
    ActualizarGrupo,
    ActualizarServidor,
    CrearGrupo,
    CrearServidor,
    GrupoDetalle,
    ServidorDetalle,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios import gestor_inventario

enrutador = APIRouter(prefix="/api/v1", tags=["inventario"])
UsuarioConsultaInventario = Annotated[
    Usuario,
    Depends(exigir_permiso("consultar_inventario")),
]
UsuarioGestionInventario = Annotated[
    Usuario,
    Depends(exigir_permiso("gestionar_inventario")),
]
IdentificadorServidor = Annotated[int, Path(gt=0)]
IdentificadorGrupo = Annotated[int, Path(gt=0)]


@enrutador.get("/servidores", response_model=list[ServidorDetalle])
async def consultar_servidores(
    sesion: SesionActual,
    _: UsuarioConsultaInventario,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ServidorDetalle]:
    """Consulta una página del inventario sin límite fijo de servidores."""

    servidores = await gestor_inventario.listar_servidores(
        sesion,
        desplazamiento=desplazamiento,
        limite=limite,
    )
    return [ServidorDetalle.model_validate(servidor) for servidor in servidores]


@enrutador.post(
    "/servidores",
    response_model=ServidorDetalle,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_servidor(
    datos: CrearServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
) -> ServidorDetalle:
    """Registra un destino Linux o Windows Server validado."""

    servidor = await gestor_inventario.crear_servidor(
        sesion,
        datos,
        usuario,
        solicitud,
    )
    return ServidorDetalle.model_validate(servidor)


@enrutador.get("/servidores/{id_servidor}", response_model=ServidorDetalle)
async def consultar_servidor(
    id_servidor: IdentificadorServidor,
    sesion: SesionActual,
    _: UsuarioConsultaInventario,
) -> ServidorDetalle:
    """Consulta un servidor concreto."""

    servidor = await gestor_inventario.obtener_servidor(sesion, id_servidor)
    return ServidorDetalle.model_validate(servidor)


@enrutador.patch("/servidores/{id_servidor}", response_model=ServidorDetalle)
async def modificar_servidor(
    id_servidor: IdentificadorServidor,
    datos: ActualizarServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
) -> ServidorDetalle:
    """Modifica parcialmente un servidor registrado."""

    servidor = await gestor_inventario.actualizar_servidor(
        sesion,
        id_servidor,
        datos,
        usuario,
        solicitud,
    )
    return ServidorDetalle.model_validate(servidor)


@enrutador.delete("/servidores/{id_servidor}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_servidor(
    id_servidor: IdentificadorServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
    confirmar: Annotated[bool, Query()] = False,
) -> Response:
    """Elimina un servidor únicamente con confirmación explícita."""

    if not confirmar:
        raise ErrorConfirmacionRequerida()
    await gestor_inventario.eliminar_servidor(
        sesion,
        id_servidor,
        usuario,
        solicitud,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador.get("/grupos", response_model=list[GrupoDetalle])
async def consultar_grupos(
    sesion: SesionActual,
    _: UsuarioConsultaInventario,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[GrupoDetalle]:
    """Consulta los grupos y sus miembros."""

    grupos = await gestor_inventario.listar_grupos(
        sesion,
        desplazamiento=desplazamiento,
        limite=limite,
    )
    return [GrupoDetalle.model_validate(grupo) for grupo in grupos]


@enrutador.post(
    "/grupos",
    response_model=GrupoDetalle,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_grupo(
    datos: CrearGrupo,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
) -> GrupoDetalle:
    """Crea un grupo de servidores vacío."""

    grupo = await gestor_inventario.crear_grupo(sesion, datos, usuario, solicitud)
    return GrupoDetalle.model_validate(grupo)


@enrutador.get("/grupos/{id_grupo}", response_model=GrupoDetalle)
async def consultar_grupo(
    id_grupo: IdentificadorGrupo,
    sesion: SesionActual,
    _: UsuarioConsultaInventario,
) -> GrupoDetalle:
    """Consulta un grupo concreto."""

    grupo = await gestor_inventario.obtener_grupo(sesion, id_grupo)
    return GrupoDetalle.model_validate(grupo)


@enrutador.patch("/grupos/{id_grupo}", response_model=GrupoDetalle)
async def modificar_grupo(
    id_grupo: IdentificadorGrupo,
    datos: ActualizarGrupo,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
) -> GrupoDetalle:
    """Modifica parcialmente un grupo."""

    grupo = await gestor_inventario.actualizar_grupo(
        sesion,
        id_grupo,
        datos,
        usuario,
        solicitud,
    )
    return GrupoDetalle.model_validate(grupo)


@enrutador.delete("/grupos/{id_grupo}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_grupo(
    id_grupo: IdentificadorGrupo,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
    confirmar: Annotated[bool, Query()] = False,
) -> Response:
    """Elimina un grupo sin eliminar sus servidores."""

    if not confirmar:
        raise ErrorConfirmacionRequerida()
    await gestor_inventario.eliminar_grupo(
        sesion,
        id_grupo,
        usuario,
        solicitud,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@enrutador.put(
    "/grupos/{id_grupo}/servidores/{id_servidor}",
    response_model=GrupoDetalle,
)
async def agregar_servidor_al_grupo(
    id_grupo: IdentificadorGrupo,
    id_servidor: IdentificadorServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
) -> GrupoDetalle:
    """Asocia un servidor existente con un grupo existente."""

    grupo = await gestor_inventario.asociar_servidor_grupo(
        sesion,
        id_grupo,
        id_servidor,
        usuario,
        solicitud,
    )
    return GrupoDetalle.model_validate(grupo)


@enrutador.delete(
    "/grupos/{id_grupo}/servidores/{id_servidor}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def retirar_servidor_del_grupo(
    id_grupo: IdentificadorGrupo,
    id_servidor: IdentificadorServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionInventario,
) -> Response:
    """Retira la asociación sin eliminar ninguna de las entidades."""

    await gestor_inventario.desasociar_servidor_grupo(
        sesion,
        id_grupo,
        id_servidor,
        usuario,
        solicitud,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
