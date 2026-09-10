"""Raíces remotas autorizadas para operaciones SFTP."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.base import FechasRegistro, ModeloBase


class RutaArchivoPermitida(FechasRegistro, ModeloBase):
    """Directorio remoto habilitado explícitamente para lectura o escritura."""

    __tablename__ = "rutas_archivos_permitidas"
    __table_args__ = (
        UniqueConstraint(
            "id_servidor",
            "ruta",
            name="uq_rutas_archivos_permitidas_servidor_ruta",
        ),
        CheckConstraint(
            "permite_lectura = 1 OR permite_escritura = 1",
            name="alguna_operacion_habilitada",
        ),
    )

    id_ruta_archivo_permitida: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    id_servidor: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("servidores.id_servidor", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ruta: Mapped[str] = mapped_column(String(1024), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255))
    permite_lectura: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    permite_escritura: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)

    servidor: Mapped[Servidor] = relationship(back_populates="rutas_archivos_permitidas")


from aplicacion.modelos.servidor import Servidor  # noqa: E402
