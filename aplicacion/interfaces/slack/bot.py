"""Adaptación de Slack Bolt hacia los casos de uso comunes de Hermes."""

import logging
import re
import secrets
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hmac import compare_digest
from time import monotonic
from typing import Any
from uuid import uuid4

from slack_bolt.async_app import AsyncApp

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorHermes, ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.esquemas.acciones import (
    ResultadoAccionMultipleRespuesta,
    ResultadoAccionRespuesta,
    SeleccionServidores,
    SolicitudEjecucionAccion,
    SolicitudEjecucionMultiple,
)
from aplicacion.interfaces.canal_mensajeria import CanalMensajeria
from aplicacion.interfaces.formateo_usuarios import (
    formatear_listado_usuarios,
    formatear_mutacion_usuario,
)
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.servicios.gestor_identidades_mensajeria import (
    construir_identificador_slack,
)
from aplicacion.servicios.gestor_slack import GestorSlack

registrador = logging.getLogger(__name__)
PATRON_IDENTIFICADOR_SLACK = re.compile(r"^[A-Z][A-Z0-9]{1,31}$")
LIMITE_TEXTO_COMANDO_SLACK = 500
LIMITE_MENSAJE_SLACK = 35_000
MAX_SOLICITUDES_SLACK_POR_MINUTO = 30
MAX_ESTADOS_SLACK = 5_000
TIEMPO_RETENCION_ESTADO_SEGUNDOS = 3_600
MAX_ID_SERVIDOR = 9_223_372_036_854_775_807
MAX_ID_PROCESO = 4_194_304

ResponderSlack = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class SolicitudSlack:
    """Identidad y conversación verificadas sintácticamente."""

    identificador_equipo: str
    identificador_usuario: str
    identificador_canal: str
    identificador_solicitud: str

    @property
    def identidad_externa(self) -> str:
        return construir_identificador_slack(
            self.identificador_equipo,
            self.identificador_usuario,
        )


@dataclass(frozen=True, slots=True)
class ConfirmacionSlack:
    """Desafío de un solo uso ligado a destinos ya fijados."""

    seleccion: SeleccionServidores
    codigo_accion: str
    solicitud: SolicitudEjecucionAccion
    codigo_aleatorio: str
    vence_en: float


@dataclass(slots=True)
class EstadoUsuarioSlack:
    """Estado efímero acotado por espacio de trabajo y usuario."""

    seleccion: SeleccionServidores | None = None
    confirmacion: ConfirmacionSlack | None = None
    solicitudes_recientes: deque[float] = field(default_factory=deque)
    ultimo_uso: float = field(default_factory=monotonic)


