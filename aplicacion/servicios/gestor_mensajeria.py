"""Fachada común del backend para interfaces de mensajería."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aplicacion.acciones.registro import obtener_definicion_accion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorServidorInactivo
from aplicacion.esquemas.acciones import (
    ResultadoAccionMultipleRespuesta,
    ResultadoAccionRespuesta,
    SeleccionServidores,
    SolicitudEjecucionAccion,
    SolicitudEjecucionMultiple,
)
from aplicacion.esquemas.archivos import (
    CargaArchivoRespuesta,
    DescargaArchivo,
    InformacionArchivoRespuesta,
)
from aplicacion.esquemas.inventario import GrupoDetalle, ServidorResumen
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import CanalAuditoria, TipoCanalMensajeria
from aplicacion.seguridad.autenticacion import comprobar_permiso_usuario
from aplicacion.servicios import gestor_archivos
from aplicacion.servicios.auditoria import ContextoAuditoria
from aplicacion.servicios.gestor_acciones import (
    comprobar_permisos_adicionales_accion,
    ejecutar_accion_servidor,
)
from aplicacion.servicios.gestor_acciones_multiples import (
    ejecutar_accion_multiple,
    resolver_objetivos_accion_multiple,
)
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto
from aplicacion.servicios.gestor_identidades_mensajeria import obtener_usuario_por_identidad
from aplicacion.servicios.gestor_inventario import (
    listar_grupos,
    listar_servidores,
    obtener_servidor,
)


class GestorMensajeria:
    """Expone casos de uso comunes sin incluir objetos propios de cada canal."""

    def __init__(
        self,
        fabrica_sesiones: async_sessionmaker[AsyncSession],
        fabrica_transporte: FabricaTransporteRemoto,
        configuracion: Configuracion,
        tipo_canal: TipoCanalMensajeria,
        canal_auditoria: CanalAuditoria,
        prefijo_solicitud: str,
        max_servidores_mostrados: int,
    ) -> None:
        self._fabrica_sesiones = fabrica_sesiones
        self._fabrica_transporte = fabrica_transporte
        self._configuracion = configuracion
        self._tipo_canal = tipo_canal
        self._canal_auditoria = canal_auditoria
        self._prefijo_solicitud = prefijo_solicitud
        self._max_servidores_mostrados = max_servidores_mostrados

    def crear_contexto(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
    ) -> ContextoAuditoria:
        """Convierte identificadores externos en metadatos de auditoría acotados."""

        return ContextoAuditoria(
            canal=self._canal_auditoria,
            direccion_origen=(f"{self._tipo_canal.value}:{identificador_externo}")[:45],
            identificador_solicitud=(f"{self._prefijo_solicitud}:{identificador_evento}")[:36],
        )

    async def _autenticar(
        self,
        sesion: AsyncSession,
        identificador_externo: str | int,
        contexto: ContextoAuditoria,
    ) -> Usuario:
        return await obtener_usuario_por_identidad(
            sesion,
            self._tipo_canal,
            str(identificador_externo),
            contexto,
        )

    async def comprobar_acceso(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
    ) -> str:
        """Comprueba el vínculo en cada interacción y devuelve el nombre visible."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            return usuario.nombre_mostrar

    async def consultar_servidores(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
    ) -> list[ServidorResumen]:
        """Lista servidores activos después de autenticar y autorizar."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
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
                limite=self._max_servidores_mostrados,
                solo_activos=True,
            )
            return [ServidorResumen.model_validate(servidor) for servidor in servidores]

    async def consultar_servidor(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        id_servidor: int,
    ) -> ServidorResumen:
        """Valida que el servidor seleccionado exista, esté activo y sea visible."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
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

    async def consultar_grupos(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
    ) -> list[GrupoDetalle]:
        """Lista grupos después de aplicar autenticación y permiso de inventario."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                "consultar_inventario",
                contexto,
            )
            grupos = await listar_grupos(
                sesion,
                desplazamiento=0,
                limite=self._max_servidores_mostrados,
            )
            return [GrupoDetalle.model_validate(grupo) for grupo in grupos]

    async def comprobar_seleccion_multiple(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        seleccion: SeleccionServidores,
    ) -> int:
        """Valida una selección dinámica antes de conservarla en la conversación."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                "consultar_inventario",
                contexto,
            )
            objetivos = await resolver_objetivos_accion_multiple(
                sesion,
                seleccion,
                self._configuracion.max_servidores_accion_multiple,
            )
            return len(objetivos)

    async def ejecutar_accion(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        id_servidor: int,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion,
    ) -> ResultadoAccionRespuesta:
        """Delega en el motor común y conserva el canal de origen."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
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

    async def ejecutar_accion_multiple(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        codigo_accion: str,
        datos: SolicitudEjecucionMultiple,
    ) -> ResultadoAccionMultipleRespuesta:
        """Reutiliza el orquestador común y conserva el canal en cada auditoría."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            return await ejecutar_accion_multiple(
                sesion,
                self._fabrica_sesiones,
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
        identificador_externo: str | int,
        identificador_evento: str | int,
        id_servidor: int,
        codigo_accion: str,
        datos: SolicitudEjecucionAccion | None = None,
    ) -> ServidorResumen:
        """Autoriza y valida una acción antes de mostrar su confirmación."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        definicion = obtener_definicion_accion(codigo_accion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                definicion.codigo_permiso,
                contexto,
            )
            parametros = definicion.validar_parametros(
                (datos or SolicitudEjecucionAccion()).parametros
            )
            await comprobar_permisos_adicionales_accion(
                sesion,
                None,
                usuario,
                definicion,
                parametros,
                contexto,
            )
            servidor = await obtener_servidor(sesion, id_servidor)
            if not servidor.activo:
                raise ErrorServidorInactivo()
            return ServidorResumen.model_validate(servidor)

    async def comprobar_accion_sensible_multiple(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        codigo_accion: str,
        datos: SolicitudEjecucionMultiple,
    ) -> tuple[SeleccionServidores, int]:
        """Autoriza una acción sensible y fija sus miembros antes de confirmar."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        definicion = obtener_definicion_accion(codigo_accion)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(
                sesion,
                None,
                usuario,
                definicion.codigo_permiso,
                contexto,
            )
            parametros = definicion.validar_parametros(datos.parametros)
            await comprobar_permisos_adicionales_accion(
                sesion,
                None,
                usuario,
                definicion,
                parametros,
                contexto,
            )
            objetivos = await resolver_objetivos_accion_multiple(
                sesion,
                datos.seleccion,
                self._configuracion.max_servidores_accion_multiple,
            )
            seleccion_fijada = SeleccionServidores(
                ids_servidores=[objetivo.id_servidor for objetivo in objetivos]
            )
            return seleccion_fijada, len(objetivos)

    async def consultar_informacion_archivo(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        id_servidor: int,
        ruta_remota: str,
    ) -> InformacionArchivoRespuesta:
        """Autoriza y delega una consulta SFTP al backend común."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(sesion, None, usuario, "consultar_archivos", contexto)
            return await gestor_archivos.consultar_informacion_archivo(
                sesion,
                id_servidor,
                ruta_remota,
                usuario,
                self._fabrica_transporte,
                self._configuracion,
                contexto=contexto,
            )

    async def descargar_archivo(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        id_servidor: int,
        ruta_remota: str,
    ) -> DescargaArchivo:
        """Autoriza una descarga y conserva el canal en auditoría."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(sesion, None, usuario, "descargar_archivos", contexto)
            return await gestor_archivos.descargar_archivo(
                sesion,
                id_servidor,
                ruta_remota,
                usuario,
                self._fabrica_transporte,
                self._configuracion,
                contexto=contexto,
            )

    async def cargar_archivo(
        self,
        identificador_externo: str | int,
        identificador_evento: str | int,
        id_servidor: int,
        ruta_remota: str,
        contenido: bytes,
    ) -> CargaArchivoRespuesta:
        """Carga con creación exclusiva; mensajería nunca sobrescribe implícitamente."""

        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            await comprobar_permiso_usuario(sesion, None, usuario, "cargar_archivos", contexto)
            return await gestor_archivos.cargar_archivo(
                sesion,
                id_servidor,
                ruta_remota,
                contenido,
                False,
                usuario,
                self._fabrica_transporte,
                self._configuracion,
                contexto=contexto,
            )
