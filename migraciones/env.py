"""Entorno asíncrono de migraciones; Alembic exige el nombre `env.py`."""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from aplicacion.configuracion import obtener_configuracion
from aplicacion.modelos import ModeloBase

configuracion_alembic = context.config
configuracion_hermes = obtener_configuracion()
configuracion_alembic.set_main_option(
    "sqlalchemy.url",
    configuracion_hermes.construir_url_base_datos()
    .render_as_string(hide_password=False)
    .replace("%", "%%"),
)
metadatos_objetivo = ModeloBase.metadata


def ejecutar_migraciones_sin_conexion() -> None:
    """Genera SQL sin abrir una conexión con MariaDB."""

    context.configure(
        url=configuracion_alembic.get_main_option("sqlalchemy.url"),
        target_metadata=metadatos_objetivo,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def ejecutar_migraciones_con_conexion(conexion: Connection) -> None:
    """Ejecuta migraciones dentro de una conexión adaptada por SQLAlchemy."""

    context.configure(
        connection=conexion,
        target_metadata=metadatos_objetivo,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def ejecutar_migraciones_asincronas() -> None:
    """Abre el motor asíncrono requerido por `asyncmy`."""

    motor = async_engine_from_config(
        configuracion_alembic.get_section(configuracion_alembic.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with motor.connect() as conexion:
        await conexion.run_sync(ejecutar_migraciones_con_conexion)
    await motor.dispose()


if context.is_offline_mode():
    ejecutar_migraciones_sin_conexion()
else:
    asyncio.run(ejecutar_migraciones_asincronas())
