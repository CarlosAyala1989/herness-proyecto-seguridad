"""Tipos compartidos por los adaptadores de acciones remotas."""

from dataclasses import dataclass

from aplicacion.acciones.registro import CodigoAccion


@dataclass(frozen=True, slots=True)
class AccionRemotaPreparada:
    """Comando interno generado después de validar todos los parámetros."""

    codigo: CodigoAccion
    comando: str
