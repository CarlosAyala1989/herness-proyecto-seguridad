"""Creación y comprobación de conexiones con MariaDB."""

from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aplicacion.configuracion import Configuracion


def crear_motor_base_datos(configuracion: Configuracion) -> AsyncEngine:
    """Crea el motor asíncrono compartido por la aplicación."""

    return create_async_engine(
        configuracion.construir_url_base_datos(),
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": configuracion.tiempo_espera_base_datos_segundos,
        },
    )


async def comprobar_conexion_base_datos(motor_base_datos: AsyncEngine) -> float:
    """Ejecuta una consulta mínima y devuelve su duración en milisegundos."""

    inicio = perf_counter()
    async with motor_base_datos.connect() as conexion:
        await conexion.execute(text("SELECT 1"))
    return round((perf_counter() - inicio) * 1000, 2)
