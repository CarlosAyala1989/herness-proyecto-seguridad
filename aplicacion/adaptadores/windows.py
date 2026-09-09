"""Detección inicial de servidores Windows Server mediante PowerShell."""

from aplicacion.adaptadores.sistema_operativo import SistemaRemotoDetectado
from aplicacion.conexiones.errores import ErrorSistemaOperativoNoCoincide
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.enumeraciones import SistemaOperativo


class AdaptadorWindows:
    """Invoca PowerShell explícitamente aunque OpenSSH use otro shell predeterminado."""

    sistema_operativo = SistemaOperativo.WINDOWS_SERVER
    comando_deteccion = (
        'powershell.exe -NoLogo -NoProfile -NonInteractive -Command "'
        "$ErrorActionPreference='Stop'; "
        "'HERMES_SO=windows_server'; "
        "$sistema=Get-CimInstance Win32_OperatingSystem; "
        '$sistema.Caption; $sistema.Version; [Environment]::MachineName"'
    )

    def interpretar_deteccion(
        self,
        resultado: ResultadoEjecucionRemota,
    ) -> SistemaRemotoDetectado:
        lineas = [linea.strip() for linea in resultado.salida.splitlines()]
        if (
            resultado.codigo_salida != 0
            or len(lineas) < 4
            or lineas[0] != "HERMES_SO=windows_server"
            or "windows server" not in lineas[1].casefold()
        ):
            raise ErrorSistemaOperativoNoCoincide()
        return SistemaRemotoDetectado(
            sistema_operativo=self.sistema_operativo,
            version=f"{lineas[1]} {lineas[2]}"[:200],
            nombre_equipo=lineas[3][:255],
        )
