"""Proceso local de monitoreo periódico de Hermes."""

import argparse
import asyncio
import logging

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.transporte_ssh import crear_transporte_ssh
from aplicacion.configuracion import obtener_configuracion
from aplicacion.monitoreo.motor import ejecutar_ciclo_monitoreo
from aplicacion.monitoreo.notificaciones import cerrar_notificadores, crear_notificadores
from aplicacion.registro_logs import configurar_logs

registrador = logging.getLogger(__name__)


def crear_analizador() -> argparse.ArgumentParser:
    """Expone una ejecución única para comprobaciones controladas."""

    analizador = argparse.ArgumentParser(
        description="Monitorea servidores configurados y notifica transiciones de alertas."
    )
    analizador.add_argument(
        "--una-vez",
        action="store_true",
        help="Ejecuta un único ciclo aunque el bucle periódico esté deshabilitado.",
    )
    return analizador


async def ejecutar(una_vez: bool) -> int:
    """Mantiene el ciclo periódico sin compartir sesiones entre destinos."""

    configuracion = obtener_configuracion()
    configurar_logs(configuracion.nivel_log)
    if not una_vez and not configuracion.monitoreo_habilitado:
        registrador.error("El monitoreo automático está deshabilitado. Usa --una-vez o habilítalo.")
        return 1

    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    notificadores = crear_notificadores(configuracion)

    def fabrica_transporte(servidor):
        return crear_transporte_ssh(servidor, configuracion)

    try:
        while True:
            await ejecutar_ciclo_monitoreo(
                fabrica_sesiones,
                fabrica_transporte,
                configuracion,
                notificadores,
            )
            if una_vez:
                return 0
            await asyncio.sleep(configuracion.intervalo_monitoreo_segundos)
    finally:
        await cerrar_notificadores(notificadores)
        await motor.dispose()
        registrador.info("Monitor detenido y conexiones liberadas.")


def principal() -> int:
    """Ejecuta el proceso y permite una detención manual limpia."""

    argumentos = crear_analizador().parse_args()
    try:
        return asyncio.run(ejecutar(argumentos.una_vez))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(principal())
