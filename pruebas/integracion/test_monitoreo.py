"""Integración del monitoreo con MariaDB, API, deduplicación y entregas."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.errores import ErrorServidorSSHNoDisponible
from aplicacion.configuracion import Configuracion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    EstadoAlerta,
    EstadoNotificacionAlerta,
    SistemaOperativo,
    TipoCanalMensajeria,
    TipoCredencialConexion,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.monitoreo import (
    Alerta,
    ConfiguracionMonitoreoServidor,
    NotificacionAlerta,
    ServicioCriticoMonitoreo,
    SuscripcionAlerta,
)
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.monitoreo.motor import ejecutar_ciclo_monitoreo
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena


class TransporteMonitoreoSimulado:
    """Simula umbral alto, recuperación y un servidor desconectado."""

    modo = "alerta"

    def __init__(self, servidor: Servidor) -> None:
        self.servidor = servidor

    async def comprobar_disponibilidad(self) -> bool:
        return True

    async def ejecutar_comando_controlado(
        self,
        comando: str,
        tiempo_limite_segundos: float,
        limite_salida_bytes: int,
    ) -> ResultadoEjecucionRemota:
        assert tiempo_limite_segundos > 0
        assert limite_salida_bytes >= 1_024
        if self.servidor.nombre.endswith("no-disponible"):
            raise ErrorServidorSSHNoDisponible()
        if "HERMES_ACCION=consultar_servicio" in comando:
            estado = "inactivo" if type(self).modo == "alerta" else "activo"
            estado_nativo = "inactive" if estado == "inactivo" else "active"
            salida = (
                "HERMES_ACCION=consultar_servicio\n"
                "nombre_servicio=hermes-prueba.service\n"
                f"estado={estado}\n"
                f"estado_nativo={estado_nativo}\n"
                "inicio_automatico=true\n"
            )
        else:
            cpu = 95.0 if type(self).modo == "alerta" else 20.0
            salida = (
                "HERMES_ACCION=obtener_diagnostico\n"
                "estado=disponible\n"
                f"cpu_porcentaje={cpu}\n"
                "memoria_porcentaje=40.0\n"
                "disco_porcentaje=50.0\n"
                "tiempo_actividad_segundos=3600\n"
                "sistema=Linux\n"
                "version=6.8.0-prueba\n"
                "nombre_equipo=ubuntu-monitoreo\n"
            )
        return ResultadoEjecucionRemota(0, salida, "", 0.01)

    async def cerrar(self) -> None:
        return None


@dataclass
class NotificadorSimulado:
    """Conserva mensajes y permite fallar los primeros intentos."""

    fallos_restantes: int = 0
    mensajes: list[tuple[str, str]] = field(default_factory=list)

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        if self.fallos_restantes:
            self.fallos_restantes -= 1
            raise ConnectionError("Fallo simulado sin datos sensibles.")
        self.mensajes.append((identificador_destino, mensaje))

    async def cerrar(self) -> None:
        return None


@dataclass
class ContextoMonitoreo:
    """Entidades aisladas por prefijo y sus accesos de prueba."""

    motor: AsyncEngine
    fabrica_sesiones: async_sessionmaker[AsyncSession]
    aplicacion: object
    configuracion: Configuracion
    prefijo: str
    usuario_admin: str
    contrasena_admin: str
    usuario_auditor: str
    contrasena_auditor: str
    id_usuario_admin: int
    id_identidad: int
    id_identidad_slack: int
    id_servidor: int
    id_servidor_no_disponible: int
    primer_registro_auditoria: int


@pytest.fixture
async def contexto_monitoreo() -> AsyncIterator[ContextoMonitoreo]:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"monitoreo-{uuid4().hex[:10]}"
    contrasena_admin = "administrador-monitoreo-pruebas"
    contrasena_auditor = "auditor-monitoreo-pruebas"
    identificador_telegram = str(int(uuid4().hex[:12], 16))

    async with fabrica_sesiones() as sesion:
        primer_registro = int(
            await sesion.scalar(
                select(func.coalesce(func.max(RegistroAuditoria.id_registro_auditoria), 0))
            )
            or 0
        )
        rol_admin = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
        rol_auditor = await sesion.scalar(select(Rol).where(Rol.nombre == "auditor"))
        assert rol_admin is not None
        assert rol_auditor is not None
        administrador = Usuario(
            nombre_usuario=f"{prefijo}-admin",
            nombre_mostrar="Administrador monitoreo",
            hash_contrasena=generar_hash_contrasena(contrasena_admin),
            activo=True,
            roles=[rol_admin],
        )
        auditor = Usuario(
            nombre_usuario=f"{prefijo}-auditor",
            nombre_mostrar="Auditor monitoreo",
            hash_contrasena=generar_hash_contrasena(contrasena_auditor),
            activo=True,
            roles=[rol_auditor],
        )
        servidor = Servidor(
            nombre=f"{prefijo}-principal",
            direccion="192.0.2.210",
            puerto_ssh=22,
            usuario_conexion="operador",
            sistema_operativo=SistemaOperativo.LINUX,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial=f"archivo:{prefijo}-principal",
            huella_clave_host="SHA256:huellaMonitoreoPrincipal1234",
            activo=True,
        )
        servidor_no_disponible = Servidor(
            nombre=f"{prefijo}-no-disponible",
            direccion="192.0.2.211",
            puerto_ssh=22,
            usuario_conexion="operador",
            sistema_operativo=SistemaOperativo.LINUX,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial=f"archivo:{prefijo}-no-disponible",
            huella_clave_host="SHA256:huellaMonitoreoSecundaria1234",
            activo=True,
        )
        identidad = IdentidadMensajeria(
            usuario=administrador,
            canal=TipoCanalMensajeria.TELEGRAM,
            identificador_externo=identificador_telegram,
            nombre_externo="destino_monitoreo",
            activo=True,
        )
        identidad_slack = IdentidadMensajeria(
            usuario=administrador,
            canal=TipoCanalMensajeria.SLACK,
            identificador_externo="T012MONITOR:U012MONITOR",
            nombre_externo="destino_monitoreo_slack",
            activo=True,
        )
        sesion.add_all(
            [
                administrador,
                auditor,
                servidor,
                servidor_no_disponible,
                identidad,
                identidad_slack,
            ]
        )
        await sesion.commit()
        contexto = ContextoMonitoreo(
            motor=motor,
            fabrica_sesiones=fabrica_sesiones,
            aplicacion=crear_aplicacion(configuracion, motor),
            configuracion=configuracion,
            prefijo=prefijo,
            usuario_admin=administrador.nombre_usuario,
            contrasena_admin=contrasena_admin,
            usuario_auditor=auditor.nombre_usuario,
            contrasena_auditor=contrasena_auditor,
            id_usuario_admin=administrador.id_usuario,
            id_identidad=identidad.id_identidad_mensajeria,
            id_identidad_slack=identidad_slack.id_identidad_mensajeria,
            id_servidor=servidor.id_servidor,
            id_servidor_no_disponible=servidor_no_disponible.id_servidor,
            primer_registro_auditoria=primer_registro,
        )

    try:
        yield contexto
    finally:
        TransporteMonitoreoSimulado.modo = "alerta"
        async with fabrica_sesiones() as sesion:
            ids_servidores = [contexto.id_servidor, contexto.id_servidor_no_disponible]
            ids_alertas = list(
                await sesion.scalars(
                    select(Alerta.id_alerta).where(Alerta.id_servidor.in_(ids_servidores))
                )
            )
            if ids_alertas:
                await sesion.execute(
                    delete(NotificacionAlerta).where(NotificacionAlerta.id_alerta.in_(ids_alertas))
                )
            await sesion.execute(delete(Alerta).where(Alerta.id_servidor.in_(ids_servidores)))
            await sesion.execute(
                delete(SuscripcionAlerta).where(
                    SuscripcionAlerta.id_identidad_mensajeria == contexto.id_identidad
                )
            )
            await sesion.execute(
                delete(ConfiguracionMonitoreoServidor).where(
                    ConfiguracionMonitoreoServidor.id_servidor.in_(ids_servidores)
                )
            )
            await sesion.execute(
                delete(RegistroAuditoria).where(
                    RegistroAuditoria.id_registro_auditoria > contexto.primer_registro_auditoria
                )
            )
            await sesion.execute(
                delete(IdentidadMensajeria).where(
                    IdentidadMensajeria.id_identidad_mensajeria == contexto.id_identidad
                )
            )
            await sesion.execute(delete(Servidor).where(Servidor.id_servidor.in_(ids_servidores)))
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario.like(f"{prefijo}%")))
            await sesion.commit()
        await motor.dispose()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_api_configura_politica_destino_y_aplica_permisos(
    contexto_monitoreo: ContextoMonitoreo,
) -> None:
    transporte = httpx.ASGITransport(app=contexto_monitoreo.aplicacion)
    autenticacion_admin = (
        contexto_monitoreo.usuario_admin,
        contexto_monitoreo.contrasena_admin,
    )
    autenticacion_auditor = (
        contexto_monitoreo.usuario_auditor,
        contexto_monitoreo.contrasena_auditor,
    )
    datos = {
        "activo": True,
        "umbral_cpu": 80,
        "umbral_memoria": 85,
        "umbral_disco": 90,
        "servicios_criticos": ["hermes-prueba.service"],
    }

    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        denegada = await cliente.put(
            f"/api/v1/monitoreo/servidores/{contexto_monitoreo.id_servidor}",
            auth=autenticacion_auditor,
            json=datos,
        )
        assert denegada.status_code == 403

        guardada = await cliente.put(
            f"/api/v1/monitoreo/servidores/{contexto_monitoreo.id_servidor}",
            auth=autenticacion_admin,
            json=datos,
        )
        assert guardada.status_code == 200, guardada.text
        assert guardada.json()["nombres_servicios_criticos"] == ["hermes-prueba.service"]

        datos["umbral_cpu"] = 75
        actualizada = await cliente.put(
            f"/api/v1/monitoreo/servidores/{contexto_monitoreo.id_servidor}",
            auth=autenticacion_admin,
            json=datos,
        )
        assert actualizada.status_code == 200, actualizada.text
        assert actualizada.json()["umbral_cpu"] == 75

        consulta = await cliente.get(
            "/api/v1/monitoreo/configuraciones",
            auth=autenticacion_auditor,
        )
        assert consulta.status_code == 200
        assert any(
            item["id_servidor"] == contexto_monitoreo.id_servidor for item in consulta.json()
        )

        destinos = await cliente.get(
            "/api/v1/monitoreo/destinos",
            auth=autenticacion_admin,
        )
        destinos_denegados = await cliente.get(
            "/api/v1/monitoreo/destinos",
            auth=autenticacion_auditor,
        )
        assert destinos_denegados.status_code == 403
        destino = next(
            item
            for item in destinos.json()
            if item["id_identidad_mensajeria"] == contexto_monitoreo.id_identidad
        )
        assert destino["suscrito"] is False

        suscripcion = await cliente.put(
            f"/api/v1/monitoreo/destinos/{contexto_monitoreo.id_identidad}",
            auth=autenticacion_admin,
            json={"activo": True},
        )
        assert suscripcion.status_code == 200
        assert suscripcion.json()["suscrito"] is True

        alertas = await cliente.get("/api/v1/alertas", auth=autenticacion_auditor)
        assert alertas.status_code == 200


async def _preparar_motor(contexto: ContextoMonitoreo) -> None:
    async with contexto.fabrica_sesiones() as sesion:
        principal = ConfiguracionMonitoreoServidor(
            id_servidor=contexto.id_servidor,
            activo=True,
            umbral_cpu=80,
            umbral_memoria=90,
            umbral_disco=90,
            servicios_criticos=[
                ServicioCriticoMonitoreo(
                    nombre_servicio="hermes-prueba.service",
                    activo=True,
                )
            ],
        )
        no_disponible = ConfiguracionMonitoreoServidor(
            id_servidor=contexto.id_servidor_no_disponible,
            activo=True,
            umbral_cpu=80,
            umbral_memoria=90,
            umbral_disco=90,
            servicios_criticos=[],
        )
        suscripcion = SuscripcionAlerta(
            id_identidad_mensajeria=contexto.id_identidad,
            activo=True,
        )
        suscripcion_slack = SuscripcionAlerta(
            id_identidad_mensajeria=contexto.id_identidad_slack,
            activo=True,
        )
        sesion.add_all([principal, no_disponible, suscripcion, suscripcion_slack])
        await sesion.commit()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_ciclo_deduplica_reintenta_recupera_y_aisla_servidores(
    contexto_monitoreo: ContextoMonitoreo,
) -> None:
    await _preparar_motor(contexto_monitoreo)
    notificador = NotificadorSimulado(fallos_restantes=3)
    notificadores = {TipoCanalMensajeria.TELEGRAM: notificador}

    primero = await ejecutar_ciclo_monitoreo(
        contexto_monitoreo.fabrica_sesiones,
        TransporteMonitoreoSimulado,
        contexto_monitoreo.configuracion,
        notificadores,
    )
    assert primero.servidores_evaluados == 2
    assert primero.servidores_disponibles == 1
    assert primero.servidores_no_disponibles == 1
    assert primero.alertas_abiertas == 3
    assert primero.notificaciones_fallidas == 3

    segundo = await ejecutar_ciclo_monitoreo(
        contexto_monitoreo.fabrica_sesiones,
        TransporteMonitoreoSimulado,
        contexto_monitoreo.configuracion,
        notificadores,
    )
    assert segundo.alertas_abiertas == 0
    assert segundo.alertas_recuperadas == 0
    assert segundo.notificaciones_enviadas == 3
    assert len(notificador.mensajes) == 3

    sin_cambios = await ejecutar_ciclo_monitoreo(
        contexto_monitoreo.fabrica_sesiones,
        TransporteMonitoreoSimulado,
        contexto_monitoreo.configuracion,
        notificadores,
    )
    assert sin_cambios.notificaciones_enviadas == 0
    assert len(notificador.mensajes) == 3

    TransporteMonitoreoSimulado.modo = "recuperacion"
    tercero = await ejecutar_ciclo_monitoreo(
        contexto_monitoreo.fabrica_sesiones,
        TransporteMonitoreoSimulado,
        contexto_monitoreo.configuracion,
        notificadores,
    )
    assert tercero.servidores_disponibles == 1
    assert tercero.servidores_no_disponibles == 1
    assert tercero.alertas_abiertas == 0
    assert tercero.alertas_recuperadas == 2
    assert tercero.notificaciones_enviadas == 2

    async with contexto_monitoreo.fabrica_sesiones() as sesion:
        alertas = list(
            await sesion.scalars(
                select(Alerta).where(
                    Alerta.id_servidor.in_(
                        [
                            contexto_monitoreo.id_servidor,
                            contexto_monitoreo.id_servidor_no_disponible,
                        ]
                    )
                )
            )
        )
        notificaciones = list(
            await sesion.scalars(
                select(NotificacionAlerta).where(
                    NotificacionAlerta.id_alerta.in_([alerta.id_alerta for alerta in alertas])
                )
            )
        )
        acciones_auditoria = set(
            await sesion.scalars(
                select(RegistroAuditoria.accion).where(
                    RegistroAuditoria.id_registro_auditoria
                    > contexto_monitoreo.primer_registro_auditoria
                )
            )
        )

    assert len(alertas) == 3
    assert sum(alerta.estado is EstadoAlerta.RECUPERADA for alerta in alertas) == 2
    assert sum(alerta.estado is EstadoAlerta.ACTIVA for alerta in alertas) == 1
    assert len(notificaciones) == 8
    assert (
        sum(
            notificacion.estado is EstadoNotificacionAlerta.ENVIADA
            for notificacion in notificaciones
        )
        == 5
    )
    assert (
        sum(
            notificacion.estado is EstadoNotificacionAlerta.OMITIDA
            for notificacion in notificaciones
        )
        == 2
    )
    assert (
        sum(
            notificacion.estado is EstadoNotificacionAlerta.PENDIENTE
            for notificacion in notificaciones
        )
        == 1
    )
    assert len(notificador.mensajes) == 5
    assert "detectar_alerta_cpu_alta" in acciones_auditoria
    assert "detectar_alerta_servidor_no_disponible" in acciones_auditoria
    assert "registrar_recuperacion_cpu_alta" in acciones_auditoria
