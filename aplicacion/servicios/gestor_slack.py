"""Fachada del backend común configurada para el canal Slack."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aplicacion.configuracion import Configuracion
from aplicacion.modelos.enumeraciones import CanalAuditoria, TipoCanalMensajeria
from aplicacion.servicios.gestor_conexiones import FabricaTransporteRemoto
from aplicacion.servicios.gestor_mensajeria import GestorMensajeria


class GestorSlack(GestorMensajeria):
    """Reutiliza todos los casos de uso y cambia identidad y canal de auditoría."""

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
            TipoCanalMensajeria.SLACK,
            CanalAuditoria.SLACK,
            "sl",
            configuracion.max_servidores_mostrados_slack,
        )
