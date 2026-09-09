"""Modelos persistentes de usuarios, roles y permisos."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aplicacion.modelos.asociaciones import roles_permisos, usuarios_roles
from aplicacion.modelos.base import FechasRegistro, ModeloBase


class Permiso(ModeloBase):
    """Capacidad atómica asignable mediante un rol."""

    __tablename__ = "permisos"
    __table_args__ = (UniqueConstraint("codigo", name="uq_permisos_codigo"),)

    id_permiso: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)

    roles: Mapped[list[Rol]] = relationship(
        secondary=roles_permisos,
        back_populates="permisos",
        lazy="selectin",
    )


class Rol(ModeloBase):
    """Agrupación persistente de permisos."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("nombre", name="uq_roles_nombre"),)

    id_rol: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    es_sistema: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")

    permisos: Mapped[list[Permiso]] = relationship(
        secondary=roles_permisos,
        back_populates="roles",
        lazy="selectin",
    )
    usuarios: Mapped[list[Usuario]] = relationship(
        secondary=usuarios_roles,
        back_populates="roles",
        lazy="selectin",
    )


class Usuario(FechasRegistro, ModeloBase):
    """Persona autorizable para utilizar Hermes."""

    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("nombre_usuario", name="uq_usuarios_nombre_usuario"),)

    id_usuario: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre_usuario: Mapped[str] = mapped_column(String(64), nullable=False)
    nombre_mostrar: Mapped[str] = mapped_column(String(120), nullable=False)
    hash_contrasena: Mapped[str] = mapped_column(String(255), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1", index=True)

    roles: Mapped[list[Rol]] = relationship(
        secondary=usuarios_roles,
        back_populates="usuarios",
        lazy="selectin",
    )
