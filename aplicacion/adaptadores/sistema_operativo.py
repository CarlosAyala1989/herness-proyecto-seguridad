"""Contrato normalizado para detectar el sistema operativo remoto."""

from dataclasses import dataclass
from typing import Protocol

from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.enumeraciones import SistemaOperativo


@dataclass(frozen=True, slots=True)
class SistemaRemotoDetectado:
    """Datos mínimos normalizados durante el saludo remoto."""

    sistema_operativo: SistemaOperativo
    version: str
    nombre_equipo: str


class AdaptadorSistemaOperativo(Protocol):
    """Define la detección controlada que cada plataforma debe implementar."""

    sistema_operativo: SistemaOperativo
    comando_deteccion: str

    def interpretar_deteccion(
        self,
        resultado: ResultadoEjecucionRemota,
    ) -> SistemaRemotoDetectado:
        """Valida y normaliza la respuesta de la plataforma."""
