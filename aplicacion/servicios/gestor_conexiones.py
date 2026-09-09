"""Orquestación común de transporte SSH y adaptadores de plataforma."""

from collections.abc import Callable

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.adaptadores.sistema_operativo import AdaptadorSistemaOperativo
from aplicacion.adaptadores.windows import AdaptadorWindows
from aplicacion.errores import ErrorHermes
from aplicacion.esquemas.conexion import ComprobacionConexionRespuesta
from aplicacion.interfaces.transporte_remoto import TransporteRemoto
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import (
    ResultadoAuditoria,
    SistemaOperativo,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.servidor import Servidor
from aplicacion.servicios.auditoria import preparar_registro_auditoria
from aplicacion.servicios.gestor_inventario import obtener_servidor

FabricaTransporteRemoto = Callable[[Servidor], TransporteRemoto]


def _obtener_adaptador(sistema: SistemaOperativo) -> AdaptadorSistemaOperativo:
    if sistema is SistemaOperativo.LINUX:
        return AdaptadorLinux()
    if sistema is SistemaOperativo.WINDOWS_SERVER:
        return AdaptadorWindows()
    raise ValueError("El sistema operativo registrado no tiene adaptador.")


async def comprobar_conexion_servidor(
    sesion: AsyncSession,
    id_servidor: int,
    usuario: Usuario,
    solicitud: Request,
    fabrica_transporte: FabricaTransporteRemoto,
) -> ComprobacionConexionRespuesta:
    """Verifica SSH y plataforma sin aceptar comandos desde la solicitud."""

    servidor = await obtener_servidor(sesion, id_servidor)
    adaptador = _obtener_adaptador(servidor.sistema_operativo)
    transporte = fabrica_transporte(servidor)
    try:
        resultado = await transporte.ejecutar_comando_controlado(
            adaptador.comando_deteccion,
            solicitud.app.state.configuracion.tiempo_operacion_ssh_segundos,
            solicitud.app.state.configuracion.limite_salida_ssh_bytes,
        )
        sistema_detectado = adaptador.interpretar_deteccion(resultado)
    except ErrorHermes as error:
        preparar_registro_auditoria(
            sesion,
            usuario=usuario,
            accion="comprobar_conexion_ssh",
            tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
            id_recurso=servidor.id_servidor,
            resultado=ResultadoAuditoria.ERROR,
            solicitud=solicitud,
            detalle=f"Comprobación SSH fallida con código {error.codigo}.",
        )
        await sesion.commit()
        raise
    finally:
        await transporte.cerrar()

    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="comprobar_conexion_ssh",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=servidor.id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Identidad, autenticación y sistema operativo verificados.",
    )
    await sesion.commit()
    return ComprobacionConexionRespuesta(
        id_servidor=servidor.id_servidor,
        nombre_servidor=servidor.nombre,
        sistema_registrado=servidor.sistema_operativo,
        sistema_detectado=sistema_detectado.sistema_operativo,
        version_detectada=sistema_detectado.version,
        nombre_equipo=sistema_detectado.nombre_equipo,
        duracion_ms=round(resultado.duracion_segundos * 1000, 2),
    )
