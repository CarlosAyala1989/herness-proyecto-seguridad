"""Comando local para autorizar una identidad de Slack."""

import argparse
import asyncio
import sys

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import obtener_configuracion
from aplicacion.errores import ErrorHermes
from aplicacion.servicios.gestor_identidades_mensajeria import vincular_identidad_slack


def crear_analizador() -> argparse.ArgumentParser:
    """Define identificadores inmutables sin recibir tokens ni contraseñas."""

    analizador = argparse.ArgumentParser(
        description="Vincula un usuario Hermes con un espacio y usuario de Slack."
    )
    analizador.add_argument("--usuario", required=True, help="Nombre del usuario de Hermes.")
    analizador.add_argument(
        "--identificador-equipo",
        required=True,
        help="Identificador del espacio de trabajo Slack, por ejemplo T012ABCDEF.",
    )
    analizador.add_argument(
        "--identificador-usuario",
        required=True,
        help="Identificador inmutable del usuario Slack, por ejemplo U012ABCDEF.",
    )
    analizador.add_argument(
        "--nombre-slack",
        help="Nombre opcional almacenado únicamente como referencia visual.",
    )
    return analizador


async def ejecutar(
    nombre_usuario: str,
    identificador_equipo: str,
    identificador_usuario: str,
    nombre_slack: str | None,
) -> None:
    """Abre una sesión corta y conserva únicamente la identidad autorizada."""

    motor = crear_motor_base_datos(obtener_configuracion())
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    try:
        async with fabrica_sesiones() as sesion:
            await vincular_identidad_slack(
                sesion,
                nombre_usuario,
                identificador_equipo,
                identificador_usuario,
                nombre_slack,
            )
        print(
            "Identidad de Slack vinculada correctamente al usuario "
            f"{nombre_usuario.strip().lower()}."
        )
    finally:
        await motor.dispose()


def principal() -> int:
    """Punto de entrada controlado para administración local."""

    argumentos = crear_analizador().parse_args()
    try:
        asyncio.run(
            ejecutar(
                argumentos.usuario,
                argumentos.identificador_equipo,
                argumentos.identificador_usuario,
                argumentos.nombre_slack,
            )
        )
    except ErrorHermes as error:
        print(f"No se pudo vincular Slack: {error.mensaje}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
