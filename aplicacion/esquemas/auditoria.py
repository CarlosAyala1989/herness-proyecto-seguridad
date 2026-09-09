"""Respuesta segura del historial de auditoría."""

from datetime import datetime

from aplicacion.esquemas.comunes import EsquemaDesdeAtributos
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    ResultadoAuditoria,
    TipoRecursoAuditoria,
)


class RegistroAuditoriaRespuesta(EsquemaDesdeAtributos):
    """Registro de auditoría sin credenciales ni trazas internas."""

    id_registro_auditoria: int
    id_usuario: int | None
    nombre_usuario: str | None
    accion: str
    tipo_recurso: TipoRecursoAuditoria
    id_recurso: int | None
    resultado: ResultadoAuditoria
    canal: CanalAuditoria
    detalle: str | None
    direccion_origen: str | None
    identificador_solicitud: str | None
    creado_en: datetime
