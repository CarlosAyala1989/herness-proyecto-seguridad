"""Contrato normalizado de cuentas locales para Linux y Windows Server."""

import re

from aplicacion.acciones.errores import (
    ErrorCuentaOperadorSSH,
    ErrorCuentaSistemaProtegida,
    ErrorEjecucionAccion,
    ErrorGestorUsuariosNoDisponible,
    ErrorGrupoSistemaNoEncontrado,
    ErrorRespuestaAccionNoValida,
    ErrorUsuarioSistemaNoEncontrado,
    ErrorUsuarioSistemaYaExiste,
)
from aplicacion.acciones.registro import CodigoAccion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota

ACCIONES_USUARIOS = frozenset(
    {
        CodigoAccion.LISTAR_USUARIOS_SISTEMA,
        CodigoAccion.CREAR_USUARIO_SISTEMA,
        CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
        CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
        CodigoAccion.ELIMINAR_USUARIO_SISTEMA,
    }
)
ESTADOS_USUARIO = frozenset(
    {
        "habilitado",
        "deshabilitado",
        "bloqueado",
        "sin_contrasena",
        "desconocido",
        "actualizado",
        "eliminado",
    }
)
ACCION_REALIZADA = {
    CodigoAccion.CREAR_USUARIO_SISTEMA: "creacion",
    CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA: "cambio_grupo",
    CodigoAccion.BLOQUEAR_USUARIO_SISTEMA: "bloqueo",
    CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA: "desbloqueo",
    CodigoAccion.ELIMINAR_USUARIO_SISTEMA: "eliminacion",
}
PATRON_NOMBRE_USUARIO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,19}$")
PATRON_IDENTIFICADOR = re.compile(r"^[A-Za-z0-9-]{1,128}$")
CLAVES_MUTACION = {
    "nombre_usuario",
    "estado",
    "cuenta_protegida",
    "nombre_grupo",
    "operacion_grupo",
}
MAX_USUARIOS_RESPUESTA = 2_000
MAX_GRUPOS_POR_USUARIO = 256


def _nombre_grupo_valido(nombre: str) -> bool:
    return bool(
        nombre
        and len(nombre) <= 128
        and nombre[0].isalnum()
        and all(caracter.isalnum() or caracter in "_ .-" for caracter in nombre)
    )


def _nombre_usuario_respuesta_valido(nombre: str) -> bool:
    """Acepta nombres existentes más amplios sin permitir romper el protocolo."""

    return bool(nombre and len(nombre) <= 64 and nombre.isprintable() and "|" not in nombre)


def _interpretar_error_controlado(lineas: list[str]) -> None:
    errores = {
        "HERMES_ERROR=usuario_sistema_no_encontrado": ErrorUsuarioSistemaNoEncontrado,
        "HERMES_ERROR=usuario_sistema_ya_existe": ErrorUsuarioSistemaYaExiste,
        "HERMES_ERROR=grupo_sistema_no_encontrado": ErrorGrupoSistemaNoEncontrado,
        "HERMES_ERROR=gestor_usuarios_no_disponible": ErrorGestorUsuariosNoDisponible,
        "HERMES_ERROR=cuenta_sistema_protegida": ErrorCuentaSistemaProtegida,
        "HERMES_ERROR=cuenta_operador_ssh": ErrorCuentaOperadorSSH,
    }
    if len(lineas) == 1 and lineas[0] in errores:
        raise errores[lineas[0]]()


def _interpretar_listado(lineas: list[str]) -> dict[str, object]:
    usuarios: list[dict[str, object]] = []
    por_nombre: dict[str, dict[str, object]] = {}
    for linea in lineas:
        partes = linea.split("|")
        if len(partes) == 5 and partes[0] == "USUARIO":
            _, nombre, identificador, estado, protegida = partes
            if (
                len(usuarios) >= MAX_USUARIOS_RESPUESTA
                or not _nombre_usuario_respuesta_valido(nombre)
                or not PATRON_IDENTIFICADOR.fullmatch(identificador)
                or estado not in ESTADOS_USUARIO
                or protegida not in {"true", "false"}
                or nombre in por_nombre
            ):
                raise ErrorRespuestaAccionNoValida()
            usuario: dict[str, object] = {
                "nombre_usuario": nombre,
                "identificador": identificador,
                "estado": estado,
                "cuenta_protegida": protegida == "true",
                "grupos": [],
            }
            usuarios.append(usuario)
            por_nombre[nombre] = usuario
        elif len(partes) == 3 and partes[0] == "GRUPO":
            _, nombre, grupo = partes
            usuario = por_nombre.get(nombre)
            if usuario is None or not _nombre_grupo_valido(grupo):
                raise ErrorRespuestaAccionNoValida()
            grupos = usuario["grupos"]
            if not isinstance(grupos, list) or len(grupos) >= MAX_GRUPOS_POR_USUARIO:
                raise ErrorRespuestaAccionNoValida()
            if grupo not in grupos:
                grupos.append(grupo)
        else:
            raise ErrorRespuestaAccionNoValida()
    return {"usuarios": usuarios, "total_usuarios": len(usuarios)}


def _interpretar_mutacion(
    codigo: CodigoAccion,
    lineas: list[str],
) -> dict[str, object]:
    campos: dict[str, str] = {}
    for linea in lineas:
        clave, separador, valor = linea.partition("=")
        if not separador or clave not in CLAVES_MUTACION or clave in campos:
            raise ErrorRespuestaAccionNoValida()
        campos[clave] = valor
    if campos.keys() != CLAVES_MUTACION:
        raise ErrorRespuestaAccionNoValida()
    if (
        not PATRON_NOMBRE_USUARIO.fullmatch(campos["nombre_usuario"])
        or campos["estado"] not in ESTADOS_USUARIO
        or campos["cuenta_protegida"] not in {"true", "false"}
    ):
        raise ErrorRespuestaAccionNoValida()
    grupo = campos["nombre_grupo"]
    operacion = campos["operacion_grupo"]
    es_cambio_grupo = codigo is CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA
    if es_cambio_grupo:
        if not _nombre_grupo_valido(grupo) or operacion not in {"agregar", "quitar"}:
            raise ErrorRespuestaAccionNoValida()
    elif grupo != "no_aplica" or operacion != "no_aplica":
        raise ErrorRespuestaAccionNoValida()
    return {
        "nombre_usuario": campos["nombre_usuario"],
        "estado": campos["estado"],
        "cuenta_protegida": campos["cuenta_protegida"] == "true",
        "nombre_grupo": grupo if es_cambio_grupo else None,
        "operacion_grupo": operacion if es_cambio_grupo else None,
        "accion_realizada": ACCION_REALIZADA[codigo],
    }


def interpretar_resultado_usuarios(
    codigo: CodigoAccion,
    resultado: ResultadoEjecucionRemota,
) -> dict[str, object]:
    """Valida marcadores, límites y campos antes de exponer datos remotos."""

    lineas = [linea.strip() for linea in resultado.salida.splitlines()]
    _interpretar_error_controlado(lineas)
    if resultado.codigo_salida != 0:
        raise ErrorEjecucionAccion(resultado.codigo_salida)
    if codigo not in ACCIONES_USUARIOS:
        raise ErrorRespuestaAccionNoValida()
    marcador = f"HERMES_ACCION={codigo.value}"
    if not lineas or lineas[0] != marcador:
        raise ErrorRespuestaAccionNoValida()
    if codigo is CodigoAccion.LISTAR_USUARIOS_SISTEMA:
        return _interpretar_listado(lineas[1:])
    return _interpretar_mutacion(codigo, lineas[1:])
