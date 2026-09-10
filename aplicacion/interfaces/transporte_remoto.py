"""Contrato independiente del mecanismo concreto de conexión remota."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ResultadoEjecucionRemota:
    """Resultado normalizado y acotado de una ejecución remota."""

    codigo_salida: int
    salida: str
    error: str
    duracion_segundos: float


@dataclass(frozen=True, slots=True)
class InformacionArchivoRemoto:
    """Metadatos de archivo normalizados entre servidores."""

    ruta_remota: str
    nombre_archivo: str
    tipo: str
    tamano_bytes: int | None
    modificado_en: datetime | None


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

    async def consultar_informacion_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
    ) -> InformacionArchivoRemoto:
        """Consulta metadatos después de comprobar la ruta canónica."""

    async def descargar_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
        limite_bytes: int,
        tamano_bloque_bytes: int,
    ) -> tuple[InformacionArchivoRemoto, bytes]:
        """Descarga un archivo regular dentro del límite indicado."""

    async def cargar_archivo(
        self,
        ruta_remota: str,
        contenido: bytes,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
        tamano_bloque_bytes: int,
        sobrescribir: bool,
    ) -> bool:
        """Carga contenido y devuelve si reemplazó un archivo existente."""

    async def eliminar_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
    ) -> None:
        """Elimina un archivo regular confinado a una raíz de escritura."""

    async def cerrar(self) -> None:
        """Libera la conexión y sus recursos."""
