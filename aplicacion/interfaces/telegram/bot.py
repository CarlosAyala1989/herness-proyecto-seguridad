"""Adaptación de mensajes Telegram hacia los casos de uso de Hermes."""

import logging
import secrets
from collections import deque
from dataclasses import dataclass
from hmac import compare_digest
from io import BytesIO
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
from aplicacion.esquemas.acciones import (
    ResultadoAccionMultipleRespuesta,
    ResultadoAccionRespuesta,
    SeleccionServidores,
    SolicitudEjecucionAccion,
    SolicitudEjecucionMultiple,
)
from aplicacion.esquemas.inventario import ServidorResumen
from aplicacion.interfaces.canal_mensajeria import CanalMensajeria
from aplicacion.interfaces.formateo_usuarios import (
    formatear_listado_usuarios,
    formatear_mutacion_usuario,
)
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.servicios.gestor_telegram import GestorTelegram

registrador = logging.getLogger(__name__)
CLAVE_SERVIDOR_SELECCIONADO = "id_servidor_seleccionado"
CLAVE_SELECCION_SERVIDORES = "seleccion_servidores"
CLAVE_CONFIRMACION_ACCION = "confirmacion_accion"
# Alias interno conservado para consumidores del hito anterior.
CLAVE_CONFIRMACION_REINICIO = CLAVE_CONFIRMACION_ACCION
LIMITE_MENSAJE_TELEGRAM = 4_000
MAX_SOLICITUDES_TELEGRAM_POR_MINUTO = 30
MAX_IDENTIDADES_EN_LIMITADOR = 5_000
MAX_ID_SERVIDOR = 9_223_372_036_854_775_807
MAX_ID_PROCESO = 4_194_304


@dataclass(frozen=True, slots=True)
class ConfirmacionAccionSensible:
    """Desafío efímero ligado a una acción y una selección inmutable."""

    seleccion: SeleccionServidores
    codigo_accion: str
    solicitud: SolicitudEjecucionAccion
    codigo_aleatorio: str
    vence_en: float


