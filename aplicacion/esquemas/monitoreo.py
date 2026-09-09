"""Contratos validados de configuración, destinos y alertas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aplicacion.adaptadores.servicios import PATRON_NOMBRE_SERVICIO
from aplicacion.esquemas.comunes import EsquemaDesdeAtributos
from aplicacion.modelos.enumeraciones import (
    EstadoAlerta,
    TipoAlerta,
    TipoCanalMensajeria,
)


class ConfigurarMonitoreoServidor(BaseModel):
    """Reemplaza de forma atómica la política de monitoreo de un servidor."""

    model_config = ConfigDict(extra="forbid")

    activo: bool = True
    umbral_cpu: float | None = Field(default=85.0, ge=0, le=100)
    umbral_memoria: float | None = Field(default=90.0, ge=0, le=100)
    umbral_disco: float | None = Field(default=90.0, ge=0, le=100)
    servicios_criticos: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("servicios_criticos")
    @classmethod
    def validar_servicios_criticos(cls, valores: list[str]) -> list[str]:
        """Rechaza nombres inseguros y duplicados sin alterar mayúsculas."""

        normalizados = [valor.strip() for valor in valores]
        if any(not PATRON_NOMBRE_SERVICIO.fullmatch(valor) for valor in normalizados):
            raise ValueError("Un servicio crítico tiene un nombre no válido.")
        if len(set(normalizados)) != len(normalizados):
            raise ValueError("Los servicios críticos no pueden estar duplicados.")
        return sorted(normalizados)


class ConfiguracionMonitoreoRespuesta(EsquemaDesdeAtributos):
    """Política persistente visible mediante la API."""

    id_configuracion_monitoreo: int
    id_servidor: int
    activo: bool
    umbral_cpu: float | None
    umbral_memoria: float | None
    umbral_disco: float | None
    nombres_servicios_criticos: list[str]
    creado_en: datetime
    actualizado_en: datetime


class ActualizarSuscripcionAlerta(BaseModel):
    """Activa o desactiva la recepción para una identidad ya vinculada."""

    model_config = ConfigDict(extra="forbid")

    activo: bool


class DestinoAlertaRespuesta(BaseModel):
    """Identidad elegible y estado de su suscripción."""

    id_identidad_mensajeria: int
    id_usuario: int
    nombre_usuario: str
    canal: TipoCanalMensajeria
    identificador_externo: str
    nombre_externo: str | None
    identidad_activa: bool
    usuario_activo: bool
    suscrito: bool


class AlertaRespuesta(EsquemaDesdeAtributos):
    """Episodio de alerta sin datos internos de conexión."""

    id_alerta: int
    id_servidor: int | None
    nombre_servidor: str
    tipo: TipoAlerta
    identificador_objetivo: str
    estado: EstadoAlerta
    mensaje_apertura: str
    mensaje_recuperacion: str | None
    valor_observado: str | None
    umbral: float | None
    detectada_en: datetime
    ultima_observacion_en: datetime
    recuperada_en: datetime | None


class ResumenCicloMonitoreo(BaseModel):
    """Resultado agregado de una vuelta del proceso automático."""

    servidores_evaluados: int
    servidores_disponibles: int
    servidores_no_disponibles: int
    alertas_abiertas: int
    alertas_recuperadas: int
    sondeos_con_error_interno: int
    notificaciones_enviadas: int
    notificaciones_fallidas: int
