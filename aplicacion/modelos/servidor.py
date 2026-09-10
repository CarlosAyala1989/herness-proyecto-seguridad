"""Modelo de servidor administrable."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.asociaciones import servidores_grupos
from aplicacion.modelos.base import FechasRegistro, ModeloBase
from aplicacion.modelos.enumeraciones import SistemaOperativo, TipoCredencialConexion


class Servidor(FechasRegistro, ModeloBase):
    """Equipo Linux o Windows Server registrado en el inventario."""

    __tablename__ = "servidores"
    __table_args__ = (
        UniqueConstraint("nombre", name="uq_servidores_nombre"),
        UniqueConstraint(
            "direccion",
            "puerto_ssh",
            name="uq_servidores_direccion_puerto_ssh",
        ),
        CheckConstraint(
            "puerto_ssh BETWEEN 1 AND 65535",
            name="puerto_ssh_valido",
        ),
    )

    id_servidor: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(500))
    direccion: Mapped[str] = mapped_column(String(255), nullable=False)
    puerto_ssh: Mapped[int] = mapped_column(nullable=False, default=22, server_default="22")
    usuario_conexion: Mapped[str] = mapped_column(String(100), nullable=False)
    sistema_operativo: Mapped[SistemaOperativo] = mapped_column(
        Enum(
            SistemaOperativo,
            name="sistema_operativo_servidor",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    tipo_credencial: Mapped[TipoCredencialConexion] = mapped_column(
        Enum(
            TipoCredencialConexion,
            name="tipo_credencial_conexion",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    referencia_credencial: Mapped[str] = mapped_column(String(255), nullable=False)
    huella_clave_host: Mapped[str | None] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        index=True,
    )

    grupos: Mapped[list[GrupoServidor]] = relationship(
        secondary=servidores_grupos,
        back_populates="servidores",
        lazy="selectin",
    )
    rutas_archivos_permitidas: Mapped[list[RutaArchivoPermitida]] = relationship(
        back_populates="servidor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    aplicaciones_administradas: Mapped[list[AplicacionAdministrada]] = relationship(
        back_populates="servidor",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    @property
    def ids_grupos(self) -> list[int]:
        """Expone únicamente identificadores para evitar respuestas recursivas."""

        return [grupo.id_grupo for grupo in self.grupos]


from aplicacion.modelos.despliegue import AplicacionAdministrada  # noqa: E402
from aplicacion.modelos.grupo_servidor import GrupoServidor  # noqa: E402
from aplicacion.modelos.ruta_archivo_permitida import RutaArchivoPermitida  # noqa: E402
