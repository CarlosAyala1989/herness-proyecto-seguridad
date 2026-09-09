"""Evaluación transaccional y deduplicada de condiciones observadas."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    EstadoAlerta,
    FaseNotificacionAlerta,
    ResultadoAuditoria,
    TipoAlerta,
    TipoRecursoAuditoria,
)
from aplicacion.modelos.monitoreo import Alerta
from aplicacion.monitoreo.sondeador import ObjetivoMonitoreo, ResultadoSondeo
from aplicacion.servicios.auditoria import preparar_registro_auditoria


@dataclass(frozen=True, slots=True)
class CondicionEvaluada:
    """Estado de una condición; `None` significa que no pudo medirse."""

    tipo: TipoAlerta
    objetivo: str
    incumplida: bool | None
    valor: str | None
    umbral: float | None
    mensaje_apertura: str
    mensaje_recuperacion: str


@dataclass(frozen=True, slots=True)
class TransicionAlerta:
    """Apertura o recuperación que debe notificarse una sola vez."""

    alerta: Alerta
    fase: FaseNotificacionAlerta


def _ahora_utc() -> datetime:
    """Genera UTC sin zona para mantener compatibilidad con MariaDB DATETIME."""

    return datetime.now(UTC).replace(tzinfo=None)


def _clave_condicion(id_servidor: int, tipo: TipoAlerta, objetivo: str) -> str:
    contenido = f"{id_servidor}:{tipo.value}:{objetivo}".encode()
    return sha256(contenido).hexdigest()


def _porcentaje(valor: object) -> float | None:
    return float(valor) if isinstance(valor, int | float) and not isinstance(valor, bool) else None


def _condicion_porcentaje(
    nombre_servidor: str,
    tipo: TipoAlerta,
    etiqueta: str,
    valor: object,
    umbral: float | None,
) -> CondicionEvaluada:
    porcentaje = _porcentaje(valor)
    if umbral is None:
        incumplida: bool | None = False
        mensaje_recuperacion = f"{etiqueta} dejó de tener un umbral configurado."
    elif porcentaje is None:
        incumplida = None
        mensaje_recuperacion = f"{etiqueta} volvió a un nivel aceptable."
    else:
        incumplida = porcentaje >= umbral
        mensaje_recuperacion = (
            f"{etiqueta} de {nombre_servidor} volvió a {porcentaje:.2f} %, "
            f"por debajo del umbral de {umbral:.2f} %."
        )
    valor_texto = f"{porcentaje:.2f}" if porcentaje is not None else None
    mensaje_apertura = (
        f"{etiqueta} de {nombre_servidor} alcanzó {valor_texto} %, con umbral de {umbral:.2f} %."
        if valor_texto is not None and umbral is not None
        else f"{etiqueta} de {nombre_servidor} no pudo evaluarse."
    )
    return CondicionEvaluada(
        tipo=tipo,
        objetivo=etiqueta.lower(),
        incumplida=incumplida,
        valor=valor_texto,
        umbral=umbral,
        mensaje_apertura=mensaje_apertura,
        mensaje_recuperacion=mensaje_recuperacion,
    )


def construir_condiciones(
    objetivo: ObjetivoMonitoreo,
    resultado: ResultadoSondeo,
    alertas_activas: list[Alerta],
) -> list[CondicionEvaluada]:
    """Traduce diagnóstico y servicios en condiciones comunes."""

    nombre = objetivo.servidor.nombre
    disponibilidad = CondicionEvaluada(
        tipo=TipoAlerta.SERVIDOR_NO_DISPONIBLE,
        objetivo="disponibilidad",
        incumplida=not resultado.disponible,
        valor=resultado.codigo_error,
        umbral=None,
        mensaje_apertura=(
            f"El servidor {nombre} no está disponible para el monitoreo. "
            f"Código: {resultado.codigo_error or 'no_disponible'}."
        ),
        mensaje_recuperacion=f"El servidor {nombre} volvió a estar disponible.",
    )
    condiciones = [disponibilidad]
    if not resultado.disponible:
        return condiciones

    condiciones.extend(
        [
            _condicion_porcentaje(
                nombre,
                TipoAlerta.CPU_ALTA,
                "CPU",
                resultado.diagnostico.get("cpu_porcentaje"),
                objetivo.umbral_cpu,
            ),
            _condicion_porcentaje(
                nombre,
                TipoAlerta.MEMORIA_ALTA,
                "Memoria",
                resultado.diagnostico.get("memoria_porcentaje"),
                objetivo.umbral_memoria,
            ),
            _condicion_porcentaje(
                nombre,
                TipoAlerta.DISCO_ALTO,
                "Disco",
                resultado.diagnostico.get("disco_porcentaje"),
                objetivo.umbral_disco,
            ),
        ]
    )
    configurados = set(objetivo.servicios_criticos)
    for servicio in objetivo.servicios_criticos:
        estado = resultado.estados_servicios.get(servicio, "no_consultable")
        condiciones.append(
            CondicionEvaluada(
                tipo=TipoAlerta.SERVICIO_CRITICO_NO_ACTIVO,
                objetivo=servicio,
                incumplida=estado != "activo",
                valor=estado,
                umbral=None,
                mensaje_apertura=(
                    f"El servicio crítico {servicio} de {nombre} no está activo. Estado: {estado}."
                ),
                mensaje_recuperacion=(
                    f"El servicio crítico {servicio} de {nombre} volvió a estar activo."
                ),
            )
        )
    for alerta in alertas_activas:
        if (
            alerta.tipo is TipoAlerta.SERVICIO_CRITICO_NO_ACTIVO
            and alerta.identificador_objetivo not in configurados
        ):
            condiciones.append(
                CondicionEvaluada(
                    tipo=alerta.tipo,
                    objetivo=alerta.identificador_objetivo,
                    incumplida=False,
                    valor=None,
                    umbral=None,
                    mensaje_apertura=alerta.mensaje_apertura,
                    mensaje_recuperacion=(
                        f"El servicio {alerta.identificador_objetivo} dejó de estar configurado "
                        "como crítico."
                    ),
                )
            )
    return condiciones


async def _abrir_alerta(
    sesion: AsyncSession,
    objetivo: ObjetivoMonitoreo,
    condicion: CondicionEvaluada,
    clave: str,
) -> TransicionAlerta:
    alerta = Alerta(
        id_servidor=objetivo.servidor.id_servidor,
        nombre_servidor=objetivo.servidor.nombre,
        tipo=condicion.tipo,
        identificador_objetivo=condicion.objetivo,
        clave_activa=clave,
        estado=EstadoAlerta.ACTIVA,
        mensaje_apertura=condicion.mensaje_apertura[:500],
        valor_observado=condicion.valor[:100] if condicion.valor else None,
        umbral=condicion.umbral,
    )
    sesion.add(alerta)
    await sesion.flush()
    preparar_registro_auditoria(
        sesion,
        usuario=None,
        accion=f"detectar_alerta_{condicion.tipo.value}",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=objetivo.servidor.id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        canal=CanalAuditoria.SISTEMA,
        detalle="El monitor abrió un episodio de alerta.",
    )
    return TransicionAlerta(alerta, FaseNotificacionAlerta.APERTURA)


def _recuperar_alerta(
    sesion: AsyncSession,
    alerta: Alerta,
    condicion: CondicionEvaluada,
    id_servidor: int,
) -> TransicionAlerta:
    ahora = _ahora_utc()
    alerta.estado = EstadoAlerta.RECUPERADA
    alerta.clave_activa = None
    alerta.mensaje_recuperacion = condicion.mensaje_recuperacion[:500]
    alerta.valor_observado = condicion.valor[:100] if condicion.valor else None
    alerta.ultima_observacion_en = ahora
    alerta.recuperada_en = ahora
    preparar_registro_auditoria(
        sesion,
        usuario=None,
        accion=f"registrar_recuperacion_{alerta.tipo.value}",
        tipo_recurso=TipoRecursoAuditoria.SERVIDOR,
        id_recurso=id_servidor,
        resultado=ResultadoAuditoria.EXITO,
        canal=CanalAuditoria.SISTEMA,
        detalle="El monitor registró la recuperación de una alerta.",
    )
    return TransicionAlerta(alerta, FaseNotificacionAlerta.RECUPERACION)


async def evaluar_resultado_sondeo(
    sesion: AsyncSession,
    objetivo: ObjetivoMonitoreo,
    resultado: ResultadoSondeo,
) -> list[TransicionAlerta]:
    """Actualiza episodios existentes y devuelve solo transiciones nuevas."""

    id_servidor = objetivo.servidor.id_servidor
    alertas_activas = list(
        (
            await sesion.scalars(
                select(Alerta)
                .where(
                    Alerta.id_servidor == id_servidor,
                    Alerta.estado == EstadoAlerta.ACTIVA,
                )
            )
        ).all()
    )
    existentes = {
        (alerta.tipo, alerta.identificador_objetivo): alerta for alerta in alertas_activas
    }
    transiciones: list[TransicionAlerta] = []
    for condicion in construir_condiciones(objetivo, resultado, alertas_activas):
        if condicion.incumplida is None:
            continue
        clave_logica = (condicion.tipo, condicion.objetivo)
        alerta = existentes.get(clave_logica)
        if condicion.incumplida:
            if alerta is None:
                transicion = await _abrir_alerta(
                    sesion,
                    objetivo,
                    condicion,
                    _clave_condicion(id_servidor, condicion.tipo, condicion.objetivo),
                )
                transiciones.append(transicion)
            else:
                alerta.ultima_observacion_en = _ahora_utc()
                alerta.valor_observado = condicion.valor[:100] if condicion.valor else None
                alerta.umbral = condicion.umbral
        elif alerta is not None:
            transiciones.append(_recuperar_alerta(sesion, alerta, condicion, id_servidor))
    return transiciones


async def cerrar_alertas_por_monitoreo_inactivo(
    sesion: AsyncSession,
    objetivo: ObjetivoMonitoreo,
) -> list[TransicionAlerta]:
    """Cierra episodios cuando la política o el servidor se deshabilitan."""

    alertas = list(
        (
            await sesion.scalars(
                select(Alerta)
                .where(
                    Alerta.id_servidor == objetivo.servidor.id_servidor,
                    Alerta.estado == EstadoAlerta.ACTIVA,
                )
            )
        ).all()
    )
    return [
        _recuperar_alerta(
            sesion,
            alerta,
            CondicionEvaluada(
                tipo=alerta.tipo,
                objetivo=alerta.identificador_objetivo,
                incumplida=False,
                valor=None,
                umbral=None,
                mensaje_apertura=alerta.mensaje_apertura,
                mensaje_recuperacion=(
                    f"El monitoreo de {objetivo.servidor.nombre} fue desactivado."
                ),
            ),
            objetivo.servidor.id_servidor,
        )
        for alerta in alertas
    ]
