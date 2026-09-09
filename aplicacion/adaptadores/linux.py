"""Detección inicial de servidores Linux."""

from aplicacion.adaptadores.sistema_operativo import SistemaRemotoDetectado
from aplicacion.conexiones.errores import ErrorSistemaOperativoNoCoincide
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.enumeraciones import SistemaOperativo


class AdaptadorLinux:
    """Usa únicamente un saludo fijo, sin parámetros recibidos del usuario."""

    sistema_operativo = SistemaOperativo.LINUX
    comando_deteccion = "printf 'HERMES_SO=linux\\n'; uname -s; uname -r; hostname"

    def interpretar_deteccion(
        self,
        resultado: ResultadoEjecucionRemota,
    ) -> SistemaRemotoDetectado:
        lineas = [linea.strip() for linea in resultado.salida.splitlines()]
        if (
            resultado.codigo_salida != 0
            or len(lineas) < 4
            or lineas[0] != "HERMES_SO=linux"
            or lineas[1].casefold() != "linux"
        ):
            raise ErrorSistemaOperativoNoCoincide()
        return SistemaRemotoDetectado(
            sistema_operativo=self.sistema_operativo,
            version=lineas[2][:200],
            nombre_equipo=lineas[3][:255],
        )