COMANDOS_TELEGRAM = (
    BotCommand("inicio", "Iniciar Hermes y comprobar autorización"),
    BotCommand("ayuda", "Mostrar los comandos disponibles"),
    BotCommand("servidores", "Listar y seleccionar un servidor"),
    BotCommand("grupos", "Listar y seleccionar un grupo"),
    BotCommand("seleccionar", "Seleccionar un servidor por identificador"),
    BotCommand("seleccionar_grupo", "Seleccionar un grupo por identificador"),
    BotCommand("seleccionar_todos", "Seleccionar todos los servidores activos"),
    BotCommand("seleccion", "Mostrar la selección actual"),
    BotCommand("diagnostico", "Consultar estado y recursos del servidor"),
    BotCommand("servicio", "Consultar un servicio del sistema"),
    BotCommand("iniciar_servicio", "Iniciar un servicio con confirmación"),
    BotCommand("detener_servicio", "Detener un servicio con confirmación"),
    BotCommand("reiniciar_servicio", "Reiniciar un servicio con confirmación"),
    BotCommand("usuarios", "Listar usuarios locales del servidor"),
    BotCommand("crear_usuario", "Crear una cuenta local deshabilitada"),
    BotCommand("agregar_grupo", "Agregar una cuenta a un grupo local"),
    BotCommand("quitar_grupo", "Quitar una cuenta de un grupo local"),
    BotCommand("bloquear_usuario", "Bloquear una cuenta con confirmación"),
    BotCommand("desbloquear_usuario", "Habilitar una cuenta con confirmación"),
    BotCommand("eliminar_usuario", "Eliminar una cuenta con confirmación"),
    BotCommand("archivo_info", "Consultar información de un archivo remoto"),
    BotCommand("descargar_archivo", "Descargar un archivo remoto permitido"),
    BotCommand("cargar_archivo", "Cargar el documento respondido sin sobrescribir"),
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
        self._solicitudes_recientes: dict[int, deque[float]] = {}

    def registrar(self, aplicacion: Application) -> None:
        """Registra todos los comandos antes de iniciar el sondeo."""

        self._aplicacion = aplicacion
        aplicacion.add_handler(CommandHandler(["inicio", "start"], self.iniciar))
        aplicacion.add_handler(CommandHandler("ayuda", self.mostrar_ayuda))
        aplicacion.add_handler(CommandHandler("servidores", self.mostrar_servidores))
        aplicacion.add_handler(CommandHandler("grupos", self.mostrar_grupos))
        aplicacion.add_handler(CommandHandler("seleccionar", self.seleccionar_por_comando))
        aplicacion.add_handler(
            CommandHandler("seleccionar_grupo", self.seleccionar_grupo_por_comando)
        )
        aplicacion.add_handler(CommandHandler("seleccionar_todos", self.seleccionar_todos))
        aplicacion.add_handler(CommandHandler("seleccion", self.mostrar_seleccion))
        aplicacion.add_handler(CommandHandler("diagnostico", self.obtener_diagnostico))
        aplicacion.add_handler(CommandHandler("servicio", self.consultar_servicio))
        aplicacion.add_handler(CommandHandler("iniciar_servicio", self.iniciar_servicio))
        aplicacion.add_handler(CommandHandler("detener_servicio", self.detener_servicio))
        aplicacion.add_handler(CommandHandler("reiniciar_servicio", self.reiniciar_servicio))
        aplicacion.add_handler(CommandHandler("usuarios", self.mostrar_usuarios_sistema))
        aplicacion.add_handler(CommandHandler("crear_usuario", self.crear_usuario_sistema))
        aplicacion.add_handler(CommandHandler("agregar_grupo", self.agregar_usuario_grupo))
        aplicacion.add_handler(CommandHandler("quitar_grupo", self.quitar_usuario_grupo))
        aplicacion.add_handler(CommandHandler("bloquear_usuario", self.bloquear_usuario_sistema))
        aplicacion.add_handler(
            CommandHandler("desbloquear_usuario", self.desbloquear_usuario_sistema)
        )
        aplicacion.add_handler(CommandHandler("eliminar_usuario", self.eliminar_usuario_sistema))
        aplicacion.add_handler(CommandHandler("archivo_info", self.consultar_archivo))
        aplicacion.add_handler(CommandHandler("descargar_archivo", self.descargar_archivo))
        aplicacion.add_handler(CommandHandler("cargar_archivo", self.cargar_archivo))
        aplicacion.add_handler(CommandHandler("identidad", self.obtener_identidad))
        aplicacion.add_handler(CommandHandler("proceso", self.consultar_proceso))
        aplicacion.add_handler(CommandHandler("reiniciar", self.solicitar_reinicio))
        aplicacion.add_handler(CommandHandler("cancelar", self.cancelar))
        aplicacion.add_handler(
            CallbackQueryHandler(
                self.seleccionar_por_boton,
                pattern=r"^seleccionar:[1-9][0-9]{0,18}$",
            )
        )
        aplicacion.add_handler(
            CallbackQueryHandler(
                self.seleccionar_grupo_por_boton,
                pattern=r"^seleccionar_grupo:[1-9][0-9]{0,18}$",
            )
        )
        aplicacion.add_handler(
            CallbackQueryHandler(
                self.resolver_accion_sensible,
                pattern=r"^accion:(confirmar|cancelar):[A-Za-z0-9_-]{8,32}$",
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
        if not self._admitir_solicitud(usuario.id):
            await self._responder(
                actualizacion,
                "Se alcanzó el límite temporal de solicitudes. Inténtalo nuevamente en un minuto.",
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

    def _admitir_solicitud(self, identificador_telegram: int) -> bool:
        """Acota abuso por identidad y evita crecimiento ilimitado en memoria."""

        ahora = monotonic()
        umbral = ahora - 60
        if (
            identificador_telegram not in self._solicitudes_recientes
            and len(self._solicitudes_recientes) >= MAX_IDENTIDADES_EN_LIMITADOR
        ):
            inactivas = [
                identificador
                for identificador, solicitudes in self._solicitudes_recientes.items()
                if not solicitudes or solicitudes[-1] < umbral
            ]
            for identificador in inactivas:
                self._solicitudes_recientes.pop(identificador, None)
            if len(self._solicitudes_recientes) >= MAX_IDENTIDADES_EN_LIMITADOR:
                return False

        solicitudes = self._solicitudes_recientes.setdefault(identificador_telegram, deque())
        while solicitudes and solicitudes[0] < umbral:
            solicitudes.popleft()
        if len(solicitudes) >= MAX_SOLICITUDES_TELEGRAM_POR_MINUTO:
            return False
        solicitudes.append(ahora)
        return True

    @staticmethod
    def _convertir_entero_acotado(texto: str, maximo: int) -> int | None:
        """Evita conversiones enormes y rechaza signos o caracteres añadidos."""

        if not texto.isascii() or not texto.isdigit() or len(texto) > len(str(maximo)):
            return None
        valor = int(texto)
        return valor if 1 <= valor <= maximo else None

    @staticmethod
    def _texto_ayuda() -> str:
        return (
            "Comandos disponibles:\n"
            "/servidores — listar y elegir un servidor\n"
            "/grupos — listar y elegir un grupo\n"
            "/seleccionar <id> — elegir un servidor\n"
            "/seleccionar_grupo <id> — elegir un grupo\n"
            "/seleccionar_todos — elegir todos los servidores activos\n"
            "/seleccion — mostrar la selección actual\n"
            "/diagnostico — consultar estado, recursos y sistema\n"
            "/servicio <nombre> — consultar un servicio\n"
            "/iniciar_servicio <nombre> — iniciar con confirmación\n"
            "/detener_servicio <nombre> — detener con confirmación\n"
            "/reiniciar_servicio <nombre> — reiniciar con confirmación\n"
            "/usuarios — listar cuentas locales y grupos\n"
            "/crear_usuario <cuenta> [nombre] — crear deshabilitada\n"
            "/agregar_grupo <cuenta> <grupo> — agregar a un grupo\n"
            "/quitar_grupo <cuenta> <grupo> — quitar de un grupo\n"
            "/bloquear_usuario <cuenta> — bloquear con confirmación\n"
            "/desbloquear_usuario <cuenta> — habilitar con confirmación\n"
            "/eliminar_usuario <cuenta> — eliminar con confirmación\n"
            "/archivo_info <ruta> — consultar un archivo remoto permitido\n"
            "/descargar_archivo <ruta> — recibir un archivo remoto\n"
            "/cargar_archivo <ruta> — responder a un documento para cargarlo\n"
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

    async def mostrar_grupos(
        self,
        actualizacion: Update,
        _: CallbackContext,
    ) -> None:
        """Lista grupos como botones sin resolver sus miembros en el bot."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        try:
            grupos = await self._gestor.consultar_grupos(acceso[0], acceso[1])
        except ErrorHermes as error:
            await self._responder(
                actualizacion,
                f"No fue posible consultar grupos: {error.mensaje}",
            )
            return
        if not grupos:
            await self._responder(actualizacion, "No hay grupos registrados.")
            return
        botones = [
            [
                InlineKeyboardButton(
                    f"{grupo.id_grupo} · {grupo.nombre[:40]} ({len(grupo.servidores)})",
                    callback_data=f"seleccionar_grupo:{grupo.id_grupo}",
                )
            ]
            for grupo in grupos
        ]
        await self._responder(
            actualizacion,
            "Selecciona un grupo de servidores:",
            InlineKeyboardMarkup(botones),
        )

    @staticmethod
    def _guardar_seleccion(
        contexto: CallbackContext,
        seleccion: SeleccionServidores,
    ) -> None:
        """Conserva el selector común y mantiene compatibilidad con la clave individual."""

        contexto.user_data[CLAVE_SELECCION_SERVIDORES] = seleccion
        ids = seleccion.ids_servidores
        if ids is not None and len(ids) == 1:
            contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = ids[0]
        else:
            contexto.user_data.pop(CLAVE_SERVIDOR_SELECCIONADO, None)
        contexto.user_data.pop(CLAVE_CONFIRMACION_ACCION, None)

    @staticmethod
    def _obtener_seleccion(contexto: CallbackContext) -> SeleccionServidores | None:
        seleccion = contexto.user_data.get(CLAVE_SELECCION_SERVIDORES)
        if isinstance(seleccion, SeleccionServidores):
            return seleccion
        id_servidor = contexto.user_data.get(CLAVE_SERVIDOR_SELECCIONADO)
        if isinstance(id_servidor, int) and not isinstance(id_servidor, bool):
            return SeleccionServidores(ids_servidores=[id_servidor])
        return None

    async def _preparar_operacion_archivo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> tuple[tuple[int, int, str], int] | None:
        """Exige un único servidor porque una transferencia produce un archivo."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return None
        seleccion = self._obtener_seleccion(contexto)
        ids = seleccion.ids_servidores if seleccion is not None else None
        if ids is None or len(ids) != 1:
            await self._responder(
                actualizacion,
                "Selecciona un único servidor antes de administrar archivos.",
            )
            return None
        return acceso, ids[0]

    async def consultar_archivo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Muestra metadatos SFTP sin descargar contenido."""

        preparado = await self._preparar_operacion_archivo(actualizacion, contexto)
        if preparado is None:
            return
        ruta = " ".join(contexto.args).strip()
        if not ruta:
            await self._responder(actualizacion, "Uso correcto: /archivo_info <ruta>.")
            return
        acceso, id_servidor = preparado
        try:
            informacion = await self._gestor.consultar_informacion_archivo(
                acceso[0], acceso[1], id_servidor, ruta
            )
        except ErrorHermes as error:
            await self._responder(
                actualizacion, f"No fue posible consultar el archivo: {error.mensaje}"
            )
            return
        modificado = (
            informacion.modificado_en.isoformat()
            if informacion.modificado_en is not None
            else "No disponible"
        )
        tamano = (
            str(informacion.tamano_bytes)
            if informacion.tamano_bytes is not None
            else "No disponible"
        )
        await self._responder(
            actualizacion,
            f"Servidor: {informacion.nombre_servidor}\n"
            f"Archivo: {informacion.nombre_archivo}\n"
            f"Tipo: {informacion.tipo}\n"
            f"Tamaño: {tamano} bytes\n"
            f"Modificado: {modificado}",
        )

    async def descargar_archivo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Entrega como documento un archivo remoto previamente autorizado."""

        preparado = await self._preparar_operacion_archivo(actualizacion, contexto)
        if preparado is None:
            return
        ruta = " ".join(contexto.args).strip()
        if not ruta:
            await self._responder(actualizacion, "Uso correcto: /descargar_archivo <ruta>.")
            return
        acceso, id_servidor = preparado
        try:
            descarga = await self._gestor.descargar_archivo(acceso[0], acceso[1], id_servidor, ruta)
        except ErrorHermes as error:
            await self._responder(
                actualizacion, f"No fue posible descargar el archivo: {error.mensaje}"
            )
            return
        mensaje = actualizacion.effective_message
        if mensaje is None:
            return
        flujo = BytesIO(descarga.contenido)
        flujo.name = descarga.nombre_archivo
        await mensaje.reply_document(
            document=flujo,
            filename=descarga.nombre_archivo,
            caption="Archivo descargado de forma segura por Hermes.",
        )

    async def cargar_archivo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Carga el documento respondido usando siempre creación exclusiva."""

        preparado = await self._preparar_operacion_archivo(actualizacion, contexto)
        if preparado is None:
            return
        ruta = " ".join(contexto.args).strip()
        mensaje = actualizacion.effective_message
        documento = (
            mensaje.reply_to_message.document
            if mensaje is not None and mensaje.reply_to_message is not None
            else None
        )
        if not ruta or documento is None:
            await self._responder(
                actualizacion,
                "Responde a un documento con: /cargar_archivo <ruta_remota>.",
            )
            return
        limite = self._configuracion.limite_archivo_transferencia_bytes
        if documento.file_size is None or documento.file_size > limite:
            await self._responder(
                actualizacion,
                f"El documento debe informar un tamaño no mayor que {limite} bytes.",
            )
            return
        acceso, id_servidor = preparado
        try:
            archivo_telegram = await documento.get_file()
            contenido = bytes(await archivo_telegram.download_as_bytearray())
            if len(contenido) > limite:
                await self._responder(actualizacion, "El documento supera el límite permitido.")
                return
            resultado = await self._gestor.cargar_archivo(
                acceso[0], acceso[1], id_servidor, ruta, contenido
            )
        except ErrorHermes as error:
            await self._responder(
                actualizacion, f"No fue posible cargar el archivo: {error.mensaje}"
            )
            return
        await self._responder(
            actualizacion,
            f"Archivo cargado en {resultado.nombre_servidor}: "
            f"{resultado.tamano_bytes} bytes. No se sobrescribió ningún archivo.",
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
        self._guardar_seleccion(
            contexto,
            SeleccionServidores(ids_servidores=[servidor.id_servidor]),
        )
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
        id_servidor = (
            self._convertir_entero_acotado(contexto.args[0], MAX_ID_SERVIDOR)
            if len(contexto.args) == 1
            else None
        )
        if id_servidor is None:
            await self._responder(actualizacion, "Uso correcto: /seleccionar <id>.")
            return
        await self._seleccionar(actualizacion, contexto, id_servidor, acceso)

    async def _seleccionar_grupo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        id_grupo: int,
        acceso: tuple[int, int, str],
    ) -> None:
        seleccion = SeleccionServidores(id_grupo=id_grupo)
        try:
            cantidad = await self._gestor.comprobar_seleccion_multiple(
                acceso[0],
                acceso[1],
                seleccion,
            )
        except ErrorHermes as error:
            await self._responder(actualizacion, f"No fue posible seleccionar: {error.mensaje}")
            return
        self._guardar_seleccion(contexto, seleccion)
        await self._responder(
            actualizacion,
            f"Grupo seleccionado: id {id_grupo}, {cantidad} servidor(es).",
        )

    async def seleccionar_grupo_por_comando(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Selecciona un grupo validado a partir de un identificador exacto."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        id_grupo = (
            self._convertir_entero_acotado(contexto.args[0], MAX_ID_SERVIDOR)
            if len(contexto.args) == 1
            else None
        )
        if id_grupo is None:
            await self._responder(actualizacion, "Uso correcto: /seleccionar_grupo <id>.")
            return
        await self._seleccionar_grupo(actualizacion, contexto, id_grupo, acceso)

    async def seleccionar_grupo_por_boton(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Acepta únicamente el identificador de grupo validado por el patrón del botón."""

        consulta = actualizacion.callback_query
        if consulta is None or not isinstance(consulta.data, str):
            return
        await consulta.answer()
        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        id_grupo = self._convertir_entero_acotado(
            consulta.data.partition(":")[2],
            MAX_ID_SERVIDOR,
        )
        if id_grupo is None:
            await self._responder(actualizacion, "La selección recibida no es válida.")
            return
        await self._seleccionar_grupo(actualizacion, contexto, id_grupo, acceso)

    async def seleccionar_todos(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Selecciona dinámicamente todos los servidores activos autorizados."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        if contexto.args:
            await self._responder(actualizacion, "Uso correcto: /seleccionar_todos.")
            return
        seleccion = SeleccionServidores(todos=True)
        try:
            cantidad = await self._gestor.comprobar_seleccion_multiple(
                acceso[0],
                acceso[1],
                seleccion,
            )
        except ErrorHermes as error:
            await self._responder(actualizacion, f"No fue posible seleccionar: {error.mensaje}")
            return
        self._guardar_seleccion(contexto, seleccion)
        await self._responder(
            actualizacion,
            f"Selección activa: todos los servidores activos ({cantidad}).",
        )

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
        id_servidor = self._convertir_entero_acotado(
            consulta.data.partition(":")[2],
            MAX_ID_SERVIDOR,
        )
        if id_servidor is None:
            await self._responder(actualizacion, "La selección recibida no es válida.")
            return
        await self._seleccionar(actualizacion, contexto, id_servidor, acceso)

    async def mostrar_seleccion(self, actualizacion: Update, contexto: CallbackContext) -> None:
        """Vuelve a validar la selección antes de mostrarla."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        seleccion = self._obtener_seleccion(contexto)
        if seleccion is None:
            await self._responder(actualizacion, "No hay servidores seleccionados.")
            return
        ids = seleccion.ids_servidores
        if ids is None or len(ids) != 1:
            try:
                cantidad = await self._gestor.comprobar_seleccion_multiple(
                    acceso[0],
                    acceso[1],
                    seleccion,
                )
            except ErrorHermes as error:
                contexto.user_data.pop(CLAVE_SELECCION_SERVIDORES, None)
                await self._responder(
                    actualizacion,
                    f"La selección dejó de estar disponible: {error.mensaje}",
                )
                return
            descripcion = (
                f"Grupo seleccionado: id {seleccion.id_grupo}"
                if seleccion.id_grupo is not None
                else "Selección: todos los servidores activos"
            )
            await self._responder(
                actualizacion,
                f"{descripcion}\nServidores incluidos ahora: {cantidad}.",
            )
            return
        id_servidor = ids[0]
        try:
            servidor = await self._gestor.consultar_servidor(acceso[0], acceso[1], id_servidor)
        except ErrorHermes as error:
            contexto.user_data.pop(CLAVE_SERVIDOR_SELECCIONADO, None)
            contexto.user_data.pop(CLAVE_SELECCION_SERVIDORES, None)
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
        seleccion = self._obtener_seleccion(contexto)
        if seleccion is None:
            await self._responder(
                actualizacion,
                "Selecciona primero un servidor, un grupo o todos los servidores.",
            )
            return
        try:
            ids = seleccion.ids_servidores
            if ids is not None and len(ids) == 1:
                resultado = await self._gestor.ejecutar_accion(
                    acceso[0],
                    acceso[1],
                    ids[0],
                    codigo_accion,
                    datos,
                )
            else:
                resultado_multiple = await self._gestor.ejecutar_accion_multiple(
                    acceso[0],
                    acceso[1],
                    codigo_accion,
                    SolicitudEjecucionMultiple(
                        seleccion=seleccion,
                        parametros=datos.parametros,
                        confirmar=datos.confirmar,
                    ),
                )
        except ErrorHermes as error:
            if codigo_accion == "obtener_diagnostico":
                await self._responder(
                    actualizacion,
                    "Estado: No disponible\n"
                    f"Detalle: No fue posible obtener el diagnóstico: {error.mensaje}",
                )
            else:
                await self._responder(
                    actualizacion,
                    f"La operación no se completó: {error.mensaje}",
                )
            return
        if ids is not None and len(ids) == 1:
            if resultado.accion.value == "listar_usuarios_sistema":
                for mensaje in formatear_listado_usuarios(
                    resultado.nombre_servidor,
                    resultado.sistema_operativo,
                    resultado.datos,
                    LIMITE_MENSAJE_TELEGRAM,
                ):
                    await self._responder(actualizacion, mensaje)
            else:
                await self._responder(actualizacion, self._formatear_resultado(resultado))
        else:
            for mensaje in self._formatear_resultado_multiple(resultado_multiple):
                await self._responder(actualizacion, mensaje)

    def _formatear_resultado_multiple(
        self,
        resultado: ResultadoAccionMultipleRespuesta,
    ) -> list[str]:
        """Genera mensajes acotados sin omitir el resultado de ningún servidor."""

        encabezado = (
            f"Acción múltiple: {resultado.accion.value}\n"
            f"Completados: {resultado.servidores_completados} · "
            f"Fallidos: {resultado.servidores_fallidos}\n"
        )
        lineas = []
        for elemento in resultado.resultados:
            nombre = elemento.nombre_servidor or f"id {elemento.id_servidor}"
            if elemento.estado == "error":
                lineas.append(f"❌ {nombre}: {elemento.mensaje_error}")
                continue
            detalle = "completada"
            if resultado.accion.value == "obtener_diagnostico" and elemento.datos:
                detalle = (
                    f"CPU {self._formatear_porcentaje(elemento.datos.get('cpu_porcentaje'))}, "
                    f"RAM {self._formatear_porcentaje(elemento.datos.get('memoria_porcentaje'))}, "
                    f"disco {self._formatear_porcentaje(elemento.datos.get('disco_porcentaje'))}"
                )
            elif resultado.accion.value.endswith("servicio") and elemento.datos:
                detalle = f"servicio {elemento.datos.get('estado', 'no disponible')}"
            elif resultado.accion.value == "listar_usuarios_sistema" and elemento.datos:
                detalle = f"{elemento.datos.get('total_usuarios', 0)} usuario(s)"
            elif resultado.accion.value.endswith("usuario_sistema") and elemento.datos:
                detalle = (
                    f"cuenta {elemento.datos.get('nombre_usuario', 'no disponible')}: "
                    f"{elemento.datos.get('estado', 'desconocido')}"
                )
            lineas.append(f"✅ {nombre}: {detalle}")

        mensajes: list[str] = []
        actual = encabezado
        for linea in lineas:
            candidato = f"{actual}\n{linea}"
            if len(candidato) > LIMITE_MENSAJE_TELEGRAM and actual != encabezado:
                mensajes.append(actual)
                actual = f"Continuación:\n{linea}"
            else:
                actual = candidato
        mensajes.append(actual)
        return mensajes

    @staticmethod
    def _formatear_porcentaje(valor: object) -> str:
        if not isinstance(valor, (int, float)) or isinstance(valor, bool):
            return "No disponible"
        return f"{valor:.2f} %"

    @staticmethod
    def _formatear_tiempo_actividad(valor: object) -> str:
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
            return "No disponible"
        dias, resto = divmod(valor, 86_400)
        horas, resto = divmod(resto, 3_600)
        minutos = resto // 60
        return f"{dias} d, {horas} h, {minutos} min"

    @staticmethod
    def _formatear_texto_diagnostico(valor: object) -> str:
        return valor if isinstance(valor, str) and valor else "No disponible"

    def _formatear_resultado(self, resultado: ResultadoAccionRespuesta) -> str:
        if resultado.accion.value == "obtener_diagnostico":
            datos = resultado.datos
            return (
                f"Servidor: {resultado.nombre_servidor}\n"
                f"Sistema: {self._formatear_texto_diagnostico(datos.get('sistema'))}\n"
                f"Versión: {self._formatear_texto_diagnostico(datos.get('version'))}\n"
                f"Equipo: {self._formatear_texto_diagnostico(datos.get('nombre_equipo'))}\n"
                "Estado: Disponible\n"
                f"CPU: {self._formatear_porcentaje(datos.get('cpu_porcentaje'))}\n"
                f"RAM: {self._formatear_porcentaje(datos.get('memoria_porcentaje'))}\n"
                f"Disco: {self._formatear_porcentaje(datos.get('disco_porcentaje'))}\n"
                "Tiempo de actividad: "
                f"{self._formatear_tiempo_actividad(datos.get('tiempo_actividad_segundos'))}"
            )
        if resultado.accion.value in {
            "consultar_servicio",
            "iniciar_servicio",
            "detener_servicio",
            "reiniciar_servicio",
        }:
            datos = resultado.datos
            inicio_automatico = datos.get("inicio_automatico")
            if inicio_automatico is True:
                texto_inicio = "Sí"
            elif inicio_automatico is False:
                texto_inicio = "No"
            else:
                texto_inicio = "No disponible"
            operacion = self._formatear_texto_diagnostico(
                datos.get("accion_realizada")
            ).capitalize()
            estado = self._formatear_texto_diagnostico(datos.get("estado")).capitalize()
            return (
                f"Servidor: {resultado.nombre_servidor}\n"
                f"Sistema: {self._formatear_sistema(resultado.sistema_operativo)}\n"
                f"Operación: {operacion}\n"
                f"Servicio: {datos.get('nombre_servicio')}\n"
                f"Estado del servicio: {estado}\n"
                f"Estado nativo: {datos.get('estado_nativo')}\n"
                f"Inicio automático: {texto_inicio}"
            )
        if resultado.accion.value in {
            "crear_usuario_sistema",
            "cambiar_grupo_usuario_sistema",
            "bloquear_usuario_sistema",
            "desbloquear_usuario_sistema",
            "eliminar_usuario_sistema",
        }:
            return formatear_mutacion_usuario(
                resultado.nombre_servidor,
                resultado.sistema_operativo,
                resultado.datos,
            )
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

    async def obtener_diagnostico(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita al backend el diagnóstico normalizado del servidor elegido."""

        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "obtener_diagnostico",
            SolicitudEjecucionAccion(),
        )

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

        id_proceso = (
            self._convertir_entero_acotado(contexto.args[0], MAX_ID_PROCESO)
            if len(contexto.args) == 1
            else None
        )
        if id_proceso is None:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(actualizacion, "Uso correcto: /proceso <id>.")
            return
        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "consultar_proceso",
            SolicitudEjecucionAccion(parametros={"id_proceso": id_proceso}),
        )

    async def consultar_servicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Consulta un nombre exacto mediante el catálogo común."""

        if len(contexto.args) != 1:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(actualizacion, "Uso correcto: /servicio <nombre>.")
            return
        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "consultar_servicio",
            SolicitudEjecucionAccion(
                parametros={"nombre_servicio": contexto.args[0]},
            ),
        )

    async def mostrar_usuarios_sistema(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Lista cuentas locales mediante el backend común."""

        if contexto.args:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(actualizacion, "Uso correcto: /usuarios.")
            return
        await self._ejecutar_accion(
            actualizacion,
            contexto,
            "listar_usuarios_sistema",
            SolicitudEjecucionAccion(),
        )

    async def crear_usuario_sistema(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Crea una cuenta sin contraseña y deshabilitada tras confirmar."""

        if not contexto.args:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(
                    actualizacion,
                    "Uso correcto: /crear_usuario <cuenta> [nombre para mostrar].",
                )
            return
        nombre_usuario = contexto.args[0]
        nombre_mostrar = " ".join(contexto.args[1:]) or None
        await self._solicitar_accion_sensible(
            actualizacion,
            contexto,
            "crear_usuario_sistema",
            SolicitudEjecucionAccion(
                parametros={
                    "nombre_usuario": nombre_usuario,
                    "nombre_mostrar": nombre_mostrar,
                }
            ),
            f"crear la cuenta local {nombre_usuario}, inicialmente deshabilitada",
        )

    async def _cambiar_grupo_usuario(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        operacion: str,
        comando: str,
    ) -> None:
        if len(contexto.args) < 2:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(
                    actualizacion,
                    f"Uso correcto: /{comando} <cuenta> <grupo>.",
                )
            return
        nombre_usuario = contexto.args[0]
        nombre_grupo = " ".join(contexto.args[1:])
        await self._solicitar_accion_sensible(
            actualizacion,
            contexto,
            "cambiar_grupo_usuario_sistema",
            SolicitudEjecucionAccion(
                parametros={
                    "nombre_usuario": nombre_usuario,
                    "nombre_grupo": nombre_grupo,
                    "operacion_grupo": operacion,
                    "autorizar_cuenta_protegida": False,
                }
            ),
            f"{operacion} la cuenta {nombre_usuario} en el grupo {nombre_grupo}",
        )

    async def agregar_usuario_grupo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita agregar una cuenta a un grupo no protegido."""

        await self._cambiar_grupo_usuario(actualizacion, contexto, "agregar", "agregar_grupo")

    async def quitar_usuario_grupo(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita quitar una cuenta de un grupo no protegido."""

        await self._cambiar_grupo_usuario(actualizacion, contexto, "quitar", "quitar_grupo")

    async def _cambiar_estado_usuario(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        codigo_accion: str,
        verbo: str,
        comando: str,
    ) -> None:
        if len(contexto.args) != 1:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(
                    actualizacion,
                    f"Uso correcto: /{comando} <cuenta>.",
                )
            return
        nombre_usuario = contexto.args[0]
        await self._solicitar_accion_sensible(
            actualizacion,
            contexto,
            codigo_accion,
            SolicitudEjecucionAccion(
                parametros={
                    "nombre_usuario": nombre_usuario,
                    "autorizar_cuenta_protegida": False,
                }
            ),
            f"{verbo} la cuenta local {nombre_usuario}",
        )

    async def bloquear_usuario_sistema(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        await self._cambiar_estado_usuario(
            actualizacion,
            contexto,
            "bloquear_usuario_sistema",
            "bloquear",
            "bloquear_usuario",
        )

    async def desbloquear_usuario_sistema(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        await self._cambiar_estado_usuario(
            actualizacion,
            contexto,
            "desbloquear_usuario_sistema",
            "habilitar",
            "desbloquear_usuario",
        )

    async def eliminar_usuario_sistema(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        await self._cambiar_estado_usuario(
            actualizacion,
            contexto,
            "eliminar_usuario_sistema",
            "eliminar junto con su directorio de usuario",
            "eliminar_usuario",
        )

    async def _solicitar_accion_sensible(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        codigo_accion: str,
        solicitud: SolicitudEjecucionAccion,
        descripcion: str,
    ) -> None:
        """Crea una confirmación de un uso tras validar permiso y parámetros."""

        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return
        seleccion = self._obtener_seleccion(contexto)
        if seleccion is None:
            await self._responder(actualizacion, "Selecciona primero uno o más servidores.")
            return
        try:
            ids = seleccion.ids_servidores
            if ids is not None and len(ids) == 1:
                servidor = await self._gestor.comprobar_accion_sensible(
                    acceso[0],
                    acceso[1],
                    ids[0],
                    codigo_accion,
                    solicitud,
                )
                seleccion_fijada = SeleccionServidores(ids_servidores=[servidor.id_servidor])
                descripcion_destino = servidor.nombre
            else:
                seleccion_fijada, cantidad = await self._gestor.comprobar_accion_sensible_multiple(
                    acceso[0],
                    acceso[1],
                    codigo_accion,
                    SolicitudEjecucionMultiple(
                        seleccion=seleccion,
                        parametros=solicitud.parametros,
                    ),
                )
                descripcion_destino = f"{cantidad} servidores"
        except ErrorHermes as error:
            await self._responder(
                actualizacion,
                f"No se puede solicitar la operación: {error.mensaje}",
            )
            return
        codigo_aleatorio = secrets.token_urlsafe(9)
        contexto.user_data[CLAVE_CONFIRMACION_ACCION] = ConfirmacionAccionSensible(
            seleccion=seleccion_fijada,
            codigo_accion=codigo_accion,
            solicitud=solicitud,
            codigo_aleatorio=codigo_aleatorio,
            vence_en=monotonic() + self._configuracion.tiempo_confirmacion_telegram_segundos,
        )
        teclado = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Confirmar",
                        callback_data=f"accion:confirmar:{codigo_aleatorio}",
                    ),
                    InlineKeyboardButton(
                        "Cancelar",
                        callback_data=f"accion:cancelar:{codigo_aleatorio}",
                    ),
                ]
            ]
        )
        await self._responder(
            actualizacion,
            f"¿Confirmas {descripcion} en {descripcion_destino}? "
            "La confirmación caduca pronto y sus destinos ya quedaron fijados.",
            teclado,
        )

    async def _solicitar_operacion_servicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        codigo_accion: str,
        verbo: str,
        comando: str,
    ) -> None:
        if len(contexto.args) != 1:
            if await self._autorizar(actualizacion) is not None:
                await self._responder(
                    actualizacion,
                    f"Uso correcto: /{comando} <nombre>.",
                )
            return
        nombre_servicio = contexto.args[0]
        await self._solicitar_accion_sensible(
            actualizacion,
            contexto,
            codigo_accion,
            SolicitudEjecucionAccion(
                parametros={"nombre_servicio": nombre_servicio},
            ),
            f"{verbo} el servicio {nombre_servicio}",
        )

    async def iniciar_servicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita confirmación antes de iniciar un servicio."""

        await self._solicitar_operacion_servicio(
            actualizacion,
            contexto,
            "iniciar_servicio",
            "iniciar",
            "iniciar_servicio",
        )

    async def detener_servicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita confirmación antes de detener un servicio."""

        await self._solicitar_operacion_servicio(
            actualizacion,
            contexto,
            "detener_servicio",
            "detener",
            "detener_servicio",
        )

    async def reiniciar_servicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita confirmación antes de reiniciar un servicio."""

        await self._solicitar_operacion_servicio(
            actualizacion,
            contexto,
            "reiniciar_servicio",
            "reiniciar",
            "reiniciar_servicio",
        )

    async def solicitar_reinicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Solicita confirmación para el reinicio completo del servidor."""

        await self._solicitar_accion_sensible(
            actualizacion,
            contexto,
            "reiniciar_servidor",
            SolicitudEjecucionAccion(),
            "reiniciar el servidor",
        )

    async def resolver_accion_sensible(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Valida usuario, desafío y caducidad antes de ejecutar la acción ligada."""

        consulta = actualizacion.callback_query
        if consulta is None or not isinstance(consulta.data, str):
            return
        await consulta.answer()
        if await self._autorizar(actualizacion) is None:
            return
        _, decision, codigo = consulta.data.split(":", maxsplit=2)
        pendiente = contexto.user_data.pop(CLAVE_CONFIRMACION_ACCION, None)
        if (
            not isinstance(pendiente, ConfirmacionAccionSensible)
            or monotonic() > pendiente.vence_en
            or not compare_digest(codigo, pendiente.codigo_aleatorio)
        ):
            await self._responder(actualizacion, "La confirmación no es válida o ha caducado.")
            return
        if decision == "cancelar":
            await self._responder(actualizacion, "Operación cancelada.")
            return
        self._guardar_seleccion(contexto, pendiente.seleccion)
        await self._ejecutar_accion(
            actualizacion,
            contexto,
            pendiente.codigo_accion,
            pendiente.solicitud.model_copy(update={"confirmar": True}),
        )

    async def resolver_reinicio(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
    ) -> None:
        """Alias interno conservado para la integración previa de reinicio."""

        await self.resolver_accion_sensible(actualizacion, contexto)

    async def cancelar(self, actualizacion: Update, contexto: CallbackContext) -> None:
        """Descarta cualquier desafío sensible del usuario."""

        if await self._autorizar(actualizacion) is None:
            return
        pendiente = contexto.user_data.pop(CLAVE_CONFIRMACION_ACCION, None)
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
