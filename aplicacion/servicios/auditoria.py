"""Registro central de acciones auditables."""

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    ResultadoAuditoria,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.registro_auditoria import RegistroAuditoria


@dataclass(frozen=True, slots=True)
class ContextoAuditoria:
    """Origen normalizado de una operación ajena o interna a HTTP."""

    canal: CanalAuditoria
    direccion_origen: str | None
    identificador_solicitud: str | None


def preparar_registro_auditoria(
    sesion: AsyncSession,
    *,
    usuario: Usuario | None,
    accion: str,
    tipo_recurso: TipoRecursoAuditoria,
    resultado: ResultadoAuditoria,
    solicitud: Request | None = None,
    id_recurso: int | None = None,
    detalle: str | None = None,
    canal: CanalAuditoria = CanalAuditoria.API,
    contexto: ContextoAuditoria | None = None,
) -> RegistroAuditoria:
    """Añade un registro seguro a la misma transacción que la acción."""

    direccion_origen = None
    identificador_solicitud = None
    if solicitud is not None:
        direccion_origen = solicitud.client.host if solicitud.client else None
        identificador_solicitud = getattr(
            solicitud.state,
            "identificador_solicitud",
            None,
        )
    if contexto is not None:
        canal = contexto.canal
        direccion_origen = contexto.direccion_origen
        identificador_solicitud = contexto.identificador_solicitud

    registro = RegistroAuditoria(
        id_usuario=usuario.id_usuario if usuario else None,
        nombre_usuario=usuario.nombre_usuario if usuario else None,
        accion=accion,
        tipo_recurso=tipo_recurso,
        id_recurso=id_recurso,
        resultado=resultado,
        canal=canal,
        detalle=detalle,
        direccion_origen=direccion_origen,
        identificador_solicitud=identificador_solicitud,
    )
    sesion.add(registro)
    return registro
