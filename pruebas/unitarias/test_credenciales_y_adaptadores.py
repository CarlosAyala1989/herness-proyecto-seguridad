"""Pruebas de referencias SSH y normalización por plataforma."""

import os
import socket
from pathlib import Path

import pytest

from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.adaptadores.windows import AdaptadorWindows
from aplicacion.conexiones.credenciales import ResolvedorCredencialesSSH
from aplicacion.conexiones.errores import (
    ErrorConfiguracionSSH,
    ErrorSistemaOperativoNoCoincide,
)
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.enumeraciones import SistemaOperativo, TipoCredencialConexion


def _resultado(salida: str, codigo_salida: int = 0) -> ResultadoEjecucionRemota:
    return ResultadoEjecucionRemota(
        codigo_salida=codigo_salida,
        salida=salida,
        error="",
        duracion_segundos=0.01,
    )


def test_resuelve_clave_privada_confinada_y_protegida(tmp_path: Path) -> None:
    directorio = tmp_path / "claves"
    directorio.mkdir()
    clave = directorio / "servidor_linux"
    clave.write_text("clave-ficticia-solo-para-probar-la-ruta", encoding="utf-8")
    clave.chmod(0o600)

    credencial = ResolvedorCredencialesSSH(directorio).resolver(
        TipoCredencialConexion.CLAVE_SSH,
        "archivo:servidor_linux",
    )

    assert credencial.claves_cliente == (clave.resolve(),)
    assert credencial.ruta_agente is None


@pytest.mark.parametrize(
    ("referencia", "preparar"),
    [
        ("archivo:../fuera", "fuera"),
        ("archivo:insegura", "permisos_lectura"),
        ("archivo:ejecutable", "permisos_ejecucion"),
        ("agente:desconocido", "ninguno"),
    ],
)
def test_rechaza_referencias_o_permisos_inseguros(
    tmp_path: Path,
    referencia: str,
    preparar: str,
) -> None:
    directorio = tmp_path / "claves"
    directorio.mkdir()
    if preparar == "fuera":
        (tmp_path / "fuera").write_text("dato", encoding="utf-8")
    elif preparar == "permisos_lectura":
        clave = directorio / "insegura"
        clave.write_text("dato", encoding="utf-8")
        clave.chmod(0o644)
    elif preparar == "permisos_ejecucion":
        clave = directorio / "ejecutable"
        clave.write_text("dato", encoding="utf-8")
        clave.chmod(0o700)

    tipo = (
        TipoCredencialConexion.AGENTE_SSH
        if referencia.startswith("agente:")
        else TipoCredencialConexion.CLAVE_SSH
    )
    with pytest.raises(ErrorConfiguracionSSH):
        ResolvedorCredencialesSSH(directorio).resolver(tipo, referencia)


def test_resuelve_agente_ssh_existente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta_socket = tmp_path / "agente.sock"
    socket_agente = socket.socket(socket.AF_UNIX)
    socket_agente.bind(str(ruta_socket))
    monkeypatch.setenv("SSH_AUTH_SOCK", str(ruta_socket))
    try:
        credencial = ResolvedorCredencialesSSH(tmp_path).resolver(
            TipoCredencialConexion.AGENTE_SSH,
            "agente:predeterminado",
        )
    finally:
        socket_agente.close()

    assert credencial.claves_cliente == ()
    assert credencial.ruta_agente == os.fspath(ruta_socket)


def test_adaptador_linux_normaliza_deteccion() -> None:
    detectado = AdaptadorLinux().interpretar_deteccion(
        _resultado("HERMES_SO=linux\nLinux\n6.8.0-79-generic\nubuntu-laboratorio\n")
    )

    assert detectado.sistema_operativo is SistemaOperativo.LINUX
    assert detectado.version == "6.8.0-79-generic"
    assert detectado.nombre_equipo == "ubuntu-laboratorio"


def test_adaptador_windows_normaliza_deteccion() -> None:
    detectado = AdaptadorWindows().interpretar_deteccion(
        _resultado(
            "HERMES_SO=windows_server\r\n"
            "Microsoft Windows Server 2022 Standard\r\n"
            "10.0.20348\r\nSERVIDOR-WIN-01\r\n"
        )
    )

    assert detectado.sistema_operativo is SistemaOperativo.WINDOWS_SERVER
    assert detectado.version == "Microsoft Windows Server 2022 Standard 10.0.20348"
    assert detectado.nombre_equipo == "SERVIDOR-WIN-01"


@pytest.mark.parametrize(
    "adaptador",
    [AdaptadorLinux(), AdaptadorWindows()],
)
def test_adaptadores_rechazan_sistema_no_coincidente(adaptador: object) -> None:
    with pytest.raises(ErrorSistemaOperativoNoCoincide):
        adaptador.interpretar_deteccion(_resultado("salida de otro sistema\n"))
