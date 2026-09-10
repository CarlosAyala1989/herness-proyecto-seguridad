"""Añade raíces permitidas y permisos de transferencia SFTP.

Revisión: 0010
Revisión anterior: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Crea la lista blanca de rutas y permisos separados por capacidad."""

    op.create_table(
        "rutas_archivos_permitidas",
        sa.Column("id_ruta_archivo_permitida", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_servidor", sa.BigInteger(), nullable=False),
        sa.Column("ruta", sa.String(length=1024), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=True),
        sa.Column("permite_lectura", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("permite_escritura", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "permite_lectura = 1 OR permite_escritura = 1",
            name="ck_rutas_archivos_permitidas_alguna_operacion_habilitada",
        ),
        sa.ForeignKeyConstraint(
            ["id_servidor"],
            ["servidores.id_servidor"],
            name="fk_rutas_archivos_permitidas_id_servidor_servidores",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_ruta_archivo_permitida", name="pk_rutas_archivos_permitidas"),
        sa.UniqueConstraint(
            "id_servidor",
            "ruta",
            name="uq_rutas_archivos_permitidas_servidor_ruta",
        ),
    )
    op.create_index(
        "ix_rutas_archivos_permitidas_id_servidor",
        "rutas_archivos_permitidas",
        ["id_servidor"],
        unique=False,
    )
    op.create_index(
        "ix_rutas_archivos_permitidas_activo",
        "rutas_archivos_permitidas",
        ["activo"],
        unique=False,
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
            {"id_permiso": 19, "codigo": "consultar_archivos", "descripcion": "Consultar metadatos de archivos en rutas remotas permitidas."},
            {"id_permiso": 20, "codigo": "descargar_archivos", "descripcion": "Descargar archivos desde rutas remotas permitidas."},
            {"id_permiso": 21, "codigo": "cargar_archivos", "descripcion": "Cargar archivos en rutas remotas permitidas."},
            {"id_permiso": 22, "codigo": "gestionar_rutas_archivos", "descripcion": "Administrar las raíces remotas permitidas por servidor."},
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            *({"id_rol": 1, "id_permiso": identificador} for identificador in range(19, 23)),
            {"id_rol": 2, "id_permiso": 19},
            {"id_rol": 2, "id_permiso": 20},
            {"id_rol": 2, "id_permiso": 21},
            {"id_rol": 3, "id_permiso": 19},
        ],
    )


def downgrade() -> None:
    """Retira únicamente los elementos incorporados en este hito."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (19, 20, 21, 22)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (19, 20, 21, 22)"))
    op.drop_index("ix_rutas_archivos_permitidas_activo", table_name="rutas_archivos_permitidas")
    op.drop_index("ix_rutas_archivos_permitidas_id_servidor", table_name="rutas_archivos_permitidas")
    op.drop_table("rutas_archivos_permitidas")
