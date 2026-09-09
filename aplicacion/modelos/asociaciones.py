"""Tablas de asociación muchos-a-muchos."""

from sqlalchemy import BigInteger, Column, ForeignKey, Table

from aplicacion.modelos.base import ModeloBase

servidores_grupos = Table(
    "servidores_grupos",
    ModeloBase.metadata,
    Column(
        "id_servidor",
        BigInteger,
        ForeignKey("servidores.id_servidor", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "id_grupo",
        BigInteger,
        ForeignKey("grupos_servidores.id_grupo", ondelete="CASCADE"),
        primary_key=True,
    ),
)

usuarios_roles = Table(
    "usuarios_roles",
    ModeloBase.metadata,
    Column(
        "id_usuario",
        BigInteger,
        ForeignKey("usuarios.id_usuario", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "id_rol",
        BigInteger,
        ForeignKey("roles.id_rol", ondelete="CASCADE"),
        primary_key=True,
    ),
)

roles_permisos = Table(
    "roles_permisos",
    ModeloBase.metadata,
    Column(
        "id_rol",
        BigInteger,
        ForeignKey("roles.id_rol", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "id_permiso",
        BigInteger,
        ForeignKey("permisos.id_permiso", ondelete="CASCADE"),
        primary_key=True,
    ),
)
