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


class TipoCanalMensajeria(StrEnum):
    """Proveedores que pueden vincular una identidad externa."""

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


class TipoAlerta(StrEnum):
    """Condiciones automáticas que puede detectar el monitor."""

    SERVIDOR_NO_DISPONIBLE = "servidor_no_disponible"
    CPU_ALTA = "cpu_alta"
    MEMORIA_ALTA = "memoria_alta"
    DISCO_ALTO = "disco_alto"
    SERVICIO_CRITICO_NO_ACTIVO = "servicio_critico_no_activo"


class EstadoAlerta(StrEnum):
    """Ciclo de vida persistente de un episodio de alerta."""

    ACTIVA = "activa"
    RECUPERADA = "recuperada"


class FaseNotificacionAlerta(StrEnum):
    """Transición que da origen a una notificación."""

    APERTURA = "apertura"
    RECUPERACION = "recuperacion"


class EstadoNotificacionAlerta(StrEnum):
    """Resultado del envío de una notificación concreta."""

    PENDIENTE = "pendiente"
    ENVIADA = "enviada"
    FALLIDA = "fallida"
