"""Validación de contratos cerrados para los despliegues."""

import pytest
from pydantic import ValidationError

from aplicacion.errores import ErrorRutaRemotaNoValida
from aplicacion.esquemas.despliegues import (
    CrearPlantillaDespliegue,
    SolicitudDespliegue,
)
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.seguridad.rutas_remotas import validar_y_normalizar_ruta_remota


def test_acepta_plantillas_linux_y_windows_sin_comandos_arbitrarios() -> None:
    linux = CrearPlantillaDespliegue(
        nombre="api_linux",
        sistema_operativo="linux",
        ruta_destino="/srv/hermes/api/aplicacion.bin",
        nombre_servicio="api-hermes.service",
    )
    windows = CrearPlantillaDespliegue(
        nombre="api_windows",
        sistema_operativo="windows_server",
        ruta_destino="C:/Hermes/api/aplicacion.exe",
        nombre_servicio="ServicioHermes",
    )

    assert linux.sistema_operativo is SistemaOperativo.LINUX
    assert windows.sistema_operativo is SistemaOperativo.WINDOWS_SERVER
    assert "comando" not in linux.model_dump()


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("nombre", "api; eliminar"),
        ("nombre_servicio", "api && systemctl stop ssh"),
    ],
)
def test_rechaza_identificadores_de_plantilla_inseguros(campo: str, valor: str) -> None:
    datos = {
        "nombre": "api_segura",
        "sistema_operativo": "linux",
        "ruta_destino": "/srv/hermes/api/aplicacion.bin",
        campo: valor,
    }

    with pytest.raises(ValidationError):
        CrearPlantillaDespliegue.model_validate(datos)


@pytest.mark.parametrize("version", ["", "1.0 estable", "1.0;reiniciar", "../2.0"])
def test_rechaza_versiones_ambiguas(version: str) -> None:
    with pytest.raises(ValidationError):
        SolicitudDespliegue(
            version=version,
            ruta_artefacto="/srv/hermes/artefactos/api.bin",
        )


def test_ruta_de_plantilla_debe_corresponder_a_su_plataforma() -> None:
    with pytest.raises(ErrorRutaRemotaNoValida):
        validar_y_normalizar_ruta_remota("C:/Hermes/api/aplicacion.exe", SistemaOperativo.LINUX)

    with pytest.raises(ErrorRutaRemotaNoValida):
        validar_y_normalizar_ruta_remota(
            "/srv/hermes/api/aplicacion.bin", SistemaOperativo.WINDOWS_SERVER
        )
