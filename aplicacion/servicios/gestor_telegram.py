"""Fachada del backend utilizada por la interfaz Telegram."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aplicacion.acciones.registro import obtener_definicion_accion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorServidorInactivo
from aplicacion.esquemas.acciones import ResultadoAccionRespuesta, SolicitudEjecucionAccion
from aplicacion.esquemas.inventario import ServidorResumen
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import CanalAuditoria, TipoCanalMensajeria
from aplicacion.seguridad.autenticacion import comprobar_permiso_usuario
from aplicacion.servicios.auditoria import ContextoAuditoria
from aplicacion.servicios.gestor_acciones import ejecutar_accion_servidor
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto
from aplicacion.servicios.gestor_identidades_mensajeria import obtener_usuario_por_identidad
from aplicacion.servicios.gestor_inventario import listar_servidores, obtener_servidor


class GestorTelegram:
    """Expone casos de uso comunes sin incluir objetos propios de Telegram."""

    def __init__(
        self,
        fabrica_sesiones: async_sessionmaker[AsyncSession],
        fabrica_transporte: FabricaTransporteRemoto,
        configuracion: Configuracion,
    ) -> None:
        self._fabrica_sesiones = fabrica_sesiones
        self._fabrica_transporte = fabrica_transporte
        self._configuracion = configuracion

    @staticmethod
    def crear_contexto(
        identificador_telegram: int,
        identificador_actualizacion: int,
    ) -> ContextoAuditoria:
        """Convierte identificadores numéricos en metadatos de auditoría acotados."""

        return ContextoAuditoria(
            canal=CanalAuditoria.TELEGRAM,
            direccion_origen=f"telegram:{identificador_telegram}",
            identificador_solicitud=f"tg:{identificador_actualizacion}",
        )

    async def _autenticar(
        self,
        sesion: AsyncSession,
        identificador_telegram: int,
        contexto: ContextoAuditoria,
    ) -> Usuario:
        return await obtener_usuario_por_identidad(
            sesion,
            TipoCanalMensajeria.TELEGRAM,
            str(identificador_telegram),
            contexto,
        )

    async def comprobar_acceso(
        self,
        identificador_telegram: int,
        identificador_actualizacion: int,
    ) -> str:
        """Comprueba el vínculo en cada interacción y devuelve el nombre visible."""

        contexto = self.crear_contexto(identificador_telegram, identificador_actualizacion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_telegram, contexto)
            return usuario.nombre_mostrar

    async def consultar_servidores(
        self,
        identificador_telegram: int,
        identificador_actualizacion: int,
    ) -> list[ServidorResumen]:
        """Lista servidores activos después de autenticar y autorizar."""

        contexto = self.crear_contexto(identificador_telegram, identificador_actualizacion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_telegram, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                "consultar_inventario",
                contexto,
            )
            servidores = await listar_servidores(
                sesion,
                desplazamiento=0,
                limite=self._configuracion.max_servidores_mostrados_telegram,
                solo_activos=True,
            )
            return [ServidorResumen.model_validate(servidor) for servidor in servidores]

    async def consultar_servidor(
        self,
        identificador_telegram: int,
        identificador_actualizacion: int,
        id_servidor: int,
    ) -> ServidorResumen:
        """Valida que el servidor seleccionado exista, esté activo y sea visible."""

        contexto = self.crear_contexto(identificador_telegram, identificador_actualizacion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_telegram, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                "consultar_inventario",
                contexto,
            )
            servidor = await obtener_servidor(sesion, id_servidor)
            if not servidor.activo:
                raise ErrorServidorInactivo()
            return ServidorResumen.model_validate(servidor)

    async def ejecutar_accion(
        self,
        identificador_telegram: int,
        identificador_actualizacion: int,
        id_servidor: int,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion,
    ) -> ResultadoAccionRespuesta:
        """Delega en el mismo motor usado por la API y conserva el canal Telegram."""

        contexto = self.crear_contexto(identificador_telegram, identificador_actualizacion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_telegram, contexto)
            return await ejecutar_accion_servidor(
                sesion,
                id_servidor,
                codigo_accion,
                datos,
                usuario,
                None,
                self._fabrica_transporte,
                self._configuracion,
                contexto,
            )

    async def comprobar_accion_sensible(
        self,
        identificador_telegram: int,
        identificador_actualizacion: int,
        id_servidor: int,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion | None = None,
    ) -> ServidorResumen:
        """Autoriza y valida una acción antes de mostrar su confirmación."""

        contexto = self.crear_contexto(identificador_telegram, identificador_actualizacion)
        definicion = obtener_definicion_accion(codigo_accion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_telegram, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                definicion.codigo_permiso,
                contexto,
            )
            definicion.validar_parametros((datos or SolicitudEjecucionAccion()).parametros)
            servidor = await obtener_servidor(sesion, id_servidor)
            if not servidor.activo:
                raise ErrorServidorInactivo()
            return ServidorResumen.model_validate(servidor)
