"""API protegida de plantillas, aplicaciones y despliegues."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status

from aplicacion.dependencias import SesionActual
from aplicacion.esquemas.despliegues import (
    AplicacionAdministradaRespuesta,
    CrearAplicacionAdministrada,
    CrearPlantillaDespliegue,
    DespliegueAplicacionRespuesta,
    EstadoAplicacionRespuesta,
    PlantillaDespliegueRespuesta,
    SolicitudDespliegue,
    SolicitudReversion,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios import gestor_despliegues

enrutador = APIRouter(prefix="/api/v1", tags=["despliegues"])
IdentificadorAplicacion = Annotated[int, Path(gt=0)]
IdentificadorDespliegue = Annotated[int, Path(gt=0)]
UsuarioConsulta = Annotated[Usuario, Depends(exigir_permiso("consultar_aplicaciones"))]
UsuarioGestion = Annotated[Usuario, Depends(exigir_permiso("gestionar_aplicaciones"))]
UsuarioDespliegue = Annotated[Usuario, Depends(exigir_permiso("desplegar_aplicaciones"))]
UsuarioReversion = Annotated[Usuario, Depends(exigir_permiso("revertir_despliegues"))]


@enrutador.post(
    "/plantillas-despliegue",
    response_model=PlantillaDespliegueRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_plantilla(
    datos: CrearPlantillaDespliegue,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestion,
) -> PlantillaDespliegueRespuesta:
    plantilla = await gestor_despliegues.crear_plantilla(sesion, datos, usuario, solicitud)
    return PlantillaDespliegueRespuesta.model_validate(plantilla)


@enrutador.get("/plantillas-despliegue", response_model=list[PlantillaDespliegueRespuesta])
async def consultar_plantillas(
    sesion: SesionActual,
    _: UsuarioConsulta,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PlantillaDespliegueRespuesta]:
    plantillas = await gestor_despliegues.listar_plantillas(
        sesion, desplazamiento=desplazamiento, limite=limite
    )
    return [PlantillaDespliegueRespuesta.model_validate(item) for item in plantillas]


@enrutador.post(
    "/aplicaciones-administradas",
    response_model=AplicacionAdministradaRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_aplicacion(
    datos: CrearAplicacionAdministrada,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestion,
) -> AplicacionAdministradaRespuesta:
    aplicacion = await gestor_despliegues.crear_aplicacion(sesion, datos, usuario, solicitud)
    return AplicacionAdministradaRespuesta.model_validate(aplicacion)


@enrutador.get("/aplicaciones-administradas", response_model=list[AplicacionAdministradaRespuesta])
async def consultar_aplicaciones(
    sesion: SesionActual,
    _: UsuarioConsulta,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AplicacionAdministradaRespuesta]:
    aplicaciones = await gestor_despliegues.listar_aplicaciones(
        sesion, desplazamiento=desplazamiento, limite=limite
    )
    return [AplicacionAdministradaRespuesta.model_validate(item) for item in aplicaciones]


@enrutador.get(
    "/aplicaciones-administradas/{id_aplicacion}/estado",
    response_model=EstadoAplicacionRespuesta,
)
async def consultar_estado(
    id_aplicacion: IdentificadorAplicacion,
    solicitud: Request,
    sesion: SesionActual,
    _: UsuarioConsulta,
) -> EstadoAplicacionRespuesta:
    return await gestor_despliegues.consultar_estado_aplicacion(
        sesion,
        id_aplicacion,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
    )


@enrutador.get(
    "/aplicaciones-administradas/{id_aplicacion}/despliegues",
    response_model=list[DespliegueAplicacionRespuesta],
)
async def consultar_historial(
    id_aplicacion: IdentificadorAplicacion,
    sesion: SesionActual,
    _: UsuarioConsulta,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DespliegueAplicacionRespuesta]:
    despliegues = await gestor_despliegues.listar_despliegues(
        sesion,
        id_aplicacion,
        desplazamiento=desplazamiento,
        limite=limite,
    )
    return [DespliegueAplicacionRespuesta.model_validate(item) for item in despliegues]


@enrutador.post(
    "/aplicaciones-administradas/{id_aplicacion}/despliegues",
    response_model=DespliegueAplicacionRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def ejecutar_despliegue(
    id_aplicacion: IdentificadorAplicacion,
    datos: SolicitudDespliegue,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioDespliegue,
) -> DespliegueAplicacionRespuesta:
    despliegue = await gestor_despliegues.desplegar_aplicacion(
        sesion,
        id_aplicacion,
        datos,
        usuario,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
        solicitud,
    )
    return DespliegueAplicacionRespuesta.model_validate(despliegue)


@enrutador.post(
    "/aplicaciones-administradas/{id_aplicacion}/despliegues/{id_despliegue}/revertir",
    response_model=DespliegueAplicacionRespuesta,
)
async def ejecutar_reversion(
    id_aplicacion: IdentificadorAplicacion,
    id_despliegue: IdentificadorDespliegue,
    datos: SolicitudReversion,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioReversion,
) -> DespliegueAplicacionRespuesta:
    despliegue = await gestor_despliegues.revertir_despliegue(
        sesion,
        id_aplicacion,
        id_despliegue,
        usuario,
        solicitud.app.state.fabrica_transporte_remoto,
        solicitud.app.state.configuracion,
        datos.confirmar,
        solicitud,
    )
    return DespliegueAplicacionRespuesta.model_validate(despliegue)
