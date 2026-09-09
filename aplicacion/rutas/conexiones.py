"""Rutas protegidas para comprobar conexiones remotas."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from aplicacion.dependencias import SesionActual
from aplicacion.esquemas.conexion import ComprobacionConexionRespuesta
from aplicacion.modelos.acceso import Usuario
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios.gestor_conexiones import comprobar_conexion_servidor

enrutador = APIRouter(prefix="/api/v1", tags=["conexiones"])
UsuarioComprobacionConexion = Annotated[
    Usuario,
    Depends(exigir_permiso("comprobar_conexion")),
]
IdentificadorServidor = Annotated[int, Path(gt=0)]


@enrutador.post(
    "/servidores/{id_servidor}/comprobar-conexion",
    response_model=ComprobacionConexionRespuesta,
)
async def comprobar_conexion(
    id_servidor: IdentificadorServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioComprobacionConexion,
) -> ComprobacionConexionRespuesta:
    """Comprueba identidad, autenticación y plataforma con operaciones fijas."""

    return await comprobar_conexion_servidor(
        sesion,
        id_servidor,
        usuario,
        solicitud,
        solicitud.app.state.fabrica_transporte_remoto,
    )
