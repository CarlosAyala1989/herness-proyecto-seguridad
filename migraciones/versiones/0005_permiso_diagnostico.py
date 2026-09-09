"""Añade el permiso para consultar diagnósticos remotos.

Revisión: 0005
Revisión anterior: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0005"
identificador_anterior = "0004"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Concede diagnóstico al administrador y al operador de inventario."""

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
                "id_permiso": 8,
                "codigo": "consultar_diagnostico",
                "descripcion": "Consultar disponibilidad y métricas remotas normalizadas.",
            }
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 8},
            {"id_rol": 2, "id_permiso": 8},
        ],
    )


def downgrade() -> None:
    """Retira asociaciones y el permiso de diagnóstico."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso = 8"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso = 8"))
