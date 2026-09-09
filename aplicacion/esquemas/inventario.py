"""Validación de servidores, grupos y asociaciones."""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from aplicacion.esquemas.comunes import EsquemaDesdeAtributos
from aplicacion.modelos.enumeraciones import SistemaOperativo, TipoCredencialConexion

patron_nombre = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,99}$")
patron_direccion = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.:-]{0,254}$")
patron_usuario_conexion = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._@\\-]{0,99}$")
patron_referencia = re.compile(r"^[a-z][a-z0-9_]{1,30}:[a-zA-Z0-9._/-]{1,220}$")
patron_huella_host = re.compile(r"^SHA256:[a-zA-Z0-9+/]{20,64}={0,2}$")


def _validar_patron(valor: str, patron: re.Pattern[str], mensaje: str) -> str:
    valor = valor.strip()
    if not patron.fullmatch(valor):
        raise ValueError(mensaje)
    return valor


class DatosServidorBase(BaseModel):
    """Campos editables de un servidor."""

    nombre: str = Field(min_length=2, max_length=100)
    descripcion: str | None = Field(default=None, max_length=500)
    direccion: str = Field(min_length=1, max_length=255)
    puerto_ssh: int = Field(default=22, ge=1, le=65535)
    usuario_conexion: str = Field(min_length=1, max_length=100)
    sistema_operativo: SistemaOperativo
    tipo_credencial: TipoCredencialConexion = TipoCredencialConexion.CLAVE_SSH
    referencia_credencial: str = Field(min_length=3, max_length=255)
    huella_clave_host: str | None = Field(default=None, min_length=16, max_length=255)
    activo: bool = True

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        return _validar_patron(
            valor,
            patron_nombre,
            "El nombre solo admite letras, números, puntos, guiones y guiones bajos.",
        )

    @field_validator("direccion")
    @classmethod
    def validar_direccion(cls, valor: str) -> str:
        return _validar_patron(
            valor,
            patron_direccion,
            "La dirección no tiene un formato de IP o nombre de equipo válido.",
        )

    @field_validator("usuario_conexion")
    @classmethod
    def validar_usuario_conexion(cls, valor: str) -> str:
        return _validar_patron(
            valor,
            patron_usuario_conexion,
            "El usuario de conexión contiene caracteres no permitidos.",
        )

    @field_validator("referencia_credencial")
    @classmethod
    def validar_referencia_credencial(cls, valor: str) -> str:
        return _validar_patron(
            valor,
            patron_referencia,
            "La referencia debe usar el formato proveedor:identificador.",
        )

    @field_validator("huella_clave_host")
    @classmethod
    def validar_huella_host(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(
            valor,
            patron_huella_host,
            "La huella del host debe tener formato SHA256 de OpenSSH.",
        )


class CrearServidor(DatosServidorBase):
    """Solicitud para registrar un servidor."""


class ActualizarServidor(BaseModel):
    """Campos opcionales para editar parcialmente un servidor."""

    nombre: str | None = Field(default=None, min_length=2, max_length=100)
    descripcion: str | None = Field(default=None, max_length=500)
    direccion: str | None = Field(default=None, min_length=1, max_length=255)
    puerto_ssh: int | None = Field(default=None, ge=1, le=65535)
    usuario_conexion: str | None = Field(default=None, min_length=1, max_length=100)
    sistema_operativo: SistemaOperativo | None = None
    tipo_credencial: TipoCredencialConexion | None = None
    referencia_credencial: str | None = Field(default=None, min_length=3, max_length=255)
    huella_clave_host: str | None = Field(default=None, min_length=16, max_length=255)
    activo: bool | None = None

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(valor, patron_nombre, "El nombre no tiene un formato válido.")

    @field_validator("direccion")
    @classmethod
    def validar_direccion(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(valor, patron_direccion, "La dirección no es válida.")

    @field_validator("usuario_conexion")
    @classmethod
    def validar_usuario(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(valor, patron_usuario_conexion, "El usuario no es válido.")

    @field_validator("referencia_credencial")
    @classmethod
    def validar_referencia(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(valor, patron_referencia, "La referencia no es válida.")

    @field_validator("huella_clave_host")
    @classmethod
    def validar_huella_host(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(
            valor,
            patron_huella_host,
            "La huella del host debe tener formato SHA256 de OpenSSH.",
        )


class ServidorResumen(EsquemaDesdeAtributos):
    """Representación breve de un servidor."""

    id_servidor: int
    nombre: str
    direccion: str
    puerto_ssh: int
    sistema_operativo: SistemaOperativo
    activo: bool


class ServidorDetalle(ServidorResumen):
    """Representación completa sin incluir secretos."""

    descripcion: str | None
    usuario_conexion: str
    tipo_credencial: TipoCredencialConexion
    referencia_credencial: str
    huella_clave_host: str | None
    creado_en: datetime
    actualizado_en: datetime
    ids_grupos: list[int] = Field(default_factory=list)


class DatosGrupoBase(BaseModel):
    """Campos editables de un grupo de servidores."""

    nombre: str = Field(min_length=2, max_length=100)
    descripcion: str | None = Field(default=None, max_length=500)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        return _validar_patron(valor, patron_nombre, "El nombre del grupo no es válido.")


class CrearGrupo(DatosGrupoBase):
    """Solicitud para registrar un grupo."""


class ActualizarGrupo(BaseModel):
    """Campos opcionales para editar un grupo."""

    nombre: str | None = Field(default=None, min_length=2, max_length=100)
    descripcion: str | None = Field(default=None, max_length=500)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _validar_patron(valor, patron_nombre, "El nombre del grupo no es válido.")


class GrupoDetalle(EsquemaDesdeAtributos):
    """Grupo con sus servidores asociados."""

    id_grupo: int
    nombre: str
    descripcion: str | None
    creado_en: datetime
    actualizado_en: datetime
    servidores: list[ServidorResumen] = Field(default_factory=list)
