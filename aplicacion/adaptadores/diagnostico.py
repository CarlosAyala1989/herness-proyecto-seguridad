"""Normalización común de diagnósticos Linux y Windows Server."""

from math import isfinite

from aplicacion.acciones.errores import ErrorEjecucionAccion, ErrorRespuestaAccionNoValida
from aplicacion.acciones.registro import CodigoAccion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota

ValorDiagnostico = str | int | float | bool | None
VALOR_NO_DISPONIBLE = "no_disponible"
CLAVES_DIAGNOSTICO = {
    "estado",
    "cpu_porcentaje",
    "memoria_porcentaje",
    "disco_porcentaje",
    "tiempo_actividad_segundos",
    "sistema",
    "version",
    "nombre_equipo",
}


def _convertir_porcentaje(valor: str) -> float | None:
    if valor == VALOR_NO_DISPONIBLE:
        return None
    try:
        porcentaje = float(valor)
    except ValueError:
        raise ErrorRespuestaAccionNoValida() from None
    if not isfinite(porcentaje) or not 0 <= porcentaje <= 100:
        raise ErrorRespuestaAccionNoValida()
    return round(porcentaje, 2)


def _convertir_tiempo_actividad(valor: str) -> int | None:
    if valor == VALOR_NO_DISPONIBLE:
        return None
    if not valor.isascii() or not valor.isdigit():
        raise ErrorRespuestaAccionNoValida()
    segundos = int(valor)
    if segundos > 9_223_372_036_854_775_807:
        raise ErrorRespuestaAccionNoValida()
    return segundos


def _convertir_texto(valor: str, limite: int) -> str | None:
    if valor == VALOR_NO_DISPONIBLE:
        return None
    texto = valor.strip()
    if not texto or not texto.isprintable():
        raise ErrorRespuestaAccionNoValida()
    return texto[:limite]


def interpretar_diagnostico(
    resultado: ResultadoEjecucionRemota,
) -> dict[str, ValorDiagnostico]:
    """Valida marcadores y devuelve campos idénticos para ambos sistemas."""

    if resultado.codigo_salida != 0:
        raise ErrorEjecucionAccion(resultado.codigo_salida)
    lineas = [linea.strip() for linea in resultado.salida.splitlines()]
    marcador = f"HERMES_ACCION={CodigoAccion.OBTENER_DIAGNOSTICO.value}"
    if not lineas or lineas[0] != marcador:
        raise ErrorRespuestaAccionNoValida()

    campos: dict[str, str] = {}
    for linea in lineas[1:]:
        clave, separador, valor = linea.partition("=")
        if not separador or clave not in CLAVES_DIAGNOSTICO or clave in campos:
            raise ErrorRespuestaAccionNoValida()
        campos[clave] = valor
    if campos.keys() != CLAVES_DIAGNOSTICO or campos["estado"] != "disponible":
        raise ErrorRespuestaAccionNoValida()

    return {
        "estado": "disponible",
        "cpu_porcentaje": _convertir_porcentaje(campos["cpu_porcentaje"]),
        "memoria_porcentaje": _convertir_porcentaje(campos["memoria_porcentaje"]),
        "disco_porcentaje": _convertir_porcentaje(campos["disco_porcentaje"]),
        "tiempo_actividad_segundos": _convertir_tiempo_actividad(
            campos["tiempo_actividad_segundos"]
        ),
        "sistema": _convertir_texto(campos["sistema"], 200),
        "version": _convertir_texto(campos["version"], 200),
        "nombre_equipo": _convertir_texto(campos["nombre_equipo"], 255),
    }
