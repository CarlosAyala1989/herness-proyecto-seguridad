"""Tareas administrativas, ocurrencias y entregas persistentes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.base import FechasRegistro, ModeloBase
from aplicacion.modelos.enumeraciones import (
    EstadoEjecucionTarea,
    EstadoNotificacionTarea,
    EstadoTareaProgramada,
    TipoCanalMensajeria,
    TipoProgramacionTarea,
)

if TYPE_CHECKING:
    from aplicacion.modelos.acceso import Usuario
    from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria


class TareaProgramada(FechasRegistro, ModeloBase):
    """Definición inmutable de acción, destinos y calendario."""

    __tablename__ = "tareas_programadas"
    __table_args__ = (
        CheckConstraint(
            "(tipo_programacion = 'una_vez' AND intervalo_segundos IS NULL) OR "
            "(tipo_programacion = 'intervalo' AND intervalo_segundos >= 60)",
            name="programacion_intervalo_valida",
        ),
    )

    id_tarea_programada: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_usuario_creador: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="SET NULL"),
        index=True,
    )
    nombre_usuario_creador: Mapped[str] = mapped_column(String(64), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(500))
    codigo_accion: Mapped[str] = mapped_column(String(100), nullable=False)
    parametros: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    ids_servidores: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    tipo_programacion: Mapped[TipoProgramacionTarea] = mapped_column(
        Enum(
            TipoProgramacionTarea,
            name="tipo_programacion_tarea",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    estado: Mapped[EstadoTareaProgramada] = mapped_column(
        Enum(
            EstadoTareaProgramada,
            name="estado_tarea_programada",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    programada_inicialmente_para: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    proxima_ejecucion_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    intervalo_segundos: Mapped[int | None] = mapped_column()
    confirmacion_otorgada: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notificar_resultado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
    )
    token_bloqueo: Mapped[str | None] = mapped_column(String(36))
    bloqueada_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    usuario_creador: Mapped[Usuario | None] = relationship(lazy="raise")
    ejecuciones: Mapped[list[EjecucionTarea]] = relationship(
        back_populates="tarea",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class EjecucionTarea(ModeloBase):
    """Ocurrencia única protegida por tarea y momento planificado."""

    __tablename__ = "ejecuciones_tareas"
    __table_args__ = (
        UniqueConstraint(
            "id_tarea_programada",
            "programada_para",
            name="uq_ejecuciones_tareas_tarea_programada_para",
        ),
    )

    id_ejecucion_tarea: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_tarea_programada: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tareas_programadas.id_tarea_programada", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    programada_para: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    iniciada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    finalizada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estado: Mapped[EstadoEjecucionTarea] = mapped_column(
        Enum(
            EstadoEjecucionTarea,
            name="estado_ejecucion_tarea",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    resumen_resultado: Mapped[dict[str, object] | None] = mapped_column(JSON)
    detalle_error: Mapped[str | None] = mapped_column(Text)

    tarea: Mapped[TareaProgramada] = relationship(back_populates="ejecuciones", lazy="selectin")
    notificaciones: Mapped[list[NotificacionTarea]] = relationship(
        back_populates="ejecucion",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class NotificacionTarea(ModeloBase):
    """Entrega reintentable del resultado a una identidad del creador."""

    __tablename__ = "notificaciones_tareas"
    __table_args__ = (
        UniqueConstraint(
            "id_ejecucion_tarea",
            "id_identidad_mensajeria",
            name="uq_notificaciones_tareas_ejecucion_identidad",
        ),
        CheckConstraint("intentos >= 0", name="intentos_no_negativos"),
    )

    id_notificacion_tarea: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_ejecucion_tarea: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("ejecuciones_tareas.id_ejecucion_tarea", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_identidad_mensajeria: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("identidades_mensajeria.id_identidad_mensajeria", ondelete="SET NULL"),
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
    estado: Mapped[EstadoNotificacionTarea] = mapped_column(
        Enum(
            EstadoNotificacionTarea,
            name="estado_notificacion_tarea",
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

    ejecucion: Mapped[EjecucionTarea] = relationship(
        back_populates="notificaciones",
        lazy="selectin",
    )
    identidad: Mapped[IdentidadMensajeria | None] = relationship(lazy="selectin")
