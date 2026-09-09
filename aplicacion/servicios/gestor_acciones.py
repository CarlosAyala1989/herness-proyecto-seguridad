"""Autorización, ejecución y auditoría del registro cerrado de acciones."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.acciones.errores import ErrorParametrosAccion
from aplicacion.acciones.registro import (
    DefinicionAccion,
    listar_definiciones_acciones,
    obtener_definicion_accion,
)
from aplicacion.errores import ErrorConfirmacionRequerida, ErrorHermes
from aplicacion.esquemas.acciones import (
    AccionDisponibleRespuesta,
    ResultadoAccionRespuesta,
    SolicitudEjecucionAccion,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import ResultadoAuditoria, TipoRecursoAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.autenticacion import comprobar_permiso_usuario
from aplicacion.servicios.auditoria import preparar_registro_auditoria
from aplicacion.servicios.gestor_conexiones import (
    FabricaTransporteRemoto,
    obtener_adaptador,
)
from aplicacion.servicios.gestor_inventario import obtener_servidor


def listar_acciones_para_usuario(usuario: Usuario) -> list[AccionDisponibleRespuesta]:
    """Filtra ayuda según los permisos persistentes del usuario."""

    permisos = {permiso.codigo for rol in usuario.roles for permiso in rol.permisos}
    return [
        AccionDisponibleRespuesta(
            codigo=definicion.codigo,
            descripcion=definicion.descripcion,
            requiere_confirmacion=definicion.requiere_confirmacion,
        )
        for definicion in listar_definiciones_acciones()
        if definicion.codigo_permiso in permisos
    ]


async def _auditar_resultado(
    sesion: AsyncSession,
    solicitud: Request,
    usuario: Usuario,
    servidor: Servidor,
    definicion: DefinicionAccion,
    resultado: ResultadoAuditoria,
    detalle: str,
) -> None:
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion=f"ejecutar_accion_{definicion.codigo.value}",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=servidor.id_servidor,
        resultado=resultado,
        solicitud=solicitud,
        detalle=detalle,
    )
    await sesion.commit()


async def ejecutar_accion_servidor(
    sesion: AsyncSession,
    id_servidor: int,
    codigo_accion: str,
    datos_solicitud: SolicitudEjecucionAccion,
    usuario: Usuario,
    solicitud: Request,
    fabrica_transporte: FabricaTransporteRemoto,
) -> ResultadoAccionRespuesta:
    """Ejecuta solo una definición registrada, autorizada y validada."""

    definicion = obtener_definicion_accion(codigo_accion)
    await comprobar_permiso_usuario(
        sesion,
        solicitud,
        usuario,
        definicion.codigo_permiso,
    )
    servidor = await obtener_servidor(sesion, id_servidor)

    try:
        parametros = definicion.validar_parametros(datos_solicitud.parametros)
    except ErrorParametrosAccion:
        await _auditar_resultado(
            sesion,
            solicitud,
            usuario,
            servidor,
            definicion,
            ResultadoAuditoria.ERROR,
            "Parámetros de acción rechazados.",
        )
        raise

    if definicion.requiere_confirmacion and not datos_solicitud.confirmar:
        await _auditar_resultado(
            sesion,
            solicitud,
            usuario,
            servidor,
            definicion,
            ResultadoAuditoria.DENEGADO,
            "La acción sensible no recibió confirmación explícita.",
        )
        raise ErrorConfirmacionRequerida()

    adaptador = obtener_adaptador(servidor.sistema_operativo)
    accion_preparada = adaptador.preparar_accion(definicion.codigo, parametros)
    transporte = fabrica_transporte(servidor)
    try:
        resultado_remoto = await transporte.ejecutar_comando_controlado(
            accion_preparada.comando,
            solicitud.app.state.configuracion.tiempo_operacion_ssh_segundos,
            solicitud.app.state.configuracion.limite_salida_ssh_bytes,
        )
        resultado_normalizado = adaptador.interpretar_accion(
            definicion.codigo,
            resultado_remoto,
        )
    except ErrorHermes as error:
        await _auditar_resultado(
            sesion,
            solicitud,
            usuario,
            servidor,
            definicion,
            ResultadoAuditoria.ERROR,
            f"Acción fallida con código {error.codigo}.",
        )
        raise
    finally:
        await transporte.cerrar()

    await _auditar_resultado(
        sesion,
        solicitud,
        usuario,
        servidor,
        definicion,
        ResultadoAuditoria.EXITO,
        "Acción autorizada completada.",
    )
    return ResultadoAccionRespuesta(
        id_servidor=servidor.id_servidor,
        nombre_servidor=servidor.nombre,
        sistema_operativo=servidor.sistema_operativo,
        accion=definicion.codigo,
        datos=resultado_normalizado,
        duracion_ms=round(resultado_remoto.duracion_segundos * 1000, 2),
    )
