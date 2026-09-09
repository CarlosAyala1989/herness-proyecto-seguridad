"""Adaptación de mensajes Telegram hacia los casos de uso de Hermes."""

import logging
import secrets
from dataclasses import dataclass
from hmac import compare_digest
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncEngine
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorHermes, ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.esquemas.acciones import ResultadoAccionRespuesta, SolicitudEjecucionAccion
from aplicacion.esquemas.inventario import ServidorResumen
from aplicacion.interfaces.canal_mensajeria import CanalMensajeria
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.servicios.gestor_telegram import GestorTelegram

registrador = logging.getLogger(__name__)
CLAVE_SERVIDOR_SELECCIONADO = "id_servidor_seleccionado"
CLAVE_CONFIRMACION_REINICIO = "confirmacion_reinicio"
LIMITE_MENSAJE_TELEGRAM = 4_000


@dataclass(frozen=True, slots=True)
class ConfirmacionReinicio:
    """Desafío efímero ligado al usuario y al servidor seleccionado."""

    id_servidor: int
    codigo_aleatorio: str
    vence_en: float


COMANDOS_TELEGRAM = (
    BotCommand("inicio", "Iniciar Hermes y comprobar autorización"),
    BotCommand("ayuda", "Mostrar los comandos disponibles"),
    BotCommand("servidores", "Listar y seleccionar un servidor"),
    BotCommand("seleccionar", "Seleccionar un servidor por identificador"),
    BotCommand("seleccion", "Mostrar el servidor seleccionado"),
    BotCommand("identidad", "Consultar identidad del servidor seleccionado"),
    BotCommand("proceso", "Consultar un proceso por identificador"),
    BotCommand("reiniciar", "Solicitar un reinicio con confirmación"),
    BotCommand("cancelar", "Cancelar una confirmación pendiente"),
)


