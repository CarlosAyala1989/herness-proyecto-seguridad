"""Ruta protegida de consulta de auditoría."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from aplicacion.dependencias import SesionActual
from aplicacion.esquemas.auditoria import RegistroAuditoriaRespuesta
from aplicacion.modelos.acceso import Usuario
from aplicacion.seguridad.autenticacion import exigir_permiso
from aplicacion.servicios.consulta_auditoria import listar_registros_auditoria

enrutador = APIRouter(prefix="/api/v1", tags=["auditoría"])
UsuarioConsultaAuditoria = Annotated[
    Usuario,
    Depends(exigir_permiso("consultar_auditoria")),
]


@enrutador.get("/auditoria", response_model=list[RegistroAuditoriaRespuesta])
async def consultar_auditoria(
    sesion: SesionActual,
    _: UsuarioConsultaAuditoria,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RegistroAuditoriaRespuesta]:
    """Consulta registros recientes de forma paginada."""

    registros = await listar_registros_auditoria(
        sesion,
        desplazamiento=desplazamiento,
        limite=limite,
    )
    return [RegistroAuditoriaRespuesta.model_validate(registro) for registro in registros]
