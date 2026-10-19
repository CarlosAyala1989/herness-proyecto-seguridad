"""Asistente local del instalador; nunca interpreta `.env` como código Bash."""

import argparse
import asyncio
import os
import re
import secrets
import sys
import tempfile
from getpass import getpass
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values
from pydantic import ValidationError
from sqlalchemy import select

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.comandos.crear_administrador import crear_administrador
from aplicacion.comandos.vincular_usuario_telegram import ejecutar as vincular_telegram
from aplicacion.configuracion import Configuracion, obtener_configuracion
from aplicacion.errores import ErrorHermes
from aplicacion.modelos.acceso import Usuario


def preguntar(texto: str, predeterminado: bool = False) -> bool:
    """Solicita una elección explícita sin habilitar funciones por accidente."""

    opciones = "S/n" if predeterminado else "s/N"
    while True:
        respuesta = input(f"{texto} [{opciones}]: ").strip().lower()
        if not respuesta:
            return predeterminado
        if respuesta in {"s", "si", "sí", "n", "no"}:
            return respuesta in {"s", "si", "sí"}
        print("Responde s o n.")


def solicitar_token(texto: str, patron: str) -> str:
    """Valida la forma del secreto sin mostrarlo en pantalla ni errores."""

    while True:
        token = getpass(texto).strip()
        if re.fullmatch(patron, token) and len(token) >= 20:
            return token
        print("El formato del token no es válido. Vuelve a introducirlo.")


