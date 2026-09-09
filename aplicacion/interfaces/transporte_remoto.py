"""Contrato independiente del mecanismo concreto de conexión remota."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResultadoEjecucionRemota:
    """Resultado normalizado y acotado de una ejecución remota."""

    codigo_salida: int
    salida: str
    error: str
    duracion_segundos: float


class TransporteRemoto(Protocol):
    """Puerto que implementará el transporte SSH seguro en el hito 3."""

    async def comprobar_disponibilidad(self) -> bool:
        """Indica si el servidor remoto está disponible."""

    async def ejecutar_comando_controlado(
        self,
        comando: str,
        tiempo_limite_segundos: float,
        limite_salida_bytes: int,
    ) -> ResultadoEjecucionRemota:
        """Ejecuta un comando generado por una operación autorizada del backend."""

    async def cerrar(self) -> None:
        """Libera la conexión y sus recursos."""
