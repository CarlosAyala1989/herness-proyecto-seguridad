"""Utilidades comunes para confirmar transacciones controladas."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.errores import ErrorConflictoDatos


async def confirmar_transaccion(
    sesion: AsyncSession,
    mensaje_conflicto: str,
) -> None:
    """Confirma una transacción y oculta detalles internos de integridad."""

    try:
        await sesion.commit()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos(mensaje_conflicto) from None
