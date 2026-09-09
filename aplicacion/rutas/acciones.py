"""Rutas del motor de acciones administrativas controladas."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

from aplicacion.dependencias import SesionActual
from aplicacion.esquemas.acciones import (
    AccionDisponibleRespuesta,
    ResultadoAccionMultipleRespuesta,
    ResultadoAccionRespuesta,
    SolicitudEjecucionAccion,
    SolicitudEjecucionMultiple,
)
from aplicacion.seguridad.autenticacion import UsuarioActual
from aplicacion.servicios.gestor_acciones import (
    ejecutar_accion_servidor,
    listar_acciones_para_usuario,
)
from aplicacion.servicios.gestor_acciones_multiples import ejecutar_accion_multiple

enrutador = APIRouter(prefix="/api/v1", tags=["acciones"])
IdentificadorServidor = Annotated[int, Path(gt=0)]
CodigoAccionRuta = Annotated[str, Path(min_length=3, max_length=100, pattern=r"^[a-z_]+$")]


@enrutador.get("/acciones", response_model=list[AccionDisponibleRespuesta])
async def consultar_acciones(usuario: UsuarioActual) -> list[AccionDisponibleRespuesta]:
    """Lista únicamente las acciones que el usuario podría solicitar."""

    return listar_acciones_para_usuario(usuario)


@enrutador.post(
    "/servidores/{id_servidor}/acciones/{codigo_accion}",
    response_model=ResultadoAccionRespuesta,
)
async def ejecutar_accion(
    id_servidor: IdentificadorServidor,
    codigo_accion: CodigoAccionRuta,
    datos: SolicitudEjecucionAccion,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioActual,
) -> ResultadoAccionRespuesta:
    """Autoriza y ejecuta una acción del catálogo cerrado."""

    return await ejecutar_accion_servidor(
        sesion,
        id_servidor,
        codigo_accion,
        datos,
        usuario,
        solicitud,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
    )


@enrutador.post(
    "/acciones-multiples/{codigo_accion}",
    response_model=ResultadoAccionMultipleRespuesta,
)
async def ejecutar_accion_sobre_seleccion(
    codigo_accion: CodigoAccionRuta,
    datos: SolicitudEjecucionMultiple,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioActual,
) -> ResultadoAccionMultipleRespuesta:
    """Ejecuta una acción común con aislamiento y concurrencia acotada."""

    return await ejecutar_accion_multiple(
        sesion,
        solicitud.app.state.fabrica_sesiones,
        codigo_accion,
        datos,
        usuario,
        solicitud,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
    )
