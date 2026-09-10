"""Casos de uso persistentes para administración segura de archivos."""

from collections.abc import Callable

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.configuracion import Configuracion
from aplicacion.errores import (
    ErrorConflictoDatos,
    ErrorHermes,
    ErrorLimiteArchivoExcedido,
    ErrorRecursoNoEncontrado,
    ErrorRutaRemotaNoPermitida,
    ErrorServidorInactivo,
)
from aplicacion.esquemas.archivos import (
    CargaArchivoRespuesta,
    CrearRutaArchivoPermitida,
    DescargaArchivo,
    InformacionArchivoRespuesta,
)
from aplicacion.interfaces.transporte_remoto import TransporteRemoto
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import ResultadoAuditoria, TipoRecursoAuditoria
from aplicacion.modelos.ruta_archivo_permitida import RutaArchivoPermitida
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.rutas_remotas import (
    ruta_esta_contenida,
    validar_y_normalizar_ruta_remota,
)
from aplicacion.servicios.auditoria import ContextoAuditoria, preparar_registro_auditoria
from aplicacion.servicios.gestor_inventario import obtener_servidor
from aplicacion.servicios.persistencia import confirmar_transaccion

FabricaTransporteArchivos = Callable[[Servidor], TransporteRemoto]


async def listar_rutas_archivos(
    sesion: AsyncSession,
    id_servidor: int,
) -> list[RutaArchivoPermitida]:
    """Lista la configuración de rutas de un servidor."""

    await obtener_servidor(sesion, id_servidor)
    consulta = (
        select(RutaArchivoPermitida)
        .where(RutaArchivoPermitida.id_servidor == id_servidor)
        .order_by(RutaArchivoPermitida.ruta)
    )
    return list((await sesion.scalars(consulta)).all())


async def crear_ruta_archivo(
    sesion: AsyncSession,
    id_servidor: int,
    datos: CrearRutaArchivoPermitida,
    usuario: Usuario,
    solicitud: Request,
) -> RutaArchivoPermitida:
    """Registra una raíz normalizada para la plataforma inventariada."""

    servidor = await obtener_servidor(sesion, id_servidor)
    ruta = validar_y_normalizar_ruta_remota(datos.ruta, servidor.sistema_operativo)
    entidad = RutaArchivoPermitida(
        id_servidor=id_servidor,
        ruta=ruta,
        descripcion=datos.descripcion,
        permite_lectura=datos.permite_lectura,
        permite_escritura=datos.permite_escritura,
        activo=datos.activo,
    )
    sesion.add(entidad)
    try:
        await sesion.flush()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos("La ruta ya está registrada para este servidor.") from None
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="crear_ruta_archivo_permitida",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Raíz remota permitida incorporada sin revelar su contenido.",
    )
    await confirmar_transaccion(sesion, "No fue posible registrar la ruta remota.")
    return entidad


async def eliminar_ruta_archivo(
    sesion: AsyncSession,
    id_servidor: int,
    id_ruta: int,
    usuario: Usuario,
    solicitud: Request,
) -> None:
    """Elimina una raíz comprobando su pertenencia al servidor indicado."""

    consulta = select(RutaArchivoPermitida).where(
        RutaArchivoPermitida.id_ruta_archivo_permitida == id_ruta,
        RutaArchivoPermitida.id_servidor == id_servidor,
    )
    entidad = await sesion.scalar(consulta)
    if entidad is None:
        raise ErrorRecursoNoEncontrado("ruta de archivos permitida")
    await sesion.delete(entidad)
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="eliminar_ruta_archivo_permitida",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Raíz remota permitida eliminada.",
    )
    await sesion.commit()


def resolver_rutas_habilitadas(
    servidor: Servidor,
    ruta_remota: str,
    *,
    escritura: bool,
) -> tuple[str, tuple[str, ...]]:
    normalizada = validar_y_normalizar_ruta_remota(ruta_remota, servidor.sistema_operativo)
    rutas = tuple(
        item.ruta
        for item in servidor.rutas_archivos_permitidas
        if item.activo
        and (item.permite_escritura if escritura else item.permite_lectura)
        and ruta_esta_contenida(normalizada, item.ruta, servidor.sistema_operativo)
    )
    if not rutas:
        raise ErrorRutaRemotaNoPermitida()
    return normalizada, rutas


def _preparar_auditoria_archivo(
    sesion: AsyncSession,
    *,
    usuario: Usuario,
    servidor: Servidor,
    accion: str,
    resultado: ResultadoAuditoria,
    solicitud: Request | None,
    contexto: ContextoAuditoria | None,
    detalle: str,
) -> None:
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion=accion,
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=servidor.id_servidor,
        resultado=resultado,
        solicitud=solicitud,
        contexto=contexto,
        detalle=detalle,
    )


