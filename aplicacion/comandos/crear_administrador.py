"""Crea interactivamente el primer administrador local."""

import argparse
import asyncio
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import obtener_configuracion
from aplicacion.errores import ErrorHermes
from aplicacion.esquemas.acceso import CrearUsuario
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import CanalAuditoria
from aplicacion.servicios.gestor_acceso import crear_usuario


async def crear_administrador(nombre_usuario: str, nombre_mostrar: str) -> int:
    """Solicita la contraseña sin mostrarla y registra un administrador."""

    configuracion = obtener_configuracion()
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    try:
        async with fabrica_sesiones() as sesion:
            existente = await sesion.scalar(
                select(Usuario).where(Usuario.nombre_usuario == nombre_usuario.strip().lower())
            )
            if existente is not None:
                print("El nombre de usuario ya está registrado.")
                return 1

            rol = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
            if rol is None:
                print("No existe el rol administrador. Ejecute primero las migraciones.")
                return 1

            contrasena = getpass("Contraseña del administrador: ")
            confirmacion = getpass("Repita la contraseña: ")
            if contrasena != confirmacion:
                print("Las contraseñas no coinciden.")
                return 1

            try:
                datos = CrearUsuario(
                    nombre_usuario=nombre_usuario,
                    nombre_mostrar=nombre_mostrar,
                    contrasena=contrasena,
                    ids_roles={rol.id_rol},
                )
                usuario = await crear_usuario(
                    sesion,
                    datos,
                    usuario_actor=None,
                    solicitud=None,
                    canal=CanalAuditoria.SISTEMA,
                )
            except ValidationError:
                print(
                    "Los datos no cumplen los requisitos: usuario válido y contraseña "
                    "de 12 a 128 caracteres."
                )
                return 1
            except ErrorHermes as error:
                print(error.mensaje)
                return 1

            print(f"Administrador creado correctamente con identificador {usuario.id_usuario}.")
            return 0
    finally:
        await motor.dispose()


def principal() -> None:
    """Analiza argumentos no secretos e inicia el flujo interactivo."""

    analizador = argparse.ArgumentParser(
        description="Crear el primer usuario administrador de Hermes."
    )
    analizador.add_argument("--usuario", required=True, help="Nombre de acceso en minúsculas.")
    analizador.add_argument("--nombre", required=True, help="Nombre visible del administrador.")
    argumentos = analizador.parse_args()
    raise SystemExit(asyncio.run(crear_administrador(argumentos.usuario, argumentos.nombre)))


if __name__ == "__main__":
    principal()
