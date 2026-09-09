"""Implementación acotada y estricta del transporte mediante AsyncSSH."""

import asyncio
import hmac
import os
import stat
from pathlib import Path
from time import perf_counter
from types import TracebackType

import asyncssh

from aplicacion.conexiones.credenciales import ResolvedorCredencialesSSH
from aplicacion.conexiones.errores import (
    ErrorAutenticacionSSH,
    ErrorConfiguracionSSH,
    ErrorIdentidadServidorSSH,
    ErrorSalidaSSHExcedida,
    ErrorServidorSSHNoDisponible,
    ErrorTiempoEsperaSSH,
)
from aplicacion.configuracion import Configuracion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.servidor import Servidor

TAMANO_MAXIMO_HOSTS_CONOCIDOS = 2_097_152
TAMANO_BLOQUE_LECTURA = 4_096


class _AcumuladorSalida:
    """Comparte un presupuesto de bytes entre salida estándar y error."""

    def __init__(self, limite: int) -> None:
        self.limite = limite
        self.total = 0
        self.excedido = False
        self.bloqueo = asyncio.Lock()

    async def agregar(self, destino: bytearray, bloque: bytes) -> None:
        async with self.bloqueo:
            restante = self.limite - self.total
            destino.extend(bloque[:restante])
            self.total += min(len(bloque), restante)
            if len(bloque) > restante:
                self.excedido = True


