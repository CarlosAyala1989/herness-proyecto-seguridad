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
    intervalo_mantenimiento_ssh_segundos: float = Field(default=15.0, gt=0, le=300)
    max_intentos_mantenimiento_ssh: int = Field(default=3, ge=1, le=10)
    max_concurrencia_acciones_multiples: int = Field(default=4, ge=1, le=32)
    max_servidores_accion_multiple: int = Field(default=100, ge=1, le=500)
    tiempo_limite_accion_multiple_segundos: float = Field(default=45.0, gt=0, le=600)

    telegram_habilitado: bool = False
    token_telegram: SecretStr | None = None
    tiempo_confirmacion_telegram_segundos: int = Field(default=60, ge=30, le=300)
    max_servidores_mostrados_telegram: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validar_configuracion_telegram(self) -> "Configuracion":
        """Exige un token no vacío únicamente cuando Telegram está habilitado."""

        if self.telegram_habilitado:
            token = self.token_telegram.get_secret_value() if self.token_telegram else ""
            if len(token) < 20 or ":" not in token or any(caracter.isspace() for caracter in token):
                raise ValueError("Telegram está habilitado pero su token no es válido.")
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
