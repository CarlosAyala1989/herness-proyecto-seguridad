"""Añade plantillas, aplicaciones e historial de despliegues.

Revisión: 0011
Revisión anterior: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea persistencia de despliegues y sus permisos separados."""

    op.alter_column(
        "registros_auditoria",
        "tipo_recurso",
        existing_type=sa.Enum(
            "servidor",
            "grupo",
            "usuario",
            "rol",
            "permiso",
            "asociacion",
            "autenticacion",
            "tarea",
            name="tipo_recurso_auditoria",
        ),
        type_=sa.Enum(
            "servidor",
            "grupo",
            "usuario",
            "rol",
            "permiso",
            "asociacion",
            "autenticacion",
            "tarea",
            "aplicacion",
            name="tipo_recurso_auditoria",
        ),
        existing_nullable=False,
    )

    op.create_table(
        "plantillas_despliegue",
        sa.Column("id_plantilla_despliegue", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column(
            "sistema_operativo",
            sa.Enum("linux", "windows_server", name="sistema_operativo_plantilla_despliegue"),
            nullable=False,
        ),
        sa.Column(
            "tipo",
            sa.Enum("archivo_unico", name="tipo_plantilla_despliegue"),
            nullable=False,
        ),
        sa.Column("ruta_destino", sa.String(length=900), nullable=False),
        sa.Column("nombre_servicio", sa.String(length=128), nullable=True),
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
        sa.PrimaryKeyConstraint("id_plantilla_despliegue", name="pk_plantillas_despliegue"),
        sa.UniqueConstraint("nombre", name="uq_plantillas_despliegue_nombre"),
    )
    op.create_index(
        "ix_plantillas_despliegue_activo", "plantillas_despliegue", ["activo"], unique=False
    )
    op.create_index(
        "ix_plantillas_despliegue_sistema_operativo",
        "plantillas_despliegue",
        ["sistema_operativo"],
        unique=False,
    )

    op.create_table(
        "aplicaciones_administradas",
        sa.Column(
            "id_aplicacion_administrada", sa.BigInteger(), autoincrement=True, nullable=False
        ),
        sa.Column("id_servidor", sa.BigInteger(), nullable=False),
        sa.Column("id_plantilla_despliegue", sa.BigInteger(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("version_actual", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["id_servidor"],
            ["servidores.id_servidor"],
            name="fk_aplicacion_servidor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_plantilla_despliegue"],
            ["plantillas_despliegue.id_plantilla_despliegue"],
            name="fk_aplicacion_plantilla",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id_aplicacion_administrada", name="pk_aplicaciones_administradas"),
        sa.UniqueConstraint(
            "id_servidor", "nombre", name="uq_aplicaciones_administradas_servidor_nombre"
        ),
    )
    op.create_index(
        "ix_aplicaciones_administradas_id_servidor",
        "aplicaciones_administradas",
        ["id_servidor"],
        unique=False,
    )
    op.create_index(
        "ix_aplicaciones_administradas_id_plantilla_despliegue",
        "aplicaciones_administradas",
        ["id_plantilla_despliegue"],
        unique=False,
    )
    op.create_index(
        "ix_aplicaciones_administradas_activo",
        "aplicaciones_administradas",
        ["activo"],
        unique=False,
    )

    op.create_table(
        "despliegues_aplicaciones",
        sa.Column("id_despliegue_aplicacion", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_aplicacion_administrada", sa.BigInteger(), nullable=False),
        sa.Column("id_usuario", sa.BigInteger(), nullable=True),
        sa.Column("nombre_usuario", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("version_anterior", sa.String(length=64), nullable=True),
        sa.Column("ruta_artefacto", sa.String(length=1024), nullable=False),
        sa.Column("ruta_respaldo", sa.String(length=1024), nullable=True),
        sa.Column("hash_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "estado",
            sa.Enum(
                "en_progreso",
                "completado",
                "fallido",
                "revertido",
                name="estado_despliegue_aplicacion",
            ),
            nullable=False,
        ),
        sa.Column("detalle_resultado", sa.Text(), nullable=True),
        sa.Column(
            "iniciado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finalizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revertido_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["id_aplicacion_administrada"],
            ["aplicaciones_administradas.id_aplicacion_administrada"],
            name="fk_despliegue_aplicacion",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_usuario"],
            ["usuarios.id_usuario"],
            name="fk_despliegue_usuario",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id_despliegue_aplicacion", name="pk_despliegues_aplicaciones"),
    )
    op.create_index(
        "ix_despliegues_aplicaciones_id_aplicacion_administrada",
        "despliegues_aplicaciones",
        ["id_aplicacion_administrada"],
        unique=False,
    )
    op.create_index(
        "ix_despliegues_aplicaciones_id_usuario",
        "despliegues_aplicaciones",
        ["id_usuario"],
        unique=False,
    )
    op.create_index(
        "ix_despliegues_aplicaciones_version", "despliegues_aplicaciones", ["version"], unique=False
    )
    op.create_index(
        "ix_despliegues_aplicaciones_estado", "despliegues_aplicaciones", ["estado"], unique=False
    )

    permisos = sa.table(
        "permisos",
        sa.column("id_permiso", sa.BigInteger()),
        sa.column("codigo", sa.String()),
        sa.column("descripcion", sa.String()),
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
                "id_permiso": 23,
                "codigo": "consultar_aplicaciones",
                "descripcion": "Consultar aplicaciones, despliegues y estado operativo.",
            },
            {
                "id_permiso": 24,
                "codigo": "gestionar_aplicaciones",
                "descripcion": "Crear plantillas y registrar aplicaciones administradas.",
            },
            {
                "id_permiso": 25,
                "codigo": "desplegar_aplicaciones",
                "descripcion": "Instalar versiones mediante plantillas autorizadas.",
            },
            {
                "id_permiso": 26,
                "codigo": "revertir_despliegues",
                "descripcion": "Restaurar el estado anterior de una aplicación.",
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            *({"id_rol": 1, "id_permiso": identificador} for identificador in range(23, 27)),
            {"id_rol": 2, "id_permiso": 23},
            {"id_rol": 2, "id_permiso": 25},
            {"id_rol": 3, "id_permiso": 23},
        ],
    )


def downgrade() -> None:
    """Retira historial, aplicaciones, plantillas y permisos del hito."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (23, 24, 25, 26)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (23, 24, 25, 26)"))
    op.drop_table("despliegues_aplicaciones")
    op.drop_table("aplicaciones_administradas")
    op.drop_table("plantillas_despliegue")
    op.execute(sa.text("DELETE FROM registros_auditoria WHERE tipo_recurso = 'aplicacion'"))
    op.alter_column(
        "registros_auditoria",
        "tipo_recurso",
        existing_type=sa.Enum(
            "servidor",
            "grupo",
            "usuario",
            "rol",
            "permiso",
            "asociacion",
            "autenticacion",
            "tarea",
            "aplicacion",
            name="tipo_recurso_auditoria",
        ),
        type_=sa.Enum(
            "servidor",
            "grupo",
            "usuario",
            "rol",
            "permiso",
            "asociacion",
            "autenticacion",
            "tarea",
            name="tipo_recurso_auditoria",
        ),
        existing_nullable=False,
    )
