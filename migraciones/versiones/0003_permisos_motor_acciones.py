"""Añade permisos para acciones remotas de lectura y reinicio.

Revisión: 0003
Revisión anterior: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0003"
identificador_anterior = "0002"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Registra permisos separados para lectura y reinicio sensible."""

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
                "id_permiso": 6,
                "codigo": "ejecutar_acciones_lectura",
                "descripcion": "Ejecutar acciones remotas predefinidas de solo lectura.",
            },
            {
                "id_permiso": 7,
                "codigo": "reiniciar_servidor",
                "descripcion": "Programar el reinicio confirmado de un servidor.",
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 6},
            {"id_rol": 1, "id_permiso": 7},
            {"id_rol": 2, "id_permiso": 6},
        ],
    )


def downgrade() -> None:
    """Retira asociaciones y permisos del motor de acciones."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (6, 7)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (6, 7)"))
