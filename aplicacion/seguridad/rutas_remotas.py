"""Validación léxica de rutas remotas Linux y Windows Server."""

import re
from pathlib import PurePosixPath, PureWindowsPath

from aplicacion.errores import ErrorRutaRemotaNoValida
from aplicacion.modelos.enumeraciones import SistemaOperativo

MAX_LONGITUD_RUTA_REMOTA = 1024
PATRON_UNIDAD_WINDOWS = re.compile(r"^[A-Za-z]:/")
NOMBRES_RESERVADOS_WINDOWS = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{numero}" for numero in range(1, 10)),
    *(f"lpt{numero}" for numero in range(1, 10)),
}


def validar_y_normalizar_ruta_remota(
    ruta: str,
    sistema_operativo: SistemaOperativo,
    *,
    permitir_raiz: bool = False,
) -> str:
    """Devuelve una ruta absoluta normalizada sin segmentos de escape."""

    if not isinstance(ruta, str):
        raise ErrorRutaRemotaNoValida()
    ruta = ruta.strip()
    if (
        not ruta
        or len(ruta) > MAX_LONGITUD_RUTA_REMOTA
        or any(ord(caracter) < 32 or ord(caracter) == 127 for caracter in ruta)
    ):
        raise ErrorRutaRemotaNoValida()

    if sistema_operativo is SistemaOperativo.LINUX:
        if "\\" in ruta:
            raise ErrorRutaRemotaNoValida()
        partes_originales = ruta.split("/")
        if ".." in partes_originales:
            raise ErrorRutaRemotaNoValida()
        objeto = PurePosixPath(ruta)
        if not objeto.is_absolute():
            raise ErrorRutaRemotaNoValida()
        normalizada = str(objeto)
        if normalizada == "/" and not permitir_raiz:
            raise ErrorRutaRemotaNoValida("No se permite autorizar la raíz completa del servidor.")
        return normalizada

    if sistema_operativo is SistemaOperativo.WINDOWS_SERVER:
        ruta_uniforme = ruta.replace("\\", "/")
        if not PATRON_UNIDAD_WINDOWS.match(ruta_uniforme) or ruta_uniforme.startswith("//"):
            raise ErrorRutaRemotaNoValida()
        partes_originales = ruta_uniforme[3:].split("/")
        if ".." in partes_originales:
            raise ErrorRutaRemotaNoValida()
        objeto_windows = PureWindowsPath(ruta_uniforme)
        if not objeto_windows.is_absolute():
            raise ErrorRutaRemotaNoValida()
        for parte in objeto_windows.parts[1:]:
            base = parte.rstrip(". ").split(".", maxsplit=1)[0].casefold()
            if (
                not parte
                or parte.endswith((".", " "))
                or ":" in parte
                or base in NOMBRES_RESERVADOS_WINDOWS
            ):
                raise ErrorRutaRemotaNoValida()
        normalizada = objeto_windows.as_posix()
        if len(objeto_windows.parts) == 1 and not permitir_raiz:
            raise ErrorRutaRemotaNoValida(
                "No se permite autorizar la unidad completa del servidor."
            )
        return normalizada

    raise ErrorRutaRemotaNoValida("El sistema operativo no admite rutas remotas.")


def ruta_esta_contenida(
    ruta: str,
    raiz: str,
    sistema_operativo: SistemaOperativo,
) -> bool:
    """Compara componentes completos y respeta mayúsculas de Windows."""

    clase_ruta = PurePosixPath if sistema_operativo is SistemaOperativo.LINUX else PureWindowsPath
    ruta_objeto = clase_ruta(ruta)
    raiz_objeto = clase_ruta(raiz)
    partes_ruta = ruta_objeto.parts
    partes_raiz = raiz_objeto.parts
    if sistema_operativo is SistemaOperativo.WINDOWS_SERVER:
        partes_ruta = tuple(parte.casefold() for parte in partes_ruta)
        partes_raiz = tuple(parte.casefold() for parte in partes_raiz)
    return len(partes_ruta) >= len(partes_raiz) and partes_ruta[: len(partes_raiz)] == partes_raiz
