"""Añade identidades autorizadas para canales de mensajería.

Revisión: 0004
Revisión anterior: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0004"
identificador_anterior = "0003"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def upgrade() -> None:
    """Crea vínculos de Telegram y deja preparado el canal Slack."""

    op.create_table(
        "identidades_mensajeria",
        sa.Column(
            "id_identidad_mensajeria",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id_usuario", sa.BigInteger(), nullable=False),
        sa.Column(
            "canal",
            sa.Enum("telegram", "slack", name="tipo_canal_mensajeria"),
            nullable=False,
        ),
        sa.Column("identificador_externo", sa.String(length=100), nullable=False),
        sa.Column("nombre_externo", sa.String(length=100), nullable=True),
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
            ["id_usuario"],
            ["usuarios.id_usuario"],
            name="fk_identidades_mensajeria_id_usuario_usuarios",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id_identidad_mensajeria",
            name="pk_identidades_mensajeria",
        ),
        sa.UniqueConstraint(
            "canal",
            "identificador_externo",
            name="uq_identidades_mensajeria_canal_identificador",
        ),
        sa.UniqueConstraint(
            "id_usuario",
            "canal",
            name="uq_identidades_mensajeria_usuario_canal",
        ),
    )
    op.create_index(
        "ix_identidades_mensajeria_id_usuario",
        "identidades_mensajeria",
        ["id_usuario"],
        unique=False,
    )
    op.create_index(
        "ix_identidades_mensajeria_activo",
        "identidades_mensajeria",
        ["activo"],
        unique=False,
    )


def downgrade() -> None:
    """Elimina los vínculos externos sin modificar los usuarios Hermes."""

    op.drop_index(
        "ix_identidades_mensajeria_activo",
        table_name="identidades_mensajeria",
    )
    op.drop_index(
        "ix_identidades_mensajeria_id_usuario",
        table_name="identidades_mensajeria",
    )
    op.drop_table("identidades_mensajeria")
