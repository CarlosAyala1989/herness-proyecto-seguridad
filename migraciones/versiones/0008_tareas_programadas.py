"""Añade tareas programadas, ejecuciones y entregas.

Revisión: 0008
Revisión anterior: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

identificador_revision = "0008"
identificador_anterior = "0007"
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
    """Crea el calendario, su historial idempotente y sus notificaciones."""

    op.create_table(
        "tareas_programadas",
        sa.Column("id_tarea_programada", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_usuario_creador", sa.BigInteger(), nullable=True),
        sa.Column("nombre_usuario_creador", sa.String(length=64), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("codigo_accion", sa.String(length=100), nullable=False),
        sa.Column("parametros", sa.JSON(), nullable=False),
        sa.Column("ids_servidores", sa.JSON(), nullable=False),
        sa.Column(
            "tipo_programacion",
            sa.Enum("una_vez", "intervalo", name="tipo_programacion_tarea"),
            nullable=False,
        ),
        sa.Column(
            "estado",
            sa.Enum("activa", "cancelada", "completada", name="estado_tarea_programada"),
            nullable=False,
        ),
        sa.Column("programada_inicialmente_para", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proxima_ejecucion_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intervalo_segundos", sa.Integer(), nullable=True),
        sa.Column("confirmacion_otorgada", sa.Boolean(), nullable=False),
        sa.Column("notificar_resultado", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("token_bloqueo", sa.String(length=36), nullable=True),
        sa.Column("bloqueada_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelada_en", sa.DateTime(timezone=True), nullable=True),
        _columna_fecha("creado_en"),
        _columna_fecha("actualizado_en"),
        sa.CheckConstraint(
            "(tipo_programacion = 'una_vez' AND intervalo_segundos IS NULL) OR "
            "(tipo_programacion = 'intervalo' AND intervalo_segundos >= 60)",
            name="ck_tareas_programadas_programacion_intervalo_valida",
        ),
        sa.ForeignKeyConstraint(
            ["id_usuario_creador"],
            ["usuarios.id_usuario"],
            name="fk_tareas_programadas_id_usuario_creador_usuarios",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id_tarea_programada", name="pk_tareas_programadas"),
    )
    op.create_index(
        "ix_tareas_programadas_id_usuario_creador",
        "tareas_programadas",
        ["id_usuario_creador"],
        unique=False,
    )
    op.create_index(
        "ix_tareas_programadas_estado",
        "tareas_programadas",
        ["estado"],
        unique=False,
    )
    op.create_index(
        "ix_tareas_programadas_proxima_ejecucion_en",
        "tareas_programadas",
        ["proxima_ejecucion_en"],
        unique=False,
    )

    op.create_table(
        "ejecuciones_tareas",
        sa.Column("id_ejecucion_tarea", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_tarea_programada", sa.BigInteger(), nullable=False),
        sa.Column("programada_para", sa.DateTime(timezone=True), nullable=False),
        _columna_fecha("iniciada_en"),
        sa.Column("finalizada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "estado",
            sa.Enum(
                "en_ejecucion",
                "completada",
                "completada_con_errores",
                "fallida",
                "interrumpida",
                name="estado_ejecucion_tarea",
            ),
            nullable=False,
        ),
        sa.Column("resumen_resultado", sa.JSON(), nullable=True),
        sa.Column("detalle_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["id_tarea_programada"],
            ["tareas_programadas.id_tarea_programada"],
            name="fk_ejecuciones_tareas_id_tarea_programada_tareas_programadas",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id_ejecucion_tarea", name="pk_ejecuciones_tareas"),
        sa.UniqueConstraint(
            "id_tarea_programada",
            "programada_para",
            name="uq_ejecuciones_tareas_tarea_programada_para",
        ),
    )
    op.create_index(
        "ix_ejecuciones_tareas_id_tarea_programada",
        "ejecuciones_tareas",
        ["id_tarea_programada"],
        unique=False,
    )
    op.create_index(
        "ix_ejecuciones_tareas_estado",
        "ejecuciones_tareas",
        ["estado"],
        unique=False,
    )

    op.create_table(
        "notificaciones_tareas",
        sa.Column("id_notificacion_tarea", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id_ejecucion_tarea", sa.BigInteger(), nullable=False),
        sa.Column("id_identidad_mensajeria", sa.BigInteger(), nullable=True),
        sa.Column(
            "canal",
            sa.Enum("telegram", "slack", name="tipo_canal_mensajeria"),
            nullable=False,
        ),
        sa.Column(
            "estado",
            sa.Enum("pendiente", "enviada", "fallida", name="estado_notificacion_tarea"),
            nullable=False,
        ),
        sa.Column("intentos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        _columna_fecha("creada_en"),
        sa.Column("ultimo_intento_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enviada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "intentos >= 0",
            name="ck_notificaciones_tareas_intentos_no_negativos",
        ),
        sa.ForeignKeyConstraint(
            ["id_ejecucion_tarea"],
            ["ejecuciones_tareas.id_ejecucion_tarea"],
            name="fk_notificaciones_tareas_id_ejecucion_tarea_ejecuciones_tareas",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["id_identidad_mensajeria"],
            ["identidades_mensajeria.id_identidad_mensajeria"],
            name="fk_notificaciones_tareas_identidad_mensajeria",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id_notificacion_tarea", name="pk_notificaciones_tareas"),
        sa.UniqueConstraint(
            "id_ejecucion_tarea",
            "id_identidad_mensajeria",
            name="uq_notificaciones_tareas_ejecucion_identidad",
        ),
    )
    op.create_index(
        "ix_notificaciones_tareas_id_ejecucion_tarea",
        "notificaciones_tareas",
        ["id_ejecucion_tarea"],
        unique=False,
    )
    op.create_index(
        "ix_notificaciones_tareas_id_identidad_mensajeria",
        "notificaciones_tareas",
        ["id_identidad_mensajeria"],
        unique=False,
    )
    op.create_index(
        "ix_notificaciones_tareas_estado",
        "notificaciones_tareas",
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
                "id_permiso": 13,
                "codigo": "consultar_tareas",
                "descripcion": "Consultar tareas programadas y su historial de ejecuciones.",
            },
            {
                "id_permiso": 14,
                "codigo": "gestionar_tareas",
                "descripcion": "Crear y cancelar tareas administrativas programadas.",
            },
        ],
    )
    op.bulk_insert(
        asociaciones,
        [
            {"id_rol": 1, "id_permiso": 13},
            {"id_rol": 1, "id_permiso": 14},
            {"id_rol": 2, "id_permiso": 13},
            {"id_rol": 2, "id_permiso": 14},
            {"id_rol": 3, "id_permiso": 13},
        ],
    )


def downgrade() -> None:
    """Retira tareas y permisos sin afectar acciones ni mensajería."""

    op.execute(sa.text("DELETE FROM roles_permisos WHERE id_permiso IN (13, 14)"))
    op.execute(sa.text("DELETE FROM permisos WHERE id_permiso IN (13, 14)"))
    op.drop_table("notificaciones_tareas")
    op.drop_table("ejecuciones_tareas")
    op.drop_table("tareas_programadas")
