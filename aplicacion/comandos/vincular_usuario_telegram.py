"""Comando local para vincular y fijar al propietario único de Telegram."""

import argparse
import asyncio
import sys

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import obtener_configuracion
from aplicacion.configuracion_local import fijar_propietario_telegram
from aplicacion.errores import ErrorHermes
from aplicacion.servicios.gestor_identidades_mensajeria import vincular_identidad_telegram


def crear_analizador() -> argparse.ArgumentParser:
    """Define argumentos sin solicitar ni mostrar secretos."""

    analizador = argparse.ArgumentParser(
        description="Vincula un usuario Hermes y fija su ID como propietario único de Telegram."
    )
    analizador.add_argument("--usuario", required=True, help="Nombre del usuario de Hermes.")
    analizador.add_argument(
        "--identificador-telegram",
        required=True,
        type=int,
        help="Identificador numérico inmutable informado por Telegram.",
    )
    analizador.add_argument(
        "--nombre-telegram",
        help="Nombre de Telegram opcional, almacenado solo como referencia visual.",
    )
    return analizador


async def ejecutar(nombre_usuario: str, identificador_telegram: int, nombre: str | None) -> None:
    """Abre una sesión corta y conserva únicamente el identificador autorizado."""

    motor = crear_motor_base_datos(obtener_configuracion())
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    try:
        async with fabrica_sesiones() as sesion:
            identidad = await vincular_identidad_telegram(
                sesion,
                nombre_usuario,
                identificador_telegram,
                nombre,
            )
        fijar_propietario_telegram(identificador_telegram)
        print(
            "Identidad de Telegram vinculada correctamente "
            f"al usuario {nombre_usuario.strip().lower()}."
        )
        print(
            "Propietario único de Telegram guardado en .env. Reinicia los procesos Hermes para aplicarlo."
        )
        if identidad.id_identidad_mensajeria is None:
            raise RuntimeError("La identidad vinculada no recibió un identificador.")
    finally:
        await motor.dispose()


def principal() -> int:
    """Punto de entrada controlado para uso local."""

    argumentos = crear_analizador().parse_args()
    try:
        asyncio.run(
            ejecutar(
                argumentos.usuario,
                argumentos.identificador_telegram,
                argumentos.nombre_telegram,
            )
        )
    except ErrorHermes as error:
        print(f"No se pudo vincular Telegram: {error.mensaje}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
