"""Prueba de integración contra la MariaDB local de Hermes."""

import pytest

from aplicacion.base_datos import comprobar_conexion_base_datos, crear_motor_base_datos
from aplicacion.configuracion import Configuracion


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_mariadb_acepta_consulta_real() -> None:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)

    try:
        duracion_ms = await comprobar_conexion_base_datos(motor)
    finally:
        await motor.dispose()

    assert duracion_ms >= 0
