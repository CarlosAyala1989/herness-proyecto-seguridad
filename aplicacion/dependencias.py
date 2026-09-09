"""Dependencias compartidas por las rutas HTTP."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def obtener_sesion(solicitud: Request) -> AsyncIterator[AsyncSession]:
    """Entrega una sesión exclusiva para la solicitud y garantiza su cierre."""

    async with solicitud.app.state.fabrica_sesiones() as sesion:
        yield sesion


SesionActual = Annotated[AsyncSession, Depends(obtener_sesion)]
