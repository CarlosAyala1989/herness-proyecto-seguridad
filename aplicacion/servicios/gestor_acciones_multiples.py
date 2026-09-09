"""Orquestación concurrente y aislada de acciones sobre varios servidores."""

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from aplicacion.acciones.registro import CodigoAccion, obtener_definicion_accion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import (
    ErrorConfirmacionRequerida,
    ErrorHermes,
    ErrorLimiteSeleccionServidores,
    ErrorNoAutenticado,
    ErrorSeleccionServidoresVacia,
)
from aplicacion.esquemas.acciones import (
    ResultadoAccionMultipleRespuesta,
    ResultadoServidorAccionMultiple,
    SeleccionServidores,
    SolicitudEjecucionMultiple,
)
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    ResultadoAuditoria,
    SistemaOperativo,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.autenticacion import comprobar_permiso_usuario
from aplicacion.servicios.auditoria import ContextoAuditoria, preparar_registro_auditoria
from aplicacion.servicios.gestor_acciones import ejecutar_accion_servidor
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto
from aplicacion.servicios.gestor_inventario import obtener_grupo

registrador = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ObjetivoAccionMultiple:
    """Datos mínimos e inmutables de un destino resuelto."""

    id_servidor: int
    nombre_servidor: str | None
    sistema_operativo: SistemaOperativo | None
    existe: bool = True


async def resolver_objetivos_accion_multiple(
    sesion: AsyncSession,
    seleccion: SeleccionServidores,
    maximo_servidores: int,
) -> list[ObjetivoAccionMultiple]:
    """Resuelve una selección dinámica y aplica el límite de seguridad solicitado."""

    servidores: list[Servidor]
    objetivos: list[ObjetivoAccionMultiple]

    if seleccion.ids_servidores is not None:
        ids = seleccion.ids_servidores
        if len(ids) > maximo_servidores:
            raise ErrorLimiteSeleccionServidores(maximo_servidores)
        consulta = select(Servidor).where(Servidor.id_servidor.in_(ids))
        encontrados = {
            servidor.id_servidor: servidor for servidor in await sesion.scalars(consulta)
        }
        objetivos = []
        for id_servidor in ids:
            servidor = encontrados.get(id_servidor)
            objetivos.append(
                ObjetivoAccionMultiple(
                    id_servidor=id_servidor,
                    nombre_servidor=servidor.nombre if servidor else None,
                    sistema_operativo=servidor.sistema_operativo if servidor else None,
                    existe=servidor is not None,
                )
            )
    elif seleccion.id_grupo is not None:
        grupo = await obtener_grupo(sesion, seleccion.id_grupo)
        servidores = sorted(grupo.servidores, key=lambda servidor: servidor.id_servidor)
        objetivos = [
            ObjetivoAccionMultiple(
                id_servidor=servidor.id_servidor,
                nombre_servidor=servidor.nombre,
                sistema_operativo=servidor.sistema_operativo,
            )
            for servidor in servidores
        ]
    else:
        consulta = select(Servidor).where(Servidor.activo.is_(True)).order_by(Servidor.id_servidor)
        servidores = list(await sesion.scalars(consulta))
        objetivos = [
            ObjetivoAccionMultiple(
                id_servidor=servidor.id_servidor,
                nombre_servidor=servidor.nombre,
                sistema_operativo=servidor.sistema_operativo,
            )
            for servidor in servidores
        ]

    if not objetivos:
        raise ErrorSeleccionServidoresVacia()
    if len(objetivos) > maximo_servidores:
        raise ErrorLimiteSeleccionServidores(maximo_servidores)
    return objetivos


async def _cargar_usuario(
    sesion: AsyncSession,
    id_usuario: int,
) -> Usuario:
    consulta = (
        select(Usuario)
        .where(Usuario.id_usuario == id_usuario)
        .options(selectinload(Usuario.roles).selectinload(Rol.permisos))
    )
    usuario = await sesion.scalar(consulta)
    if usuario is None or not usuario.activo:
        raise ErrorNoAutenticado()
    return usuario


async def _auditar_error_orquestacion(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    usuario: Usuario,
    objetivo: ObjetivoAccionMultiple,
    codigo_accion: CodigoAccion,
    detalle: str,
    solicitud: Request | None,
    contexto_auditoria: ContextoAuditoria | None,
) -> None:
    async with fabrica_sesiones() as sesion:
        preparar_registro_auditoria(
            sesion,
            usuario=usuario,
            accion=f"ejecutar_accion_{codigo_accion.value}",
            tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
            id_recurso=objetivo.id_servidor,
            resultado=ResultadoAuditoria.ERROR,
            solicitud=solicitud,
            contexto=contexto_auditoria,
            detalle=detalle,
        )
        await sesion.commit()


def _resultado_error(
    objetivo: ObjetivoAccionMultiple,
    inicio: float,
    codigo: str,
    mensaje: str,
) -> ResultadoServidorAccionMultiple:
    return ResultadoServidorAccionMultiple(
        id_servidor=objetivo.id_servidor,
        nombre_servidor=objetivo.nombre_servidor,
        sistema_operativo=objetivo.sistema_operativo,
        estado="error",
        codigo_error=codigo,
        mensaje_error=mensaje,
        duracion_ms=round((perf_counter() - inicio) * 1_000, 2),
    )


