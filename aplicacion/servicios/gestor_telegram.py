"""Fachada del backend común configurada para Telegram."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorIdentidadMensajeriaNoAutorizada
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
