"""Añade el permiso para comprobar conexiones SSH.

Revisión: 0002
Revisión anterior: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0002"
identificador_anterior = "0001"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Registra el permiso y lo concede a administradores y operadores."""

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
                "id_permiso": 5,
                "codigo": "comprobar_conexion",
                "descripcion": "Comprobar identidad, autenticación y plataforma mediante SSH.",
            }
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 5},
            {"id_rol": 2, "id_permiso": 5},
        ],
    )


def downgrade() -> None:
    """Retira las asociaciones antes de eliminar el permiso."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso = 5"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso = 5"))
