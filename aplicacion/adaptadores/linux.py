"""Detección y acciones controladas para servidores Linux."""

import shlex

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


class AdaptadorLinux:
    """Usa únicamente un saludo fijo, sin parámetros recibidos del usuario."""

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

tiempo_actividad_segundos=$(awk '{ printf "%.0f", $1 }' /proc/uptime 2>/dev/null)
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
        else:
            raise ErrorRespuestaAccionNoValida()
        return AccionRemotaPreparada(codigo=codigo, comando=comando)

    def interpretar_accion(
        self,
        codigo: CodigoAccion,
        resultado: ResultadoEjecucionRemota,
    ) -> dict[str, str | int | float | bool | None]:
        """Normaliza marcadores emitidos únicamente por comandos autorizados."""

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
        if codigo is CodigoAccion.CONSULTAR_PROCESO:
            partes = lineas[1].split(maxsplit=1)
            if len(partes) == 2 and partes[0].isdigit():
                return {"id_proceso": int(partes[0]), "nombre_proceso": partes[1][:255]}
        if codigo is CodigoAccion.REINICIAR_SERVIDOR and lineas[1] == "PROGRAMADO":
            return {"reinicio_programado": True, "demora_segundos": 60}
        raise ErrorRespuestaAccionNoValida()
