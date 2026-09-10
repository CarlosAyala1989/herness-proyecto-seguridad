"""Añade permisos para administrar usuarios locales remotos.

Revisión: 0009
Revisión anterior: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0009"
identificador_anterior = "0008"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Registra permisos separados de consulta, gestión, protección y borrado."""

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
                "id_permiso": 15,
                "codigo": "consultar_usuarios_sistema",
                "descripcion": "Consultar usuarios y grupos locales de servidores autorizados.",
            },
            {
                "id_permiso": 16,
                "codigo": "gestionar_usuarios_sistema",
                "descripcion": "Crear, bloquear, habilitar y cambiar grupos de usuarios locales.",
            },
            {
                "id_permiso": 17,
                "codigo": "gestionar_usuarios_protegidos",
                "descripcion": "Autorizar expresamente cambios sobre cuentas locales protegidas.",
            },
            {
                "id_permiso": 18,
                "codigo": "eliminar_usuarios_sistema",
                "descripcion": "Eliminar cuentas locales mediante confirmación reforzada.",
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 15},
            {"id_rol": 1, "id_permiso": 16},
            {"id_rol": 1, "id_permiso": 17},
            {"id_rol": 1, "id_permiso": 18},
            {"id_rol": 2, "id_permiso": 15},
            {"id_rol": 3, "id_permiso": 15},
        ],
    )


def downgrade() -> None:
    """Retira exclusivamente los permisos de usuarios del sistema."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (15, 16, 17, 18)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (15, 16, 17, 18)"))
