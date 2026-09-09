"""Añade monitoreo automático, alertas, destinos y entregas.

Revisión: 0007
Revisión anterior: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0007"
identificador_anterior = "0006"
etiquetas_rama = None
dependencias = None

# Alembic exige estos cuatro identificadores con sus nombres convencionales.
revision: str = identificador_revision
down_revision: str | None = identificador_anterior
branch_labels: str | Sequence[str] | None = etiquetas_rama
depends_on: str | Sequence[str] | None = dependencias


def _columna_fecha(nombre: str) -> sa.Column:
    return sa.Column(
        nombre,
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    """Crea configuración, episodios deduplicados y notificaciones persistentes."""

    op.create_table(
        "configuraciones_monitoreo",
        sa.Column(
            "id_configuracion_monitoreo",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id_servidor", sa.BigInteger(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("umbral_cpu", sa.Float(), nullable=True),
        sa.Column("umbral_memoria", sa.Float(), nullable=True),
        sa.Column("umbral_disco", sa.Float(), nullable=True),
        _columna_fecha("creado_en"),
        _columna_fecha("actualizado_en"),
        sa.CheckConstraint(
            "umbral_cpu IS NULL OR umbral_cpu BETWEEN 0 AND 100",
            name="ck_configuraciones_monitoreo_umbral_cpu_valido",
        ),
        sa.CheckConstraint(
            "umbral_memoria IS NULL OR umbral_memoria BETWEEN 0 AND 100",
            name="ck_configuraciones_monitoreo_umbral_memoria_valido",
        ),
        sa.CheckConstraint(
            "umbral_disco IS NULL OR umbral_disco BETWEEN 0 AND 100",
            name="ck_configuraciones_monitoreo_umbral_disco_valido",
        ),
        sa.ForeignKeyConstraint(
            ["id_servidor"],
            ["servidores.id_servidor"],
            name="fk_configuraciones_monitoreo_id_servidor_servidores",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id_configuracion_monitoreo",
            name="pk_configuraciones_monitoreo",
        ),
        sa.UniqueConstraint(
            "id_servidor",
            name="uq_configuraciones_monitoreo_servidor",
        ),
    )
    op.create_index(
        "ix_configuraciones_monitoreo_id_servidor",
        "configuraciones_monitoreo",
        ["id_servidor"],
        unique=False,
    )

    op.create_table(
        "servicios_criticos_monitoreo",
        sa.Column("id_servicio_critico", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_configuracion_monitoreo", sa.BigInteger(), nullable=False),
        sa.Column("nombre_servicio", sa.String(length=128), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        _columna_fecha("creado_en"),
        _columna_fecha("actualizado_en"),
        sa.ForeignKeyConstraint(
            ["id_configuracion_monitoreo"],
            ["configuraciones_monitoreo.id_configuracion_monitoreo"],
            name="fk_servicios_criticos_configuracion_monitoreo",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_servicio_critico", name="pk_servicios_criticos_monitoreo"),
        sa.UniqueConstraint(
            "id_configuracion_monitoreo",
            "nombre_servicio",
            name="uq_servicios_criticos_configuracion_nombre",
        ),
    )
    op.create_index(
        "ix_servicios_criticos_monitoreo_id_configuracion_monitoreo",
        "servicios_criticos_monitoreo",
        ["id_configuracion_monitoreo"],
        unique=False,
    )

    op.create_table(
        "alertas",
        sa.Column("id_alerta", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_servidor", sa.BigInteger(), nullable=True),
        sa.Column("nombre_servidor", sa.String(length=100), nullable=False),
        sa.Column(
            "tipo",
            sa.Enum(
                "servidor_no_disponible",
                "cpu_alta",
                "memoria_alta",
                "disco_alto",
                "servicio_critico_no_activo",
                name="tipo_alerta",
            ),
            nullable=False,
        ),
        sa.Column("identificador_objetivo", sa.String(length=128), nullable=False),
        sa.Column("clave_activa", sa.String(length=64), nullable=True),
        sa.Column(
            "estado",
            sa.Enum("activa", "recuperada", name="estado_alerta"),
            nullable=False,
        ),
        sa.Column("mensaje_apertura", sa.String(length=500), nullable=False),
        sa.Column("mensaje_recuperacion", sa.String(length=500), nullable=True),
        sa.Column("valor_observado", sa.String(length=100), nullable=True),
        sa.Column("umbral", sa.Float(), nullable=True),
        _columna_fecha("detectada_en"),
        _columna_fecha("ultima_observacion_en"),
        sa.Column("recuperada_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["id_servidor"],
            ["servidores.id_servidor"],
            name="fk_alertas_id_servidor_servidores",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id_alerta", name="pk_alertas"),
        sa.UniqueConstraint("clave_activa", name="uq_alertas_clave_activa"),
    )
    op.create_index("ix_alertas_id_servidor", "alertas", ["id_servidor"], unique=False)
    op.create_index("ix_alertas_tipo", "alertas", ["tipo"], unique=False)
    op.create_index("ix_alertas_estado", "alertas", ["estado"], unique=False)
    op.create_index(
        "ix_alertas_detectada_en",
        "alertas",
        ["detectada_en"],
        unique=False,
    )

    op.create_table(
        "suscripciones_alertas",
        sa.Column(
            "id_suscripcion_alerta",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id_identidad_mensajeria", sa.BigInteger(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        _columna_fecha("creado_en"),
        _columna_fecha("actualizado_en"),
        sa.ForeignKeyConstraint(
            ["id_identidad_mensajeria"],
            ["identidades_mensajeria.id_identidad_mensajeria"],
            name="fk_suscripciones_alertas_identidad_mensajeria",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_suscripcion_alerta", name="pk_suscripciones_alertas"),
        sa.UniqueConstraint(
            "id_identidad_mensajeria",
            name="uq_suscripciones_alertas_identidad",
        ),
    )
    op.create_index(
        "ix_suscripciones_alertas_id_identidad_mensajeria",
        "suscripciones_alertas",
        ["id_identidad_mensajeria"],
        unique=False,
    )

    op.create_table(
        "notificaciones_alertas",
        sa.Column(
            "id_notificacion_alerta",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("id_alerta", sa.BigInteger(), nullable=False),
        sa.Column("id_identidad_mensajeria", sa.BigInteger(), nullable=True),
        sa.Column(
            "canal",
            sa.Enum("telegram", "slack", name="tipo_canal_mensajeria"),
            nullable=False,
        ),
        sa.Column(
            "fase",
            sa.Enum("apertura", "recuperacion", name="fase_notificacion_alerta"),
            nullable=False,
        ),
        sa.Column(
            "estado",
            sa.Enum(
                "pendiente",
                "enviada",
                "fallida",
                "omitida",
                name="estado_notificacion_alerta",
            ),
            nullable=False,
        ),
        sa.Column("intentos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        _columna_fecha("creada_en"),
        sa.Column("ultimo_intento_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enviada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "intentos >= 0",
            name="ck_notificaciones_alertas_intentos_no_negativos",
        ),
        sa.ForeignKeyConstraint(
            ["id_alerta"],
            ["alertas.id_alerta"],
            name="fk_notificaciones_alertas_id_alerta_alertas",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_identidad_mensajeria"],
            ["identidades_mensajeria.id_identidad_mensajeria"],
            name="fk_notificaciones_alertas_identidad_mensajeria",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id_notificacion_alerta", name="pk_notificaciones_alertas"),
        sa.UniqueConstraint(
            "id_alerta",
            "id_identidad_mensajeria",
            "fase",
            name="uq_notificaciones_alertas_alerta_identidad_fase",
        ),
    )
    op.create_index(
        "ix_notificaciones_alertas_id_alerta",
        "notificaciones_alertas",
        ["id_alerta"],
        unique=False,
    )
    op.create_index(
        "ix_notificaciones_alertas_id_identidad_mensajeria",
        "notificaciones_alertas",
        ["id_identidad_mensajeria"],
        unique=False,
    )
    op.create_index(
        "ix_notificaciones_alertas_estado",
        "notificaciones_alertas",
        ["estado"],
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
            {
                "id_permiso": 11,
                "codigo": "consultar_monitoreo",
                "descripcion": "Consultar configuraciones, destinos y alertas de monitoreo.",
            },
            {
                "id_permiso": 12,
                "codigo": "gestionar_monitoreo",
                "descripcion": "Configurar umbrales, servicios críticos y destinos de alertas.",
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 11},
            {"id_rol": 1, "id_permiso": 12},
            {"id_rol": 2, "id_permiso": 11},
            {"id_rol": 3, "id_permiso": 11},
        ],
    )


def downgrade() -> None:
    """Retira monitoreo y sus permisos sin afectar el inventario."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (11, 12)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (11, 12)"))
    op.drop_table("notificaciones_alertas")
    op.drop_table("suscripciones_alertas")
    op.drop_table("alertas")
    op.drop_table("servicios_criticos_monitoreo")
    op.drop_table("configuraciones_monitoreo")
