"""${message}

Revisión: ${up_revision}
Revisión anterior: ${down_revision | comma,n}
Creada: ${create_date}
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

identificador_revision: str = ${repr(up_revision)}
identificador_anterior: str | Sequence[str] | None = ${repr(down_revision)}
etiquetas_rama: str | Sequence[str] | None = ${repr(branch_labels)}
dependencias: str | Sequence[str] | None = ${repr(depends_on)}

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision = identificador_revision
down_revision = identificador_anterior
branch_labels = etiquetas_rama
depends_on = dependencias


def upgrade() -> None:
    """Aplica los cambios del esquema."""

    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Revierte los cambios del esquema."""

    ${downgrades if downgrades else "pass"}
