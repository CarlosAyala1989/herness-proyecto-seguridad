"""Pruebas de validación independiente para rutas Linux y Windows."""

import pytest

from aplicacion.errores import ErrorRutaRemotaNoValida
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.seguridad.rutas_remotas import (
    ruta_esta_contenida,
    validar_y_normalizar_ruta_remota,
)


@pytest.mark.parametrize(
    ("ruta", "sistema", "esperada"),
    [
        ("/srv/hermes/intercambio/archivo.txt", SistemaOperativo.LINUX, "/srv/hermes/intercambio/archivo.txt"),
        (r"C:\Hermes\Intercambio\archivo.txt", SistemaOperativo.WINDOWS_SERVER, "C:/Hermes/Intercambio/archivo.txt"),
    ],
)
def test_normaliza_rutas_absolutas_por_plataforma(
    ruta: str,
    sistema: SistemaOperativo,
    esperada: str,
) -> None:
    assert validar_y_normalizar_ruta_remota(ruta, sistema) == esperada


@pytest.mark.parametrize(
    ("ruta", "sistema"),
    [
        ("relativa/archivo.txt", SistemaOperativo.LINUX),
        ("/srv/hermes/../secreto", SistemaOperativo.LINUX),
        ("/", SistemaOperativo.LINUX),
        (r"..\secreto", SistemaOperativo.WINDOWS_SERVER),
        (r"C:\Hermes\..\secreto", SistemaOperativo.WINDOWS_SERVER),
        (r"C:\Hermes\CON.txt", SistemaOperativo.WINDOWS_SERVER),
        ("C:/", SistemaOperativo.WINDOWS_SERVER),
        ("//servidor/recurso/archivo", SistemaOperativo.WINDOWS_SERVER),
    ],
)
def test_rechaza_rutas_ambiguas_o_demasiado_amplias(
    ruta: str,
    sistema: SistemaOperativo,
) -> None:
    with pytest.raises(ErrorRutaRemotaNoValida):
        validar_y_normalizar_ruta_remota(ruta, sistema)


def test_contencion_no_confunde_prefijos_linux() -> None:
    assert ruta_esta_contenida(
        "/srv/hermes/intercambio/uno.txt",
        "/srv/hermes/intercambio",
        SistemaOperativo.LINUX,
    )
    assert not ruta_esta_contenida(
        "/srv/hermes/intercambio_privado/uno.txt",
        "/srv/hermes/intercambio",
        SistemaOperativo.LINUX,
    )


def test_contencion_windows_no_distingue_mayusculas() -> None:
    assert ruta_esta_contenida(
        "c:/hermes/intercambio/uno.txt",
        "C:/Hermes/Intercambio",
        SistemaOperativo.WINDOWS_SERVER,
    )
