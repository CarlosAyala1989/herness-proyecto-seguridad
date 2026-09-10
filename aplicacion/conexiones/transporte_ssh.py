"""Implementación acotada y estricta del transporte mediante AsyncSSH."""

import asyncio
import hmac
import os
import posixpath
import stat
from datetime import UTC, datetime
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
from aplicacion.errores import (
    ErrorArchivoRemotoNoCompatible,
    ErrorConflictoDatos,
    ErrorHermes,
    ErrorLimiteArchivoExcedido,
    ErrorRecursoNoEncontrado,
    ErrorRutaRemotaNoPermitida,
)
from aplicacion.interfaces.transporte_remoto import (
    InformacionArchivoRemoto,
    ResultadoEjecucionRemota,
)
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.rutas_remotas import ruta_esta_contenida

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

    async def consultar_informacion_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
    ) -> InformacionArchivoRemoto:
        """Consulta un archivo SFTP únicamente tras resolver su ruta real."""

        try:
            async with asyncio.timeout(tiempo_limite_segundos):
                conexion = await self._conectar()
                async with conexion.start_sftp_client() as cliente:
                    ruta_canonica = await self._resolver_ruta_existente_autorizada(
                        cliente, ruta_remota, rutas_permitidas
                    )
                    atributos = await cliente.stat(ruta_canonica)
                    return self._crear_informacion_archivo(ruta_canonica, atributos)
        except TimeoutError:
            raise ErrorTiempoEsperaSSH() from None
        except ErrorHermes:
            raise
        except asyncssh.SFTPNoSuchFile:
            raise ErrorRecursoNoEncontrado("archivo remoto") from None
        except asyncssh.SFTPPermissionDenied:
            raise ErrorArchivoRemotoNoCompatible(
                "El servidor rechazó el acceso al archivo remoto."
            ) from None
        except (asyncssh.Error, OSError):
            raise ErrorServidorSSHNoDisponible() from None

    async def descargar_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
        limite_bytes: int,
        tamano_bloque_bytes: int,
    ) -> tuple[InformacionArchivoRemoto, bytes]:
        """Lee un archivo regular por bloques sin superar el límite global."""

        try:
            async with asyncio.timeout(tiempo_limite_segundos):
                conexion = await self._conectar()
                async with conexion.start_sftp_client() as cliente:
                    ruta_canonica = await self._resolver_ruta_existente_autorizada(
                        cliente, ruta_remota, rutas_permitidas
                    )
                    atributos = await cliente.stat(ruta_canonica)
                    informacion = self._crear_informacion_archivo(ruta_canonica, atributos)
                    if informacion.tipo != "archivo":
                        raise ErrorArchivoRemotoNoCompatible(
                            "Solo se permite descargar archivos regulares."
                        )
                    if informacion.tamano_bytes is None or informacion.tamano_bytes > limite_bytes:
                        raise ErrorLimiteArchivoExcedido(limite_bytes)

                    contenido = bytearray()
                    async with cliente.open(ruta_canonica, "rb") as archivo:
                        while True:
                            bloque = await archivo.read(tamano_bloque_bytes)
                            if not bloque:
                                break
                            contenido.extend(bloque)
                            if len(contenido) > limite_bytes:
                                raise ErrorLimiteArchivoExcedido(limite_bytes)
                    return informacion, bytes(contenido)
        except TimeoutError:
            raise ErrorTiempoEsperaSSH() from None
        except ErrorHermes:
            raise
        except asyncssh.SFTPNoSuchFile:
            raise ErrorRecursoNoEncontrado("archivo remoto") from None
        except asyncssh.SFTPPermissionDenied:
            raise ErrorArchivoRemotoNoCompatible(
                "El servidor rechazó la lectura del archivo remoto."
            ) from None
        except (asyncssh.Error, OSError):
            raise ErrorServidorSSHNoDisponible() from None

    async def cargar_archivo(
        self,
        ruta_remota: str,
        contenido: bytes,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
        tamano_bloque_bytes: int,
        sobrescribir: bool,
    ) -> bool:
        """Escribe por SFTP usando creación exclusiva salvo confirmación de reemplazo."""

        try:
            async with asyncio.timeout(tiempo_limite_segundos):
                conexion = await self._conectar()
                async with conexion.start_sftp_client() as cliente:
                    ruta_canonica = await self._resolver_destino_autorizado(
                        cliente, ruta_remota, rutas_permitidas
                    )
                    existia = False
                    try:
                        atributos = await cliente.lstat(ruta_canonica)
                        existia = True
                        if atributos.type == asyncssh.FILEXFER_TYPE_SYMLINK:
                            raise ErrorArchivoRemotoNoCompatible(
                                "No se permite cargar sobre un enlace simbólico."
                            )
                        if atributos.type != asyncssh.FILEXFER_TYPE_REGULAR:
                            raise ErrorArchivoRemotoNoCompatible(
                                "El destino existente no es un archivo regular."
                            )
                    except asyncssh.SFTPNoSuchFile:
                        pass
                    if existia and not sobrescribir:
                        raise ErrorConflictoDatos(
                            "El archivo remoto ya existe; confirme la sobrescritura para reemplazarlo."
                        )

                    modo = "wb" if sobrescribir else "xb"
                    async with cliente.open(ruta_canonica, modo) as archivo:
                        for inicio in range(0, len(contenido), tamano_bloque_bytes):
                            await archivo.write(contenido[inicio : inicio + tamano_bloque_bytes])
                    return existia
        except TimeoutError:
            raise ErrorTiempoEsperaSSH() from None
        except ErrorHermes:
            raise
        except asyncssh.SFTPFileAlreadyExists:
            raise ErrorConflictoDatos(
                "El archivo remoto ya existe; confirme la sobrescritura para reemplazarlo."
            ) from None
        except asyncssh.SFTPNoSuchFile:
            raise ErrorRecursoNoEncontrado("directorio remoto de destino") from None
        except asyncssh.SFTPPermissionDenied:
            raise ErrorArchivoRemotoNoCompatible(
                "El servidor rechazó la escritura del archivo remoto."
            ) from None
        except (asyncssh.Error, OSError):
            raise ErrorServidorSSHNoDisponible() from None

    async def _resolver_ruta_existente_autorizada(
        self,
        cliente: asyncssh.SFTPClient,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
    ) -> str:
        ruta_canonica = str(await cliente.realpath(ruta_remota))
        raices_canonicas = await self._resolver_raices_canonicas(cliente, rutas_permitidas)
        self._exigir_contencion_canonica(ruta_canonica, raices_canonicas)
        return ruta_canonica

    async def _resolver_destino_autorizado(
        self,
        cliente: asyncssh.SFTPClient,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
    ) -> str:
        padre, nombre = posixpath.split(ruta_remota.replace("\\", "/"))
        if not nombre or nombre in {".", ".."}:
            raise ErrorArchivoRemotoNoCompatible("La ruta de destino debe identificar un archivo.")
        padre_canonico = str(await cliente.realpath(padre))
        destino_canonico = posixpath.join(padre_canonico.rstrip("/"), nombre)
        raices_canonicas = await self._resolver_raices_canonicas(cliente, rutas_permitidas)
        self._exigir_contencion_canonica(destino_canonico, raices_canonicas)
        return destino_canonico

    async def _resolver_raices_canonicas(
        self,
        cliente: asyncssh.SFTPClient,
        rutas_permitidas: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not rutas_permitidas:
            raise ErrorRutaRemotaNoPermitida()
        raices: list[str] = []
        for ruta in rutas_permitidas:
            canonica = str(await cliente.realpath(ruta))
            atributos = await cliente.stat(canonica)
            if atributos.type != asyncssh.FILEXFER_TYPE_DIRECTORY:
                continue
            raices.append(canonica)
        if not raices:
            raise ErrorRutaRemotaNoPermitida()
        return tuple(raices)

    def _exigir_contencion_canonica(
        self,
        ruta_canonica: str,
        raices_canonicas: tuple[str, ...],
    ) -> None:
        if not any(
            ruta_esta_contenida(ruta_canonica, raiz, self._servidor.sistema_operativo)
            for raiz in raices_canonicas
        ):
            raise ErrorRutaRemotaNoPermitida()

    @staticmethod
    def _crear_informacion_archivo(
        ruta_canonica: str,
        atributos: asyncssh.SFTPAttrs,
    ) -> InformacionArchivoRemoto:
        tipos = {
            asyncssh.FILEXFER_TYPE_REGULAR: "archivo",
            asyncssh.FILEXFER_TYPE_DIRECTORY: "directorio",
            asyncssh.FILEXFER_TYPE_SYMLINK: "enlace_simbolico",
        }
        modificado = (
            datetime.fromtimestamp(atributos.mtime, tz=UTC)
            if atributos.mtime is not None
            else None
        )
        return InformacionArchivoRemoto(
            ruta_remota=ruta_canonica,
            nombre_archivo=posixpath.basename(ruta_canonica.rstrip("/")) or ruta_canonica,
            tipo=tipos.get(atributos.type, "otro"),
            tamano_bytes=atributos.size,
            modificado_en=modificado,
        )

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
