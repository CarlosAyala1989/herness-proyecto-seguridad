"""Detección y acciones controladas para servidores Linux."""

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
        else:
            raise ErrorRespuestaAccionNoValida()
        return AccionRemotaPreparada(codigo=codigo, comando=comando)

    def interpretar_accion(
        self,
        codigo: CodigoAccion,
        resultado: ResultadoEjecucionRemota,
    ) -> dict[str, str | int | bool]:
        """Normaliza marcadores emitidos únicamente por comandos autorizados."""

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
