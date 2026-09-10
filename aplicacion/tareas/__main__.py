"""Proceso local del programador persistente de Hermes."""

import argparse
import asyncio
import logging

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.transporte_ssh import crear_transporte_ssh
from aplicacion.configuracion import obtener_configuracion
from aplicacion.monitoreo.notificaciones import cerrar_notificadores, crear_notificadores
from aplicacion.registro_logs import configurar_logs
from aplicacion.tareas.motor import ejecutar_ciclo_tareas
from aplicacion.tareas.notificaciones import enviar_notificaciones_tareas_pendientes

registrador = logging.getLogger(__name__)


def crear_analizador() -> argparse.ArgumentParser:
    analizador = argparse.ArgumentParser(
        description="Ejecuta las tareas administrativas vencidas de Hermes."
    )
    analizador.add_argument(
        "--una-vez",
        action="store_true",
        help="Ejecuta un ciclo aunque el programador periódico esté deshabilitado.",
    )
    return analizador


async def ejecutar(una_vez: bool) -> int:
    configuracion = obtener_configuracion()
    configurar_logs(configuracion.nivel_log)
    if not una_vez and not configuracion.tareas_habilitadas:
        registrador.error(
            "Las tareas automáticas están deshabilitadas. Usa --una-vez o habilítalas."
        )
        return 1

    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    notificadores = crear_notificadores(configuracion)

    def fabrica_transporte(servidor):
        return crear_transporte_ssh(servidor, configuracion)

    async def enviar_notificaciones():
        return await enviar_notificaciones_tareas_pendientes(
            fabrica_sesiones,
            notificadores,
            configuracion.max_intentos_notificacion_tarea,
        )

    try:
        while True:
            await ejecutar_ciclo_tareas(
                fabrica_sesiones,
                fabrica_transporte,
                configuracion,
                enviar_notificaciones,
            )
            if una_vez:
                return 0
            await asyncio.sleep(configuracion.intervalo_revision_tareas_segundos)
    finally:
        await cerrar_notificadores(notificadores)
        await motor.dispose()
        registrador.info("Programador detenido y conexiones liberadas.")


def principal() -> int:
    argumentos = crear_analizador().parse_args()
    try:
        return asyncio.run(ejecutar(argumentos.una_vez))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(principal())
