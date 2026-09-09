"""Validación de usuarios, roles y permisos."""

import re
from datetime import datetime

from pydantic import BaseModel, Field, SecretStr, field_validator

from aplicacion.esquemas.comunes import EsquemaDesdeAtributos

patron_nombre_usuario = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class CrearUsuario(BaseModel):
    """Solicitud para registrar un usuario autorizado."""

    nombre_usuario: str = Field(min_length=3, max_length=64)
    nombre_mostrar: str = Field(min_length=2, max_length=120)
    contrasena: SecretStr = Field(min_length=12, max_length=128)
    ids_roles: set[int] = Field(min_length=1, max_length=10)

    @field_validator("nombre_usuario")
    @classmethod
    def validar_nombre_usuario(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if not patron_nombre_usuario.fullmatch(valor):
            raise ValueError("El usuario solo admite letras minúsculas, números, puntos y guiones.")
        return valor


class ActualizarUsuario(BaseModel):
    """Campos permitidos al editar un usuario."""

    nombre_mostrar: str | None = Field(default=None, min_length=2, max_length=120)
    contrasena: SecretStr | None = Field(default=None, min_length=12, max_length=128)
    activo: bool | None = None


class PermisoRespuesta(EsquemaDesdeAtributos):
    """Permiso persistente expuesto sin datos internos."""

    id_permiso: int
    codigo: str
    descripcion: str


class RolRespuesta(EsquemaDesdeAtributos):
    """Rol y permisos que concede."""

    id_rol: int
    nombre: str
    descripcion: str
    es_sistema: bool
    permisos: list[PermisoRespuesta]


class UsuarioRespuesta(EsquemaDesdeAtributos):
    """Usuario autorizado sin su hash de contraseña."""

    id_usuario: int
    nombre_usuario: str
    nombre_mostrar: str
    activo: bool
    creado_en: datetime
    actualizado_en: datetime
    roles: list[RolRespuesta]
