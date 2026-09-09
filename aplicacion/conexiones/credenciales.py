"""Resolución de referencias SSH sin persistir secretos en MariaDB."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from aplicacion.conexiones.errores import ErrorConfiguracionSSH
from aplicacion.modelos.enumeraciones import TipoCredencialConexion

TAMANO_MAXIMO_CLAVE_PRIVADA = 65_536


@dataclass(frozen=True, slots=True)
class CredencialSSHResuelta:
    """Parámetros mínimos que AsyncSSH utilizará para autenticarse."""

    claves_cliente: tuple[Path, ...]
    ruta_agente: str | None


class ResolvedorCredencialesSSH:
    """Resuelve claves locales confinadas o el agente del proceso."""

    def __init__(self, directorio_credenciales: Path) -> None:
        self._directorio_credenciales = directorio_credenciales

    def resolver(
        self,
        tipo_credencial: TipoCredencialConexion,
        referencia: str,
    ) -> CredencialSSHResuelta:
        """Convierte una referencia validada en opciones explícitas de cliente."""

        proveedor, separador, identificador = referencia.partition(":")
        if not separador or not identificador:
            raise ErrorConfiguracionSSH("La referencia de credencial SSH no es válida.")

        if tipo_credencial is TipoCredencialConexion.CLAVE_SSH:
            if proveedor != "archivo":
                raise ErrorConfiguracionSSH(
                    "Una credencial de clave SSH debe usar el proveedor archivo."
                )
            return self._resolver_archivo(identificador)

        if tipo_credencial is TipoCredencialConexion.AGENTE_SSH:
            if proveedor != "agente" or identificador != "predeterminado":
                raise ErrorConfiguracionSSH(
                    "La credencial de agente debe usar agente:predeterminado."
                )
            return self._resolver_agente()

        raise ErrorConfiguracionSSH("El tipo de credencial SSH no está admitido.")

    def _resolver_archivo(self, identificador: str) -> CredencialSSHResuelta:
        base = self._directorio_credenciales.expanduser().resolve()
        candidata = base / identificador
        if candidata.is_symlink():
            raise ErrorConfiguracionSSH("No se permiten enlaces simbólicos como claves SSH.")

        try:
            ruta = candidata.resolve(strict=True)
        except OSError:
            raise ErrorConfiguracionSSH("No se encontró la clave SSH referenciada.") from None

        if not ruta.is_relative_to(base) or not ruta.is_file():
            raise ErrorConfiguracionSSH("La clave SSH está fuera del directorio permitido.")

        datos_archivo = ruta.stat()
        if datos_archivo.st_uid != os.geteuid():
            raise ErrorConfiguracionSSH("La clave SSH debe pertenecer al usuario de Hermes.")
        if stat.S_IMODE(datos_archivo.st_mode) & 0o077:
            raise ErrorConfiguracionSSH("La clave SSH debe tener permisos 600 o más restrictivos.")
        if datos_archivo.st_size > TAMANO_MAXIMO_CLAVE_PRIVADA:
            raise ErrorConfiguracionSSH("La clave SSH supera el tamaño máximo permitido.")

        return CredencialSSHResuelta(claves_cliente=(ruta,), ruta_agente=None)

    @staticmethod
    def _resolver_agente() -> CredencialSSHResuelta:
        ruta_agente = os.environ.get("SSH_AUTH_SOCK")
        if not ruta_agente or not Path(ruta_agente).is_socket():
            raise ErrorConfiguracionSSH("No existe un agente SSH disponible para Hermes.")
        return CredencialSSHResuelta(claves_cliente=(), ruta_agente=ruta_agente)
