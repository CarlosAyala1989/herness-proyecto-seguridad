"""Detección y acciones controladas para Windows Server mediante PowerShell."""

from aplicacion.acciones.errores import ErrorEjecucionAccion, ErrorRespuestaAccionNoValida
from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosAccion,
    ParametrosConsultaProceso,
)
from aplicacion.adaptadores.acciones import AccionRemotaPreparada
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
        else:
            raise ErrorRespuestaAccionNoValida()
        return AccionRemotaPreparada(codigo=codigo, comando=f'{prefijo}{cuerpo}"')

    def interpretar_accion(
        self,
        codigo: CodigoAccion,
        resultado: ResultadoEjecucionRemota,
    ) -> dict[str, str | int | bool]:
        """Normaliza la salida PowerShell con los mismos campos que Linux."""

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
