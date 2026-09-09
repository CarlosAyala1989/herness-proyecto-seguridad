"""Administración autorizada de políticas y destinos de monitoreo."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aplicacion.errores import ErrorRecursoNoEncontrado
from aplicacion.esquemas.monitoreo import (
    AlertaRespuesta,
    ConfiguracionMonitoreoRespuesta,
    ConfigurarMonitoreoServidor,
    DestinoAlertaRespuesta,
)
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import EstadoAlerta, ResultadoAuditoria, TipoRecursoAuditoria
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.monitoreo import (
    Alerta,
    ConfiguracionMonitoreoServidor,
    ServicioCriticoMonitoreo,
    SuscripcionAlerta,
)
from aplicacion.servicios.auditoria import preparar_registro_auditoria
from aplicacion.servicios.gestor_inventario import obtener_servidor
from aplicacion.servicios.persistencia import confirmar_transaccion


async def listar_configuraciones_monitoreo(
    sesion: AsyncSession,
    *,
    desplazamiento: int,
    limite: int,
) -> list[ConfiguracionMonitoreoRespuesta]:
    """Consulta políticas con sus servicios críticos sin material SSH."""

    consulta = (
        select(ConfiguracionMonitoreoServidor)
        .options(selectinload(ConfiguracionMonitoreoServidor.servicios_criticos))
        .order_by(ConfiguracionMonitoreoServidor.id_servidor)
        .offset(desplazamiento)
        .limit(limite)
    )
    configuraciones = list((await sesion.scalars(consulta)).all())
    return [
        ConfiguracionMonitoreoRespuesta.model_validate(configuracion)
        for configuracion in configuraciones
    ]


async def guardar_configuracion_monitoreo(
    sesion: AsyncSession,
    id_servidor: int,
    datos: ConfigurarMonitoreoServidor,
    usuario: Usuario,
    solicitud: Request,
) -> ConfiguracionMonitoreoRespuesta:
    """Crea o reemplaza umbrales y servicios en una transacción auditada."""

    await obtener_servidor(sesion, id_servidor)
    consulta = (
        select(ConfiguracionMonitoreoServidor)
        .where(ConfiguracionMonitoreoServidor.id_servidor == id_servidor)
        .options(selectinload(ConfiguracionMonitoreoServidor.servicios_criticos))
    )
    configuracion = await sesion.scalar(consulta)
    valores = datos.model_dump(exclude={"servicios_criticos"})
    if configuracion is None:
        configuracion = ConfiguracionMonitoreoServidor(
            id_servidor=id_servidor,
            **valores,
        )
        sesion.add(configuracion)
        servicios_actuales: dict[str, ServicioCriticoMonitoreo] = {}
    else:
        for campo, valor in valores.items():
            setattr(configuracion, campo, valor)
        servicios_actuales = {
            servicio.nombre_servicio: servicio for servicio in configuracion.servicios_criticos
        }

    nombres_deseados = set(datos.servicios_criticos)
    configuracion.servicios_criticos[:] = [
        servicio
        for servicio in configuracion.servicios_criticos
        if servicio.nombre_servicio in nombres_deseados
    ]
    for nombre in datos.servicios_criticos:
        servicio = servicios_actuales.get(nombre)
        if servicio is None:
            configuracion.servicios_criticos.append(
                ServicioCriticoMonitoreo(nombre_servicio=nombre, activo=True)
            )
        else:
            servicio.activo = True
    await sesion.flush()
    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="guardar_configuracion_monitoreo",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Configuración de monitoreo actualizada.",
    )
    await confirmar_transaccion(sesion, "No fue posible guardar la configuración de monitoreo.")
    await sesion.refresh(configuracion, attribute_names=["actualizado_en", "servicios_criticos"])
    return ConfiguracionMonitoreoRespuesta.model_validate(configuracion)


async def listar_destinos_alertas(sesion: AsyncSession) -> list[DestinoAlertaRespuesta]:
    """Lista identidades y su suscripción sin exponer tokens de los canales."""

    consulta = (
        select(IdentidadMensajeria, SuscripcionAlerta)
        .join(IdentidadMensajeria.usuario)
        .outerjoin(
            SuscripcionAlerta,
            SuscripcionAlerta.id_identidad_mensajeria
            == IdentidadMensajeria.id_identidad_mensajeria,
        )
        .options(selectinload(IdentidadMensajeria.usuario))
        .order_by(IdentidadMensajeria.canal, IdentidadMensajeria.id_identidad_mensajeria)
    )
    filas = (await sesion.execute(consulta)).all()
    return [
        DestinoAlertaRespuesta(
            id_identidad_mensajeria=identidad.id_identidad_mensajeria,
            id_usuario=identidad.id_usuario,
            nombre_usuario=identidad.usuario.nombre_usuario,
            canal=identidad.canal,
            identificador_externo=identidad.identificador_externo,
            nombre_externo=identidad.nombre_externo,
            identidad_activa=identidad.activo,
            usuario_activo=identidad.usuario.activo,
            suscrito=suscripcion is not None and suscripcion.activo,
        )
        for identidad, suscripcion in filas
    ]


async def actualizar_suscripcion_alerta(
    sesion: AsyncSession,
    id_identidad_mensajeria: int,
    activo: bool,
    usuario: Usuario,
    solicitud: Request,
) -> DestinoAlertaRespuesta:
    """Crea o modifica la suscripción de una identidad existente."""

    consulta_identidad = (
        select(IdentidadMensajeria)
        .where(IdentidadMensajeria.id_identidad_mensajeria == id_identidad_mensajeria)
        .options(selectinload(IdentidadMensajeria.usuario))
    )
    identidad = await sesion.scalar(consulta_identidad)
    if identidad is None:
        raise ErrorRecursoNoEncontrado("identidad de mensajería")
    suscripcion = await sesion.scalar(
        select(SuscripcionAlerta).where(
            SuscripcionAlerta.id_identidad_mensajeria == id_identidad_mensajeria
        )
    )
    if suscripcion is None:
        suscripcion = SuscripcionAlerta(
            id_identidad_mensajeria=id_identidad_mensajeria,
            activo=activo,
        )
        sesion.add(suscripcion)
    else:
        suscripcion.activo = activo

    preparar_registro_auditoria(
        sesion,
        usuario=usuario,
        accion="actualizar_suscripcion_alertas",
        tipo_recurso=TipoRecursoAuditoria.ASOCIACION,
        id_recurso=id_identidad_mensajeria,
        resultado=ResultadoAuditoria.EXITO,
        solicitud=solicitud,
        detalle="Suscripción de alertas actualizada.",
    )
    await confirmar_transaccion(sesion, "No fue posible actualizar la suscripción de alertas.")
    return DestinoAlertaRespuesta(
        id_identidad_mensajeria=identidad.id_identidad_mensajeria,
        id_usuario=identidad.id_usuario,
        nombre_usuario=identidad.usuario.nombre_usuario,
        canal=identidad.canal,
        identificador_externo=identidad.identificador_externo,
        nombre_externo=identidad.nombre_externo,
        identidad_activa=identidad.activo,
        usuario_activo=identidad.usuario.activo,
        suscrito=suscripcion.activo,
    )


async def listar_alertas(
    sesion: AsyncSession,
    *,
    estado: EstadoAlerta | None,
    desplazamiento: int,
    limite: int,
) -> list[AlertaRespuesta]:
    """Consulta episodios recientes con filtro opcional de estado."""

    consulta = select(Alerta)
    if estado is not None:
        consulta = consulta.where(Alerta.estado == estado)
    consulta = consulta.order_by(Alerta.detectada_en.desc(), Alerta.id_alerta.desc())
    alertas = list((await sesion.scalars(consulta.offset(desplazamiento).limit(limite))).all())
    return [AlertaRespuesta.model_validate(alerta) for alerta in alertas]