async def _ejecutar_objetivo(
    objetivo: ObjetivoAccionMultiple,
    semaforo: asyncio.Semaphore,
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    usuario_inicial: Usuario,
    codigo_accion: CodigoAccion,
    datos: SolicitudEjecucionMultiple,
    solicitud: Request | None,
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
    contexto_auditoria: ContextoAuditoria | None,
) -> ResultadoServidorAccionMultiple:
    inicio = perf_counter()
    if not objetivo.existe:
        await _auditar_error_orquestacion(
            fabrica_sesiones,
            usuario_inicial,
            objetivo,
            codigo_accion,
            "El identificador de servidor seleccionado no existe.",
            solicitud,
            contexto_auditoria,
        )
        return _resultado_error(
            objetivo,
            inicio,
            "recurso_no_encontrado",
            "No se encontró el servidor seleccionado.",
        )

    try:
        async with semaforo:
            async with asyncio.timeout(configuracion.tiempo_limite_accion_multiple_segundos):
                async with fabrica_sesiones() as sesion:
                    usuario = await _cargar_usuario(sesion, usuario_inicial.id_usuario)
                    resultado = await ejecutar_accion_servidor(
                        sesion,
                        objetivo.id_servidor,
                        codigo_accion.value,
                        datos.como_solicitud_individual(),
                        usuario,
                        solicitud,
                        fabrica_transporte,
                        configuracion,
                        contexto_auditoria,
                    )
        return ResultadoServidorAccionMultiple(
            id_servidor=resultado.id_servidor,
            nombre_servidor=resultado.nombre_servidor,
            sistema_operativo=resultado.sistema_operativo,
            estado="completada",
            datos=resultado.datos,
            duracion_ms=round((perf_counter() - inicio) * 1_000, 2),
        )
    except TimeoutError:
        await _auditar_error_orquestacion(
            fabrica_sesiones,
            usuario_inicial,
            objetivo,
            codigo_accion,
            "La acción superó el tiempo límite individual.",
            solicitud,
            contexto_auditoria,
        )
        return _resultado_error(
            objetivo,
            inicio,
            "tiempo_limite_accion_multiple",
            "La operación superó el tiempo límite para este servidor.",
        )
    except ErrorHermes as error:
        return _resultado_error(objetivo, inicio, error.codigo, error.mensaje)
    except Exception as error:
        registrador.exception(
            "Falló un destino de una acción múltiple. id_servidor=%s accion=%s",
            objetivo.id_servidor,
            codigo_accion.value,
            exc_info=error,
        )
        await _auditar_error_orquestacion(
            fabrica_sesiones,
            usuario_inicial,
            objetivo,
            codigo_accion,
            "La acción produjo un error interno aislado.",
            solicitud,
            contexto_auditoria,
        )
        return _resultado_error(
            objetivo,
            inicio,
            "error_interno",
            "Ocurrió un error interno al operar este servidor.",
        )


async def ejecutar_accion_multiple(
    sesion: AsyncSession,
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    codigo_accion: str,
    datos: SolicitudEjecucionMultiple,
    usuario: Usuario,
    solicitud: Request | None,
    fabrica_transporte: FabricaTransporteRemoto,
    configuracion: Configuracion,
    contexto_auditoria: ContextoAuditoria | None = None,
) -> ResultadoAccionMultipleRespuesta:
    """Ejecuta concurrentemente sin compartir sesiones ni propagar fallos entre destinos."""

    inicio = perf_counter()
    definicion = obtener_definicion_accion(codigo_accion)
    await comprobar_permiso_usuario(
        sesion,
        solicitud,
        usuario,
        definicion.codigo_permiso,
        contexto_auditoria,
    )
    definicion.validar_parametros(datos.parametros)
    if definicion.requiere_confirmacion and not datos.confirmar:
        raise ErrorConfirmacionRequerida()

    objetivos = await resolver_objetivos_accion_multiple(
        sesion,
        datos.seleccion,
        configuracion.max_servidores_accion_multiple,
    )
    semaforo = asyncio.Semaphore(configuracion.max_concurrencia_acciones_multiples)
    resultados = await asyncio.gather(
        *(
            _ejecutar_objetivo(
                objetivo,
                semaforo,
                fabrica_sesiones,
                usuario,
                definicion.codigo,
                datos,
                solicitud,
                fabrica_transporte,
                configuracion,
                contexto_auditoria,
            )
            for objetivo in objetivos
        )
    )
    completados = sum(resultado.estado == "completada" for resultado in resultados)
    fallidos = len(resultados) - completados
    estado = (
        "completada"
        if fallidos == 0
        else "fallida"
        if completados == 0
        else "completada_con_errores"
    )
    return ResultadoAccionMultipleRespuesta(
        accion=definicion.codigo,
        estado=estado,
        total_servidores=len(resultados),
        servidores_completados=completados,
        servidores_fallidos=fallidos,
        duracion_ms=round((perf_counter() - inicio) * 1_000, 2),
        resultados=resultados,
    )