class TransporteSSHAsync:
    """Conexión SSH reutilizable que no acepta hosts ni credenciales implícitas."""

    def __init__(
        self,
        servidor: Servidor,
        configuracion: Configuracion,
        resolvedor: ResolvedorCredencialesSSH | None = None,
    ) -> None:
        self._servidor = servidor
        self._configuracion = configuracion
        self._resolvedor = resolvedor or ResolvedorCredencialesSSH(
            configuracion.directorio_credenciales_ssh
        )
        self._conexion: asyncssh.SSHClientConnection | None = None

    async def __aenter__(self) -> "TransporteSSHAsync":
        await self._conectar()
        return self

    async def __aexit__(
        self,
        tipo_error: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        await self.cerrar()

    async def comprobar_disponibilidad(self) -> bool:
        """Completa red, negociación, verificación del host y autenticación."""

        await self._conectar()
        return True

    async def ejecutar_comando_controlado(
        self,
        comando: str,
        tiempo_limite_segundos: float,
        limite_salida_bytes: int,
    ) -> ResultadoEjecucionRemota:
        """Ejecuta un comando interno con plazo y recolección de salida acotados."""

        if not comando or tiempo_limite_segundos <= 0 or limite_salida_bytes <= 0:
            raise ErrorConfiguracionSSH("Los límites de ejecución SSH no son válidos.")

        conexion = await self._conectar()
        inicio = perf_counter()
        proceso: asyncssh.SSHClientProcess[bytes] | None = None
        try:
            async with asyncio.timeout(tiempo_limite_segundos):
                proceso = await conexion.create_process(comando, encoding=None)
                salida = bytearray()
                error = bytearray()
                acumulador = _AcumuladorSalida(limite_salida_bytes)

                async def leer(
                    lector: asyncssh.SSHReader[bytes],
                    destino: bytearray,
                ) -> None:
                    while True:
                        bloque = await lector.read(TAMANO_BLOQUE_LECTURA)
                        if not bloque:
                            return
                        await acumulador.agregar(destino, bloque)
                        if acumulador.excedido:
                            proceso.close()
                            return

                await asyncio.gather(
                    leer(proceso.stdout, salida),
                    leer(proceso.stderr, error),
                    proceso.wait_closed(),
                )

                if acumulador.excedido:
                    raise ErrorSalidaSSHExcedida()

                codigo_salida = proceso.exit_status
                if codigo_salida is None:
                    codigo_salida = -1
                return ResultadoEjecucionRemota(
                    codigo_salida=codigo_salida,
                    salida=salida.decode("utf-8", errors="replace"),
                    error=error.decode("utf-8", errors="replace"),
                    duracion_segundos=perf_counter() - inicio,
                )
        except TimeoutError:
            if proceso is not None:
                proceso.close()
            raise ErrorTiempoEsperaSSH() from None
        except ErrorSalidaSSHExcedida:
            raise
        except (asyncssh.Error, OSError):
            raise ErrorServidorSSHNoDisponible() from None

    async def cerrar(self) -> None:
        """Cierra la conexión de forma idempotente y espera su liberación."""

        if self._conexion is None:
            return
        conexion, self._conexion = self._conexion, None
        conexion.close()
        await conexion.wait_closed()

    async def _conectar(self) -> asyncssh.SSHClientConnection:
        if self._conexion is not None and not self._conexion.is_closed():
            return self._conexion

        if not self._servidor.activo:
            raise ErrorConfiguracionSSH("El servidor está inactivo en el inventario.")
        if not self._servidor.huella_clave_host:
            raise ErrorConfiguracionSSH("Falta la huella SHA-256 de la clave del host.")

        credencial = self._resolvedor.resolver(
            self._servidor.tipo_credencial,
            self._servidor.referencia_credencial,
        )
        archivo_hosts = self._validar_archivo_hosts_conocidos()

        try:
            conexion = await asyncssh.connect(
                self._servidor.direccion,
                port=self._servidor.puerto_ssh,
                username=self._servidor.usuario_conexion,
                client_keys=[str(ruta) for ruta in credencial.claves_cliente],
                agent_path=credencial.ruta_agente,
                known_hosts=str(archivo_hosts),
                connect_timeout=self._configuracion.tiempo_conexion_ssh_segundos,
                login_timeout=self._configuracion.tiempo_autenticacion_ssh_segundos,
                keepalive_interval=(self._configuracion.intervalo_mantenimiento_ssh_segundos),
                keepalive_count_max=self._configuracion.max_intentos_mantenimiento_ssh,
                password_auth=False,
                kbdint_auth=False,
                preferred_auth="publickey",
                config=None,
            )
        except asyncssh.HostKeyNotVerifiable:
            raise ErrorIdentidadServidorSSH() from None
        except asyncssh.PermissionDenied:
            raise ErrorAutenticacionSSH() from None
        except TimeoutError:
            raise ErrorTiempoEsperaSSH() from None
        except asyncssh.KeyImportError:
            raise ErrorConfiguracionSSH("La clave SSH referenciada no se puede utilizar.") from None
        except (asyncssh.Error, OSError):
            raise ErrorServidorSSHNoDisponible() from None

        huella_recibida = conexion.get_server_host_key().get_fingerprint("sha256")
        if not hmac.compare_digest(
            self._servidor.huella_clave_host.strip(),
            huella_recibida,
        ):
            conexion.close()
            await conexion.wait_closed()
            raise ErrorIdentidadServidorSSH()

        self._conexion = conexion
        return conexion

    def _validar_archivo_hosts_conocidos(self) -> Path:
        candidata = self._configuracion.archivo_hosts_conocidos_ssh.expanduser()
        if candidata.is_symlink():
            raise ErrorConfiguracionSSH(
                "No se permiten enlaces simbólicos como archivo de hosts conocidos."
            )
        try:
            ruta = candidata.resolve(strict=True)
        except OSError:
            raise ErrorConfiguracionSSH("No existe el archivo SSH de hosts conocidos.") from None
        if not ruta.is_file():
            raise ErrorConfiguracionSSH("El archivo SSH de hosts conocidos no es válido.")
        datos_archivo = ruta.stat()
        if datos_archivo.st_uid not in {0, os.geteuid()}:
            raise ErrorConfiguracionSSH(
                "El archivo de hosts conocidos tiene un propietario no permitido."
            )
        if stat.S_IMODE(datos_archivo.st_mode) & 0o022:
            raise ErrorConfiguracionSSH(
                "El archivo de hosts conocidos no puede permitir escritura a terceros."
            )
        if datos_archivo.st_size > TAMANO_MAXIMO_HOSTS_CONOCIDOS:
            raise ErrorConfiguracionSSH("El archivo de hosts conocidos es demasiado grande.")
        return ruta


def crear_transporte_ssh(
    servidor: Servidor,
    configuracion: Configuracion,
) -> TransporteSSHAsync:
    """Fábrica predeterminada sustituible durante las pruebas."""

    return TransporteSSHAsync(servidor, configuracion)
