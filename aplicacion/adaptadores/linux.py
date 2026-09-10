"""Detección y acciones controladas para servidores Linux."""

import shlex

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


class AdaptadorLinux:
    """Traduce acciones controladas a herramientas estándar de Linux."""

    sistema_operativo = SistemaOperativo.LINUX
    comando_deteccion = "printf 'HERMES_SO=linux\\n'; uname -s; uname -r; hostname"

    guion_diagnostico = r"""
no_disponible=no_disponible

leer_cpu() {
    [ -r /proc/stat ] || return
    set -- $(head -n 1 /proc/stat 2>/dev/null)
    [ "$#" -ge 8 ] || return
    total=$(( $2 + $3 + $4 + $5 + $6 + $7 + $8 + ${9:-0} ))
    inactivo=$(( $5 + $6 ))
    printf '%s %s' "$total" "$inactivo"
}

primera_lectura=$(leer_cpu)
cpu_porcentaje=$no_disponible
if [ -n "$primera_lectura" ]; then
    set -- $primera_lectura
    total_inicial=$1
    inactivo_inicial=$2
    sleep 0.2
    segunda_lectura=$(leer_cpu)
    if [ -n "$segunda_lectura" ]; then
        set -- $segunda_lectura
        diferencia_total=$(( $1 - total_inicial ))
        diferencia_inactivo=$(( $2 - inactivo_inicial ))
        if [ "$diferencia_total" -gt 0 ]; then
            cpu_porcentaje=$(awk -v total="$diferencia_total" -v inactivo="$diferencia_inactivo" 'BEGIN { uso=100 * (total - inactivo) / total; if (uso < 0) uso=0; if (uso > 100) uso=100; printf "%.2f", uso }')
        fi
    fi
fi

memoria_porcentaje=$(awk '/^MemTotal:/ { total=$2 } /^MemAvailable:/ { disponible=$2 } END { if (total > 0 && disponible >= 0) printf "%.2f", 100 * (total - disponible) / total }' /proc/meminfo 2>/dev/null)
[ -n "$memoria_porcentaje" ] || memoria_porcentaje=$no_disponible

disco_porcentaje=$(df -Pk / 2>/dev/null | awk 'NR == 2 { gsub(/%/, "", $5); print $5 }')
[ -n "$disco_porcentaje" ] || disco_porcentaje=$no_disponible

tiempo_actividad_segundos=$(awk '{ split($1, partes, "."); print partes[1] }' /proc/uptime 2>/dev/null)
[ -n "$tiempo_actividad_segundos" ] || tiempo_actividad_segundos=$no_disponible

version=$(uname -r 2>/dev/null)
[ -n "$version" ] || version=$no_disponible
nombre_equipo=$(hostname 2>/dev/null)
[ -n "$nombre_equipo" ] || nombre_equipo=$no_disponible

printf 'HERMES_ACCION=obtener_diagnostico\n'
printf 'estado=disponible\n'
printf 'cpu_porcentaje=%s\n' "$cpu_porcentaje"
printf 'memoria_porcentaje=%s\n' "$memoria_porcentaje"
printf 'disco_porcentaje=%s\n' "$disco_porcentaje"
printf 'tiempo_actividad_segundos=%s\n' "$tiempo_actividad_segundos"
printf 'sistema=Linux\n'
printf 'version=%s\n' "$version"
printf 'nombre_equipo=%s\n' "$nombre_equipo"
"""

    @staticmethod
    def _preparar_servicio(
        codigo: CodigoAccion,
        parametros: ParametrosServicio,
    ) -> AccionRemotaPreparada:
        nombre = shlex.quote(parametros.nombre_servicio)
        operaciones = {
            CodigoAccion.CONSULTAR_SERVICIO: "",
            CodigoAccion.INICIAR_SERVICIO: "start",
            CodigoAccion.DETENER_SERVICIO: "stop",
            CodigoAccion.REINICIAR_SERVICIO: "restart",
        }
        operacion = operaciones[codigo]
        bloque_operacion = ""
        if operacion:
            bloque_operacion = f"""
if [ "$(id -u)" -eq 0 ]; then
    systemctl {operacion} -- "$nombre_servicio"
elif command -v sudo >/dev/null 2>&1; then
    sudo -n systemctl {operacion} -- "$nombre_servicio"
else
    exit 126
fi
"""
        guion = f"""
if ! command -v systemctl >/dev/null 2>&1; then
    printf 'HERMES_ERROR=gestor_servicios_no_disponible\\n'
    exit 0
fi
nombre_servicio={nombre}
{bloque_operacion}
propiedades=$(systemctl show --no-pager --property=LoadState --property=ActiveState --property=UnitFileState -- "$nombre_servicio" 2>/dev/null) || exit $?
estado_carga=$(printf '%s\\n' "$propiedades" | awk -F= '$1 == "LoadState" {{ print substr($0, index($0, "=") + 1) }}')
estado_nativo=$(printf '%s\\n' "$propiedades" | awk -F= '$1 == "ActiveState" {{ print substr($0, index($0, "=") + 1) }}')
estado_inicio=$(printf '%s\\n' "$propiedades" | awk -F= '$1 == "UnitFileState" {{ print substr($0, index($0, "=") + 1) }}')

if [ "$estado_carga" = "not-found" ] || [ -z "$estado_carga" ]; then
    printf 'HERMES_ERROR=servicio_no_encontrado\\n'
    exit 0
fi

case "$estado_nativo" in
    active) estado=activo ;;
    inactive) estado=inactivo ;;
    activating) estado=iniciando ;;
    deactivating) estado=deteniendo ;;
    failed) estado=fallido ;;
    reloading) estado=recargando ;;
    *) estado=desconocido ;;
esac
case "$estado_inicio" in
    enabled|enabled-runtime) inicio_automatico=true ;;
    disabled|masked|masked-runtime) inicio_automatico=false ;;
    *) inicio_automatico=no_disponible ;;
esac

printf 'HERMES_ACCION={codigo.value}\\n'
printf 'nombre_servicio=%s\\n' "$nombre_servicio"
printf 'estado=%s\\n' "$estado"
printf 'estado_nativo=%s\\n' "$estado_nativo"
printf 'inicio_automatico=%s\\n' "$inicio_automatico"
"""
        return AccionRemotaPreparada(
            codigo=codigo,
            comando=f"LC_ALL=C sh -c {shlex.quote(guion)}",
        )

    @staticmethod
    def _envolver_guion(guion: str) -> str:
        return f"LC_ALL=C sh -c {shlex.quote(guion)}"

    @classmethod
    def _preparar_listado_usuarios(cls) -> AccionRemotaPreparada:
        guion = r"""
if ! command -v getent >/dev/null 2>&1 || ! command -v id >/dev/null 2>&1; then
    printf 'HERMES_ERROR=gestor_usuarios_no_disponible\n'
    exit 0
fi
uid_min=$(awk '$1 == "UID_MIN" { print $2; exit }' /etc/login.defs 2>/dev/null)
case "$uid_min" in ''|*[!0-9]*) uid_min=1000 ;; esac
usuario_actual=$(id -un 2>/dev/null)
printf 'HERMES_ACCION=listar_usuarios_sistema\n'
getent passwd | while IFS=: read -r nombre _ uid _ _ _ _; do
    [ -n "$nombre" ] || continue
    estado=desconocido
    detalle=$(passwd -S "$nombre" 2>/dev/null) || detalle=
    set -- $detalle
    case "${2:-}" in
        P) estado=habilitado ;;
        L) estado=bloqueado ;;
        NP) estado=sin_contrasena ;;
    esac
    protegida=false
    case "$uid" in ''|*[!0-9]*) protegida=true ;; *) [ "$uid" -lt "$uid_min" ] && protegida=true ;; esac
    [ "$nombre" = "$usuario_actual" ] && protegida=true
    printf 'USUARIO|%s|%s|%s|%s\n' "$nombre" "$uid" "$estado" "$protegida"
    grupos=$(id -nG "$nombre" 2>/dev/null) || grupos=
    for grupo in $grupos; do
        printf 'GRUPO|%s|%s\n' "$nombre" "$grupo"
    done
done
"""
        return AccionRemotaPreparada(
            codigo=CodigoAccion.LISTAR_USUARIOS_SISTEMA,
            comando=cls._envolver_guion(guion),
        )

    @staticmethod
    def _bloque_comun_usuario(
        nombre_usuario: str,
        autorizar_cuenta_protegida: bool,
        *,
        proteger_operador: bool,
    ) -> str:
        nombre = shlex.quote(nombre_usuario)
        autorizar = "true" if autorizar_cuenta_protegida else "false"
        validar_operador = (
            """
if [ "$nombre_usuario" = "$usuario_actual" ]; then
    printf 'HERMES_ERROR=cuenta_operador_ssh\\n'
    exit 0
fi
"""
            if proteger_operador
            else ""
        )
        return f"""
nombre_usuario={nombre}
autorizar_cuenta_protegida={autorizar}
if ! command -v getent >/dev/null 2>&1 || ! command -v id >/dev/null 2>&1; then
    printf 'HERMES_ERROR=gestor_usuarios_no_disponible\n'
    exit 0
fi
registro_usuario=$(getent passwd "$nombre_usuario" 2>/dev/null) || registro_usuario=
if [ -z "$registro_usuario" ]; then
    printf 'HERMES_ERROR=usuario_sistema_no_encontrado\n'
    exit 0
fi
uid_usuario=$(printf '%s\n' "$registro_usuario" | awk -F: '{{ print $3 }}')
uid_min=$(awk '$1 == "UID_MIN" {{ print $2; exit }}' /etc/login.defs 2>/dev/null)
case "$uid_min" in ''|*[!0-9]*) uid_min=1000 ;; esac
usuario_actual=$(id -un 2>/dev/null)
cuenta_protegida=false
case "$uid_usuario" in
    ''|*[!0-9]*) cuenta_protegida=true ;;
    *) [ "$uid_usuario" -lt "$uid_min" ] && cuenta_protegida=true ;;
esac
[ "$nombre_usuario" = "$usuario_actual" ] && cuenta_protegida=true
{validar_operador}
if [ "$cuenta_protegida" = true ] && [ "$autorizar_cuenta_protegida" != true ]; then
    printf 'HERMES_ERROR=cuenta_sistema_protegida\n'
    exit 0
fi
ejecutar_privilegiado() {{
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -n -- "$@"
    else
        return 126
    fi
}}
"""

    @classmethod
    def _preparar_creacion_usuario(
        cls,
        parametros: ParametrosCrearUsuarioSistema,
    ) -> AccionRemotaPreparada:
        nombre = shlex.quote(parametros.nombre_usuario)
        nombre_mostrar = shlex.quote(parametros.nombre_mostrar or parametros.nombre_usuario)
        guion = f"""
nombre_usuario={nombre}
nombre_mostrar={nombre_mostrar}
if ! command -v getent >/dev/null 2>&1 || ! command -v useradd >/dev/null 2>&1; then
    printf 'HERMES_ERROR=gestor_usuarios_no_disponible\n'
    exit 0
fi
if getent passwd "$nombre_usuario" >/dev/null 2>&1; then
    printf 'HERMES_ERROR=usuario_sistema_ya_existe\n'
    exit 0
fi
ejecutar_privilegiado() {{
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -n -- "$@"
    else
        return 126
    fi
}}
ejecutar_privilegiado useradd --create-home --shell /bin/bash --comment "$nombre_mostrar" --expiredate 1 "$nombre_usuario" || exit $?
printf 'HERMES_ACCION=crear_usuario_sistema\n'
printf 'nombre_usuario=%s\n' "$nombre_usuario"
printf 'estado=deshabilitado\n'
printf 'cuenta_protegida=false\n'
printf 'nombre_grupo=no_aplica\n'
printf 'operacion_grupo=no_aplica\n'
"""
        return AccionRemotaPreparada(
            codigo=CodigoAccion.CREAR_USUARIO_SISTEMA,
            comando=cls._envolver_guion(guion),
        )

    @classmethod
    def _preparar_cambio_grupo(
        cls,
        parametros: ParametrosCambioGrupoUsuarioSistema,
    ) -> AccionRemotaPreparada:
        comun = cls._bloque_comun_usuario(
            parametros.nombre_usuario,
            parametros.autorizar_cuenta_protegida,
            proteger_operador=False,
        )
        grupo = shlex.quote(parametros.nombre_grupo)
        operacion = parametros.operacion_grupo
        herramienta = "usermod" if operacion == "agregar" else "gpasswd"
        orden = (
            'ejecutar_privilegiado usermod --append --groups "$nombre_grupo" '
            '"$nombre_usuario" || exit $?'
            if operacion == "agregar"
            else 'ejecutar_privilegiado gpasswd --delete "$nombre_usuario" '
            '"$nombre_grupo" >/dev/null || exit $?'
        )
        guion = f"""
{comun}
nombre_grupo={grupo}
operacion_grupo={operacion}
if ! command -v {herramienta} >/dev/null 2>&1; then
    printf 'HERMES_ERROR=gestor_usuarios_no_disponible\n'
    exit 0
fi
registro_grupo=$(getent group "$nombre_grupo" 2>/dev/null) || registro_grupo=
if [ -z "$registro_grupo" ]; then
    printf 'HERMES_ERROR=grupo_sistema_no_encontrado\n'
    exit 0
fi
gid_grupo=$(printf '%s\n' "$registro_grupo" | awk -F: '{{ print $3 }}')
gid_min=$(awk '$1 == "GID_MIN" {{ print $2; exit }}' /etc/login.defs 2>/dev/null)
case "$gid_min" in ''|*[!0-9]*) gid_min=1000 ;; esac
grupo_protegido=false
case "$gid_grupo" in
    ''|*[!0-9]*) grupo_protegido=true ;;
    *) [ "$gid_grupo" -lt "$gid_min" ] && grupo_protegido=true ;;
esac
case "$nombre_grupo" in sudo|wheel|root|adm|shadow|docker) grupo_protegido=true ;; esac
if [ "$grupo_protegido" = true ] && [ "$autorizar_cuenta_protegida" != true ]; then
    printf 'HERMES_ERROR=cuenta_sistema_protegida\n'
    exit 0
fi
{orden}
printf 'HERMES_ACCION=cambiar_grupo_usuario_sistema\n'
printf 'nombre_usuario=%s\n' "$nombre_usuario"
printf 'estado=actualizado\n'
printf 'cuenta_protegida=%s\n' "$cuenta_protegida"
printf 'nombre_grupo=%s\n' "$nombre_grupo"
printf 'operacion_grupo=%s\n' "$operacion_grupo"
"""
        return AccionRemotaPreparada(
            codigo=CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
            comando=cls._envolver_guion(guion),
        )

    @classmethod
    def _preparar_estado_o_eliminacion_usuario(
        cls,
        codigo: CodigoAccion,
        parametros: ParametrosNombreUsuarioSistema,
    ) -> AccionRemotaPreparada:
        comun = cls._bloque_comun_usuario(
            parametros.nombre_usuario,
            parametros.autorizar_cuenta_protegida,
            proteger_operador=True,
        )
        operaciones = {
            CodigoAccion.BLOQUEAR_USUARIO_SISTEMA: (
                "usermod",
                'ejecutar_privilegiado usermod --lock --expiredate 1 "$nombre_usuario" || exit $?',
                "bloqueado",
            ),
            CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA: (
                "usermod",
                'ejecutar_privilegiado usermod --unlock --expiredate "" '
                '"$nombre_usuario" || exit $?',
                "habilitado",
            ),
            CodigoAccion.ELIMINAR_USUARIO_SISTEMA: (
                "userdel",
                'ejecutar_privilegiado userdel --remove "$nombre_usuario" || exit $?',
                "eliminado",
            ),
        }
        herramienta, orden, estado = operaciones[codigo]
        guion = f"""
{comun}
if ! command -v {herramienta} >/dev/null 2>&1; then
    printf 'HERMES_ERROR=gestor_usuarios_no_disponible\n'
    exit 0
fi
{orden}
printf 'HERMES_ACCION={codigo.value}\n'
printf 'nombre_usuario=%s\n' "$nombre_usuario"
printf 'estado={estado}\n'
printf 'cuenta_protegida=%s\n' "$cuenta_protegida"
printf 'nombre_grupo=no_aplica\n'
printf 'operacion_grupo=no_aplica\n'
"""
        return AccionRemotaPreparada(codigo=codigo, comando=cls._envolver_guion(guion))

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

    def preparar_accion(
        self,
        codigo: CodigoAccion,
        parametros: ParametrosAccion,
    ) -> AccionRemotaPreparada:
        """Selecciona uno de los comandos Linux inmutables."""

        if codigo is CodigoAccion.OBTENER_IDENTIDAD:
            comando = "printf 'HERMES_ACCION=obtener_identidad\\n'; id -un; hostname"
        elif codigo is CodigoAccion.CONSULTAR_PROCESO and isinstance(
            parametros, ParametrosConsultaProceso
        ):
            comando = (
                "printf 'HERMES_ACCION=consultar_proceso\\n'; "
                f"ps -p {parametros.id_proceso} -o pid= -o comm="
            )
        elif codigo is CodigoAccion.REINICIAR_SERVIDOR:
            comando = (
                "sudo -n shutdown -r +1 'Reinicio autorizado por Hermes' "
                ">/dev/null 2>&1 && "
                "printf 'HERMES_ACCION=reiniciar_servidor\\nPROGRAMADO\\n'"
            )
        elif codigo is CodigoAccion.OBTENER_DIAGNOSTICO:
            comando = f"LC_ALL=C sh -c {shlex.quote(self.guion_diagnostico)}"
        elif codigo in ACCIONES_SERVICIO and isinstance(parametros, ParametrosServicio):
            return self._preparar_servicio(codigo, parametros)
        elif codigo in ACCIONES_USUARIOS:
            return self._preparar_accion_usuario(codigo, parametros)
        else:
            raise ErrorRespuestaAccionNoValida()
        return AccionRemotaPreparada(codigo=codigo, comando=comando)

    def interpretar_accion(
        self,
        codigo: CodigoAccion,
        resultado: ResultadoEjecucionRemota,
    ) -> dict[str, object]:
        """Normaliza marcadores emitidos únicamente por comandos autorizados."""

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
        if codigo is CodigoAccion.CONSULTAR_PROCESO:
            partes = lineas[1].split(maxsplit=1)
            if len(partes) == 2 and partes[0].isdigit():
                return {"id_proceso": int(partes[0]), "nombre_proceso": partes[1][:255]}
        if codigo is CodigoAccion.REINICIAR_SERVIDOR and lineas[1] == "PROGRAMADO":
            return {"reinicio_programado": True, "demora_segundos": 60}
        raise ErrorRespuestaAccionNoValida()
