"""Inicio local de Slack Bolt mediante Socket Mode saliente."""

import asyncio
import logging

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.transporte_ssh import crear_transporte_ssh
from aplicacion.configuracion import obtener_configuracion
from aplicacion.interfaces.slack.bot import crear_aplicacion_slack
from aplicacion.registro_logs import configurar_logs
from aplicacion.servicios.gestor_slack import GestorSlack

registrador = logging.getLogger(__name__)


async def ejecutar() -> int:
    """Prepara recursos comunes y mantiene la conexión saliente con Slack."""

    configuracion = obtener_configuracion()
    configurar_logs(configuracion.nivel_log)
    if not configuracion.slack_habilitado or configuracion.token_aplicacion_slack is None:
        registrador.error(
            "Slack está deshabilitado. Configura sus tokens locales y habilita el canal."
        )
        return 1
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)

    def fabrica_transporte(servidor):
        return crear_transporte_ssh(servidor, configuracion)

    gestor = GestorSlack(fabrica_sesiones, fabrica_transporte, configuracion)
    aplicacion = crear_aplicacion_slack(configuracion, gestor)
    manejador = AsyncSocketModeHandler(
        aplicacion,
        configuracion.token_aplicacion_slack.get_secret_value(),
    )
    try:
        registrador.info("Interfaz Slack iniciada mediante Socket Mode privado.")
        await manejador.start_async()
    finally:
        await motor.dispose()
        registrador.info("Interfaz Slack detenida y conexiones liberadas.")
    return 0


def principal() -> int:
    """Ejecuta el ciclo asíncrono desde la línea de comandos."""

    return asyncio.run(ejecutar())


if __name__ == "__main__":
    raise SystemExit(principal())
