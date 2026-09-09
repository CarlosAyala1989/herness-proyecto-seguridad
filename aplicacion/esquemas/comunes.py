"""Configuración compartida por los esquemas de respuesta."""

from pydantic import BaseModel, ConfigDict


class EsquemaDesdeAtributos(BaseModel):
    """Permite construir respuestas a partir de entidades SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)
