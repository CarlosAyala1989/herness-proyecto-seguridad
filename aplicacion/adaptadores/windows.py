"""Detección y acciones controladas para Windows Server mediante PowerShell."""

from base64 import b64encode

from aplicacion.acciones.errores import ErrorEjecucionAccion, ErrorRespuestaAccionNoValida
from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosAccion,
    ParametrosCambioGrupoUsuarioSistema,
    ParametrosConsultaProceso,
    ParametrosCrearUsuarioSistema,
    ParametrosNombreUsuarioSistema,
    ParametrosServicio,
)
from aplicacion.adaptadores.acciones import AccionRemotaPreparada
from aplicacion.adaptadores.diagnostico import interpretar_diagnostico
from aplicacion.adaptadores.servicios import (
    ACCIONES_SERVICIO,
    interpretar_resultado_servicio,
)
from aplicacion.adaptadores.sistema_operativo import SistemaRemotoDetectado
from aplicacion.adaptadores.usuarios import ACCIONES_USUARIOS, interpretar_resultado_usuarios
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

    @staticmethod
    def _literal_powershell(valor: str) -> str:
        """Escapa una cadena validada como literal de comillas simples."""

        return "'" + valor.replace("'", "''") + "'"

    @classmethod
    def _envolver_guion(cls, codigo: CodigoAccion, guion: str) -> AccionRemotaPreparada:
        return AccionRemotaPreparada(
            codigo=codigo,
            comando=(
                "powershell.exe -NoLogo -NoProfile -NonInteractive "
                f"-EncodedCommand {cls._codificar_guion_powershell(guion)}"
            ),
        )

    @classmethod
    def _preparar_listado_usuarios(cls) -> AccionRemotaPreparada:
        guion = r"""
$ErrorActionPreference = 'Stop'
if ($null -eq (Get-Command Get-LocalUser -ErrorAction SilentlyContinue)) {
    Write-Output 'HERMES_ERROR=gestor_usuarios_no_disponible'
    exit 0
}
Write-Output 'HERMES_ACCION=listar_usuarios_sistema'
$usuario_actual = [Environment]::UserName
$sids_grupos_protegidos = @('S-1-5-32-544', 'S-1-5-32-551', 'S-1-5-32-555', 'S-1-5-32-580')
$usuarios = @(Get-LocalUser | Sort-Object -Property Name)
foreach ($usuario in $usuarios) {
    $sid = [string]$usuario.SID.Value
    $partes_sid = $sid.Split('-')
    $rid = 0
    [void][int]::TryParse($partes_sid[-1], [ref]$rid)
    $protegida = ($rid -lt 1000) -or ($usuario.Name -ieq $usuario_actual)
    $estado = if ($usuario.Enabled) { 'habilitado' } else { 'deshabilitado' }
    $grupos = @()
    try {
        $grupos = @(Get-LocalGroup | Where-Object {
            $miembros = @(Get-LocalGroupMember -Group $_ -ErrorAction Stop)
            $miembros.SID.Value -contains $sid
        } | Sort-Object -Property Name)
        foreach ($grupo in $grupos) {
            if ([string]$grupo.SID.Value -in $sids_grupos_protegidos) {
                $protegida = $true
            }
        }
    } catch {}
    Write-Output ('USUARIO|{0}|{1}|{2}|{3}' -f $usuario.Name, $sid, $estado, $protegida.ToString().ToLowerInvariant())
    foreach ($grupo in $grupos) {
        Write-Output ('GRUPO|{0}|{1}' -f $usuario.Name, $grupo.Name)
    }
}
"""
        return cls._envolver_guion(CodigoAccion.LISTAR_USUARIOS_SISTEMA, guion)

    @classmethod
    def _bloque_comun_usuario(
        cls,
        parametros: ParametrosNombreUsuarioSistema,
        *,
        proteger_operador: bool,
    ) -> str:
        nombre = cls._literal_powershell(parametros.nombre_usuario)
        autorizar = "$true" if parametros.autorizar_cuenta_protegida else "$false"
        validar_operador = (
            """
if ($nombre_usuario -ieq $usuario_actual) {
    Write-Output 'HERMES_ERROR=cuenta_operador_ssh'
    exit 0
}
"""
            if proteger_operador
            else ""
        )
        return f"""
$ErrorActionPreference = 'Stop'
$nombre_usuario = {nombre}
$autorizar_cuenta_protegida = {autorizar}
if ($null -eq (Get-Command Get-LocalUser -ErrorAction SilentlyContinue)) {{
    Write-Output 'HERMES_ERROR=gestor_usuarios_no_disponible'
    exit 0
}}
$usuario = Get-LocalUser -Name $nombre_usuario -ErrorAction SilentlyContinue
if ($null -eq $usuario) {{
    Write-Output 'HERMES_ERROR=usuario_sistema_no_encontrado'
    exit 0
}}
$sid = [string]$usuario.SID.Value
$partes_sid = $sid.Split('-')
$rid = 0
[void][int]::TryParse($partes_sid[-1], [ref]$rid)
$usuario_actual = [Environment]::UserName
$cuenta_protegida = ($rid -lt 1000) -or ($nombre_usuario -ieq $usuario_actual)
foreach ($sid_grupo_protegido in @('S-1-5-32-544', 'S-1-5-32-551', 'S-1-5-32-555', 'S-1-5-32-580')) {{
    try {{
        $grupo_protegido = Get-LocalGroup -SID $sid_grupo_protegido -ErrorAction Stop
        $miembros_protegidos = @(Get-LocalGroupMember -Group $grupo_protegido -ErrorAction Stop)
        if ($miembros_protegidos.SID.Value -contains $sid) {{
            $cuenta_protegida = $true
        }}
    }} catch {{}}
}}
{validar_operador}
if ($cuenta_protegida -and -not $autorizar_cuenta_protegida) {{
    Write-Output 'HERMES_ERROR=cuenta_sistema_protegida'
    exit 0
}}
"""

    @classmethod
    def _preparar_creacion_usuario(
        cls,
        parametros: ParametrosCrearUsuarioSistema,
    ) -> AccionRemotaPreparada:
        nombre = cls._literal_powershell(parametros.nombre_usuario)
        nombre_mostrar = cls._literal_powershell(
            parametros.nombre_mostrar or parametros.nombre_usuario
        )
        guion = f"""
$ErrorActionPreference = 'Stop'
$nombre_usuario = {nombre}
$nombre_mostrar = {nombre_mostrar}
if ($null -eq (Get-Command New-LocalUser -ErrorAction SilentlyContinue)) {{
    Write-Output 'HERMES_ERROR=gestor_usuarios_no_disponible'
    exit 0
}}
if ($null -ne (Get-LocalUser -Name $nombre_usuario -ErrorAction SilentlyContinue)) {{
    Write-Output 'HERMES_ERROR=usuario_sistema_ya_existe'
    exit 0
}}
$usuario = New-LocalUser -Name $nombre_usuario -FullName $nombre_mostrar -NoPassword -AccountNeverExpires -Disabled -Description 'Creada por Hermes; credenciales pendientes'
Write-Output 'HERMES_ACCION=crear_usuario_sistema'
Write-Output "nombre_usuario=$nombre_usuario"
Write-Output 'estado=deshabilitado'
Write-Output 'cuenta_protegida=false'
Write-Output 'nombre_grupo=no_aplica'
Write-Output 'operacion_grupo=no_aplica'
"""
        return cls._envolver_guion(CodigoAccion.CREAR_USUARIO_SISTEMA, guion)

    @classmethod
    def _preparar_cambio_grupo(
        cls,
        parametros: ParametrosCambioGrupoUsuarioSistema,
    ) -> AccionRemotaPreparada:
        comun = cls._bloque_comun_usuario(parametros, proteger_operador=False)
        grupo = cls._literal_powershell(parametros.nombre_grupo)
        operacion = parametros.operacion_grupo
        orden = (
            "Add-LocalGroupMember -Group $grupo -Member $usuario -ErrorAction Stop"
            if operacion == "agregar"
            else "Remove-LocalGroupMember -Group $grupo -Member $usuario "
            "-Confirm:$false -ErrorAction Stop"
        )
        guion = f"""
{comun}
$nombre_grupo = {grupo}
$operacion_grupo = '{operacion}'
if ($null -eq (Get-Command Get-LocalGroup -ErrorAction SilentlyContinue)) {{
    Write-Output 'HERMES_ERROR=gestor_usuarios_no_disponible'
    exit 0
}}
$grupo = Get-LocalGroup -Name $nombre_grupo -ErrorAction SilentlyContinue
if ($null -eq $grupo) {{
    Write-Output 'HERMES_ERROR=grupo_sistema_no_encontrado'
    exit 0
}}
$sid_grupo = [string]$grupo.SID.Value
$partes_grupo = $sid_grupo.Split('-')
$rid_grupo = 0
[void][int]::TryParse($partes_grupo[-1], [ref]$rid_grupo)
$grupo_protegido = ($rid_grupo -lt 1000) -or ($nombre_grupo -iin @('Administrators', 'Remote Desktop Users', 'Backup Operators', 'Remote Management Users'))
if ($grupo_protegido -and -not $autorizar_cuenta_protegida) {{
    Write-Output 'HERMES_ERROR=cuenta_sistema_protegida'
    exit 0
}}
{orden}
Write-Output 'HERMES_ACCION=cambiar_grupo_usuario_sistema'
Write-Output "nombre_usuario=$nombre_usuario"
Write-Output 'estado=actualizado'
Write-Output ('cuenta_protegida=' + $cuenta_protegida.ToString().ToLowerInvariant())
Write-Output "nombre_grupo=$nombre_grupo"
Write-Output "operacion_grupo=$operacion_grupo"
"""
        return cls._envolver_guion(CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA, guion)

    @classmethod
    def _preparar_estado_o_eliminacion_usuario(
        cls,
        codigo: CodigoAccion,
        parametros: ParametrosNombreUsuarioSistema,
    ) -> AccionRemotaPreparada:
        comun = cls._bloque_comun_usuario(parametros, proteger_operador=True)
        operaciones = {
            CodigoAccion.BLOQUEAR_USUARIO_SISTEMA: (
                "Disable-LocalUser -InputObject $usuario",
                "bloqueado",
            ),
            CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA: (
                "Enable-LocalUser -InputObject $usuario",
                "habilitado",
            ),
            CodigoAccion.ELIMINAR_USUARIO_SISTEMA: (
                "Remove-LocalUser -InputObject $usuario -Confirm:$false",
                "eliminado",
            ),
        }
        orden, estado = operaciones[codigo]
        guion = f"""
{comun}
{orden}
Write-Output 'HERMES_ACCION={codigo.value}'
Write-Output "nombre_usuario=$nombre_usuario"
Write-Output 'estado={estado}'
Write-Output ('cuenta_protegida=' + $cuenta_protegida.ToString().ToLowerInvariant())
Write-Output 'nombre_grupo=no_aplica'
Write-Output 'operacion_grupo=no_aplica'
"""
        return cls._envolver_guion(codigo, guion)

    @classmethod
    def _preparar_accion_usuario(
        cls,
        codigo: CodigoAccion,
        parametros: ParametrosAccion,
    ) -> AccionRemotaPreparada:
        if codigo is CodigoAccion.LISTAR_USUARIOS_SISTEMA:
            return cls._preparar_listado_usuarios()
        if codigo is CodigoAccion.CREAR_USUARIO_SISTEMA and isinstance(
            parametros, ParametrosCrearUsuarioSistema
        ):
            return cls._preparar_creacion_usuario(parametros)
        if codigo is CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA and isinstance(
            parametros, ParametrosCambioGrupoUsuarioSistema
        ):
            return cls._preparar_cambio_grupo(parametros)
        if isinstance(parametros, ParametrosNombreUsuarioSistema):
            return cls._preparar_estado_o_eliminacion_usuario(codigo, parametros)
        raise ErrorRespuestaAccionNoValida()

    def _preparar_servicio(
        self,
        codigo: CodigoAccion,
        parametros: ParametrosServicio,
    ) -> AccionRemotaPreparada:
        operaciones = {
            CodigoAccion.CONSULTAR_SERVICIO: "",
            CodigoAccion.INICIAR_SERVICIO: (
                "Start-Service -InputObject $servicio -ErrorAction Stop\n"
                "$servicio.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, "
                "[TimeSpan]::FromSeconds(8))"
            ),
            CodigoAccion.DETENER_SERVICIO: (
                "Stop-Service -InputObject $servicio -Confirm:$false -ErrorAction Stop\n"
                "$servicio.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, "
                "[TimeSpan]::FromSeconds(8))"
            ),
            CodigoAccion.REINICIAR_SERVICIO: (
                "Restart-Service -InputObject $servicio -Confirm:$false -ErrorAction Stop\n"
                "$servicio.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, "
                "[TimeSpan]::FromSeconds(8))"
            ),
        }
        operacion = operaciones[codigo]
        guion = f"""
$ErrorActionPreference = 'Stop'
$nombre_servicio = '{parametros.nombre_servicio}'
if ($null -eq (Get-Command Get-Service -ErrorAction SilentlyContinue)) {{
    Write-Output 'HERMES_ERROR=gestor_servicios_no_disponible'
    exit 0
}}
$servicio = Get-Service -Name $nombre_servicio -ErrorAction SilentlyContinue
if ($null -eq $servicio) {{
    Write-Output 'HERMES_ERROR=servicio_no_encontrado'
    exit 0
}}
{operacion}
$servicio = Get-Service -Name $nombre_servicio -ErrorAction Stop
$estado_nativo = [string]$servicio.Status
$estado = switch ($estado_nativo) {{
    'Running' {{ 'activo' }}
    'Stopped' {{ 'inactivo' }}
    'StartPending' {{ 'iniciando' }}
    'StopPending' {{ 'deteniendo' }}
    'Paused' {{ 'pausado' }}
    'PausePending' {{ 'pausado' }}
    'ContinuePending' {{ 'iniciando' }}
    default {{ 'desconocido' }}
}}
$inicio_automatico = 'no_disponible'
try {{
    $filtro = "Name = '$nombre_servicio'"
    $servicio_cim = Get-CimInstance Win32_Service -Filter $filtro -ErrorAction Stop
    if ($null -ne $servicio_cim) {{
        $inicio_automatico = if ($servicio_cim.StartMode -eq 'Auto') {{ 'true' }} else {{ 'false' }}
    }}
}} catch {{}}
Write-Output 'HERMES_ACCION={codigo.value}'
Write-Output "nombre_servicio=$nombre_servicio"
Write-Output "estado=$estado"
Write-Output "estado_nativo=$estado_nativo"
Write-Output "inicio_automatico=$inicio_automatico"
"""
        guion_codificado = self._codificar_guion_powershell(guion)
        return AccionRemotaPreparada(
            codigo=codigo,
            comando=(
                "powershell.exe -NoLogo -NoProfile -NonInteractive "
                f"-EncodedCommand {guion_codificado}"
            ),
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
        elif codigo is CodigoAccion.OBTENER_DIAGNOSTICO:
            guion_codificado = self._codificar_guion_powershell(self.guion_diagnostico)
            return AccionRemotaPreparada(
                codigo=codigo,
                comando=(
                    "powershell.exe -NoLogo -NoProfile -NonInteractive "
                    f"-EncodedCommand {guion_codificado}"
                ),
            )
        elif codigo in ACCIONES_SERVICIO and isinstance(parametros, ParametrosServicio):
            return self._preparar_servicio(codigo, parametros)
        elif codigo in ACCIONES_USUARIOS:
            return self._preparar_accion_usuario(codigo, parametros)
        else:
            raise ErrorRespuestaAccionNoValida()
        return AccionRemotaPreparada(codigo=codigo, comando=f'{prefijo}{cuerpo}"')

    def interpretar_accion(
        self,
        codigo: CodigoAccion,
        resultado: ResultadoEjecucionRemota,
    ) -> dict[str, object]:
        """Normaliza la salida PowerShell con los mismos campos que Linux."""

        if codigo is CodigoAccion.OBTENER_DIAGNOSTICO:
            return interpretar_diagnostico(resultado)
        if codigo in ACCIONES_SERVICIO:
            return interpretar_resultado_servicio(codigo, resultado)
        if codigo in ACCIONES_USUARIOS:
            return interpretar_resultado_usuarios(codigo, resultado)
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
