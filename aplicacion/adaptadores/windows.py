"""Detección y acciones controladas para Windows Server mediante PowerShell."""

from base64 import b64encode

from aplicacion.acciones.errores import ErrorEjecucionAccion, ErrorRespuestaAccionNoValida
from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosAccion,
    ParametrosConsultaProceso,
)
from aplicacion.adaptadores.acciones import AccionRemotaPreparada
from aplicacion.adaptadores.diagnostico import interpretar_diagnostico
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

    guion_diagnostico = r"""
$ErrorActionPreference = 'Stop'
$no_disponible = 'no_disponible'
$cultura = [Globalization.CultureInfo]::InvariantCulture

$cpu_porcentaje = $no_disponible
try {
    $cargas = @(Get-CimInstance Win32_Processor | Where-Object { $null -ne $_.LoadPercentage })
    if ($cargas.Count -gt 0) {
        $promedio = ($cargas | Measure-Object -Property LoadPercentage -Average).Average
        $cpu_porcentaje = ([double]$promedio).ToString('F2', $cultura)
    }
} catch {}

$sistema = $null
try { $sistema = Get-CimInstance Win32_OperatingSystem } catch {}

$memoria_porcentaje = $no_disponible
if ($null -ne $sistema -and [double]$sistema.TotalVisibleMemorySize -gt 0) {
    $memoria = 100 * (1 - ([double]$sistema.FreePhysicalMemory / [double]$sistema.TotalVisibleMemorySize))
    $memoria_porcentaje = $memoria.ToString('F2', $cultura)
}

$disco_porcentaje = $no_disponible
try {
    $disco = Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DeviceID -eq $env:SystemDrive } | Select-Object -First 1
    if ($null -ne $disco -and [double]$disco.Size -gt 0) {
        $disco_usado = 100 * (1 - ([double]$disco.FreeSpace / [double]$disco.Size))
        $disco_porcentaje = $disco_usado.ToString('F2', $cultura)
    }
} catch {}

$tiempo_actividad_segundos = $no_disponible
if ($null -ne $sistema -and $null -ne $sistema.LastBootUpTime) {
    $tiempo_actividad_segundos = [string][math]::Floor(((Get-Date) - $sistema.LastBootUpTime).TotalSeconds)
}

$nombre_sistema = if ($null -ne $sistema -and $sistema.Caption) { [string]$sistema.Caption } else { $no_disponible }
$version = if ($null -ne $sistema -and $sistema.Version) { [string]$sistema.Version } else { $no_disponible }
$nombre_equipo = if ([Environment]::MachineName) { [Environment]::MachineName } else { $no_disponible }

Write-Output 'HERMES_ACCION=obtener_diagnostico'
Write-Output 'estado=disponible'
Write-Output "cpu_porcentaje=$cpu_porcentaje"
Write-Output "memoria_porcentaje=$memoria_porcentaje"
Write-Output "disco_porcentaje=$disco_porcentaje"
Write-Output "tiempo_actividad_segundos=$tiempo_actividad_segundos"
Write-Output "sistema=$nombre_sistema"
Write-Output "version=$version"
Write-Output "nombre_equipo=$nombre_equipo"
"""

    @staticmethod
    def _codificar_guion_powershell(guion: str) -> str:
        """Codifica un guion fijo para evitar capas frágiles de comillas."""

        return b64encode(guion.encode("utf-16-le")).decode("ascii")

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

    def preparar_accion(
        self,
        codigo: CodigoAccion,
        parametros: ParametrosAccion,
    ) -> AccionRemotaPreparada:
        """Selecciona una instrucción PowerShell fija por operación."""

        prefijo = (
            'powershell.exe -NoLogo -NoProfile -NonInteractive -Command "'
            "$ErrorActionPreference='Stop'; "
        )
        if codigo is CodigoAccion.OBTENER_IDENTIDAD:
            cuerpo = (
                "'HERMES_ACCION=obtener_identidad'; "
                "[Environment]::UserName; [Environment]::MachineName"
            )
        elif codigo is CodigoAccion.CONSULTAR_PROCESO and isinstance(
            parametros, ParametrosConsultaProceso
        ):
            cuerpo = (
                f"$proceso=Get-Process -Id {parametros.id_proceso}; "
                "'HERMES_ACCION=consultar_proceso'; "
                "$proceso.Id; $proceso.ProcessName"
            )
        elif codigo is CodigoAccion.REINICIAR_SERVIDOR:
            cuerpo = (
                "shutdown.exe /r /t 60 /f /d p:0:0 "
                "/c 'Reinicio autorizado por Hermes'; "
                "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
                "'HERMES_ACCION=reiniciar_servidor'; 'PROGRAMADO'"
            )
        elif codigo is CodigoAccion.OBTENER_DIAGNOSTICO:
            guion_codificado = self._codificar_guion_powershell(self.guion_diagnostico)
            return AccionRemotaPreparada(
                codigo=codigo,
                comando=(
                    "powershell.exe -NoLogo -NoProfile -NonInteractive "
                    f"-EncodedCommand {guion_codificado}"
                ),
            )
        else:
            raise ErrorRespuestaAccionNoValida()
        return AccionRemotaPreparada(codigo=codigo, comando=f'{prefijo}{cuerpo}"')

    def interpretar_accion(
        self,
        codigo: CodigoAccion,
        resultado: ResultadoEjecucionRemota,
    ) -> dict[str, str | int | float | bool | None]:
        """Normaliza la salida PowerShell con los mismos campos que Linux."""

        if codigo is CodigoAccion.OBTENER_DIAGNOSTICO:
            return interpretar_diagnostico(resultado)
        if resultado.codigo_salida != 0:
            raise ErrorEjecucionAccion(resultado.codigo_salida)
        lineas = [linea.strip() for linea in resultado.salida.splitlines()]
        marcador = f"HERMES_ACCION={codigo.value}"
        if len(lineas) < 2 or lineas[0] != marcador:
            raise ErrorRespuestaAccionNoValida()

        if codigo is CodigoAccion.OBTENER_IDENTIDAD and len(lineas) >= 3:
            return {"usuario": lineas[1][:100], "nombre_equipo": lineas[2][:255]}
        if codigo is CodigoAccion.CONSULTAR_PROCESO and len(lineas) >= 3:
            if lineas[1].isdigit():
                return {"id_proceso": int(lineas[1]), "nombre_proceso": lineas[2][:255]}
        if codigo is CodigoAccion.REINICIAR_SERVIDOR and lineas[1] == "PROGRAMADO":
            return {"reinicio_programado": True, "demora_segundos": 60}
        raise ErrorRespuestaAccionNoValida()
