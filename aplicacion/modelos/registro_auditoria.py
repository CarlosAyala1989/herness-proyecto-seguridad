"""Modelo del historial inmutable de acciones."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.base import ModeloBase
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    ResultadoAuditoria,
    TipoRecursoAuditoria,
)


class RegistroAuditoria(ModeloBase):
    """Evidencia persistente de una acción solicitada o ejecutada."""

    __tablename__ = "registros_auditoria"

    id_registro_auditoria: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_usuario: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="SET NULL"),
        index=True,
    )
    nombre_usuario: Mapped[str | None] = mapped_column(String(64))
    accion: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tipo_recurso: Mapped[TipoRecursoAuditoria] = mapped_column(
        Enum(
            TipoRecursoAuditoria,
            name="tipo_recurso_auditoria",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    id_recurso: Mapped[int | None] = mapped_column(BigInteger)
    resultado: Mapped[ResultadoAuditoria] = mapped_column(
        Enum(
            ResultadoAuditoria,
            name="resultado_auditoria",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    canal: Mapped[CanalAuditoria] = mapped_column(
        Enum(
            CanalAuditoria,
            name="canal_auditoria",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    detalle: Mapped[str | None] = mapped_column(Text)
    direccion_origen: Mapped[str | None] = mapped_column(String(45))
    identificador_solicitud: Mapped[str | None] = mapped_column(String(36), index=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        index=True,
    )

    usuario: Mapped[Usuario | None] = relationship(lazy="raise")
