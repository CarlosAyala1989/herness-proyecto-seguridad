"""Valores enumerados persistentes del dominio de Hermes."""

from enum import StrEnum


class SistemaOperativo(StrEnum):
    """Familias de sistema operativo administrables."""

    LINUX = "linux"
    WINDOWS_SERVER = "windows_server"


class TipoCredencialConexion(StrEnum):
    """Mecanismo referenciado para autenticar una conexión futura."""

    CLAVE_SSH = "clave_ssh"
    AGENTE_SSH = "agente_ssh"


class CanalAuditoria(StrEnum):
    """Canal desde el que se originó una acción."""

    API = "api"
    SISTEMA = "sistema"
    TELEGRAM = "telegram"
    SLACK = "slack"


class ResultadoAuditoria(StrEnum):
    """Resultado normalizado de una acción auditable."""

    EXITO = "exito"
    DENEGADO = "denegado"
    ERROR = "error"


class TipoRecursoAuditoria(StrEnum):
    """Recursos que pueden aparecer en el historial de auditoría."""

    SERVIDOR = "servidor"
    GRUPO = "grupo"
    USUARIO = "usuario"
    ROL = "rol"
    PERMISO = "permiso"
    ASOCIACION = "asociacion"
    AUTENTICACION = "autenticacion"
