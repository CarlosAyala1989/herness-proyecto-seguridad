"""Orquestación persistente de despliegues de archivo único."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aplicacion.acciones.registro import CodigoAccion, ParametrosServicio
from aplicacion.configuracion import Configuracion
from aplicacion.errores import (
    ErrorAplicacionNoOperativa,
    ErrorConfirmacionRequerida,
    ErrorConflictoDatos,
    ErrorDespliegueNoRevertible,
    ErrorHermes,
    ErrorPlantillaDespliegueIncompatible,
    ErrorRecursoNoEncontrado,
    ErrorRutaRemotaNoPermitida,
    ErrorServidorInactivo,
)
from aplicacion.esquemas.despliegues import (
    CrearAplicacionAdministrada,
    CrearPlantillaDespliegue,
    EstadoAplicacionRespuesta,
    SolicitudDespliegue,
)
from aplicacion.interfaces.transporte_remoto import TransporteRemoto
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.despliegue import (
    AplicacionAdministrada,
    DespliegueAplicacion,
    PlantillaDespliegue,
)
from aplicacion.modelos.enumeraciones import (
    EstadoDespliegue,
    ResultadoAuditoria,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.rutas_remotas import validar_y_normalizar_ruta_remota
from aplicacion.servicios.auditoria import ContextoAuditoria, preparar_registro_auditoria
from aplicacion.servicios.gestor_archivos import resolver_rutas_habilitadas
from aplicacion.servicios.gestor_conexiones import obtener_adaptador
from aplicacion.servicios.gestor_inventario import obtener_servidor
from aplicacion.servicios.persistencia import confirmar_transaccion

FabricaTransporteDespliegue = Callable[[Servidor], TransporteRemoto]


async def obtener_plantilla(sesion: AsyncSession, id_plantilla: int) -> PlantillaDespliegue:
    plantilla = await sesion.get(PlantillaDespliegue, id_plantilla)
    if plantilla is None:
        raise ErrorRecursoNoEncontrado("plantilla de despliegue")
    return plantilla


async def listar_plantillas(
    sesion: AsyncSession, *, desplazamiento: int, limite: int
) -> list[PlantillaDespliegue]:
    consulta = (
        select(PlantillaDespliegue)
        .order_by(PlantillaDespliegue.nombre)
        .offset(desplazamiento)
        .limit(limite)
    )
    return list((await sesion.scalars(consulta)).all())


async def crear_plantilla(
    sesion: AsyncSession,
    datos: CrearPlantillaDespliegue,
    usuario: Usuario,
    solicitud: Request,
) -> PlantillaDespliegue:
    """Registra parámetros estructurados, nunca guiones configurables."""

    ruta_destino = validar_y_normalizar_ruta_remota(datos.ruta_destino, datos.sistema_operativo)
    plantilla = PlantillaDespliegue(
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        sistema_operativo=datos.sistema_operativo,
        tipo=datos.tipo,
        ruta_destino=ruta_destino,
        nombre_servicio=datos.nombre_servicio,
        activo=datos.activo,
    )
    sesion.add(plantilla)
    try:
        await sesion.flush()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos("Ya existe una plantilla con ese nombre.") from None
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="crear_plantilla_despliegue",
        tipo_recurso=TipoRecursoAuditoria.APLICACION,
        id_recurso=plantilla.id_plantilla_despliegue,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Plantilla cerrada de despliegue creada.",
    )
    await confirmar_transaccion(sesion, "Ya existe una plantilla con ese nombre.")
    return plantilla


def _cargar_aplicacion() -> tuple[object, ...]:
    return (
        selectinload(AplicacionAdministrada.plantilla),
        selectinload(AplicacionAdministrada.servidor).selectinload(
            Servidor.rutas_archivos_permitidas
        ),
    )


async def obtener_aplicacion(
    sesion: AsyncSession,
    id_aplicacion: int,
    *,
    bloquear: bool = False,
) -> AplicacionAdministrada:
    consulta = (
        select(AplicacionAdministrada)
        .where(AplicacionAdministrada.id_aplicacion_administrada == id_aplicacion)
        .options(*_cargar_aplicacion())
    )
    if bloquear:
        consulta = consulta.with_for_update()
    aplicacion = await sesion.scalar(consulta)
    if aplicacion is None:
        raise ErrorRecursoNoEncontrado("aplicación administrada")
    return aplicacion


async def listar_aplicaciones(
    sesion: AsyncSession, *, desplazamiento: int, limite: int
) -> list[AplicacionAdministrada]:
    consulta = (
        select(AplicacionAdministrada)
        .options(*_cargar_aplicacion())
        .order_by(AplicacionAdministrada.nombre)
        .offset(desplazamiento)
        .limit(limite)
    )
    return list((await sesion.scalars(consulta)).all())


async def crear_aplicacion(
    sesion: AsyncSession,
    datos: CrearAplicacionAdministrada,
    usuario: Usuario,
    solicitud: Request,
) -> AplicacionAdministrada:
    """Asocia servidor y plantilla solo si existe una raíz de lectura y escritura."""

    servidor = await obtener_servidor(sesion, datos.id_servidor)
    plantilla = await obtener_plantilla(sesion, datos.id_plantilla_despliegue)
    if (
        not servidor.activo
        or not plantilla.activo
        or servidor.sistema_operativo is not plantilla.sistema_operativo
    ):
        raise ErrorPlantillaDespliegueIncompatible()
    try:
        resolver_rutas_habilitadas(servidor, plantilla.ruta_destino, escritura=False)
        resolver_rutas_habilitadas(servidor, plantilla.ruta_destino, escritura=True)
    except ErrorRutaRemotaNoPermitida:
        raise ErrorPlantillaDespliegueIncompatible(
            "El destino de la plantilla requiere una raíz activa de lectura y escritura."
        ) from None
    aplicacion = AplicacionAdministrada(
        id_servidor=servidor.id_servidor,
        id_plantilla_despliegue=plantilla.id_plantilla_despliegue,
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        activo=datos.activo,
    )
    sesion.add(aplicacion)
    try:
        await sesion.flush()
    except IntegrityError:
        await sesion.rollback()
        raise ErrorConflictoDatos(
            "Ya existe una aplicación con ese nombre en el servidor."
        ) from None
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="crear_aplicacion_administrada",
        tipo_recurso=TipoRecursoAuditoria.APLICACION,
        id_recurso=aplicacion.id_aplicacion_administrada,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Aplicación vinculada con servidor y plantilla compatibles.",
    )
    await confirmar_transaccion(sesion, "Ya existe una aplicación con ese nombre en el servidor.")
    return await obtener_aplicacion(sesion, aplicacion.id_aplicacion_administrada)


async def listar_despliegues(
    sesion: AsyncSession,
    id_aplicacion: int,
    *,
    desplazamiento: int,
    limite: int,
) -> list[DespliegueAplicacion]:
    await obtener_aplicacion(sesion, id_aplicacion)
    consulta = (
        select(DespliegueAplicacion)
        .where(DespliegueAplicacion.id_aplicacion_administrada == id_aplicacion)
        .order_by(DespliegueAplicacion.id_despliegue_aplicacion.desc())
        .offset(desplazamiento)
        .limit(limite)
    )
    return list((await sesion.scalars(consulta)).all())


def validar_preparacion_despliegue(
    aplicacion: AplicacionAdministrada,
    datos: SolicitudDespliegue,
) -> None:
    """Comprueba estado, versión y rutas antes de solicitar confirmación."""

    servidor = aplicacion.servidor
    plantilla = aplicacion.plantilla
    if not servidor.activo:
        raise ErrorServidorInactivo()
    if not aplicacion.activo or not plantilla.activo:
        raise ErrorConflictoDatos("La aplicación o su plantilla está inactiva.")
    if aplicacion.version_actual == datos.version:
        raise ErrorConflictoDatos("La versión solicitada ya está instalada.")
    ruta_artefacto, _ = resolver_rutas_habilitadas(servidor, datos.ruta_artefacto, escritura=False)
    ruta_destino, _ = resolver_rutas_habilitadas(servidor, plantilla.ruta_destino, escritura=True)
    resolver_rutas_habilitadas(servidor, plantilla.ruta_destino, escritura=False)
    if ruta_artefacto == ruta_destino:
        raise ErrorConflictoDatos("El artefacto y el destino deben ser archivos diferentes.")


async def validar_preparacion_reversion(
    sesion: AsyncSession,
    aplicacion: AplicacionAdministrada,
    id_despliegue: int,
) -> DespliegueAplicacion:
    """Exige que el historial indicado represente exactamente la versión vigente."""

    if not aplicacion.servidor.activo:
        raise ErrorServidorInactivo()
    if not aplicacion.activo or not aplicacion.plantilla.activo:
        raise ErrorConflictoDatos("La aplicación o su plantilla está inactiva.")
    despliegue = await sesion.scalar(
        select(DespliegueAplicacion).where(
            DespliegueAplicacion.id_despliegue_aplicacion == id_despliegue,
            DespliegueAplicacion.id_aplicacion_administrada
            == aplicacion.id_aplicacion_administrada,
        )
    )
    if (
        despliegue is None
        or despliegue.estado is not EstadoDespliegue.COMPLETADO
        or aplicacion.version_actual != despliegue.version
    ):
        raise ErrorDespliegueNoRevertible()
    return despliegue


async def _ejecutar_servicio(
    transporte: TransporteRemoto,
    servidor: Servidor,
    nombre_servicio: str,
    codigo: CodigoAccion,
    configuracion: Configuracion,
) -> dict[str, object]:
    adaptador = obtener_adaptador(servidor.sistema_operativo)
    preparada = adaptador.preparar_accion(
        codigo, ParametrosServicio(nombre_servicio=nombre_servicio)
    )
    resultado = await transporte.ejecutar_comando_controlado(
        preparada.comando,
        configuracion.tiempo_operacion_ssh_segundos,
        configuracion.limite_salida_ssh_bytes,
    )
    return adaptador.interpretar_accion(codigo, resultado)


async def _verificar_instalacion(
    transporte: TransporteRemoto,
    servidor: Servidor,
    ruta_destino: str,
    rutas_destino: tuple[str, ...],
    hash_esperado: str,
    nombre_servicio: str | None,
    configuracion: Configuracion,
    *,
    reiniciar_servicio: bool,
) -> tuple[bool, str | None]:
    _, contenido = await transporte.descargar_archivo(
        ruta_destino,
        rutas_destino,
        configuracion.tiempo_operacion_ssh_segundos,
        configuracion.limite_archivo_transferencia_bytes,
        configuracion.tamano_bloque_transferencia_bytes,
    )
    if sha256(contenido).hexdigest() != hash_esperado:
        raise ErrorAplicacionNoOperativa()
    if nombre_servicio is None:
        return True, None
    codigo = (
        CodigoAccion.REINICIAR_SERVICIO if reiniciar_servicio else CodigoAccion.CONSULTAR_SERVICIO
    )
    datos = await _ejecutar_servicio(transporte, servidor, nombre_servicio, codigo, configuracion)
    estado = str(datos.get("estado", "desconocido"))
    if estado != "activo":
        raise ErrorAplicacionNoOperativa()
    return True, estado


def _auditar(
    sesion: AsyncSession,
    usuario: Usuario,
    aplicacion: AplicacionAdministrada,
    accion: str,
    resultado: ResultadoAuditoria,
    detalle: str,
    solicitud: Request | None,
    contexto: ContextoAuditoria | None,
) -> None:
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion=accion,
        tipo_recurso=TipoRecursoAuditoria.APLICACION,
        id_recurso=aplicacion.id_aplicacion_administrada,
        resultado=resultado,
        detalle=detalle,
        solicitud=solicitud,
        contexto=contexto,
    )


async def desplegar_aplicacion(
    sesion: AsyncSession,
    id_aplicacion: int,
    datos: SolicitudDespliegue,
    usuario: Usuario,
    fabrica_transporte: FabricaTransporteDespliegue,
    configuracion: Configuracion,
    solicitud: Request | None = None,
    contexto: ContextoAuditoria | None = None,
) -> DespliegueAplicacion:
    """Respalda, instala, verifica y restaura automáticamente ante fallos."""

    aplicacion = await obtener_aplicacion(sesion, id_aplicacion, bloquear=True)
    if not datos.confirmar:
        raise ErrorConfirmacionRequerida()
    servidor = aplicacion.servidor
    plantilla = aplicacion.plantilla
    validar_preparacion_despliegue(aplicacion, datos)

    ruta_artefacto, rutas_artefacto = resolver_rutas_habilitadas(
        servidor, datos.ruta_artefacto, escritura=False
    )
    ruta_destino, rutas_destino = resolver_rutas_habilitadas(
        servidor, plantilla.ruta_destino, escritura=True
    )
    _, rutas_lectura_destino = resolver_rutas_habilitadas(
        servidor, plantilla.ruta_destino, escritura=False
    )
    if ruta_artefacto == ruta_destino:
        raise ErrorConflictoDatos("El artefacto y el destino deben ser archivos diferentes.")

    despliegue = DespliegueAplicacion(
        id_aplicacion_administrada=aplicacion.id_aplicacion_administrada,
        id_usuario=usuario.id_usuario,
        nombre_usuario=usuario.nombre_usuario,
        version=datos.version,
        version_anterior=aplicacion.version_actual,
        ruta_artefacto=ruta_artefacto,
        estado=EstadoDespliegue.EN_PROGRESO,
    )
    sesion.add(despliegue)
    await sesion.flush()
    ruta_respaldo = f"{ruta_destino}.hermes-respaldo-{despliegue.id_despliegue_aplicacion}"
    transporte = fabrica_transporte(servidor)
    contenido_anterior: bytes | None = None
    destino_modificado = False
    try:
        _, artefacto = await transporte.descargar_archivo(
            ruta_artefacto,
            rutas_artefacto,
            configuracion.tiempo_operacion_ssh_segundos,
            configuracion.limite_archivo_transferencia_bytes,
            configuracion.tamano_bloque_transferencia_bytes,
        )
        hash_artefacto = sha256(artefacto).hexdigest()
        try:
            _, contenido_anterior = await transporte.descargar_archivo(
                ruta_destino,
                rutas_lectura_destino,
                configuracion.tiempo_operacion_ssh_segundos,
                configuracion.limite_archivo_transferencia_bytes,
                configuracion.tamano_bloque_transferencia_bytes,
            )
        except ErrorRecursoNoEncontrado:
            contenido_anterior = None
        if contenido_anterior is not None:
            await transporte.cargar_archivo(
                ruta_respaldo,
                contenido_anterior,
                rutas_destino,
                configuracion.tiempo_operacion_ssh_segundos,
                configuracion.tamano_bloque_transferencia_bytes,
                False,
            )
            despliegue.ruta_respaldo = ruta_respaldo
            despliegue.hash_respaldo_sha256 = sha256(contenido_anterior).hexdigest()
        await transporte.cargar_archivo(
            ruta_destino,
            artefacto,
            rutas_destino,
            configuracion.tiempo_operacion_ssh_segundos,
            configuracion.tamano_bloque_transferencia_bytes,
            True,
        )
        destino_modificado = True
        await _verificar_instalacion(
            transporte,
            servidor,
            ruta_destino,
            rutas_lectura_destino,
            hash_artefacto,
            plantilla.nombre_servicio,
            configuracion,
            reiniciar_servicio=True,
        )
    except ErrorHermes as error:
        restaurado = not destino_modificado
        if destino_modificado:
            try:
                if contenido_anterior is None:
                    await transporte.eliminar_archivo(
                        ruta_destino,
                        rutas_destino,
                        configuracion.tiempo_operacion_ssh_segundos,
                    )
                else:
                    await transporte.cargar_archivo(
                        ruta_destino,
                        contenido_anterior,
                        rutas_destino,
                        configuracion.tiempo_operacion_ssh_segundos,
                        configuracion.tamano_bloque_transferencia_bytes,
                        True,
                    )
                    if plantilla.nombre_servicio:
                        await _ejecutar_servicio(
                            transporte,
                            servidor,
                            plantilla.nombre_servicio,
                            CodigoAccion.REINICIAR_SERVICIO,
                            configuracion,
                        )
                restaurado = True
            except ErrorHermes:
                restaurado = False
        despliegue.estado = EstadoDespliegue.FALLIDO
        despliegue.finalizado_en = datetime.now(UTC)
        despliegue.detalle_resultado = f"Despliegue fallido con código {error.codigo}; " + (
            "estado anterior restaurado." if restaurado else "reversión automática no confirmada."
        )
        _auditar(
            sesion,
            usuario,
            aplicacion,
            "desplegar_aplicacion",
            ResultadoAuditoria.ERROR,
            despliegue.detalle_resultado,
            solicitud,
            contexto,
        )
        await sesion.commit()
        raise
    finally:
        await transporte.cerrar()

    aplicacion.version_actual = datos.version
    despliegue.hash_sha256 = hash_artefacto
    despliegue.estado = EstadoDespliegue.COMPLETADO
    despliegue.finalizado_en = datetime.now(UTC)
    despliegue.detalle_resultado = "Versión instalada y verificación operativa completada."
    _auditar(
        sesion,
        usuario,
        aplicacion,
        "desplegar_aplicacion",
        ResultadoAuditoria.EXITO,
        despliegue.detalle_resultado,
        solicitud,
        contexto,
    )
    await sesion.commit()
    await sesion.refresh(despliegue)
    return despliegue


async def revertir_despliegue(
    sesion: AsyncSession,
    id_aplicacion: int,
    id_despliegue: int,
    usuario: Usuario,
    fabrica_transporte: FabricaTransporteDespliegue,
    configuracion: Configuracion,
    confirmar: bool,
    solicitud: Request | None = None,
    contexto: ContextoAuditoria | None = None,
) -> DespliegueAplicacion:
    """Restaura el respaldo del despliegue que representa la versión vigente."""

    if not confirmar:
        raise ErrorConfirmacionRequerida()
    aplicacion = await obtener_aplicacion(sesion, id_aplicacion, bloquear=True)
    despliegue = await validar_preparacion_reversion(sesion, aplicacion, id_despliegue)
    servidor = aplicacion.servidor
    plantilla = aplicacion.plantilla
    ruta_destino, rutas_escritura = resolver_rutas_habilitadas(
        servidor, plantilla.ruta_destino, escritura=True
    )
    _, rutas_lectura = resolver_rutas_habilitadas(servidor, plantilla.ruta_destino, escritura=False)
    transporte = fabrica_transporte(servidor)
    try:
        if despliegue.ruta_respaldo is None:
            await transporte.eliminar_archivo(
                ruta_destino, rutas_escritura, configuracion.tiempo_operacion_ssh_segundos
            )
        else:
            _, respaldo = await transporte.descargar_archivo(
                despliegue.ruta_respaldo,
                rutas_lectura,
                configuracion.tiempo_operacion_ssh_segundos,
                configuracion.limite_archivo_transferencia_bytes,
                configuracion.tamano_bloque_transferencia_bytes,
            )
            if (
                despliegue.hash_respaldo_sha256 is None
                or sha256(respaldo).hexdigest() != despliegue.hash_respaldo_sha256
            ):
                raise ErrorAplicacionNoOperativa()
            await transporte.cargar_archivo(
                ruta_destino,
                respaldo,
                rutas_escritura,
                configuracion.tiempo_operacion_ssh_segundos,
                configuracion.tamano_bloque_transferencia_bytes,
                True,
            )
            if plantilla.nombre_servicio:
                datos_servicio = await _ejecutar_servicio(
                    transporte,
                    servidor,
                    plantilla.nombre_servicio,
                    CodigoAccion.REINICIAR_SERVICIO,
                    configuracion,
                )
                if datos_servicio.get("estado") != "activo":
                    raise ErrorAplicacionNoOperativa()
    except ErrorHermes as error:
        _auditar(
            sesion,
            usuario,
            aplicacion,
            "revertir_despliegue",
            ResultadoAuditoria.ERROR,
            f"Reversión fallida con código {error.codigo}.",
            solicitud,
            contexto,
        )
        await sesion.commit()
        raise
    finally:
        await transporte.cerrar()
    aplicacion.version_actual = despliegue.version_anterior
    despliegue.estado = EstadoDespliegue.REVERTIDO
    despliegue.revertido_en = datetime.now(UTC)
    despliegue.detalle_resultado = "Estado anterior restaurado de forma confirmada."
    _auditar(
        sesion,
        usuario,
        aplicacion,
        "revertir_despliegue",
        ResultadoAuditoria.EXITO,
        despliegue.detalle_resultado,
        solicitud,
        contexto,
    )
    await sesion.commit()
    await sesion.refresh(despliegue)
    return despliegue


async def consultar_estado_aplicacion(
    sesion: AsyncSession,
    id_aplicacion: int,
    fabrica_transporte: FabricaTransporteDespliegue,
    configuracion: Configuracion,
) -> EstadoAplicacionRespuesta:
    """Compara archivo, hash persistido y servicio asociado sin mutar el destino."""

    aplicacion = await obtener_aplicacion(sesion, id_aplicacion)
    servidor = aplicacion.servidor
    plantilla = aplicacion.plantilla
    if not servidor.activo:
        raise ErrorServidorInactivo()
    if not aplicacion.activo or not plantilla.activo:
        raise ErrorConflictoDatos("La aplicación o su plantilla está inactiva.")
    _, rutas_lectura = resolver_rutas_habilitadas(servidor, plantilla.ruta_destino, escritura=False)
    despliegue = None
    if aplicacion.version_actual is not None:
        despliegue = await sesion.scalar(
            select(DespliegueAplicacion)
            .where(
                DespliegueAplicacion.id_aplicacion_administrada == id_aplicacion,
                DespliegueAplicacion.version == aplicacion.version_actual,
                DespliegueAplicacion.estado == EstadoDespliegue.COMPLETADO,
            )
            .order_by(DespliegueAplicacion.id_despliegue_aplicacion.desc())
            .limit(1)
        )
    transporte = fabrica_transporte(servidor)
    archivo_disponible = False
    integridad: bool | None = None
    estado_servicio: str | None = None
    try:
        try:
            _, contenido = await transporte.descargar_archivo(
                plantilla.ruta_destino,
                rutas_lectura,
                configuracion.tiempo_operacion_ssh_segundos,
                configuracion.limite_archivo_transferencia_bytes,
                configuracion.tamano_bloque_transferencia_bytes,
            )
            archivo_disponible = True
            integridad = (
                sha256(contenido).hexdigest() == despliegue.hash_sha256
                if despliegue is not None and despliegue.hash_sha256 is not None
                else None
            )
        except ErrorRecursoNoEncontrado:
            archivo_disponible = False
        if plantilla.nombre_servicio:
            datos_servicio = await _ejecutar_servicio(
                transporte,
                servidor,
                plantilla.nombre_servicio,
                CodigoAccion.CONSULTAR_SERVICIO,
                configuracion,
            )
            estado_servicio = str(datos_servicio.get("estado", "desconocido"))
    finally:
        await transporte.cerrar()
    operativa = (
        aplicacion.version_actual is not None
        and despliegue is not None
        and archivo_disponible
        and integridad is True
        and (plantilla.nombre_servicio is None or estado_servicio == "activo")
    )
    estado = (
        "operativa"
        if operativa
        else "no_desplegada"
        if aplicacion.version_actual is None
        else "degradada"
    )
    return EstadoAplicacionRespuesta(
        id_aplicacion_administrada=aplicacion.id_aplicacion_administrada,
        nombre_aplicacion=aplicacion.nombre,
        nombre_servidor=servidor.nombre,
        sistema_operativo=servidor.sistema_operativo,
        version_actual=aplicacion.version_actual,
        estado=estado,
        archivo_disponible=archivo_disponible,
        integridad_verificada=integridad,
        servicio=plantilla.nombre_servicio,
        estado_servicio=estado_servicio,
    )
