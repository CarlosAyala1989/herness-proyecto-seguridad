"""Plantillas, aplicaciones administradas e historial de despliegues."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    EstadoDespliegue,
    SistemaOperativo,
    TipoPlantillaDespliegue,
)

if TYPE_CHECKING:
    from aplicacion.modelos.acceso import Usuario
    from aplicacion.modelos.servidor import Servidor


class PlantillaDespliegue(FechasRegistro, ModeloBase):
    """Procedimiento reutilizable sin comandos configurables por el usuario."""

    __tablename__ = "plantillas_despliegue"

    id_plantilla_despliegue: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(500))
    sistema_operativo: Mapped[SistemaOperativo] = mapped_column(
        Enum(
            SistemaOperativo,
            name="sistema_operativo_plantilla_despliegue",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    tipo: Mapped[TipoPlantillaDespliegue] = mapped_column(
        Enum(
            TipoPlantillaDespliegue,
            name="tipo_plantilla_despliegue",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
    )
    ruta_destino: Mapped[str] = mapped_column(String(900), nullable=False)
    nombre_servicio: Mapped[str | None] = mapped_column(String(128))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)

    aplicaciones: Mapped[list[AplicacionAdministrada]] = relationship(
        back_populates="plantilla", lazy="raise"
    )


class AplicacionAdministrada(FechasRegistro, ModeloBase):
    """Instancia de una plantilla sobre un servidor concreto."""

    __tablename__ = "aplicaciones_administradas"
    __table_args__ = (
        UniqueConstraint(
            "id_servidor", "nombre", name="uq_aplicaciones_administradas_servidor_nombre"
        ),
    )

    id_aplicacion_administrada: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    id_servidor: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "servidores.id_servidor",
            name="fk_aplicacion_servidor",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    id_plantilla_despliegue: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "plantillas_despliegue.id_plantilla_despliegue",
            name="fk_aplicacion_plantilla",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(500))
    version_actual: Mapped[str | None] = mapped_column(String(64))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)

    servidor: Mapped[Servidor] = relationship(
        back_populates="aplicaciones_administradas", lazy="selectin"
    )
    plantilla: Mapped[PlantillaDespliegue] = relationship(
        back_populates="aplicaciones", lazy="selectin"
    )
    despliegues: Mapped[list[DespliegueAplicacion]] = relationship(
        back_populates="aplicacion", cascade="all, delete-orphan", lazy="raise"
    )


class DespliegueAplicacion(ModeloBase):
    """Resultado durable de instalar una versión y su punto de retorno."""

    __tablename__ = "despliegues_aplicaciones"

    id_despliegue_aplicacion: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    id_aplicacion_administrada: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "aplicaciones_administradas.id_aplicacion_administrada",
            name="fk_despliegue_aplicacion",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    id_usuario: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("usuarios.id_usuario", name="fk_despliegue_usuario", ondelete="SET NULL"),
        index=True,
    )
    nombre_usuario: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_anterior: Mapped[str | None] = mapped_column(String(64))
    ruta_artefacto: Mapped[str] = mapped_column(String(1024), nullable=False)
    ruta_respaldo: Mapped[str | None] = mapped_column(String(1024))
    hash_sha256: Mapped[str | None] = mapped_column(String(64))
    estado: Mapped[EstadoDespliegue] = mapped_column(
        Enum(
            EstadoDespliegue,
            name="estado_despliegue_aplicacion",
            values_callable=lambda enumeracion: [miembro.value for miembro in enumeracion],
        ),
        nullable=False,
        index=True,
    )
    detalle_resultado: Mapped[str | None] = mapped_column(Text)
    iniciado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    finalizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revertido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    aplicacion: Mapped[AplicacionAdministrada] = relationship(
        back_populates="despliegues", lazy="selectin"
    )
    usuario: Mapped[Usuario | None] = relationship(lazy="raise")
