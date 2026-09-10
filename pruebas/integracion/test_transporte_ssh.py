"""Pruebas reales del cliente AsyncSSH contra un servidor efímero local."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncssh
import pytest

from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.conexiones.errores import (
    ErrorAutenticacionSSH,
    ErrorIdentidadServidorSSH,
    ErrorSalidaSSHExcedida,
    ErrorTiempoEsperaSSH,
)
from aplicacion.conexiones.transporte_ssh import TransporteSSHAsync
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorConflictoDatos, ErrorRutaRemotaNoPermitida
from aplicacion.modelos.enumeraciones import SistemaOperativo, TipoCredencialConexion
from aplicacion.modelos.servidor import Servidor


@dataclass(frozen=True, slots=True)
class LaboratorioSSH:
    """Material efímero confiable para una prueba de transporte."""

    puerto: int
    clave_cliente: Path
    hosts_conocidos: Path
    huella_host: str
    raiz_sftp: Path


async def _atender_proceso(proceso: asyncssh.SSHServerProcess[bytes]) -> None:
    if proceso.command == AdaptadorLinux.comando_deteccion:
        proceso.stdout.write(b"HERMES_SO=linux\nLinux\n6.8.0-prueba\nservidor-ssh-efimero\n")
        proceso.exit(0)
    elif proceso.command == "generar_salida_de_prueba":
        proceso.stdout.write(b"x" * 4_096)
        proceso.exit(0)
    elif proceso.command == "esperar_en_prueba":
        await asyncio.sleep(2)
        proceso.exit(0)
    else:
        proceso.stderr.write(b"operacion de prueba no reconocida")
        proceso.exit(127)


@asynccontextmanager
async def _crear_laboratorio_ssh(tmp_path: Path) -> AsyncIterator[LaboratorioSSH]:
    clave_host = asyncssh.generate_private_key("ssh-ed25519")
    clave_cliente = asyncssh.generate_private_key("ssh-ed25519")

    ruta_host = tmp_path / "clave_host"
    ruta_cliente = tmp_path / "clave_cliente"
    ruta_autorizadas = tmp_path / "claves_autorizadas"
    ruta_hosts = tmp_path / "hosts_conocidos"
    raiz_sftp = tmp_path / "raiz_sftp"
    (raiz_sftp / "intercambio").mkdir(parents=True)
    (raiz_sftp / "fuera").mkdir()
    (raiz_sftp / "fuera" / "secreto.txt").write_text("secreto", encoding="utf-8")
    (raiz_sftp / "intercambio" / "enlace_fuera").symlink_to("../fuera/secreto.txt")
    ruta_host.write_bytes(clave_host.export_private_key())
    ruta_cliente.write_bytes(clave_cliente.export_private_key())
    ruta_autorizadas.write_bytes(clave_cliente.export_public_key())
    ruta_host.chmod(0o600)
    ruta_cliente.chmod(0o600)

    servidor = await asyncssh.listen(
        "127.0.0.1",
        0,
        server_host_keys=[str(ruta_host)],
        authorized_client_keys=str(ruta_autorizadas),
        process_factory=_atender_proceso,
        sftp_factory=lambda canal: asyncssh.SFTPServer(canal, chroot=os.fsencode(raiz_sftp)),
        encoding=None,
    )
    puerto = servidor.get_port()
    clave_publica_host = clave_host.export_public_key().decode("ascii").strip()
    ruta_hosts.write_text(
        f"[127.0.0.1]:{puerto} {clave_publica_host}\n",
        encoding="ascii",
    )
    ruta_hosts.chmod(0o600)
    try:
        yield LaboratorioSSH(
            puerto=puerto,
            clave_cliente=ruta_cliente,
            hosts_conocidos=ruta_hosts,
            huella_host=clave_host.get_fingerprint("sha256"),
            raiz_sftp=raiz_sftp,
        )
    finally:
        servidor.close()
        await servidor.wait_closed()


def _crear_servidor(laboratorio: LaboratorioSSH, huella: str | None = None) -> Servidor:
    return Servidor(
        id_servidor=1,
        nombre="servidor-ssh-efimero",
        direccion="127.0.0.1",
        puerto_ssh=laboratorio.puerto,
        usuario_conexion="usuario_prueba",
        sistema_operativo=SistemaOperativo.LINUX,
        tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
        referencia_credencial="archivo:clave_cliente",
        huella_clave_host=huella or laboratorio.huella_host,
        activo=True,
    )


def _crear_configuracion(
    configuracion_pruebas: Configuracion,
    laboratorio: LaboratorioSSH,
) -> Configuracion:
    return configuracion_pruebas.model_copy(
        update={
            "directorio_credenciales_ssh": laboratorio.clave_cliente.parent,
            "archivo_hosts_conocidos_ssh": laboratorio.hosts_conocidos,
            "tiempo_conexion_ssh_segundos": 1.0,
            "tiempo_autenticacion_ssh_segundos": 1.0,
            "intervalo_mantenimiento_ssh_segundos": 1.0,
        }
    )


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_conecta_verifica_y_detecta_linux(
    tmp_path: Path,
    configuracion_pruebas: Configuracion,
) -> None:
    async with _crear_laboratorio_ssh(tmp_path) as laboratorio:
        transporte = TransporteSSHAsync(
            _crear_servidor(laboratorio),
            _crear_configuracion(configuracion_pruebas, laboratorio),
        )
        assert await transporte.comprobar_disponibilidad()
        resultado = await transporte.ejecutar_comando_controlado(
            AdaptadorLinux.comando_deteccion,
            tiempo_limite_segundos=1,
            limite_salida_bytes=2_048,
        )
        detectado = AdaptadorLinux().interpretar_deteccion(resultado)
        await transporte.cerrar()
        await transporte.cerrar()

    assert resultado.codigo_salida == 0
    assert detectado.sistema_operativo is SistemaOperativo.LINUX
    assert detectado.nombre_equipo == "servidor-ssh-efimero"


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_rechaza_huella_de_host_distinta(
    tmp_path: Path,
    configuracion_pruebas: Configuracion,
) -> None:
    async with _crear_laboratorio_ssh(tmp_path) as laboratorio:
        transporte = TransporteSSHAsync(
            _crear_servidor(laboratorio, "SHA256:huellaDistintaDePruebaSegura000000000000"),
            _crear_configuracion(configuracion_pruebas, laboratorio),
        )
        with pytest.raises(ErrorIdentidadServidorSSH):
            await transporte.comprobar_disponibilidad()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_rechaza_clave_de_usuario_no_autorizada(
    tmp_path: Path,
    configuracion_pruebas: Configuracion,
) -> None:
    async with _crear_laboratorio_ssh(tmp_path) as laboratorio:
        clave_no_autorizada = asyncssh.generate_private_key("ssh-ed25519")
        laboratorio.clave_cliente.write_bytes(clave_no_autorizada.export_private_key())
        laboratorio.clave_cliente.chmod(0o600)
        transporte = TransporteSSHAsync(
            _crear_servidor(laboratorio),
            _crear_configuracion(configuracion_pruebas, laboratorio),
        )
        with pytest.raises(ErrorAutenticacionSSH):
            await transporte.comprobar_disponibilidad()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_interrumpe_salida_y_tiempo_excedidos(
    tmp_path: Path,
    configuracion_pruebas: Configuracion,
) -> None:
    async with _crear_laboratorio_ssh(tmp_path) as laboratorio:
        transporte = TransporteSSHAsync(
            _crear_servidor(laboratorio),
            _crear_configuracion(configuracion_pruebas, laboratorio),
        )
        with pytest.raises(ErrorSalidaSSHExcedida):
            await transporte.ejecutar_comando_controlado(
                "generar_salida_de_prueba",
                tiempo_limite_segundos=1,
                limite_salida_bytes=1_024,
            )
        await transporte.cerrar()

        transporte = TransporteSSHAsync(
            _crear_servidor(laboratorio),
            _crear_configuracion(configuracion_pruebas, laboratorio),
        )
        with pytest.raises(ErrorTiempoEsperaSSH):
            await transporte.ejecutar_comando_controlado(
                "esperar_en_prueba",
                tiempo_limite_segundos=0.05,
                limite_salida_bytes=1_024,
            )
        await transporte.cerrar()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_transfiere_archivo_sftp_con_ruta_y_tamano_controlados(
    tmp_path: Path,
    configuracion_pruebas: Configuracion,
) -> None:
    async with _crear_laboratorio_ssh(tmp_path) as laboratorio:
        transporte = TransporteSSHAsync(
            _crear_servidor(laboratorio),
            _crear_configuracion(configuracion_pruebas, laboratorio),
        )
        reemplazado = await transporte.cargar_archivo(
            "/intercambio/prueba.txt",
            b"contenido seguro de prueba",
            ("/intercambio",),
            2,
            4_096,
            False,
        )
        informacion = await transporte.consultar_informacion_archivo(
            "/intercambio/prueba.txt", ("/intercambio",), 2
        )
        informacion_descarga, contenido = await transporte.descargar_archivo(
            "/intercambio/prueba.txt",
            ("/intercambio",),
            2,
            1_024,
            4_096,
        )
        with pytest.raises(ErrorConflictoDatos):
            await transporte.cargar_archivo(
                "/intercambio/prueba.txt",
                b"otro contenido",
                ("/intercambio",),
                2,
                4_096,
                False,
            )
        reemplazado_confirmado = await transporte.cargar_archivo(
            "/intercambio/prueba.txt",
            b"contenido reemplazado",
            ("/intercambio",),
            2,
            4_096,
            True,
        )
        with pytest.raises(ErrorRutaRemotaNoPermitida):
            await transporte.consultar_informacion_archivo("/fuera.txt", ("/intercambio",), 2)
        with pytest.raises(ErrorRutaRemotaNoPermitida):
            await transporte.consultar_informacion_archivo(
                "/intercambio/enlace_fuera", ("/intercambio",), 2
            )
        await transporte.cerrar()

    assert reemplazado is False
    assert reemplazado_confirmado is True
    assert informacion.tipo == "archivo"
    assert informacion.tamano_bytes == len(b"contenido seguro de prueba")
    assert informacion_descarga.nombre_archivo == "prueba.txt"
    assert contenido == b"contenido seguro de prueba"
    assert (laboratorio.raiz_sftp / "intercambio" / "prueba.txt").read_bytes() == (
        b"contenido reemplazado"
    )
