"""Preparación, envío y reintento acotado de notificaciones."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from telegram import Bot

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorHermes, ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import (
    EstadoNotificacionAlerta,
    FaseNotificacionAlerta,
    TipoCanalMensajeria,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.monitoreo import NotificacionAlerta, SuscripcionAlerta
from aplicacion.monitoreo.evaluador import TransicionAlerta
from aplicacion.servicios.gestor_identidades_mensajeria import construir_identificador_slack

registrador = logging.getLogger(__name__)
LIMITE_NOTIFICACIONES_POR_CICLO = 500


class NotificadorMensajeria(Protocol):
    """Puerto mínimo para entregar alertas sin conocer el proveedor."""

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        """Entrega un texto a una identidad externa validada."""

    async def cerrar(self) -> None:
        """Libera clientes de red inicializados por el notificador."""


class NotificadorTelegram:
    """Entrega mensajes mediante el cliente oficial ya configurado."""

    def __init__(self, token: str, id_propietario: int | None = None) -> None:
        self._bot = Bot(token=token)
        self._inicializado = False
        self._id_propietario = id_propietario

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        if (
            not identificador_destino.isascii()
            or not identificador_destino.isdigit()
            or not 1 <= int(identificador_destino) <= 9_223_372_036_854_775_807
        ):
            raise ValueError("El destino de Telegram no es numérico.")
        if self._id_propietario is None or identificador_destino != str(self._id_propietario):
            raise ErrorIdentidadMensajeriaNoAutorizada()
        if not self._inicializado:
            await self._bot.initialize()
            self._inicializado = True
        await self._bot.send_message(
            chat_id=int(identificador_destino),
            text=mensaje[:4_000],
        )

    async def cerrar(self) -> None:
        if self._inicializado:
            await self._bot.shutdown()
            self._inicializado = False


class NotificadorSlack:
    """Entrega mensajes mediante `chat.postMessage` sin abrir Socket Mode."""

    def __init__(self, token: str) -> None:
        self._cliente = AsyncWebClient(token=token)
        self._equipo_verificado: str | None = None

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        equipo, separador, usuario = identificador_destino.partition(":")
        try:
            es_valido = (
                bool(separador)
                and construir_identificador_slack(equipo, usuario) == identificador_destino
            )
        except ErrorHermes:
            es_valido = False
        if not es_valido:
            raise ValueError("El destino de Slack no tiene un formato válido.")
        if self._equipo_verificado is None:
            respuesta = await self._cliente.auth_test()
            equipo_token = respuesta.get("team_id")
            if not isinstance(equipo_token, str):
                raise ValueError("No se pudo verificar el espacio de trabajo de Slack.")
            try:
                construir_identificador_slack(equipo_token, usuario)
            except ErrorHermes:
                raise ValueError("El espacio de trabajo del token de Slack no es válido.") from None
            self._equipo_verificado = equipo_token
        if equipo != self._equipo_verificado:
            raise ValueError("El destino pertenece a otro espacio de trabajo de Slack.")
        await self._cliente.chat_postMessage(channel=usuario, text=mensaje[:35_000])

    async def cerrar(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class TrabajoNotificacion:
    """Copia separada de la sesión para realizar una llamada externa."""

    id_notificacion: int
    canal: TipoCanalMensajeria
    identificador_destino: str
    mensaje: str


@dataclass(frozen=True, slots=True)
class ResumenNotificaciones:
    """Contadores de entregas intentadas en una vuelta."""

    enviadas: int
    fallidas: int


def crear_notificadores(
    configuracion: Configuracion,
) -> dict[TipoCanalMensajeria, NotificadorMensajeria]:
    """Crea únicamente proveedores habilitados y con secretos validados."""

    notificadores: dict[TipoCanalMensajeria, NotificadorMensajeria] = {}
    if (
        configuracion.telegram_habilitado
        and configuracion.token_telegram is not None
        and configuracion.id_propietario_telegram is not None
    ):
        notificadores[TipoCanalMensajeria.TELEGRAM] = NotificadorTelegram(
            configuracion.token_telegram.get_secret_value(), configuracion.id_propietario_telegram
        )
    if configuracion.slack_habilitado and configuracion.token_bot_slack is not None:
        notificadores[TipoCanalMensajeria.SLACK] = NotificadorSlack(
            configuracion.token_bot_slack.get_secret_value()
        )
    return notificadores


async def preparar_notificaciones(
    sesion: AsyncSession,
    transiciones: list[TransicionAlerta],
) -> None:
    """Materializa una entrega por transición y suscripción activa."""

    if not transiciones:
        return
    destinos = list(
        (
            await sesion.scalars(
                select(IdentidadMensajeria)
                .join(IdentidadMensajeria.usuario)
                .join(
                    SuscripcionAlerta,
                    SuscripcionAlerta.id_identidad_mensajeria
                    == IdentidadMensajeria.id_identidad_mensajeria,
                )
                .where(
                    IdentidadMensajeria.activo.is_(True),
                    Usuario.activo.is_(True),
                    SuscripcionAlerta.activo.is_(True),
                )
            )
        ).all()
    )
    for transicion in transiciones:
        ids_aperturas_enviadas: set[int] | None = None
        if transicion.fase is FaseNotificacionAlerta.RECUPERACION:
            aperturas = list(
                (
                    await sesion.scalars(
                        select(NotificacionAlerta).where(
                            NotificacionAlerta.id_alerta == transicion.alerta.id_alerta,
                            NotificacionAlerta.fase == FaseNotificacionAlerta.APERTURA,
                        )
                    )
                ).all()
            )
            ids_aperturas_enviadas = {
                apertura.id_identidad_mensajeria
                for apertura in aperturas
                if apertura.estado is EstadoNotificacionAlerta.ENVIADA
                and apertura.id_identidad_mensajeria is not None
            }
            for apertura in aperturas:
                if apertura.estado is not EstadoNotificacionAlerta.ENVIADA:
                    apertura.estado = EstadoNotificacionAlerta.OMITIDA
                    apertura.ultimo_error = (
                        "La condición se recuperó antes de completar esta entrega."
                    )
        for identidad in destinos:
            if (
                ids_aperturas_enviadas is not None
                and identidad.id_identidad_mensajeria not in ids_aperturas_enviadas
            ):
                continue
            sesion.add(
                NotificacionAlerta(
                    id_alerta=transicion.alerta.id_alerta,
                    id_identidad_mensajeria=identidad.id_identidad_mensajeria,
                    canal=identidad.canal,
                    fase=transicion.fase,
                    estado=EstadoNotificacionAlerta.PENDIENTE,
                )
            )


def _formatear_mensaje(notificacion: NotificacionAlerta) -> str:
    alerta = notificacion.alerta
    if notificacion.fase is FaseNotificacionAlerta.APERTURA:
        return (
            "ALERTA HERMES\n"
            f"Servidor: {alerta.nombre_servidor}\n"
            f"Problema: {alerta.tipo.value}\n"
            f"Detalle: {alerta.mensaje_apertura}"
        )
    return (
        "RECUPERACIÓN HERMES\n"
        f"Servidor: {alerta.nombre_servidor}\n"
        f"Condición: {alerta.tipo.value}\n"
        f"Detalle: {alerta.mensaje_recuperacion or 'La condición volvió a la normalidad.'}"
    )


async def _cargar_trabajos(
    sesion: AsyncSession,
    max_intentos: int,
) -> list[TrabajoNotificacion]:
    consulta = (
        select(NotificacionAlerta)
        .join(NotificacionAlerta.identidad)
        .join(IdentidadMensajeria.usuario)
        .join(
            SuscripcionAlerta,
            SuscripcionAlerta.id_identidad_mensajeria
            == IdentidadMensajeria.id_identidad_mensajeria,
        )
        .where(
            or_(
                NotificacionAlerta.estado == EstadoNotificacionAlerta.PENDIENTE,
                NotificacionAlerta.estado == EstadoNotificacionAlerta.FALLIDA,
            ),
            NotificacionAlerta.intentos < max_intentos,
            IdentidadMensajeria.activo.is_(True),
            Usuario.activo.is_(True),
            SuscripcionAlerta.activo.is_(True),
        )
        .options(
            selectinload(NotificacionAlerta.alerta),
            selectinload(NotificacionAlerta.identidad),
        )
        .order_by(NotificacionAlerta.id_notificacion_alerta)
        .limit(LIMITE_NOTIFICACIONES_POR_CICLO)
    )
    notificaciones = list((await sesion.scalars(consulta)).all())
    return [
        TrabajoNotificacion(
            id_notificacion=notificacion.id_notificacion_alerta,
            canal=notificacion.canal,
            identificador_destino=notificacion.identidad.identificador_externo,
            mensaje=_formatear_mensaje(notificacion),
        )
        for notificacion in notificaciones
        if notificacion.identidad is not None
    ]


async def _registrar_resultado_envio(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    id_notificacion: int,
    enviada: bool,
    tipo_error: str | None,
) -> None:
    async with fabrica_sesiones() as sesion:
        notificacion = await sesion.get(NotificacionAlerta, id_notificacion)
        if notificacion is None or notificacion.estado not in (
            EstadoNotificacionAlerta.PENDIENTE,
            EstadoNotificacionAlerta.FALLIDA,
        ):
            return
        ahora = datetime.now(UTC).replace(tzinfo=None)
        notificacion.intentos += 1
        notificacion.ultimo_intento_en = ahora
        if enviada:
            notificacion.estado = EstadoNotificacionAlerta.ENVIADA
            notificacion.enviada_en = ahora
            notificacion.ultimo_error = None
        else:
            notificacion.estado = EstadoNotificacionAlerta.FALLIDA
            notificacion.ultimo_error = f"Fallo de entrega de tipo {tipo_error or 'desconocido'}."
        await sesion.commit()


async def enviar_notificaciones_pendientes(
    fabrica_sesiones: async_sessionmaker[AsyncSession],
    notificadores: Mapping[TipoCanalMensajeria, NotificadorMensajeria],
    max_intentos: int,
) -> ResumenNotificaciones:
    """Entrega pendientes y reintenta fallos sin superar el máximo configurado."""

    async with fabrica_sesiones() as sesion:
        trabajos = await _cargar_trabajos(sesion, max_intentos)
    enviadas = 0
    fallidas = 0
    for trabajo in trabajos:
        notificador = notificadores.get(trabajo.canal)
        if notificador is None:
            continue
        try:
            await notificador.enviar_mensaje(
                trabajo.identificador_destino,
                trabajo.mensaje,
            )
        except Exception as error:
            fallidas += 1
            await _registrar_resultado_envio(
                fabrica_sesiones,
                trabajo.id_notificacion,
                False,
                type(error).__name__,
            )
            registrador.warning(
                "Falló una notificación de alerta. id_notificacion=%s canal=%s tipo=%s",
                trabajo.id_notificacion,
                trabajo.canal.value,
                type(error).__name__,
            )
        else:
            enviadas += 1
            await _registrar_resultado_envio(
                fabrica_sesiones,
                trabajo.id_notificacion,
                True,
                None,
            )
    return ResumenNotificaciones(enviadas=enviadas, fallidas=fallidas)


async def cerrar_notificadores(
    notificadores: Mapping[TipoCanalMensajeria, NotificadorMensajeria],
) -> None:
    """Cierra cada proveedor sin impedir el cierre de los demás."""

    for canal, notificador in notificadores.items():
        try:
            await notificador.cerrar()
        except Exception as error:
            registrador.warning(
                "No se pudo cerrar un notificador. canal=%s tipo=%s",
                canal.value,
                type(error).__name__,
            )
