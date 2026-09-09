"""Validación común de resultados de servicios Linux y Windows Server."""

import re

from aplicacion.acciones.errores import (
    ErrorEjecucionAccion,
    ErrorGestorServiciosNoDisponible,
    ErrorRespuestaAccionNoValida,
    ErrorServicioNoEncontrado,
)
from aplicacion.acciones.registro import CodigoAccion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota

ACCIONES_SERVICIO = frozenset(
    {
        CodigoAccion.CONSULTAR_SERVICIO,
        CodigoAccion.INICIAR_SERVICIO,
        CodigoAccion.DETENER_SERVICIO,
        CodigoAccion.REINICIAR_SERVICIO,
    }
)
ESTADOS_SERVICIO = frozenset(
    {
        "activo",
        "inactivo",
        "iniciando",
        "deteniendo",
        "pausado",
        "fallido",
        "recargando",
        "desconocido",
    }
)
ACCION_REALIZADA = {
    CodigoAccion.CONSULTAR_SERVICIO: "consulta",
    CodigoAccion.INICIAR_SERVICIO: "inicio",
    CodigoAccion.DETENER_SERVICIO: "detencion",
    CodigoAccion.REINICIAR_SERVICIO: "reinicio",
}
PATRON_NOMBRE_SERVICIO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
PATRON_ESTADO_NATIVO = re.compile(r"^[A-Za-z][A-Za-z0-9_.@()-]{0,63}$")
CLAVES_RESPUESTA = {
    "nombre_servicio",
    "estado",
    "estado_nativo",
    "inicio_automatico",
}


def _interpretar_error_controlado(lineas: list[str]) -> None:
    if lineas == ["HERMES_ERROR=servicio_no_encontrado"]:
        raise ErrorServicioNoEncontrado()
    if lineas == ["HERMES_ERROR=gestor_servicios_no_disponible"]:
        raise ErrorGestorServiciosNoDisponible()


def interpretar_resultado_servicio(
    codigo: CodigoAccion,
    resultado: ResultadoEjecucionRemota,
) -> dict[str, str | bool | None]:
    """Exige un contrato idéntico y acotado para ambos adaptadores."""

    lineas = [linea.strip() for linea in resultado.salida.splitlines()]
    _interpretar_error_controlado(lineas)
    if resultado.codigo_salida != 0:
        raise ErrorEjecucionAccion(resultado.codigo_salida)
    if codigo not in ACCIONES_SERVICIO:
        raise ErrorRespuestaAccionNoValida()
    marcador = f"HERMES_ACCION={codigo.value}"
    if not lineas or lineas[0] != marcador:
        raise ErrorRespuestaAccionNoValida()

    campos: dict[str, str] = {}
    for linea in lineas[1:]:
        clave, separador, valor = linea.partition("=")
        if not separador or clave not in CLAVES_RESPUESTA or clave in campos:
            raise ErrorRespuestaAccionNoValida()
        campos[clave] = valor
    if campos.keys() != CLAVES_RESPUESTA:
        raise ErrorRespuestaAccionNoValida()
    if not PATRON_NOMBRE_SERVICIO.fullmatch(campos["nombre_servicio"]):
        raise ErrorRespuestaAccionNoValida()
    if campos["estado"] not in ESTADOS_SERVICIO:
        raise ErrorRespuestaAccionNoValida()
    if not PATRON_ESTADO_NATIVO.fullmatch(campos["estado_nativo"]):
        raise ErrorRespuestaAccionNoValida()

    valor_inicio = campos["inicio_automatico"]
    if valor_inicio == "true":
        inicio_automatico: bool | None = True
    elif valor_inicio == "false":
        inicio_automatico = False
    elif valor_inicio == "no_disponible":
        inicio_automatico = None
    else:
        raise ErrorRespuestaAccionNoValida()

    return {
        "nombre_servicio": campos["nombre_servicio"],
        "estado": campos["estado"],
        "estado_nativo": campos["estado_nativo"],
        "inicio_automatico": inicio_automatico,
        "accion_realizada": ACCION_REALIZADA[codigo],
    }
