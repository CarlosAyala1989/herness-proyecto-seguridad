"""Elementos compartidos por las pruebas."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from aplicacion.configuracion import Configuracion
from aplicacion.principal import crear_aplicacion


@pytest.fixture
def configuracion_pruebas() -> Configuracion:
    """Crea una configuración independiente del archivo local `.env`."""

    return Configuracion(
        entorno="pruebas",
        nivel_log="CRITICAL",
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_solo_para_pruebas",
    )


@pytest.fixture
def aplicacion_pruebas(configuracion_pruebas: Configuracion) -> Iterator[FastAPI]:
    """Construye la API sustituyendo el motor para no abrir conexiones reales."""

    motor_simulado = AsyncMock(spec=AsyncEngine)
    yield crear_aplicacion(configuracion_pruebas, motor_simulado)