class InterfazTelegram(CanalMensajeria):
    """Traduce comandos y botones sin contener lógica SSH ni permisos propios."""

    def __init__(
        self,
        gestor: GestorTelegram,
        configuracion: Configuracion,
        motor_base_datos: AsyncEngine,
    ) -> None:
        self._gestor = gestor
        self._configuracion = configuracion
        self._motor_base_datos = motor_base_datos
        self._aplicacion: Application | None = None

    def registrar(self, aplicacion: Application) -> None:
        """Registra todos los comandos antes de iniciar el sondeo."""

        self._aplicacion = aplicacion
        aplicacion.add_handler(CommandHandler(["inicio", "start"], self.iniciar))
        aplicacion.add_handler(CommandHandler("ayuda", self.mostrar_ayuda))
        aplicacion.add_handler(CommandHandler("servidores", self.mostrar_servidores))
        aplicacion.add_handler(CommandHandler("seleccionar", self.seleccionar_por_comando))
        aplicacion.add_handler(CommandHandler("seleccion", self.mostrar_seleccion))
        aplicacion.add_handler(CommandHandler("identidad", self.obtener_identidad))
        aplicacion.add_handler(CommandHandler("proceso", self.consultar_proceso))
        aplicacion.add_handler(CommandHandler("reiniciar", self.solicitar_reinicio))
        aplicacion.add_handler(CommandHandler("cancelar", self.cancelar))
        aplicacion.add_handler(
            CallbackQueryHandler(self.seleccionar_por_boton, pattern=r"^seleccionar:[1-9][0-9]*$")
        )
        aplicacion.add_handler(
            CallbackQueryHandler(
                self.resolver_reinicio,
                pattern=r"^reinicio:(confirmar|cancelar):[A-Za-z0-9_-]{8,32}$",
            )
        )
        aplicacion.add_handler(MessageHandler(filters.COMMAND, self.comando_desconocido))
        aplicacion.add_error_handler(self.manejar_error)

    async def preparar(self, aplicacion: Application) -> None:
        """Publica el menú de comandos sin incluir secretos en los registros."""

        await aplicacion.bot.set_my_commands(COMANDOS_TELEGRAM)
        registrador.info("Interfaz Telegram iniciada mediante sondeo privado.")

    async def cerrar(self, _: Application) -> None:
        """Libera el motor compartido cuando finaliza el proceso del bot."""

        await self._motor_base_datos.dispose()
        registrador.info("Interfaz Telegram detenida y conexiones liberadas.")

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        """Permite reutilizar el canal para notificaciones de hitos posteriores."""

        if self._aplicacion is None:
            raise RuntimeError("La interfaz Telegram todavía no está inicializada.")
        await self._aplicacion.bot.send_message(
            chat_id=int(identificador_destino),
            text=mensaje[:LIMITE_MENSAJE_TELEGRAM],
        )

    @staticmethod
    async def _responder(
        actualizacion: Update,
        texto: str,
        teclado: InlineKeyboardMarkup | None = None,
    ) -> None:
        mensaje = actualizacion.effective_message
        if mensaje is not None:
            await mensaje.reply_text(texto[:LIMITE_MENSAJE_TELEGRAM], reply_markup=teclado)

    async def _autorizar(self, actualizacion: Update) -> tuple[int, int, str] | None:
        usuario = actualizacion.effective_user
        conversacion = actualizacion.effective_chat
        if usuario is None or conversacion is None:
            return None
        if conversacion.type != "private":
            await self._responder(
                actualizacion,
                "Por seguridad, Hermes solo atiende conversaciones privadas.",
            )
            return None
        try:
            nombre = await self._gestor.comprobar_acceso(usuario.id, actualizacion.update_id)
        except ErrorIdentidadMensajeriaNoAutorizada:
            await self._responder(
                actualizacion,
                "Acceso denegado. Tu identificador de Telegram es "
                f"{usuario.id}. Solicita al administrador que lo vincule en Hermes.",
            )
            return None
        return usuario.id, actualizacion.update_id, nombre

    @staticmethod
    def _texto_ayuda() -> str:
        return (
            "Comandos disponibles:\n"
            "/servidores — listar y elegir un servidor\n"
            "/seleccionar <id> — elegir un servidor\n"
            "/seleccion — mostrar la selección actual\n"
            "/identidad — consultar usuario remoto y equipo\n"
            "/proceso <id> — consultar un proceso\n"
            "/reiniciar — solicitar un reinicio confirmado\n"
            "/cancelar — cancelar una confirmación pendiente\n"
            "/ayuda — mostrar esta ayuda"
        )

    async def iniciar(self, actualizacion: Update, _: CallbackContext) -> None:
        """Da la bienvenida únicamente después de resolver el vínculo persistente."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        await self._responder(
            actualizacion,
            f"Bienvenido a Hermes, {acceso[2]}.\n\n{self._texto_ayuda()}",
        )

    async def mostrar_ayuda(self, actualizacion: Update, _: CallbackContext) -> None:
        """Muestra exclusivamente operaciones ya incorporadas al backend."""

        if await self._autorizar(actualizacion) is not None:
            await self._responder(actualizacion, self._texto_ayuda())

    async def mostrar_servidores(
        self,
        actualizacion: Update,
        _: CallbackContext,
    ) -> None:
        """Lista servidores activos como botones de selección."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        try:
            servidores = await self._gestor.consultar_servidores(acceso[0], acceso[1])
        except ErrorHermes as error:
            await self._responder(
                actualizacion, f"No fue posible consultar servidores: {error.mensaje}"
            )
            return
        if not servidores:
            await self._responder(actualizacion, "No hay servidores activos disponibles.")
            return
        botones = [
            [
                InlineKeyboardButton(
                    f"{servidor.id_servidor} · {servidor.nombre[:40]}",
                    callback_data=f"seleccionar:{servidor.id_servidor}",
                )
            ]
            for servidor in servidores
        ]
        await self._responder(
            actualizacion,
            "Selecciona un servidor activo:",
            InlineKeyboardMarkup(botones),
        )

    async def _seleccionar(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        id_servidor: int,
        acceso: tuple[int, int, str],
    ) -> None:
        try:
            servidor = await self._gestor.consultar_servidor(
                acceso[0],
                acceso[1],
                id_servidor,
            )
        except ErrorHermes as error:
            await self._responder(actualizacion, f"No fue posible seleccionar: {error.mensaje}")
            return
        contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = servidor.id_servidor
        contexto.user_data.pop(CLAVE_CONFIRMACION_REINICIO, None)
        await self._responder(
            actualizacion,
            f"Servidor seleccionado: {servidor.nombre} (id {servidor.id_servidor}).",
        )

    async def seleccionar_por_comando(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Selecciona por identificador entero, sin aceptar texto adicional."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        if len(contexto.args) != 1 or not contexto.args[0].isdigit():
            await self._responder(actualizacion, "Uso correcto: /seleccionar <id>.")
            return
        await self._seleccionar(actualizacion, contexto, int(contexto.args[0]), acceso)

    async def seleccionar_por_boton(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Procesa únicamente datos de botón con el patrón registrado."""

        consulta = actualizacion.callback_query
        if consulta is None or not isinstance(consulta.data, str):
            return
        await consulta.answer()
        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        id_servidor = int(consulta.data.partition(":")[2])
        await self._seleccionar(actualizacion, contexto, id_servidor, acceso)

    async def mostrar_seleccion(self, actualizacion: Update, contexto: CallbackContext) -> None:
        """Vuelve a validar la selección antes de mostrarla."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        id_servidor = contexto.user_data.get(CLAVE_SERVIDOR_SELECCIONADO)
        if not isinstance(id_servidor, int):
            await self._responder(actualizacion, "No hay servidor seleccionado.")
            return
        try:
            servidor = await self._gestor.consultar_servidor(acceso[0], acceso[1], id_servidor)
        except ErrorHermes as error:
            contexto.user_data.pop(CLAVE_SERVIDOR_SELECCIONADO, None)
            await self._responder(
                actualizacion, f"La selección dejó de estar disponible: {error.mensaje}"
            )
            return
        await self._responder(actualizacion, self._formatear_servidor(servidor))

    @staticmethod
    def _formatear_sistema(sistema: SistemaOperativo) -> str:
        return "Linux" if sistema is SistemaOperativo.LINUX else "Windows Server"

    def _formatear_servidor(self, servidor: ServidorResumen) -> str:
        return (
            f"Servidor: {servidor.nombre}\n"
            f"Identificador: {servidor.id_servidor}\n"
            f"Sistema: {self._formatear_sistema(servidor.sistema_operativo)}\n"
            "Estado en inventario: Activo"
        )

    async def _ejecutar_accion(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion,
    ) -> None:
        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        id_servidor = contexto.user_data.get(CLAVE_SERVIDOR_SELECCIONADO)
        if not isinstance(id_servidor, int):
            await self._responder(
                actualizacion,
                "Selecciona primero un servidor con /servidores o /seleccionar <id>.",
            )
            return
        try:
            resultado = await self._gestor.ejecutar_accion(
                acceso[0],
                acceso[1],
                id_servidor,
                codigo_accion,
                datos,
            )
        except ErrorHermes as error:
            await self._responder(actualizacion, f"La operación no se completó: {error.mensaje}")
            return
        await self._responder(actualizacion, self._formatear_resultado(resultado))

    def _formatear_resultado(self, resultado: ResultadoAccionRespuesta) -> str:
        encabezado = (
            f"Servidor: {resultado.nombre_servidor}\n"
            f"Sistema: {self._formatear_sistema(resultado.sistema_operativo)}\n"
            "Estado: Completada\n"
        )
        if resultado.accion.value == "obtener_identidad":
            return (
                encabezado
                + f"Usuario remoto: {resultado.datos['usuario']}\n"
                + f"Equipo: {resultado.datos['nombre_equipo']}"
            )
        if resultado.accion.value == "consultar_proceso":
            return (
                encabezado
                + f"Proceso: {resultado.datos['id_proceso']}\n"
                + f"Nombre: {resultado.datos['nombre_proceso']}"
            )
        return encabezado + "Reinicio programado en 60 segundos."

    async def obtener_identidad(self, actualizacion: Update, contexto: CallbackContext) -> None:
        """Solicita la acción de identidad al backend común."""

        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "obtener_identidad",
            SolicitudEjecucionAccion(),
        )

    async def consultar_proceso(self, actualizacion: Update, contexto: CallbackContext) -> None:
        """Valida sintaxis básica y deja el rango al esquema central de la acción."""

        if len(contexto.args) != 1 or not contexto.args[0].isdigit():
            if await self._autorizar(actualizacion) is not None:
                await self._responder(actualizacion, "Uso correcto: /proceso <id>.")
            return
        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "consultar_proceso",
            SolicitudEjecucionAccion(parametros={"id_proceso": int(contexto.args[0])}),
        )

    async def solicitar_reinicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Crea una confirmación de un solo uso sin ejecutar todavía la acción."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        id_servidor = contexto.user_data.get(CLAVE_SERVIDOR_SELECCIONADO)
        if not isinstance(id_servidor, int):
            await self._responder(actualizacion, "Selecciona primero un servidor.")
            return
        try:
            servidor = await self._gestor.comprobar_accion_sensible(
                acceso[0],
                acceso[1],
                id_servidor,
                "reiniciar_servidor",
            )
        except ErrorHermes as error:
            await self._responder(
                actualizacion, f"No se puede solicitar el reinicio: {error.mensaje}"
            )
            return
        codigo = secrets.token_urlsafe(9)
        contexto.user_data[CLAVE_CONFIRMACION_REINICIO] = ConfirmacionReinicio(
            id_servidor=servidor.id_servidor,
            codigo_aleatorio=codigo,
            vence_en=monotonic() + self._configuracion.tiempo_confirmacion_telegram_segundos,
        )
        teclado = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Confirmar reinicio",
                        callback_data=f"reinicio:confirmar:{codigo}",
                    ),
                    InlineKeyboardButton(
                        "Cancelar",
                        callback_data=f"reinicio:cancelar:{codigo}",
                    ),
                ]
            ]
        )
        await self._responder(
            actualizacion,
            f"¿Confirmas reiniciar {servidor.nombre}? La confirmación caduca pronto.",
            teclado,
        )

    async def resolver_reinicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Valida usuario, desafío, caducidad y servidor antes de confirmar."""

        consulta = actualizacion.callback_query
        if consulta is None or not isinstance(consulta.data, str):
            return
        await consulta.answer()
        if await self._autorizar(actualizacion) is None:
            return
        _, decision, codigo = consulta.data.split(":", maxsplit=2)
        pendiente = contexto.user_data.pop(CLAVE_CONFIRMACION_REINICIO, None)
        if (
            not isinstance(pendiente, ConfirmacionReinicio)
            or monotonic() > pendiente.vence_en
            or not compare_digest(codigo, pendiente.codigo_aleatorio)
        ):
            await self._responder(actualizacion, "La confirmación no es válida o ha caducado.")
            return
        if decision == "cancelar":
            await self._responder(actualizacion, "Reinicio cancelado.")
            return
        contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = pendiente.id_servidor
        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "reiniciar_servidor",
            SolicitudEjecucionAccion(confirmar=True),
        )

    async def cancelar(self, actualizacion: Update, contexto: CallbackContext) -> None:
        """Descarta cualquier desafío de reinicio del usuario."""

        if await self._autorizar(actualizacion) is None:
            return
        pendiente = contexto.user_data.pop(CLAVE_CONFIRMACION_REINICIO, None)
        texto = (
            "Confirmación cancelada."
            if pendiente is not None
            else "No hay confirmaciones pendientes."
        )
        await self._responder(actualizacion, texto)

    async def comando_desconocido(
        self,
        actualizacion: Update,
        _: CallbackContext,
    ) -> None:
        """Rechaza órdenes no registradas sin intentar interpretarlas."""

        if await self._autorizar(actualizacion) is not None:
            await self._responder(actualizacion, "Comando no reconocido. Usa /ayuda.")

    async def manejar_error(self, _: object, contexto: CallbackContext) -> None:
        """Registra solo el tipo del fallo para evitar filtrar mensajes o el token."""

        registrador.error(
            "La interfaz Telegram encontró un error controlado por su límite. tipo=%s",
            type(contexto.error).__name__,
        )


def crear_aplicacion_telegram(
    configuracion: Configuracion,
    gestor: GestorTelegram,
    motor_base_datos: AsyncEngine,
) -> Application:
    """Construye el cliente de sondeo con plazos y concurrencia explícitos."""

    if not configuracion.telegram_habilitado or configuracion.token_telegram is None:
        raise RuntimeError("La interfaz Telegram no está habilitada en la configuración.")
    token = configuracion.token_telegram.get_secret_value()
    interfaz = InterfazTelegram(gestor, configuracion, motor_base_datos)
    aplicacion = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(False)
        .connect_timeout(10)
        .read_timeout(15)
        .write_timeout(15)
        .pool_timeout(5)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(15)
        .get_updates_pool_timeout(5)
        .post_init(interfaz.preparar)
        .post_shutdown(interfaz.cerrar)
        .build()
    )
    interfaz.registrar(aplicacion)
    aplicacion.bot_data["interfaz_telegram"] = interfaz
    return aplicacion
