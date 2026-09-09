"""Identidades externas autorizadas para acceder a Hermes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.base import FechasRegistro, ModeloBase
from aplicacion.modelos.enumeraciones import TipoCanalMensajeria

if TYPE_CHECKING:
    from aplicacion.modelos.acceso import Usuario


class IdentidadMensajeria(FechasRegistro, ModeloBase):
    """Vincula un identificador inmutable del proveedor con un usuario local."""

    __tablename__ = "identidades_mensajeria"
    __table_args__ = (
        UniqueConstraint(
            "canal",
            "identificador_externo",
            name="uq_identidades_mensajeria_canal_identificador",
        ),
        UniqueConstraint(
            "id_usuario",
            "canal",
            name="uq_identidades_mensajeria_usuario_canal",
        ),
    )

    id_identidad_mensajeria: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    id_usuario: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
        nullable=False,
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
    identificador_externo: Mapped[str] = mapped_column(String(100), nullable=False)
    nombre_externo: Mapped[str | None] = mapped_column(String(100))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)

    usuario: Mapped[Usuario] = relationship(back_populates="identidades_mensajeria")