async def consultar_informacion_archivo(
    sesion: AsyncSession,
    id_servidor: int,
    ruta_remota: str,
    usuario: Usuario,
    fabrica_transporte: FabricaTransporteArchivos,
    configuracion: Configuracion,
    solicitud: Request | None = None,
    contexto: ContextoAuditoria | None = None,
) -> InformacionArchivoRespuesta:
    """Consulta metadatos con doble comprobación léxica y canónica."""

    servidor = await obtener_servidor(sesion, id_servidor)
    if not servidor.activo:
        raise ErrorServidorInactivo()
    transporte = fabrica_transporte(servidor)
    try:
        normalizada, rutas = resolver_rutas_habilitadas(servidor, ruta_remota, escritura=False)
        informacion = await transporte.consultar_informacion_archivo(
            normalizada,
            rutas,
            configuracion.tiempo_operacion_ssh_segundos,
        )
    except ErrorHermes as error:
        _preparar_auditoria_archivo(
            sesion,
            usuario=usuario,
            servidor=servidor,
            accion="consultar_informacion_archivo",
            resultado=ResultadoAuditoria.ERROR,
            solicitud=solicitud,
            contexto=contexto,
            detalle=f"Consulta SFTP rechazada o fallida con código {error.codigo}.",
        )
        await sesion.commit()
        raise
    finally:
        await transporte.cerrar()
    _preparar_auditoria_archivo(
        sesion,
        usuario=usuario,
        servidor=servidor,
        accion="consultar_informacion_archivo",
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        contexto=contexto,
        detalle=f"Metadatos SFTP consultados; tipo {informacion.tipo}.",
    )
    await sesion.commit()
    return InformacionArchivoRespuesta(
        id_servidor=servidor.id_servidor,
        nombre_servidor=servidor.nombre,
        ruta_remota=normalizada,
        nombre_archivo=informacion.nombre_archivo,
        tipo=informacion.tipo,
        tamano_bytes=informacion.tamano_bytes,
        modificado_en=informacion.modificado_en,
    )


async def descargar_archivo(
    sesion: AsyncSession,
    id_servidor: int,
    ruta_remota: str,
    usuario: Usuario,
    fabrica_transporte: FabricaTransporteArchivos,
    configuracion: Configuracion,
    solicitud: Request | None = None,
    contexto: ContextoAuditoria | None = None,
) -> DescargaArchivo:
    """Descarga contenido acotado y audita solo metadatos mínimos."""

    servidor = await obtener_servidor(sesion, id_servidor)
    if not servidor.activo:
        raise ErrorServidorInactivo()
    transporte = fabrica_transporte(servidor)
    try:
        normalizada, rutas = resolver_rutas_habilitadas(servidor, ruta_remota, escritura=False)
        informacion, contenido = await transporte.descargar_archivo(
            normalizada,
            rutas,
            configuracion.tiempo_operacion_ssh_segundos,
            configuracion.limite_archivo_transferencia_bytes,
            configuracion.tamano_bloque_transferencia_bytes,
        )
    except ErrorHermes as error:
        _preparar_auditoria_archivo(
            sesion,
            usuario=usuario,
            servidor=servidor,
            accion="descargar_archivo",
            resultado=ResultadoAuditoria.ERROR,
            solicitud=solicitud,
            contexto=contexto,
            detalle=f"Descarga SFTP rechazada o fallida con código {error.codigo}.",
        )
        await sesion.commit()
        raise
    finally:
        await transporte.cerrar()
    _preparar_auditoria_archivo(
        sesion,
        usuario=usuario,
        servidor=servidor,
        accion="descargar_archivo",
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        contexto=contexto,
        detalle=f"Archivo descargado por SFTP; bytes={len(contenido)}.",
    )
    await sesion.commit()
    return DescargaArchivo(informacion.nombre_archivo, contenido, normalizada)


async def cargar_archivo(
    sesion: AsyncSession,
    id_servidor: int,
    ruta_remota: str,
    contenido: bytes,
    sobrescribir: bool,
    usuario: Usuario,
    fabrica_transporte: FabricaTransporteArchivos,
    configuracion: Configuracion,
    solicitud: Request | None = None,
    contexto: ContextoAuditoria | None = None,
) -> CargaArchivoRespuesta:
    """Carga bytes acotados con creación exclusiva como comportamiento inicial."""

    servidor = await obtener_servidor(sesion, id_servidor)
    if not servidor.activo:
        raise ErrorServidorInactivo()
    transporte = fabrica_transporte(servidor)
    try:
        if len(contenido) > configuracion.limite_archivo_transferencia_bytes:
            raise ErrorLimiteArchivoExcedido(configuracion.limite_archivo_transferencia_bytes)
        normalizada, rutas = resolver_rutas_habilitadas(servidor, ruta_remota, escritura=True)
        reemplazado = await transporte.cargar_archivo(
            normalizada,
            contenido,
            rutas,
            configuracion.tiempo_operacion_ssh_segundos,
            configuracion.tamano_bloque_transferencia_bytes,
            sobrescribir,
        )
    except ErrorHermes as error:
        _preparar_auditoria_archivo(
            sesion,
            usuario=usuario,
            servidor=servidor,
            accion="cargar_archivo",
            resultado=ResultadoAuditoria.ERROR,
            solicitud=solicitud,
            contexto=contexto,
            detalle=f"Carga SFTP rechazada o fallida con código {error.codigo}.",
        )
        await sesion.commit()
        raise
    finally:
        await transporte.cerrar()
    _preparar_auditoria_archivo(
        sesion,
        usuario=usuario,
        servidor=servidor,
        accion="cargar_archivo",
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        contexto=contexto,
        detalle=f"Archivo cargado por SFTP; bytes={len(contenido)}; reemplazo={reemplazado}.",
    )
    await sesion.commit()
    return CargaArchivoRespuesta(
        id_servidor=servidor.id_servidor,
        nombre_servidor=servidor.nombre,
        ruta_remota=normalizada,
        tamano_bytes=len(contenido),
        sobrescrito=reemplazado,
    )


async def auditar_carga_rechazada_por_tamano(
    sesion: AsyncSession,
    id_servidor: int,
    usuario: Usuario,
    solicitud: Request,
) -> None:
    """Conserva evidencia cuando la API corta el cuerpo antes de abrir SFTP."""

    servidor = await obtener_servidor(sesion, id_servidor)
    _preparar_auditoria_archivo(
        sesion,
        usuario=usuario,
        servidor=servidor,
        accion="cargar_archivo",
        resultado=ResultadoAuditoria.ERROR,
        solicitud=solicitud,
        contexto=None,
        detalle="Carga rechazada antes de SFTP con código limite_archivo_superado.",
    )
    await sesion.commit()
