"""Carga y validación de la configuración de Hermes."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


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
    version_aplicacion: str = "0.1.0"
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
