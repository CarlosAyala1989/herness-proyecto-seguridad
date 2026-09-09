"""Consulta paginada del historial de auditoría."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.modelos.registro_auditoria import RegistroAuditoria


async def listar_registros_auditoria(
    sesion: AsyncSession,
    *,
    desplazamiento: int,
    limite: int,
) -> list[RegistroAuditoria]:
    """Devuelve los registros más recientes primero."""

    consulta = (
        select(RegistroAuditoria)
        .order_by(
            RegistroAuditoria.creado_en.desc(),
            RegistroAuditoria.id_registro_auditoria.desc(),
        )
        .offset(desplazamiento)
        .limit(limite)
    )
    return list((await sesion.scalars(consulta)).all())
