"""Configuración, episodios y entregas persistentes del monitoreo."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.base import FechasRegistro, ModeloBase
from aplicacion.modelos.enumeraciones import (
    EstadoAlerta,
    EstadoNotificacionAlerta,
    FaseNotificacionAlerta,
    TipoAlerta,
    TipoCanalMensajeria,
)

if TYPE_CHECKING:
    from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
    from aplicacion.modelos.servidor import Servidor


class ConfiguracionMonitoreoServidor(FechasRegistro, ModeloBase):
    """Umbrales y comprobaciones automáticas de un servidor."""

    __tablename__ = "configuraciones_monitoreo"
    __table_args__ = (
        UniqueConstraint("id_servidor", name="uq_configuraciones_monitoreo_servidor"),
        CheckConstraint(
            "umbral_cpu IS NULL OR umbral_cpu BETWEEN 0 AND 100",
            name="umbral_cpu_valido",
        ),
        CheckConstraint(
            "umbral_memoria IS NULL OR umbral_memoria BETWEEN 0 AND 100",
            name="umbral_memoria_valido",
        ),
        CheckConstraint(
            "umbral_disco IS NULL OR umbral_disco BETWEEN 0 AND 100",
            name="umbral_disco_valido",
        ),
    )

    id_configuracion_monitoreo: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_servidor: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("servidores.id_servidor", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    umbral_cpu: Mapped[float | None] = mapped_column(Float)
    umbral_memoria: Mapped[float | None] = mapped_column(Float)
    umbral_disco: Mapped[float | None] = mapped_column(Float)

    servidor: Mapped[Servidor] = relationship(lazy="selectin")
    servicios_criticos: Mapped[list[ServicioCriticoMonitoreo]] = relationship(
        back_populates="configuracion",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def nombres_servicios_criticos(self) -> list[str]:
        """Expone nombres ordenados sin filtrar objetos ORM al contrato externo."""

        return sorted(
            servicio.nombre_servicio for servicio in self.servicios_criticos if servicio.activo
        )


class ServicioCriticoMonitoreo(FechasRegistro, ModeloBase):
    """Servicio que debe permanecer activo en un servidor concreto."""

    __tablename__ = "servicios_criticos_monitoreo"
    __table_args__ = (
        UniqueConstraint(
            "id_configuracion_monitoreo",
            "nombre_servicio",
            name="uq_servicios_criticos_configuracion_nombre",
        ),
    )

    id_servicio_critico: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_configuracion_monitoreo: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "configuraciones_monitoreo.id_configuracion_monitoreo",
            ondelete="CASCADE",
            name="fk_servicios_criticos_configuracion_monitoreo",
        ),
        nullable=False,
        index=True,
    )
    nombre_servicio: Mapped[str] = mapped_column(String(128), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")

    configuracion: Mapped[ConfiguracionMonitoreoServidor] = relationship(
        back_populates="servicios_criticos"
    )


class Alerta(ModeloBase):
    """Episodio deduplicado desde su detección hasta su recuperación."""

    __tablename__ = "alertas"
    __table_args__ = (UniqueConstraint("clave_activa", name="uq_alertas_clave_activa"),)

    id_alerta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_servidor: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("servidores.id_servidor", ondelete="SET NULL"),
        index=True,
    )
    nombre_servidor: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo: Mapped[TipoAlerta] = mapped_column(
        Enum(
            TipoAlerta,
            name="tipo_alerta",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    identificador_objetivo: Mapped[str] = mapped_column(String(128), nullable=False)
    clave_activa: Mapped[str | None] = mapped_column(String(64))
    estado: Mapped[EstadoAlerta] = mapped_column(
        Enum(
            EstadoAlerta,
            name="estado_alerta",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    mensaje_apertura: Mapped[str] = mapped_column(String(500), nullable=False)
    mensaje_recuperacion: Mapped[str | None] = mapped_column(String(500))
    valor_observado: Mapped[str | None] = mapped_column(String(100))
    umbral: Mapped[float | None] = mapped_column(Float)
    detectada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        index=True,
    )
    ultima_observacion_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    recuperada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    servidor: Mapped[Servidor | None] = relationship(lazy="raise")
    notificaciones: Mapped[list[NotificacionAlerta]] = relationship(
        back_populates="alerta",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class SuscripcionAlerta(FechasRegistro, ModeloBase):
    """Habilitación explícita de alertas para una identidad vinculada."""

    __tablename__ = "suscripciones_alertas"
    __table_args__ = (
        UniqueConstraint("id_identidad_mensajeria", name="uq_suscripciones_alertas_identidad"),
    )

    id_suscripcion_alerta: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_identidad_mensajeria: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "identidades_mensajeria.id_identidad_mensajeria",
            ondelete="CASCADE",
            name="fk_suscripciones_alertas_identidad_mensajeria",
        ),
        nullable=False,
        index=True,
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")

    identidad: Mapped[IdentidadMensajeria] = relationship(lazy="selectin")


class NotificacionAlerta(ModeloBase):
    """Intentos y resultado de una entrega a un destino concreto."""

    __tablename__ = "notificaciones_alertas"
    __table_args__ = (
        UniqueConstraint(
            "id_alerta",
            "id_identidad_mensajeria",
            "fase",
            name="uq_notificaciones_alertas_alerta_identidad_fase",
        ),
        CheckConstraint("intentos >= 0", name="intentos_no_negativos"),
    )

    id_notificacion_alerta: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_alerta: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("alertas.id_alerta", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_identidad_mensajeria: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "identidades_mensajeria.id_identidad_mensajeria",
            ondelete="SET NULL",
            name="fk_notificaciones_alertas_identidad_mensajeria",
        ),
        index=True,
    )
    canal: Mapped[TipoCanalMensajeria] = mapped_column(
        Enum(
            TipoCanalMensajeria,
            name="tipo_canal_mensajeria",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    fase: Mapped[FaseNotificacionAlerta] = mapped_column(
        Enum(
            FaseNotificacionAlerta,
            name="fase_notificacion_alerta",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    estado: Mapped[EstadoNotificacionAlerta] = mapped_column(
        Enum(
            EstadoNotificacionAlerta,
            name="estado_notificacion_alerta",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    intentos: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    creada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    ultimo_intento_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enviada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    alerta: Mapped[Alerta] = relationship(back_populates="notificaciones", lazy="selectin")
    identidad: Mapped[IdentidadMensajeria | None] = relationship(lazy="selectin")