def guardar_configuracion(ruta: Path, contenido: str) -> None:
    """Reemplaza el archivo de forma atómica y con permisos privados."""

    if ruta.is_symlink():
        raise ValueError("El archivo .env no puede ser un enlace simbólico.")
    descriptor, temporal = tempfile.mkstemp(prefix=".hermes-config-", dir=ruta.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            archivo.write(contenido)
        os.replace(temporal, ruta)
    finally:
        Path(temporal).unlink(missing_ok=True)


def sustituir_variable(contenido: str, nombre: str, valor: str) -> str:
    """Actualiza valores simples del asistente conservando las demás líneas."""

    patron = rf"(?m)^(?:export[ \t]+)?{re.escape(nombre)}[ \t]*=.*$"
    linea = f"{nombre}={valor}"
    if re.search(patron, contenido):
        return re.sub(patron, lambda _: linea, contenido)
    return contenido.rstrip("\n") + "\n" + linea + "\n"


def configurar(ruta: Path = Path(".env"), ejemplo: Path = Path(".env.ejemplo")) -> None:
    """Prepara secretos propios y solicita únicamente credenciales externas."""

    if ruta.is_symlink():
        raise ValueError("El archivo .env no puede ser un enlace simbólico.")
    nueva = not ruta.exists()
    contenido = ejemplo.read_text(encoding="utf-8") if nueva else ruta.read_text(encoding="utf-8")
    variables = dotenv_values(stream=StringIO(contenido), interpolate=False)
    cambios: dict[str, str] = {}
    if nueva:
        cambios = {
            "HERMES_ENTORNO": "produccion",
            "HERMES_CONTRASENA_BASE_DATOS": secrets.token_hex(32),
            "HERMES_CONTRASENA_RAIZ_BASE_DATOS": secrets.token_hex(32),
        }
        print("Se generarán contraseñas aleatorias de MariaDB y un .env privado.")
    else:
        print("Se conserva el .env existente y sus credenciales de MariaDB.")
        for nombre in ("HERMES_CONTRASENA_BASE_DATOS", "HERMES_CONTRASENA_RAIZ_BASE_DATOS"):
            if not variables.get(nombre) or variables[nombre].startswith("cambie_"):
                raise ValueError(
                    "El .env existente contiene contraseñas demostrativas o vacías. "
                    "Configura las credenciales reales de tu MariaDB antes de continuar; "
                    "cambiarlas en .env no cambia un volumen ya inicializado."
                )

    def habilitado(nombre: str) -> bool:
        return str(variables.get(nombre, "false")).lower() in {"true", "1", "yes", "on"}

    if not habilitado("HERMES_TELEGRAM_HABILITADO") and preguntar(
        "¿Configurar Telegram ahora? Necesitas el token de @BotFather"
    ):
        cambios["HERMES_TOKEN_TELEGRAM"] = solicitar_token(
            "Token de Telegram (oculto): ", r"[0-9]+:[A-Za-z0-9_-]+"
        )
        cambios["HERMES_TELEGRAM_HABILITADO"] = "true"
    if not habilitado("HERMES_SLACK_HABILITADO") and preguntar("¿Configurar Slack ahora?"):
        cambios["HERMES_TOKEN_BOT_SLACK"] = solicitar_token(
            "Token del bot Slack (oculto): ", r"xoxb-[A-Za-z0-9-]+"
        )
        cambios["HERMES_TOKEN_APLICACION_SLACK"] = solicitar_token(
            "Token de aplicación Slack (oculto): ", r"xapp-[A-Za-z0-9-]+"
        )
        cambios["HERMES_SLACK_HABILITADO"] = "true"
    if nueva:
        cambios["HERMES_MONITOREO_HABILITADO"] = (
            "true" if preguntar("¿Activar el monitoreo automático?", True) else "false"
        )
        cambios["HERMES_TAREAS_HABILITADAS"] = (
            "true" if preguntar("¿Activar las tareas programadas?", True) else "false"
        )
    for nombre, valor in cambios.items():
        contenido = sustituir_variable(contenido, nombre, valor)

    # Validar antes de reemplazar la configuración que ya funciona.
    valores = dotenv_values(stream=StringIO(contenido), interpolate=False)
    configuracion = Configuracion(
        _env_file=None,
        **{
            nombre.removeprefix("HERMES_").lower(): valor
            for nombre, valor in valores.items()
            if nombre.startswith("HERMES_")
        },
    )
    if configuracion.host_base_datos != "127.0.0.1" or configuracion.puerto_base_datos != int(
        valores.get("PUERTO_PUBLICADO_BASE_DATOS", "3378")
    ):
        raise ValueError("Este instalador requiere MariaDB local y puertos coincidentes en .env.")
    if nueva or cambios:
        guardar_configuracion(ruta, contenido)
    ruta.chmod(0o600)
    Path(".secretos/claves_ssh").mkdir(mode=0o700, parents=True, exist_ok=True)
    Path(".secretos").chmod(0o700)
    hosts = Path(".secretos/hosts_conocidos")
    if not hosts.exists():
        hosts.touch(mode=0o600)
    print("Configuración lista. Las claves SSH y huellas de servidores se preparan después.")


async def preparar_administrador() -> int:
    """Reutiliza administradores existentes sin restablecer su contraseña."""

    nombre = (
        await asyncio.to_thread(input, "Usuario administrador [administrador_local]: ")
    ).strip().lower() or "administrador_local"
    motor = crear_motor_base_datos(obtener_configuracion())
    try:
        async with crear_fabrica_sesiones(motor)() as sesion:
            usuario = await sesion.scalar(select(Usuario).where(Usuario.nombre_usuario == nombre))
            if usuario is not None:
                if not usuario.activo or not any(
                    rol.nombre == "administrador" for rol in usuario.roles
                ):
                    raise ValueError(
                        "La cuenta existente no es un administrador activo. Elige otra cuenta."
                    )
                print("Administrador existente conservado; no se cambió su contraseña.")
                return 0
    finally:
        await motor.dispose()
    nombre_visible = (
        await asyncio.to_thread(input, "Nombre visible [Administrador local]: ")
    ).strip() or "Administrador local"
    return await crear_administrador(nombre, nombre_visible)


async def ofrecer_vinculo() -> None:
    """Vincula una identidad solo si el operador aporta el ID y la cuenta."""

    if not obtener_configuracion().telegram_habilitado:
        return
    print("Abre tu bot en privado y envía /inicio para consultar tu ID numérico.")
    identificador = (
        await asyncio.to_thread(
            input, "ID de Telegram para autorizar (Enter para hacerlo después): "
        )
    ).strip()
    if not identificador:
        print("Vínculo pendiente. Puedes repetir bash instalar.sh para completarlo.")
        return
    if not identificador.isascii() or not identificador.isdecimal() or len(identificador) > 19:
        raise ValueError("El ID de Telegram debe ser un entero positivo de hasta 19 dígitos.")
    usuario = (
        await asyncio.to_thread(input, "Usuario Hermes que deseas vincular [administrador_local]: ")
    ).strip() or "administrador_local"
    await vincular_telegram(usuario, int(identificador), None)


def principal() -> int:
    analizador = argparse.ArgumentParser(description="Asistente local de instalación de Hermes.")
    modos = analizador.add_mutually_exclusive_group(required=True)
    for opcion in (
        "configuracion",
        "administrador",
        "servicios",
        "vincular-telegram",
        "puerto-api",
    ):
        modos.add_argument(f"--{opcion}", action="store_true")
    argumentos = analizador.parse_args()
    try:
        if argumentos.configuracion:
            configurar()
        elif argumentos.administrador:
            return asyncio.run(preparar_administrador())
        elif argumentos.vincular_telegram:
            asyncio.run(ofrecer_vinculo())
        elif argumentos.puerto_api:
            print(obtener_configuracion().puerto_api)
        else:
            configuracion = obtener_configuracion()
            for servicio, habilitado in (
                ("api", True),
                ("telegram", configuracion.telegram_habilitado),
                ("slack", configuracion.slack_habilitado),
                ("monitoreo", configuracion.monitoreo_habilitado),
                ("tareas", configuracion.tareas_habilitadas),
            ):
                print(servicio, str(habilitado).lower())
    except ValidationError:
        print(
            "La configuración no es válida. Revisa .env; sus valores no se mostrarán.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, ErrorHermes) as error:
        mensaje = error.mensaje if isinstance(error, ErrorHermes) else str(error)
        print(mensaje, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nInstalación interrumpida; puedes volver a ejecutarla.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
