"""Crea inventario, usuarios, permisos y auditoría.

Revisión: 0001
Revisión anterior: ninguna
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0001"
identificador_anterior = None
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Crea el esquema inicial persistente de Hermes."""

    op.create_table(
        "permisos",
        sa.Column("id_permiso", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("codigo", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id_permiso", name="pk_permisos"),
        sa.UniqueConstraint("codigo", name="uq_permisos_codigo"),
    )
    op.create_table(
        "roles",
        sa.Column("id_rol", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=False),
        sa.Column("es_sistema", sa.Boolean(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id_rol", name="pk_roles"),
        sa.UniqueConstraint("nombre", name="uq_roles_nombre"),
    )
    op.create_table(
        "usuarios",
        sa.Column("id_usuario", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre_usuario", sa.String(length=64), nullable=False),
        sa.Column("nombre_mostrar", sa.String(length=120), nullable=False),
        sa.Column("hash_contrasena", sa.String(length=255), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_usuario", name="pk_usuarios"),
        sa.UniqueConstraint("nombre_usuario", name="uq_usuarios_nombre_usuario"),
    )
    op.create_index("ix_usuarios_activo", "usuarios", ["activo"], unique=False)
    op.create_table(
        "grupos_servidores",
        sa.Column("id_grupo", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id_grupo", name="pk_grupos_servidores"),
        sa.UniqueConstraint("nombre", name="uq_grupos_servidores_nombre"),
    )
    op.create_table(
        "servidores",
        sa.Column("id_servidor", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("direccion", sa.String(length=255), nullable=False),
        sa.Column("puerto_ssh", sa.Integer(), server_default="22", nullable=False),
        sa.Column("usuario_conexion", sa.String(length=100), nullable=False),
        sa.Column(
            "sistema_operativo",
            sa.Enum("linux", "windows_server", name="sistema_operativo_servidor"),
            nullable=False,
        ),
        sa.Column(
            "tipo_credencial",
            sa.Enum("clave_ssh", "agente_ssh", name="tipo_credencial_conexion"),
            nullable=False,
        ),
        sa.Column("referencia_credencial", sa.String(length=255), nullable=False),
        sa.Column("huella_clave_host", sa.String(length=255), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "puerto_ssh BETWEEN 1 AND 65535",
            name="ck_servidores_puerto_ssh_valido",
        ),
        sa.PrimaryKeyConstraint("id_servidor", name="pk_servidores"),
        sa.UniqueConstraint("nombre", name="uq_servidores_nombre"),
        sa.UniqueConstraint(
            "direccion",
            "puerto_ssh",
            name="uq_servidores_direccion_puerto_ssh",
        ),
    )
    op.create_index("ix_servidores_activo", "servidores", ["activo"], unique=False)
    op.create_index(
        "ix_servidores_sistema_operativo",
        "servidores",
        ["sistema_operativo"],
        unique=False,
    )
    op.create_table(
        "roles_permisos",
        sa.Column("id_rol", sa.BigInteger(), nullable=False),
        sa.Column("id_permiso", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id_permiso"],
            ["permisos.id_permiso"],
            name="fk_roles_permisos_id_permiso_permisos",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_rol"],
            ["roles.id_rol"],
            name="fk_roles_permisos_id_rol_roles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_rol", "id_permiso", name="pk_roles_permisos"),
    )
    op.create_table(
        "usuarios_roles",
        sa.Column("id_usuario", sa.BigInteger(), nullable=False),
        sa.Column("id_rol", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id_rol"],
            ["roles.id_rol"],
            name="fk_usuarios_roles_id_rol_roles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_usuario"],
            ["usuarios.id_usuario"],
            name="fk_usuarios_roles_id_usuario_usuarios",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_usuario", "id_rol", name="pk_usuarios_roles"),
    )
    op.create_table(
        "servidores_grupos",
        sa.Column("id_servidor", sa.BigInteger(), nullable=False),
        sa.Column("id_grupo", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id_grupo"],
            ["grupos_servidores.id_grupo"],
            name="fk_servidores_grupos_id_grupo_grupos_servidores",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_servidor"],
            ["servidores.id_servidor"],
            name="fk_servidores_grupos_id_servidor_servidores",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_servidor", "id_grupo", name="pk_servidores_grupos"),
    )
    op.create_table(
        "registros_auditoria",
        sa.Column(
            "id_registro_auditoria",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id_usuario", sa.BigInteger(), nullable=True),
        sa.Column("nombre_usuario", sa.String(length=64), nullable=True),
        sa.Column("accion", sa.String(length=100), nullable=False),
        sa.Column(
            "tipo_recurso",
            sa.Enum(
                "servidor",
                "grupo",
                "usuario",
                "rol",
                "permiso",
                "asociacion",
                "autenticacion",
                name="tipo_recurso_auditoria",
            ),
            nullable=False,
        ),
        sa.Column("id_recurso", sa.BigInteger(), nullable=True),
        sa.Column(
            "resultado",
            sa.Enum("exito", "denegado", "error", name="resultado_auditoria"),
            nullable=False,
        ),
        sa.Column(
            "canal",
            sa.Enum("api", "sistema", "telegram", "slack", name="canal_auditoria"),
            nullable=False,
        ),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("direccion_origen", sa.String(length=45), nullable=True),
        sa.Column("identificador_solicitud", sa.String(length=36), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["id_usuario"],
            ["usuarios.id_usuario"],
            name="fk_registros_auditoria_id_usuario_usuarios",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id_registro_auditoria",
            name="pk_registros_auditoria",
        ),
    )
    op.create_index(
        "ix_registros_auditoria_accion",
        "registros_auditoria",
        ["accion"],
        unique=False,
    )
    op.create_index(
        "ix_registros_auditoria_creado_en",
        "registros_auditoria",
        ["creado_en"],
        unique=False,
    )
    op.create_index(
        "ix_registros_auditoria_id_usuario",
        "registros_auditoria",
        ["id_usuario"],
        unique=False,
    )
    op.create_index(
        "ix_registros_auditoria_identificador_solicitud",
        "registros_auditoria",
        ["identificador_solicitud"],
        unique=False,
    )

    permisos = sa.table(
        "permisos",
        sa.column("id_permiso", sa.BigInteger()),
        sa.column("codigo", sa.String()),
        sa.column("descripcion", sa.String()),
    )
    roles = sa.table(
        "roles",
        sa.column("id_rol", sa.BigInteger()),
        sa.column("nombre", sa.String()),
        sa.column("descripcion", sa.String()),
        sa.column("es_sistema", sa.Boolean()),
    )
    asociaciones = sa.table(
        "roles_permisos",
        sa.column("id_rol", sa.BigInteger()),
        sa.column("id_permiso", sa.BigInteger()),
    )
    op.bulk_insert(
        permisos,
        [
            {
                "id_permiso": 1,
                "codigo": "consultar_inventario",
                "descripcion": "Consultar servidores y grupos autorizados.",
            },
            {
                "id_permiso": 2,
                "codigo": "gestionar_inventario",
                "descripcion": "Crear, modificar y eliminar servidores y grupos.",
            },
            {
                "id_permiso": 3,
                "codigo": "gestionar_acceso",
                "descripcion": "Administrar usuarios, roles y permisos.",
            },
            {
                "id_permiso": 4,
                "codigo": "consultar_auditoria",
                "descripcion": "Consultar el historial de auditoría.",
            },
        ],
    )
    op.bulk_insert(
        roles,
        [
            {
                "id_rol": 1,
                "nombre": "administrador",
                "descripcion": "Administración completa de Hermes.",
                "es_sistema": True,
            },
            {
                "id_rol": 2,
                "nombre": "operador_inventario",
                "descripcion": "Consulta y mantenimiento del inventario.",
                "es_sistema": True,
            },
            {
                "id_rol": 3,
                "nombre": "auditor",
                "descripcion": "Consulta del inventario y de la auditoría.",
                "es_sistema": True,
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 1},
            {"id_rol": 1, "id_permiso": 2},
            {"id_rol": 1, "id_permiso": 3},
            {"id_rol": 1, "id_permiso": 4},
            {"id_rol": 2, "id_permiso": 1},
            {"id_rol": 2, "id_permiso": 2},
            {"id_rol": 3, "id_permiso": 1},
            {"id_rol": 3, "id_permiso": 4},
        ],
    )


def downgrade() -> None:
    """Elimina el esquema inicial persistente de Hermes."""

    # MariaDB elimina automáticamente los índices de cada tabla. Intentar quitar
    # antes el índice de una clave foránea produce el error 1553.
    op.drop_table("registros_auditoria")
    op.drop_table("servidores_grupos")
    op.drop_table("usuarios_roles")
    op.drop_table("roles_permisos")
    op.drop_table("servidores")
    op.drop_table("grupos_servidores")
    op.drop_table("usuarios")
    op.drop_table("roles")
    op.drop_table("permisos")
