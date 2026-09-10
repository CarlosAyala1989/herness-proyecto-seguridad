"""Carga y validación de la configuración de Hermes."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from aplicacion import __version__


class Configuracion(BaseSettings):
    """Configuración validada obtenida del entorno y del archivo local `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HERMES_",
        case_sensitive=False,
        extra="ignore",
    )

    nombre_aplicacion: str = "Hermes"
    version_aplicacion: str = __version__
    entorno: Literal["desarrollo", "pruebas", "produccion"] = "desarrollo"
    host_api: str = "127.0.0.1"
    puerto_api: int = Field(default=8000, ge=1, le=65535)
    nivel_log: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    host_base_datos: str = "127.0.0.1"
    puerto_base_datos: int = Field(default=3378, ge=1, le=65535)
    nombre_base_datos: str = Field(pattern=r"^[a-zA-Z0-9_]+$")
    usuario_base_datos: str = Field(min_length=1)
    contrasena_base_datos: SecretStr
    tiempo_espera_base_datos_segundos: float = Field(default=5.0, gt=0, le=60)

    directorio_credenciales_ssh: Path = Path(".secretos/claves_ssh")
    archivo_hosts_conocidos_ssh: Path = Path(".secretos/hosts_conocidos")
    tiempo_conexion_ssh_segundos: float = Field(default=10.0, gt=0, le=120)
    tiempo_autenticacion_ssh_segundos: float = Field(default=10.0, gt=0, le=120)
    tiempo_operacion_ssh_segundos: float = Field(default=15.0, gt=0, le=300)
    limite_salida_ssh_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    limite_archivo_transferencia_bytes: int = Field(default=8_388_608, ge=1_024, le=52_428_800)
    tamano_bloque_transferencia_bytes: int = Field(default=65_536, ge=4_096, le=1_048_576)
    intervalo_mantenimiento_ssh_segundos: float = Field(default=15.0, gt=0, le=300)
    max_intentos_mantenimiento_ssh: int = Field(default=3, ge=1, le=10)
    max_concurrencia_acciones_multiples: int = Field(default=4, ge=1, le=32)
    max_servidores_accion_multiple: int = Field(default=100, ge=1, le=500)
    tiempo_limite_accion_multiple_segundos: float = Field(default=45.0, gt=0, le=600)

    telegram_habilitado: bool = False
    token_telegram: SecretStr | None = None
    tiempo_confirmacion_telegram_segundos: int = Field(default=60, ge=30, le=300)
    max_servidores_mostrados_telegram: int = Field(default=50, ge=1, le=100)

    slack_habilitado: bool = False
    token_bot_slack: SecretStr | None = None
    token_aplicacion_slack: SecretStr | None = None
    tiempo_confirmacion_slack_segundos: int = Field(default=60, ge=30, le=300)
    max_servidores_mostrados_slack: int = Field(default=50, ge=1, le=100)

    monitoreo_habilitado: bool = False
    intervalo_monitoreo_segundos: float = Field(default=60.0, ge=10, le=86_400)
    max_concurrencia_monitoreo: int = Field(default=4, ge=1, le=32)
    tiempo_limite_sondeo_segundos: float = Field(default=45.0, gt=0, le=600)
    max_intentos_notificacion_alerta: int = Field(default=3, ge=1, le=10)

    tareas_habilitadas: bool = False
    intervalo_revision_tareas_segundos: float = Field(default=15.0, ge=1, le=3_600)
    duracion_bloqueo_tarea_segundos: int = Field(default=600, ge=60, le=3_600)
    max_tareas_por_ciclo: int = Field(default=20, ge=1, le=100)
    max_concurrencia_tareas: int = Field(default=2, ge=1, le=16)
    max_intentos_notificacion_tarea: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validar_configuracion_telegram(self) -> "Configuracion":
        """Exige un token no vacío únicamente cuando Telegram está habilitado."""

        if self.telegram_habilitado:
            token = self.token_telegram.get_secret_value() if self.token_telegram else ""
            if len(token) < 20 or ":" not in token or any(caracter.isspace() for caracter in token):
                raise ValueError("Telegram está habilitado pero su token no es válido.")
        return self

    @model_validator(mode="after")
    def validar_configuracion_slack(self) -> "Configuracion":
        """Exige los dos tokens de Socket Mode solo al habilitar Slack."""

        if not self.slack_habilitado:
            return self
        token_bot = self.token_bot_slack.get_secret_value() if self.token_bot_slack else ""
        token_aplicacion = (
            self.token_aplicacion_slack.get_secret_value() if self.token_aplicacion_slack else ""
        )
        if (
            not token_bot.startswith("xoxb-")
            or len(token_bot) < 20
            or any(caracter.isspace() for caracter in token_bot)
        ):
            raise ValueError("Slack está habilitado pero el token del bot no es válido.")
        if (
            not token_aplicacion.startswith("xapp-")
            or len(token_aplicacion) < 20
            or any(caracter.isspace() for caracter in token_aplicacion)
        ):
            raise ValueError("Slack está habilitado pero el token de aplicación no es válido.")
        return self

    @model_validator(mode="after")
    def validar_bloqueo_tareas(self) -> "Configuracion":
        """Mantiene el bloqueo por encima del plazo máximo de una acción."""

        if self.duracion_bloqueo_tarea_segundos <= self.tiempo_limite_accion_multiple_segundos:
            raise ValueError(
                "La duración del bloqueo de tareas debe superar el tiempo límite de acciones."
            )
        return self

    def construir_url_base_datos(self) -> URL:
        """Construye la URL sin concatenar ni registrar la contraseña en texto claro."""

        return URL.create(
            drivername="mysql+asyncmy",
            username=self.usuario_base_datos,
            password=self.contrasena_base_datos.get_secret_value(),
            host=self.host_base_datos,
            port=self.puerto_base_datos,
            database=self.nombre_base_datos,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def obtener_configuracion() -> Configuracion:
    """Devuelve una única configuración validada por proceso."""

    return Configuracion()  # type: ignore[call-arg]
