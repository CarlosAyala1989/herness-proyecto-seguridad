"""Fachada del backend común configurada para Telegram."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aplicacion.configuracion import Configuracion
from aplicacion.modelos.enumeraciones import CanalAuditoria, TipoCanalMensajeria
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