class InterfazSlack(CanalMensajeria):
    """Interpreta `/hermes` y botones sin duplicar lógica administrativa."""

    def __init__(self, gestor: GestorSlack, configuracion: Configuracion) -> None:
        self._gestor = gestor
        self._configuracion = configuracion
        self._aplicacion: AsyncApp | None = None
        self._estados: dict[str, EstadoUsuarioSlack] = {}

    def registrar(self, aplicacion: AsyncApp) -> None:
        """Registra un comando y dos acciones interactivas de alcance cerrado."""

        self._aplicacion = aplicacion
        aplicacion.command("/hermes")(self.recibir_comando)
        aplicacion.action("hermes_confirmar")(self.resolver_confirmacion)
        aplicacion.action("hermes_cancelar")(self.resolver_confirmacion)
        aplicacion.error(self.manejar_error)

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        """Envía una notificación futura mediante el cliente autenticado de Bolt."""

        if self._aplicacion is None:
            raise RuntimeError("La interfaz Slack todavía no está inicializada.")
        await self._aplicacion.client.chat_postMessage(
            channel=identificador_destino,
            text=mensaje[:LIMITE_MENSAJE_SLACK],
        )

    @staticmethod
    async def _responder(
        responder: ResponderSlack,
        texto: str,
        **opciones: object,
    ) -> None:
        await responder(
            text=texto[:LIMITE_MENSAJE_SLACK],
            response_type="ephemeral",
            **opciones,
        )

    @staticmethod
    def _cadena_identificador(valor: object) -> str | None:
        if not isinstance(valor, str):
            return None
        valor = valor.strip().upper()
        return valor if PATRON_IDENTIFICADOR_SLACK.fullmatch(valor) else None

    @classmethod
    def _extraer_solicitud_comando(cls, comando: object) -> SolicitudSlack | None:
        if not isinstance(comando, dict) or comando.get("command") != "/hermes":
            return None
        equipo = cls._cadena_identificador(comando.get("team_id"))
        usuario = cls._cadena_identificador(comando.get("user_id"))
        canal = cls._cadena_identificador(comando.get("channel_id"))
        if equipo is None or usuario is None or canal is None:
            return None
        return SolicitudSlack(equipo, usuario, canal, uuid4().hex)

    @classmethod
    def _extraer_solicitud_accion(cls, cuerpo: object) -> SolicitudSlack | None:
        if not isinstance(cuerpo, dict):
            return None
        equipo_datos = cuerpo.get("team")
        usuario_datos = cuerpo.get("user")
        canal_datos = cuerpo.get("channel")
        if not all(isinstance(datos, dict) for datos in (equipo_datos, usuario_datos, canal_datos)):
            return None
        equipo = cls._cadena_identificador(equipo_datos.get("id"))
        usuario = cls._cadena_identificador(usuario_datos.get("id"))
        canal = cls._cadena_identificador(canal_datos.get("id"))
        if equipo is None or usuario is None or canal is None:
            return None
        return SolicitudSlack(equipo, usuario, canal, uuid4().hex)

    def _obtener_estado(self, identidad: str) -> EstadoUsuarioSlack | None:
        ahora = monotonic()
        estado = self._estados.get(identidad)
        if estado is not None:
            estado.ultimo_uso = ahora
            return estado
        if len(self._estados) >= MAX_ESTADOS_SLACK:
            limite = ahora - TIEMPO_RETENCION_ESTADO_SEGUNDOS
            inactivos = [
                clave for clave, actual in self._estados.items() if actual.ultimo_uso < limite
            ]
            for clave in inactivos:
                self._estados.pop(clave, None)
        if len(self._estados) >= MAX_ESTADOS_SLACK:
            return None
        estado = EstadoUsuarioSlack()
        self._estados[identidad] = estado
        return estado

    @staticmethod
    def _admitir_solicitud(estado: EstadoUsuarioSlack) -> bool:
        ahora = monotonic()
        limite = ahora - 60
        while estado.solicitudes_recientes and estado.solicitudes_recientes[0] < limite:
            estado.solicitudes_recientes.popleft()
        if len(estado.solicitudes_recientes) >= MAX_SOLICITUDES_SLACK_POR_MINUTO:
            return False
        estado.solicitudes_recientes.append(ahora)
        return True

    async def _autorizar(
        self,
        solicitud: SolicitudSlack,
        responder: ResponderSlack,
    ) -> EstadoUsuarioSlack | None:
        if not solicitud.identificador_canal.startswith("D"):
            await self._responder(
                responder,
                "Por seguridad, Hermes solo atiende mensajes directos en Slack.",
            )
            return None
        estado = self._obtener_estado(solicitud.identidad_externa)
        if estado is None or not self._admitir_solicitud(estado):
            await self._responder(
                responder,
                "Se alcanzó el límite temporal de solicitudes. Inténtalo nuevamente en un minuto.",
            )
            return None
        try:
            await self._gestor.comprobar_acceso(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
            )
        except ErrorIdentidadMensajeriaNoAutorizada:
            await self._responder(
                responder,
                "Acceso denegado. Solicita la vinculación de estos identificadores: "
                f"equipo {solicitud.identificador_equipo}, "
                f"usuario {solicitud.identificador_usuario}.",
            )
            return None
        return estado

    @staticmethod
    def _convertir_entero(texto: str, maximo: int) -> int | None:
        if not texto.isascii() or not texto.isdigit() or len(texto) > len(str(maximo)):
            return None
        valor = int(texto)
        return valor if 1 <= valor <= maximo else None

    @staticmethod
    def _texto_ayuda() -> str:
        return (
            "Uso: /hermes <subcomando> [parámetros]\n"
            "ayuda · servidores · grupos · seleccionar <id> · "
            "seleccionar_grupo <id> · seleccionar_todos · seleccion\n"
            "diagnostico · identidad · proceso <id> · servicio <nombre>\n"
            "iniciar_servicio <nombre> · detener_servicio <nombre> · "
            "reiniciar_servicio <nombre> · usuarios · crear_usuario <cuenta> [nombre]\n"
            "agregar_grupo <cuenta> <grupo> · quitar_grupo <cuenta> <grupo> · "
            "bloquear_usuario <cuenta> · desbloquear_usuario <cuenta> · "
            "eliminar_usuario <cuenta> · archivo_info <ruta> · "
            "descargar_archivo <ruta> · reiniciar · cancelar"
        )

    async def recibir_comando(
        self,
        ack: ResponderSlack,
        command: dict[str, Any],
        respond: ResponderSlack,
    ) -> None:
        """Confirma la recepción antes de consultar base de datos o SSH."""

        await ack()
        solicitud = self._extraer_solicitud_comando(command)
        if solicitud is None:
            await self._responder(respond, "La solicitud de Slack no tiene un formato válido.")
            return
        texto = command.get("text", "")
        if not isinstance(texto, str) or len(texto) > LIMITE_TEXTO_COMANDO_SLACK:
            await self._responder(respond, "El comando supera el tamaño permitido.")
            return
        partes = texto.strip().split()
        subcomando = partes[0].lower() if partes else "ayuda"
        argumentos = partes[1:]
        estado = await self._autorizar(solicitud, respond)
        if estado is None:
            return
        await self._despachar(subcomando, argumentos, solicitud, estado, respond)

    async def _despachar(
        self,
        subcomando: str,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        if subcomando in {"ayuda", "inicio"} and not argumentos:
            await self._responder(responder, self._texto_ayuda())
        elif subcomando == "servidores" and not argumentos:
            await self._mostrar_servidores(solicitud, responder)
        elif subcomando == "grupos" and not argumentos:
            await self._mostrar_grupos(solicitud, responder)
        elif subcomando == "seleccionar":
            await self._seleccionar_servidor(argumentos, solicitud, estado, responder)
        elif subcomando == "seleccionar_grupo":
            await self._seleccionar_grupo(argumentos, solicitud, estado, responder)
        elif subcomando == "seleccionar_todos" and not argumentos:
            await self._seleccionar_todos(solicitud, estado, responder)
        elif subcomando == "seleccion" and not argumentos:
            await self._mostrar_seleccion(solicitud, estado, responder)
        elif subcomando in {"diagnostico", "identidad"} and not argumentos:
            codigo = "obtener_diagnostico" if subcomando == "diagnostico" else "obtener_identidad"
            await self._ejecutar_accion(
                solicitud,
                estado,
                codigo,
                SolicitudEjecucionAccion(),
                responder,
            )
        elif subcomando == "proceso":
            await self._consultar_proceso(argumentos, solicitud, estado, responder)
        elif subcomando == "servicio":
            await self._consultar_servicio(argumentos, solicitud, estado, responder)
        elif subcomando == "usuarios" and not argumentos:
            await self._ejecutar_accion(
                solicitud,
                estado,
                "listar_usuarios_sistema",
                SolicitudEjecucionAccion(),
                responder,
            )
        elif subcomando == "archivo_info":
            await self._consultar_archivo(argumentos, solicitud, estado, responder)
        elif subcomando == "descargar_archivo":
            await self._descargar_archivo(argumentos, solicitud, estado, responder)
        elif subcomando == "crear_usuario":
            await self._crear_usuario_sistema(argumentos, solicitud, estado, responder)
        elif subcomando in {"agregar_grupo", "quitar_grupo"}:
            await self._cambiar_grupo_usuario(
                subcomando,
                argumentos,
                solicitud,
                estado,
                responder,
            )
        elif subcomando in {
            "bloquear_usuario",
            "desbloquear_usuario",
            "eliminar_usuario",
        }:
            await self._cambiar_estado_usuario(
                subcomando,
                argumentos,
                solicitud,
                estado,
                responder,
            )
        elif subcomando in {
            "iniciar_servicio",
            "detener_servicio",
            "reiniciar_servicio",
        }:
            await self._solicitar_servicio(
                subcomando,
                argumentos,
                solicitud,
                estado,
                responder,
            )
        elif subcomando == "reiniciar" and not argumentos:
            await self._solicitar_accion_sensible(
                solicitud,
                estado,
                "reiniciar_servidor",
                SolicitudEjecucionAccion(),
                "reiniciar la selección",
                responder,
            )
        elif subcomando == "cancelar" and not argumentos:
            habia_confirmacion = estado.confirmacion is not None
            estado.confirmacion = None
            texto = (
                "Confirmación cancelada."
                if habia_confirmacion
                else "No hay confirmaciones pendientes."
            )
            await self._responder(responder, texto)
        else:
            await self._responder(
                responder,
                "Subcomando no reconocido o parámetros incorrectos. Usa `/hermes ayuda`.",
            )

    @staticmethod
    def _id_servidor_archivos(estado: EstadoUsuarioSlack) -> int | None:
        seleccion = estado.seleccion
        ids = seleccion.ids_servidores if seleccion is not None else None
        return ids[0] if ids is not None and len(ids) == 1 else None

    async def _consultar_archivo(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        ruta = " ".join(argumentos).strip()
        id_servidor = self._id_servidor_archivos(estado)
        if id_servidor is None:
            await self._responder(responder, "Selecciona un único servidor para administrar archivos.")
            return
        if not ruta:
            await self._responder(responder, "Uso correcto: `/hermes archivo_info <ruta>`.")
            return
        try:
            informacion = await self._gestor.consultar_informacion_archivo(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
                id_servidor,
                ruta,
            )
        except ErrorHermes as error:
            await self._responder(responder, f"No fue posible consultar el archivo: {error.mensaje}")
            return
        await self._responder(
            responder,
            f"Servidor: {informacion.nombre_servidor}\n"
            f"Archivo: {informacion.nombre_archivo}\n"
            f"Tipo: {informacion.tipo}\n"
            f"Tamaño: {informacion.tamano_bytes if informacion.tamano_bytes is not None else 'No disponible'} bytes",
        )

    async def _descargar_archivo(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        ruta = " ".join(argumentos).strip()
        id_servidor = self._id_servidor_archivos(estado)
        if id_servidor is None:
            await self._responder(responder, "Selecciona un único servidor para administrar archivos.")
            return
        if not ruta:
            await self._responder(responder, "Uso correcto: `/hermes descargar_archivo <ruta>`.")
            return
        if self._aplicacion is None:
            await self._responder(responder, "La entrega de archivos de Slack no está inicializada.")
            return
        try:
            descarga = await self._gestor.descargar_archivo(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
                id_servidor,
                ruta,
            )
        except ErrorHermes as error:
            await self._responder(responder, f"No fue posible descargar el archivo: {error.mensaje}")
            return
        await self._aplicacion.client.files_upload_v2(
            channel=solicitud.identificador_canal,
            filename=descarga.nombre_archivo,
            content=descarga.contenido,
            title=descarga.nombre_archivo,
            initial_comment="Archivo descargado de forma segura por Hermes.",
        )
        await self._responder(responder, "El archivo se envió en esta conversación directa.")

    async def _mostrar_servidores(
        self,
        solicitud: SolicitudSlack,
        responder: ResponderSlack,
    ) -> None:
        try:
            servidores = await self._gestor.consultar_servidores(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
            )
        except ErrorHermes as error:
            await self._responder(
                responder, f"No fue posible consultar servidores: {error.mensaje}"
            )
            return
        if not servidores:
            await self._responder(responder, "No hay servidores activos disponibles.")
            return
        lineas = [
            f"{servidor.id_servidor} · {servidor.nombre} · {servidor.sistema_operativo.value}"
            for servidor in servidores
        ]
        await self._responder(responder, "Servidores activos:\n" + "\n".join(lineas))

    async def _mostrar_grupos(
        self,
        solicitud: SolicitudSlack,
        responder: ResponderSlack,
    ) -> None:
        try:
            grupos = await self._gestor.consultar_grupos(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
            )
        except ErrorHermes as error:
            await self._responder(responder, f"No fue posible consultar grupos: {error.mensaje}")
            return
        if not grupos:
            await self._responder(responder, "No hay grupos registrados.")
            return
        lineas = [
            f"{grupo.id_grupo} · {grupo.nombre} · {len(grupo.servidores)} servidor(es)"
            for grupo in grupos
        ]
        await self._responder(responder, "Grupos registrados:\n" + "\n".join(lineas))

    async def _seleccionar_servidor(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        id_servidor = (
            self._convertir_entero(argumentos[0], MAX_ID_SERVIDOR) if len(argumentos) == 1 else None
        )
        if id_servidor is None:
            await self._responder(responder, "Uso correcto: `/hermes seleccionar <id>`.")
            return
        try:
            servidor = await self._gestor.consultar_servidor(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
                id_servidor,
            )
        except ErrorHermes as error:
            await self._responder(responder, f"No fue posible seleccionar: {error.mensaje}")
            return
        estado.seleccion = SeleccionServidores(ids_servidores=[servidor.id_servidor])
        estado.confirmacion = None
        await self._responder(
            responder,
            f"Servidor seleccionado: {servidor.nombre} (id {servidor.id_servidor}).",
        )

    async def _seleccionar_grupo(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        id_grupo = (
            self._convertir_entero(argumentos[0], MAX_ID_SERVIDOR) if len(argumentos) == 1 else None
        )
        if id_grupo is None:
            await self._responder(responder, "Uso correcto: `/hermes seleccionar_grupo <id>`.")
            return
        seleccion = SeleccionServidores(id_grupo=id_grupo)
        try:
            cantidad = await self._gestor.comprobar_seleccion_multiple(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
                seleccion,
            )
        except ErrorHermes as error:
            await self._responder(responder, f"No fue posible seleccionar: {error.mensaje}")
            return
        estado.seleccion = seleccion
        estado.confirmacion = None
        await self._responder(
            responder,
            f"Grupo seleccionado: id {id_grupo}, {cantidad} servidor(es).",
        )

    async def _seleccionar_todos(
        self,
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        seleccion = SeleccionServidores(todos=True)
        try:
            cantidad = await self._gestor.comprobar_seleccion_multiple(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
                seleccion,
            )
        except ErrorHermes as error:
            await self._responder(responder, f"No fue posible seleccionar: {error.mensaje}")
            return
        estado.seleccion = seleccion
        estado.confirmacion = None
        await self._responder(
            responder,
            f"Selección activa: todos los servidores activos ({cantidad}).",
        )

    async def _mostrar_seleccion(
        self,
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        seleccion = estado.seleccion
        if seleccion is None:
            await self._responder(responder, "No hay servidores seleccionados.")
            return
        ids = seleccion.ids_servidores
        if ids is not None and len(ids) == 1:
            try:
                servidor = await self._gestor.consultar_servidor(
                    solicitud.identidad_externa,
                    solicitud.identificador_solicitud,
                    ids[0],
                )
            except ErrorHermes as error:
                estado.seleccion = None
                await self._responder(
                    responder,
                    f"La selección dejó de estar disponible: {error.mensaje}",
                )
                return
            await self._responder(
                responder,
                f"Servidor: {servidor.nombre}\nIdentificador: {servidor.id_servidor}\n"
                f"Sistema: {servidor.sistema_operativo.value}",
            )
            return
        try:
            cantidad = await self._gestor.comprobar_seleccion_multiple(
                solicitud.identidad_externa,
                solicitud.identificador_solicitud,
                seleccion,
            )
        except ErrorHermes as error:
            estado.seleccion = None
            await self._responder(
                responder,
                f"La selección dejó de estar disponible: {error.mensaje}",
            )
            return
        descripcion = (
            f"Grupo seleccionado: id {seleccion.id_grupo}"
            if seleccion.id_grupo is not None
            else "Todos los servidores activos"
        )
        await self._responder(responder, f"{descripcion}\nServidores incluidos ahora: {cantidad}.")

    async def _consultar_proceso(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        id_proceso = (
            self._convertir_entero(argumentos[0], MAX_ID_PROCESO) if len(argumentos) == 1 else None
        )
        if id_proceso is None:
            await self._responder(responder, "Uso correcto: `/hermes proceso <id>`.")
            return
        await self._ejecutar_accion(
            solicitud,
            estado,
            "consultar_proceso",
            SolicitudEjecucionAccion(parametros={"id_proceso": id_proceso}),
            responder,
        )

    async def _consultar_servicio(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        if len(argumentos) != 1:
            await self._responder(responder, "Uso correcto: `/hermes servicio <nombre>`.")
            return
        await self._ejecutar_accion(
            solicitud,
            estado,
            "consultar_servicio",
            SolicitudEjecucionAccion(parametros={"nombre_servicio": argumentos[0]}),
            responder,
        )

    async def _crear_usuario_sistema(
        self,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        if not argumentos:
            await self._responder(
                responder,
                "Uso correcto: `/hermes crear_usuario <cuenta> [nombre para mostrar]`.",
            )
            return
        nombre_usuario = argumentos[0]
        nombre_mostrar = " ".join(argumentos[1:]) or None
        await self._solicitar_accion_sensible(
            solicitud,
            estado,
            "crear_usuario_sistema",
            SolicitudEjecucionAccion(
                parametros={
                    "nombre_usuario": nombre_usuario,
                    "nombre_mostrar": nombre_mostrar,
                }
            ),
            f"crear la cuenta local {nombre_usuario}, inicialmente deshabilitada",
            responder,
        )

    async def _cambiar_grupo_usuario(
        self,
        subcomando: str,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        if len(argumentos) < 2:
            await self._responder(
                responder,
                f"Uso correcto: `/hermes {subcomando} <cuenta> <grupo>`.",
            )
            return
        operacion = "agregar" if subcomando == "agregar_grupo" else "quitar"
        nombre_usuario = argumentos[0]
        nombre_grupo = " ".join(argumentos[1:])
        await self._solicitar_accion_sensible(
            solicitud,
            estado,
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
            responder,
        )

    async def _cambiar_estado_usuario(
        self,
        subcomando: str,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        if len(argumentos) != 1:
            await self._responder(
                responder,
                f"Uso correcto: `/hermes {subcomando} <cuenta>`.",
            )
            return
        configuraciones = {
            "bloquear_usuario": ("bloquear_usuario_sistema", "bloquear"),
            "desbloquear_usuario": ("desbloquear_usuario_sistema", "habilitar"),
            "eliminar_usuario": (
                "eliminar_usuario_sistema",
                "eliminar junto con su directorio de usuario",
            ),
        }
        codigo_accion, verbo = configuraciones[subcomando]
        nombre_usuario = argumentos[0]
        await self._solicitar_accion_sensible(
            solicitud,
            estado,
            codigo_accion,
            SolicitudEjecucionAccion(
                parametros={
                    "nombre_usuario": nombre_usuario,
                    "autorizar_cuenta_protegida": False,
                }
            ),
            f"{verbo} la cuenta local {nombre_usuario}",
            responder,
        )

    async def _ejecutar_accion(
        self,
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion,
        responder: ResponderSlack,
    ) -> None:
        seleccion = estado.seleccion
        if seleccion is None:
            await self._responder(
                responder,
                "Selecciona primero un servidor, un grupo o todos los servidores.",
            )
            return
        try:
            ids = seleccion.ids_servidores
            if ids is not None and len(ids) == 1:
                resultado = await self._gestor.ejecutar_accion(
                    solicitud.identidad_externa,
                    solicitud.identificador_solicitud,
                    ids[0],
                    codigo_accion,
                    datos,
                )
                if resultado.accion.value == "listar_usuarios_sistema":
                    for texto in formatear_listado_usuarios(
                        resultado.nombre_servidor,
                        resultado.sistema_operativo,
                        resultado.datos,
                        LIMITE_MENSAJE_SLACK,
                    ):
                        await self._responder(responder, texto)
                else:
                    await self._responder(responder, self._formatear_resultado(resultado))
            else:
                resultado_multiple = await self._gestor.ejecutar_accion_multiple(
                    solicitud.identidad_externa,
                    solicitud.identificador_solicitud,
                    codigo_accion,
                    SolicitudEjecucionMultiple(
                        seleccion=seleccion,
                        parametros=datos.parametros,
                        confirmar=datos.confirmar,
                    ),
                )
                for texto in self._formatear_resultado_multiple(resultado_multiple):
                    await self._responder(responder, texto)
        except ErrorHermes as error:
            await self._responder(responder, f"La operación no se completó: {error.mensaje}")

    @staticmethod
    def _formatear_sistema(sistema: SistemaOperativo) -> str:
        return "Linux" if sistema is SistemaOperativo.LINUX else "Windows Server"

    def _formatear_resultado(self, resultado: ResultadoAccionRespuesta) -> str:
        encabezado = (
            f"Servidor: {resultado.nombre_servidor}\n"
            f"Sistema: {self._formatear_sistema(resultado.sistema_operativo)}\n"
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
        if resultado.accion.value == "obtener_diagnostico":
            return (
                encabezado
                + f"Estado: Disponible\nCPU: {resultado.datos.get('cpu_porcentaje')} %\n"
                + f"RAM: {resultado.datos.get('memoria_porcentaje')} %\n"
                + f"Disco: {resultado.datos.get('disco_porcentaje')} %"
            )
        if resultado.accion.value.endswith("servicio"):
            return (
                encabezado
                + f"Servicio: {resultado.datos.get('nombre_servicio')}\n"
                + f"Estado: {resultado.datos.get('estado')}\n"
                + f"Operación: {resultado.datos.get('accion_realizada')}"
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
        return encabezado + "Reinicio programado en 60 segundos."

    @staticmethod
    def _formatear_resultado_multiple(
        resultado: ResultadoAccionMultipleRespuesta,
    ) -> list[str]:
        encabezado = (
            f"Acción múltiple: {resultado.accion.value}\n"
            f"Completados: {resultado.servidores_completados} · "
            f"Fallidos: {resultado.servidores_fallidos}\n"
        )
        lineas = []
        for elemento in resultado.resultados:
            nombre = elemento.nombre_servidor or f"id {elemento.id_servidor}"
            if elemento.estado == "error":
                linea = f"ERROR · {nombre}: {elemento.mensaje_error}"
            elif resultado.accion.value == "listar_usuarios_sistema" and elemento.datos:
                linea = f"OK · {nombre}: {elemento.datos.get('total_usuarios', 0)} usuario(s)"
            elif resultado.accion.value.endswith("usuario_sistema") and elemento.datos:
                linea = (
                    f"OK · {nombre}: cuenta "
                    f"{elemento.datos.get('nombre_usuario', 'no disponible')}, "
                    f"{elemento.datos.get('estado', 'desconocido')}"
                )
            else:
                linea = f"OK · {nombre}: completada"
            lineas.append(linea)
        mensajes: list[str] = []
        actual = encabezado
        for linea in lineas:
            candidato = f"{actual}\n{linea}"
            if len(candidato) > LIMITE_MENSAJE_SLACK and actual != encabezado:
                mensajes.append(actual)
                actual = f"Continuación:\n{linea}"
            else:
                actual = candidato
        mensajes.append(actual)
        return mensajes

    async def _solicitar_servicio(
        self,
        codigo_accion: str,
        argumentos: list[str],
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        responder: ResponderSlack,
    ) -> None:
        if len(argumentos) != 1:
            await self._responder(
                responder,
                f"Uso correcto: `/hermes {codigo_accion} <nombre>`.",
            )
            return
        await self._solicitar_accion_sensible(
            solicitud,
            estado,
            codigo_accion,
            SolicitudEjecucionAccion(parametros={"nombre_servicio": argumentos[0]}),
            f"{codigo_accion.replace('_', ' ')} {argumentos[0]}",
            responder,
        )

    async def _solicitar_accion_sensible(
        self,
        solicitud: SolicitudSlack,
        estado: EstadoUsuarioSlack,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion,
        descripcion: str,
        responder: ResponderSlack,
    ) -> None:
        seleccion = estado.seleccion
        if seleccion is None:
            await self._responder(responder, "Selecciona primero uno o más servidores.")
            return
        try:
            ids = seleccion.ids_servidores
            if ids is not None and len(ids) == 1:
                servidor = await self._gestor.comprobar_accion_sensible(
                    solicitud.identidad_externa,
                    solicitud.identificador_solicitud,
                    ids[0],
                    codigo_accion,
                    datos,
                )
                seleccion_fijada = SeleccionServidores(ids_servidores=[servidor.id_servidor])
                destino = servidor.nombre
            else:
                seleccion_fijada, cantidad = await self._gestor.comprobar_accion_sensible_multiple(
                    solicitud.identidad_externa,
                    solicitud.identificador_solicitud,
                    codigo_accion,
                    SolicitudEjecucionMultiple(
                        seleccion=seleccion,
                        parametros=datos.parametros,
                    ),
                )
                destino = f"{cantidad} servidores"
        except ErrorHermes as error:
            await self._responder(
                responder,
                f"No se puede solicitar la operación: {error.mensaje}",
            )
            return
        codigo_aleatorio = secrets.token_urlsafe(12)
        estado.confirmacion = ConfirmacionSlack(
            seleccion=seleccion_fijada,
            codigo_accion=codigo_accion,
            solicitud=datos,
            codigo_aleatorio=codigo_aleatorio,
            vence_en=monotonic() + self._configuracion.tiempo_confirmacion_slack_segundos,
        )
        bloques = [
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": f"¿Confirmas {descripcion} en {destino}?",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Confirmar"},
                        "style": "danger",
                        "action_id": "hermes_confirmar",
                        "value": codigo_aleatorio,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Cancelar"},
                        "action_id": "hermes_cancelar",
                        "value": codigo_aleatorio,
                    },
                ],
            },
        ]
        await self._responder(
            responder,
            f"Confirma la operación sobre {destino}.",
            blocks=bloques,
        )

    async def resolver_confirmacion(
        self,
        ack: ResponderSlack,
        body: dict[str, Any],
        respond: ResponderSlack,
    ) -> None:
        """Reconoce primero el botón y luego valida identidad y desafío."""

        await ack()
        solicitud = self._extraer_solicitud_accion(body)
        acciones = body.get("actions") if isinstance(body, dict) else None
        accion = acciones[0] if isinstance(acciones, list) and len(acciones) == 1 else None
        if solicitud is None or not isinstance(accion, dict):
            await self._responder(respond, "La confirmación recibida no es válida.")
            return
        id_accion = accion.get("action_id")
        codigo = accion.get("value")
        if id_accion not in {"hermes_confirmar", "hermes_cancelar"} or not isinstance(codigo, str):
            await self._responder(respond, "La confirmación recibida no es válida.")
            return
        estado = await self._autorizar(solicitud, respond)
        if estado is None:
            return
        pendiente = estado.confirmacion
        estado.confirmacion = None
        if (
            pendiente is None
            or monotonic() > pendiente.vence_en
            or not compare_digest(codigo, pendiente.codigo_aleatorio)
        ):
            await self._responder(
                respond,
                "La confirmación no es válida o ha caducado.",
                replace_original=True,
            )
            return
        if id_accion == "hermes_cancelar":
            await self._responder(respond, "Operación cancelada.", replace_original=True)
            return
        await self._responder(respond, "Confirmación aceptada.", replace_original=True)
        estado.seleccion = pendiente.seleccion
        await self._ejecutar_accion(
            solicitud,
            estado,
            pendiente.codigo_accion,
            pendiente.solicitud.model_copy(update={"confirmar": True}),
            respond,
        )

    async def manejar_error(self, error: Exception) -> None:
        """Registra solo el tipo para no copiar payloads ni tokens."""

        registrador.error(
            "La interfaz Slack encontró un error controlado por su límite. tipo=%s",
            type(error).__name__,
        )


def crear_aplicacion_slack(
    configuracion: Configuracion,
    gestor: GestorSlack,
) -> AsyncApp:
    """Construye Bolt asíncrono para usarse exclusivamente mediante Socket Mode."""

    if not configuracion.slack_habilitado or configuracion.token_bot_slack is None:
        raise RuntimeError("La interfaz Slack no está habilitada en la configuración.")
    aplicacion = AsyncApp(token=configuracion.token_bot_slack.get_secret_value())
    interfaz = InterfazSlack(gestor, configuracion)
    interfaz.registrar(aplicacion)
    return aplicacion
