"""Inicio local del bot Telegram mediante sondeo saliente."""

import logging

from telegram import Update

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.transporte_ssh import crear_transporte_ssh
from aplicacion.configuracion import obtener_configuracion
from aplicacion.interfaces.telegram.bot import crear_aplicacion_telegram
from aplicacion.registro_logs import configurar_logs
from aplicacion.servicios.gestor_telegram import GestorTelegram

registrador = logging.getLogger(__name__)


def principal() -> int:
    """Prepara recursos compartidos e inicia el sondeo de Telegram."""

    configuracion = obtener_configuracion()
    configurar_logs(configuracion.nivel_log)
    if not configuracion.telegram_habilitado:
        registrador.error(
            "Telegram está deshabilitado. Configura el token local y habilita el canal."
        )
        return 1

    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)

    def fabrica_transporte(servidor):
        return crear_transporte_ssh(servidor, configuracion)

    gestor = GestorTelegram(fabrica_sesiones, fabrica_transporte, configuracion)
    aplicacion = crear_aplicacion_telegram(configuracion, gestor, motor)
    aplicacion.run_polling(
        allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
        drop_pending_updates=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
