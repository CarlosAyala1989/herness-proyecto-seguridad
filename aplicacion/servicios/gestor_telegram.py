"""Fachada del backend común configurada para Telegram."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorIdentidadMensajeriaNoAutorizada, ErrorPermisoDenegado
from aplicacion.modelos.acceso import Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    ResultadoAuditoria,
    TipoCanalMensajeria,
    TipoRecursoAuditoria,
)
from aplicacion.servicios.auditoria import ContextoAuditoria, preparar_registro_auditoria
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto
from aplicacion.servicios.gestor_mensajeria import GestorMensajeria


class GestorTelegram(GestorMensajeria):
    """Configura identidad, límites y auditoría del canal Telegram."""

    def __init__(
        self,
        fabrica_sesiones: async_sessionmaker[AsyncSession],
        fabrica_transporte: FabricaTransporteRemoto,
        configuracion: Configuracion,
    ) -> None:
        super().__init__(
            fabrica_sesiones,
            fabrica_transporte,
            configuracion,
            TipoCanalMensajeria.TELEGRAM,
            CanalAuditoria.TELEGRAM,
            "tg",
            configuracion.max_servidores_mostrados_telegram,
        )

    async def registrar_ia(
        self,
        identificador_externo: int,
        identificador_evento: int,
        estado: str,
        modelo: str = "",
        esfuerzo: str = "",
    ) -> None:
        """Reautoriza al propietario administrador y audita sin prompts ni respuestas."""
        contexto = self.crear_contexto(identificador_externo, identificador_evento)
        async with self._fabrica_sesiones() as sesion:
            usuario = await self._autenticar(sesion, identificador_externo, contexto)
            administrador = any(rol.nombre == "administrador" for rol in usuario.roles)
            preparar_registro_auditoria(
                sesion,
                usuario=usuario,
                accion="codex_ia",
                tipo_recurso=TipoRecursoAuditoria.APLICACION,
                resultado=(
                    (ResultadoAuditoria.ERROR if estado == "error" else ResultadoAuditoria.EXITO)
                    if administrador
                    else ResultadoAuditoria.DENEGADO
                ),
                detalle=(
                    f"Estado={estado[:30]}; modelo={modelo[:100]}; esfuerzo={esfuerzo[:20]}."
                    if administrador
                    else "IA requiere el rol administrador."
                ),
                contexto=contexto,
            )
            await sesion.commit()
            if not administrador:
                raise ErrorPermisoDenegado("administrador_ia")

    async def _autenticar(
        self,
        sesion: AsyncSession,
        identificador_externo: str | int,
        contexto: ContextoAuditoria,
    ) -> Usuario:
        """Rechaza cualquier otro ID, aunque tenga una identidad o rol activos."""

        propietario = self._configuracion.id_propietario_telegram
        if propietario is None or str(identificador_externo) != str(propietario):
            preparar_registro_auditoria(
                sesion,
                usuario=None,
                accion="autenticar_identidad_mensajeria",
                tipo_recurso=TipoRecursoAuditoria.AUTENTICACION,
                resultado=ResultadoAuditoria.DENEGADO,
                detalle="La identidad no corresponde al propietario único de Telegram.",
                contexto=contexto,
            )
            await sesion.commit()
            raise ErrorIdentidadMensajeriaNoAutorizada()
        return await super()._autenticar(sesion, identificador_externo, contexto)
