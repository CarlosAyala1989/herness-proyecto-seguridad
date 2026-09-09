"""Añade permisos separados de consulta y gestión de servicios.

Revisión: 0006
Revisión anterior: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0006"
identificador_anterior = "0005"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Concede consulta al operador y reserva las mutaciones al administrador."""

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
                "id_permiso": 9,
                "codigo": "consultar_servicios",
                "descripcion": "Consultar el estado de servicios remotos.",
            },
            {
                "id_permiso": 10,
                "codigo": "gestionar_servicios",
                "descripcion": "Iniciar, detener y reiniciar servicios remotos.",
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 9},
            {"id_rol": 1, "id_permiso": 10},
            {"id_rol": 2, "id_permiso": 9},
        ],
    )


def downgrade() -> None:
    """Retira las asociaciones y permisos de servicios."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (9, 10)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (9, 10)"))
