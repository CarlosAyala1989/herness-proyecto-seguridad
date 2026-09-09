"""Pruebas de contraseñas y entradas sensibles del inventario."""

import pytest
from pydantic import ValidationError

from aplicacion.esquemas.inventario import CrearServidor
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.seguridad.contrasenas import (
    generar_hash_contrasena,
    verificar_contrasena,
)


def test_contrasena_se_almacena_como_hash_argon2() -> None:
    contrasena = "frase-segura-de-prueba"

    hash_generado = generar_hash_contrasena(contrasena)

    assert hash_generado != contrasena
    assert hash_generado.startswith("$argon2")
    assert verificar_contrasena(contrasena, hash_generado)
    assert not verificar_contrasena("frase-incorrecta", hash_generado)


@pytest.mark.parametrize(
    "sistema_operativo",
    [SistemaOperativo.LINUX, SistemaOperativo.WINDOWS_SERVER],
)
def test_servidor_admite_linux_y_windows_server(
    sistema_operativo: SistemaOperativo,
) -> None:
    servidor = CrearServidor(
        nombre="servidor-prueba-01",
        direccion="192.0.2.10",
        usuario_conexion="operador",
        sistema_operativo=sistema_operativo,
        referencia_credencial="archivo:claves/servidor-prueba-01",
    )

    assert servidor.sistema_operativo == sistema_operativo


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("nombre", "servidor; systemctl stop ssh"),
        ("direccion", "192.0.2.10 && peligro"),
        ("usuario_conexion", "usuario$(id)"),
        ("referencia_credencial", "../../clave_privada"),
    ],
)
def test_servidor_rechaza_entradas_no_controladas(campo: str, valor: str) -> None:
    datos = {
        "nombre": "servidor-prueba-01",
        "direccion": "192.0.2.10",
        "usuario_conexion": "operador",
        "sistema_operativo": SistemaOperativo.LINUX,
        "referencia_credencial": "archivo:claves/servidor-prueba-01",
    }
    datos[campo] = valor

    with pytest.raises(ValidationError):
        CrearServidor(**datos)
