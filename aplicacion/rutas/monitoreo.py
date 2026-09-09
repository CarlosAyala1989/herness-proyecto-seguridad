"""Rutas protegidas de configuración y consulta del monitoreo."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from aplicacion.dependencias import SesionActual
from aplicacion.esquemas.monitoreo import (
    ActualizarSuscripcionAlerta,
    AlertaRespuesta,
    ConfiguracionMonitoreoRespuesta,
    ConfigurarMonitoreoServidor,
    DestinoAlertaRespuesta,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import EstadoAlerta
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios.gestor_configuracion_monitoreo import (
    actualizar_suscripcion_alerta,
    guardar_configuracion_monitoreo,
    listar_alertas,
    listar_configuraciones_monitoreo,
    listar_destinos_alertas,
)

enrutador = APIRouter(prefix="/api/v1", tags=["monitoreo"])
UsuarioConsultaMonitoreo = Annotated[
    Usuario,
    Depends(exigir_permiso("consultar_monitoreo")),
]
UsuarioGestionMonitoreo = Annotated[
    Usuario,
    Depends(exigir_permiso("gestionar_monitoreo")),
]
IdentificadorServidor = Annotated[int, Path(gt=0)]
IdentificadorIdentidad = Annotated[int, Path(gt=0)]


@enrutador.get(
    "/monitoreo/configuraciones",
    response_model=list[ConfiguracionMonitoreoRespuesta],
)
async def consultar_configuraciones(
    sesion: SesionActual,
    _: UsuarioConsultaMonitoreo,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConfiguracionMonitoreoRespuesta]:
    """Consulta políticas y servicios críticos configurados."""

    return await listar_configuraciones_monitoreo(
        sesion,
        desplazamiento=desplazamiento,
        limite=limite,
    )


@enrutador.put(
    "/monitoreo/servidores/{id_servidor}",
    response_model=ConfiguracionMonitoreoRespuesta,
)
async def configurar_servidor(
    id_servidor: IdentificadorServidor,
    datos: ConfigurarMonitoreoServidor,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionMonitoreo,
) -> ConfiguracionMonitoreoRespuesta:
    """Crea o reemplaza la política de un servidor existente."""

    return await guardar_configuracion_monitoreo(
        sesion,
        id_servidor,
        datos,
        usuario,
        solicitud,
    )


@enrutador.get(
    "/monitoreo/destinos",
    response_model=list[DestinoAlertaRespuesta],
)
async def consultar_destinos(
    sesion: SesionActual,
    _: UsuarioGestionMonitoreo,
) -> list[DestinoAlertaRespuesta]:
    """Lista identidades elegibles solo para quien puede configurarlas."""

    return await listar_destinos_alertas(sesion)


@enrutador.put(
    "/monitoreo/destinos/{id_identidad_mensajeria}",
    response_model=DestinoAlertaRespuesta,
)
async def configurar_destino(
    id_identidad_mensajeria: IdentificadorIdentidad,
    datos: ActualizarSuscripcionAlerta,
    solicitud: Request,
    sesion: SesionActual,
    usuario: UsuarioGestionMonitoreo,
) -> DestinoAlertaRespuesta:
    """Activa o desactiva alertas para una identidad vinculada."""

    return await actualizar_suscripcion_alerta(
        sesion,
        id_identidad_mensajeria,
        datos.activo,
        usuario,
        solicitud,
    )


@enrutador.get("/alertas", response_model=list[AlertaRespuesta])
async def consultar_alertas(
    sesion: SesionActual,
    _: UsuarioConsultaMonitoreo,
    estado: Annotated[EstadoAlerta | None, Query()] = None,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AlertaRespuesta]:
    """Consulta episodios activos, recuperados o ambos."""

    return await listar_alertas(
        sesion,
        estado=estado,
        desplazamiento=desplazamiento,
        limite=limite,
    )
