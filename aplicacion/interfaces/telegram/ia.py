"""Selección de modelo y tareas locales de IA para el propietario de Telegram."""

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from contextlib import suppress
from io import BytesIO
from time import monotonic

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorHermes
from aplicacion.servicios.codex_local import CodexLocal, ErrorCodexLocal, ModeloCodex
from aplicacion.servicios.gestor_telegram import GestorTelegram

registrador = logging.getLogger(__name__)
CLAVE_IA = "configuracion_ia"
CLAVE_MENU_IA = "menu_ia"


class InterfazIATelegram:
    def __init__(
        self,
        gestor: GestorTelegram,
        configuracion: Configuracion,
        autorizar: Callable[[Update], Awaitable[tuple[int, int, str] | None]],
    ) -> None:
        self._gestor = gestor
        self._configuracion = configuracion
        self._autorizar = autorizar
        self._codex = CodexLocal(configuracion)
        self._tarea: asyncio.Task | None = None

    def registrar(self, aplicacion: Application) -> None:
        aplicacion.add_handler(CommandHandler("ia", self.comando))
        aplicacion.add_handler(CallbackQueryHandler(self.elegir, pattern=r"^ia:"))
        aplicacion.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.texto))

    async def cerrar(self) -> None:
        if self._tarea is not None and not self._tarea.done():
            self._tarea.cancel()
            with suppress(asyncio.CancelledError):
                await self._tarea

    async def _acceso(self, actualizacion: Update) -> tuple[int, int, str] | None:
        acceso = await self._autorizar(actualizacion)
        if acceso is None:
            return None
        if not self._configuracion.ia_habilitada:
            await actualizacion.effective_message.reply_text(
                "IA está deshabilitada. Habilita HERMES_IA_HABILITADA en la configuración local."
            )
            return None
        try:
            await self._gestor.registrar_ia(acceso[0], acceso[1], "autorizacion")
        except ErrorHermes as error:
            await actualizacion.effective_message.reply_text(error.mensaje)
            return None
        return acceso

    async def comando(self, actualizacion: Update, contexto: CallbackContext) -> None:
        acceso = await self._acceso(actualizacion)
        if acceso is None:
            return
        mensaje = actualizacion.effective_message
        argumentos = contexto.args
        if argumentos == ["detener"]:
            if self._tarea is None or self._tarea.done():
                await mensaje.reply_text("No hay una tarea de IA en ejecución.")
            else:
                self._tarea.cancel()
                with suppress(asyncio.CancelledError):
                    await self._tarea
                await mensaje.reply_text(
                    "Tarea de IA detenida. Los cambios ya realizados se conservan."
                )
            return
        if argumentos == ["salir"]:
            contexto.user_data.pop(CLAVE_IA, None)
            contexto.user_data.pop(CLAVE_MENU_IA, None)
            await mensaje.reply_text(
                "Modo IA desactivado. Para detener una tarea activa utiliza /ia detener."
            )
            return
        if argumentos == ["estado"]:
            seleccion = contexto.user_data.get(CLAVE_IA)
            estado = (
                "en ejecución"
                if self._tarea is not None and not self._tarea.done()
                else "sin tarea activa"
            )
            detalle = (
                f"{seleccion[0].identificador} · {seleccion[1]}"
                if seleccion
                else "modelo sin seleccionar"
            )
            await mensaje.reply_text(
                f"IA: {detalle}; {estado}.\nDirectorio local: {self._configuracion.directorio_trabajo_ia}\nPermisos: sin sandbox ni aprobaciones de Codex; permisos del usuario del servicio."
            )
            return
        if not argumentos or argumentos == ["modelos"]:
            try:
                modelos = await self._codex.listar_modelos()
            except ErrorCodexLocal as error:
                await mensaje.reply_text(str(error))
                return
            nonce = secrets.token_hex(4)
            contexto.user_data[CLAVE_MENU_IA] = (nonce, monotonic(), modelos)
            teclado = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            modelo.nombre, callback_data=f"ia:{nonce}:modelo:{indice}"
                        )
                    ]
                    for indice, modelo in enumerate(modelos)
                ]
            )
            await mensaje.reply_text(
                "Elige el modelo de Codex CLI para esta máquina. Después elegirás el esfuerzo.\n"
                "Las tareas se ejecutan sin sandbox ni aprobaciones de Codex, con acceso a los archivos y comandos de la cuenta local. No equivale a root.\n"
                "No dependen del servidor elegido con /seleccionar. Cada mensaje inicia una tarea independiente.",
                reply_markup=teclado,
            )
            return
        texto = getattr(mensaje, "text", None)
        partes_texto = texto.split(maxsplit=1) if isinstance(texto, str) else []
        instruccion = (
            partes_texto[1]
            if len(partes_texto) == 2 and partes_texto[0].split("@")[0] == "/ia"
            else " ".join(argumentos)
        )
        await self._iniciar(actualizacion, contexto, acceso, instruccion)

    async def elegir(self, actualizacion: Update, contexto: CallbackContext) -> None:
        consulta = actualizacion.callback_query
        if consulta is None:
            return
        await consulta.answer()
        if await self._acceso(actualizacion) is None:
            return
        mensaje = actualizacion.effective_message
        menu = contexto.user_data.get(CLAVE_MENU_IA)
        partes = (consulta.data or "").split(":")
        if (
            not menu
            or len(partes) != 4
            or partes[1] != menu[0]
            or monotonic() - menu[1] > 300
            or not partes[3].isdigit()
            or len(partes[3]) > 2
        ):
            await mensaje.reply_text(
                "Este menú de IA caducó o no es válido. Envía /ia para abrir otro."
            )
            return
        indice = int(partes[3])
        if partes[2] == "modelo" and indice < len(menu[2]):
            modelo = menu[2][indice]
            # Invalida también botones anteriores de esfuerzo al cambiar modelo.
            nonce = secrets.token_hex(4)
            contexto.user_data[CLAVE_MENU_IA] = (nonce, monotonic(), menu[2], modelo)
            await mensaje.reply_text(
                f"Modelo: {modelo.nombre}. Elige el esfuerzo:",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                esfuerzo, callback_data=f"ia:{nonce}:esfuerzo:{posicion}"
                            )
                        ]
                        for posicion, esfuerzo in enumerate(modelo.esfuerzos)
                    ]
                ),
            )
        elif partes[2] == "esfuerzo" and len(menu) == 4 and indice < len(menu[3].esfuerzos):
            modelo = menu[3]
            esfuerzo = modelo.esfuerzos[indice]
            contexto.user_data[CLAVE_IA] = (modelo, esfuerzo)
            contexto.user_data.pop(CLAVE_MENU_IA, None)
            await mensaje.reply_text(
                f"IA lista: {modelo.identificador} · {esfuerzo}.\nEnvía /ia <instrucción> o un mensaje de texto. /ia detener interrumpe la tarea; /ia salir desactiva los mensajes a IA."
            )
        else:
            await mensaje.reply_text("Opción de IA no válida. Envía /ia para abrir otro menú.")

    async def texto(self, actualizacion: Update, contexto: CallbackContext) -> None:
        if CLAVE_IA not in contexto.user_data:
            return
        acceso = await self._acceso(actualizacion)
        if acceso is not None:
            await self._iniciar(
                actualizacion, contexto, acceso, actualizacion.effective_message.text or ""
            )

    async def _iniciar(
        self,
        actualizacion: Update,
        contexto: CallbackContext,
        acceso: tuple[int, int, str],
        instruccion: str,
    ) -> None:
        seleccion = contexto.user_data.get(CLAVE_IA)
        mensaje = actualizacion.effective_message
        if seleccion is None:
            await mensaje.reply_text("Primero envía /ia y elige modelo y esfuerzo.")
            return
        if self._tarea is not None and not self._tarea.done():
            await mensaje.reply_text(
                "Ya hay una tarea de IA en curso. Consulta /ia estado o usa /ia detener."
            )
            return
        modelo, esfuerzo = seleccion
        await self._gestor.registrar_ia(
            acceso[0], acceso[1], "iniciada", modelo.identificador, esfuerzo
        )
        await mensaje.reply_text(
            f"Codex está trabajando en esta máquina: {modelo.identificador} · {esfuerzo}. Puedes usar /ia detener."
        )
        self._tarea = asyncio.create_task(
            self._ejecutar(actualizacion, acceso, modelo, esfuerzo, instruccion)
        )

    async def _ejecutar(
        self,
        actualizacion: Update,
        acceso: tuple[int, int, str],
        modelo: ModeloCodex,
        esfuerzo: str,
        instruccion: str,
    ) -> None:
        estado = "completada"
        try:
            try:
                respuesta = await self._codex.ejecutar(modelo, esfuerzo, instruccion)
            except ErrorCodexLocal as error:
                estado = "error"
                respuesta = str(error)
            # Si se revocó el vínculo o el rol durante la tarea, no entrega la respuesta.
            await self._gestor.registrar_ia(
                acceso[0], acceso[1], estado, modelo.identificador, esfuerzo
            )
            mensaje = actualizacion.effective_message
            if len(respuesta) <= 3900:
                await mensaje.reply_text(respuesta)
            else:
                await mensaje.reply_document(
                    document=BytesIO(respuesta.encode("utf-8")),
                    filename="respuesta_codex.md",
                    caption="Respuesta de Codex CLI.",
                )
        except asyncio.CancelledError:
            with suppress(Exception):
                await self._gestor.registrar_ia(
                    acceso[0], acceso[1], "interrumpida", modelo.identificador, esfuerzo
                )
            raise
        except ErrorHermes:
            registrador.warning("La autorización de IA fue revocada durante la tarea.")
        except Exception:
            registrador.error("No se pudo completar o entregar una tarea de IA.")
