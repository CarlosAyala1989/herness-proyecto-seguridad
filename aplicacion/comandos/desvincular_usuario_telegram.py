"""Comando local para revocar el acceso de un usuario desde Telegram."""

import argparse
import asyncio
import sys

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import obtener_configuracion
from aplicacion.errores import ErrorHermes
from aplicacion.servicios.gestor_identidades_mensajeria import desactivar_identidad_telegram


async def ejecutar(nombre_usuario: str) -> None:
    """Desactiva únicamente el vínculo Telegram indicado."""

    motor = crear_motor_base_datos(obtener_configuracion())
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    try:
        async with fabrica_sesiones() as sesion:
            await desactivar_identidad_telegram(sesion, nombre_usuario)
        print(
            "Acceso de Telegram desactivado correctamente para el usuario "
            f"{nombre_usuario.strip().lower()}."
        )
    finally:
        await motor.dispose()


def principal() -> int:
    """Valida argumentos y devuelve un código apto para automatización local."""

    analizador = argparse.ArgumentParser(
        description="Desactiva el vínculo Telegram de un usuario de Hermes."
    )
    analizador.add_argument("--usuario", required=True, help="Nombre del usuario de Hermes.")
    argumentos = analizador.parse_args()
    try:
        asyncio.run(ejecutar(argumentos.usuario))
    except ErrorHermes as error:
        print(f"No se pudo desactivar Telegram: {error.mensaje}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
