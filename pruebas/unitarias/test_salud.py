"""Pruebas de la API de salud y de sus respuestas de error."""

from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from aplicacion.rutas import salud as modulo_salud


@pytest.mark.asyncio
async def test_salud_confirma_backend_y_base_datos(
    aplicacion_pruebas: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def comprobar_conexion_simulada(motor_base_datos: object) -> float:
        assert motor_base_datos is aplicacion_pruebas.state.motor_base_datos
        return 1.25

    monkeypatch.setattr(
        modulo_salud,
        "comprobar_conexion_base_datos",
        comprobar_conexion_simulada,
    )
    transporte = httpx.ASGITransport(app=aplicacion_pruebas)

    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        respuesta = await cliente.get("/salud")

    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "aplicacion": "Hermes",
        "version": "0.1.0",
        "estado": "saludable",
        "base_datos": {"estado": "disponible", "tiempo_respuesta_ms": 1.25},
    }
    UUID(respuesta.headers["X-Identificador-Solicitud"])


@pytest.mark.asyncio
async def test_salud_responde_error_controlado_si_mariadb_falla(
    aplicacion_pruebas: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def simular_fallo(_: object) -> float:
        raise ConnectionError("detalle técnico que no debe exponerse")

    monkeypatch.setattr(
        modulo_salud,
        "comprobar_conexion_base_datos",
        simular_fallo,
    )
    transporte = httpx.ASGITransport(app=aplicacion_pruebas)

    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        respuesta = await cliente.get("/salud")

    contenido = respuesta.json()
    assert respuesta.status_code == 503
    assert contenido["codigo"] == "base_datos_no_disponible"
    assert contenido["mensaje"] == "La base de datos no está disponible temporalmente."
    assert "detalle técnico" not in respuesta.text
    assert contenido["identificador_solicitud"] == respuesta.headers["X-Identificador-Solicitud"]


@pytest.mark.asyncio
async def test_ruta_inexistente_responde_en_espanol(aplicacion_pruebas: FastAPI) -> None:
    transporte = httpx.ASGITransport(app=aplicacion_pruebas)

    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        respuesta = await cliente.get("/ruta-inexistente")

    assert respuesta.status_code == 404
    assert respuesta.json()["mensaje"] == "El recurso solicitado no existe."
    assert respuesta.json()["codigo"] == "error_http_404"


@pytest.mark.asyncio
async def test_error_inesperado_no_expone_detalles(aplicacion_pruebas: FastAPI) -> None:
    @aplicacion_pruebas.get("/provocar-error")
    async def provocar_error() -> None:
        raise RuntimeError("secreto que no debe aparecer")

    transporte = httpx.ASGITransport(app=aplicacion_pruebas, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        respuesta = await cliente.get("/provocar-error")

    assert respuesta.status_code == 500
    assert respuesta.json()["codigo"] == "error_interno"
    assert "secreto que no debe aparecer" not in respuesta.text
