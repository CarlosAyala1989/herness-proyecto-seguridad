"""Modelo para agrupar servidores dinámicamente."""

from __future__ import annotations

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.asociaciones import servidores_grupos
from aplicacion.modelos.base import FechasRegistro, ModeloBase


class GrupoServidor(FechasRegistro, ModeloBase):
    """Conjunto reutilizable de servidores del inventario."""

    __tablename__ = "grupos_servidores"
    __table_args__ = (UniqueConstraint("nombre", name="uq_grupos_servidores_nombre"),)

    id_grupo: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(500))

    servidores: Mapped[list[Servidor]] = relationship(
        secondary=servidores_grupos,
        back_populates="grupos",
        lazy="selectin",
    )


from aplicacion.modelos.servidor import Servidor  # noqa: E402
