"""Escritura privada de la configuración administrada desde la terminal local."""

import os
import re
import tempfile
from pathlib import Path


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
    """Actualiza valores simples conservando las demás líneas del archivo."""

    patron = rf"(?m)^(?:export[ \t]+)?{re.escape(nombre)}[ \t]*=.*$"
    linea = f"{nombre}={valor}"
    if re.search(patron, contenido):
        return re.sub(patron, lambda _: linea, contenido)
    return contenido.rstrip("\n") + "\n" + linea + "\n"


def fijar_propietario_telegram(identificador: int, ruta: Path = Path(".env")) -> None:
    """Fija el único ID autorizado; se invoca solo desde comandos locales."""

    if (
        isinstance(identificador, bool)
        or not isinstance(identificador, int)
        or not 1 <= identificador <= 9_223_372_036_854_775_807
    ):
        raise ValueError("El ID del propietario de Telegram no es válido.")
    if ruta.is_symlink():
        raise ValueError("El archivo .env no puede ser un enlace simbólico.")
    contenido = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    guardar_configuracion(
        ruta, sustituir_variable(contenido, "HERMES_ID_PROPIETARIO_TELEGRAM", str(identificador))
    )
