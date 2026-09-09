"""Pruebas de carga y protección de la configuración."""

import pytest
from pydantic import ValidationError

from aplicacion.configuracion import Configuracion


def test_construye_url_sin_exponer_contrasena() -> None:
    configuracion = Configuracion(
        nombre_base_datos="hermes",
        usuario_base_datos="usuario_prueba",
        contrasena_base_datos="secreto_con_caracteres@:/",
    )

    url = configuracion.construir_url_base_datos()

    assert url.drivername == "mysql+asyncmy"
    assert url.database == "hermes"
    assert url.port == 3378
    assert url.password == "secreto_con_caracteres@:/"
    assert "secreto_con_caracteres" not in str(url)
    assert "***" in str(url)
    assert "secreto_con_caracteres" not in repr(configuracion)


@pytest.mark.parametrize("puerto", [0, 65536])
def test_rechaza_puerto_base_datos_fuera_de_rango(puerto: int) -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes",
            usuario_base_datos="usuario_prueba",
            contrasena_base_datos="contrasena_prueba",
            puerto_base_datos=puerto,
        )


def test_rechaza_nombre_base_datos_con_caracteres_no_permitidos() -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes; DROP DATABASE hermes",
            usuario_base_datos="usuario_prueba",
            contrasena_base_datos="contrasena_prueba",
        )


def test_rechaza_limites_ssh_desactivados() -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes",
            usuario_base_datos="usuario_prueba",
            contrasena_base_datos="contrasena_prueba",
            tiempo_conexion_ssh_segundos=0,
            limite_salida_ssh_bytes=0,
        )


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("max_concurrencia_acciones_multiples", 0),
        ("max_concurrencia_acciones_multiples", 33),
        ("max_servidores_accion_multiple", 0),
        ("max_servidores_accion_multiple", 501),
        ("tiempo_limite_accion_multiple_segundos", 0),
        ("tiempo_limite_accion_multiple_segundos", 601),
    ],
)
def test_rechaza_limites_inseguros_para_acciones_multiples(
    campo: str,
    valor: int,
) -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes",
            usuario_base_datos="usuario_prueba",
            contrasena_base_datos="contrasena_prueba",
            **{campo: valor},
        )
