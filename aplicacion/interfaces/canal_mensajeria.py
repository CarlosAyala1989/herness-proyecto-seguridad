"""Contrato para canales de entrada y salida de mensajería."""

from typing import Protocol


class CanalMensajeria(Protocol):
    """Puerto que deberán implementar Telegram y Slack en sus respectivos hitos."""

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        """Envía una respuesta sin contener lógica administrativa."""

