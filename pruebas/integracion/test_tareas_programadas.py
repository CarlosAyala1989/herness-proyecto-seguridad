"""Integración de API, reclamo único, motor común y notificaciones de tareas."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import Configuracion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    EstadoEjecucionTarea,
    SistemaOperativo,
    TipoCanalMensajeria,
    TipoCredencialConexion,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.modelos.tarea_programada import (
    EjecucionTarea,
    NotificacionTarea,
    TareaProgramada,
)
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena
from aplicacion.tareas.motor import ejecutar_trabajo, reclamar_tareas_vencidas
from aplicacion.tareas.notificaciones import enviar_notificaciones_tareas_pendientes


class TransporteTareaSimulado:
    """Responde al catálogo normal sin abrir una conexión SSH."""

    ejecuciones = 0

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
        assert "HERMES_ACCION=obtener_identidad" in comando
        assert tiempo_limite_segundos > 0
        assert limite_salida_bytes >= 1_024
        type(self).ejecuciones += 1
        return ResultadoEjecucionRemota(
            0,
            f"HERMES_ACCION=obtener_identidad\noperador_tareas\n{self.servidor.nombre}\n",
            "",
            0.01,
        )

    async def cerrar(self) -> None:
        return None


@dataclass
class NotificadorTareaSimulado:
    mensajes: list[tuple[str, str]] = field(default_factory=list)

    async def enviar_mensaje(self, identificador_destino: str, mensaje: str) -> None:
        self.mensajes.append((identificador_destino, mensaje))

    async def cerrar(self) -> None:
        return None


@dataclass
class ContextoTareas:
    motor: AsyncEngine
    fabrica_sesiones: async_sessionmaker[AsyncSession]
    aplicacion: object
    configuracion: Configuracion
    prefijo: str
    usuario_admin: str
    contrasena_admin: str
    usuario_auditor: str
    contrasena_auditor: str
    id_servidor: int
    id_identidad: int
    primer_registro_auditoria: int


@pytest.fixture
async def contexto_tareas() -> AsyncIterator[ContextoTareas]:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"tareas-{uuid4().hex[:10]}"
    contrasena_admin = "administrador-tareas-pruebas"
    contrasena_auditor = "auditor-tareas-pruebas"
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
            nombre_mostrar="Administrador de tareas",
            hash_contrasena=generar_hash_contrasena(contrasena_admin),
            activo=True,
            roles=[rol_admin],
        )
        auditor = Usuario(
            nombre_usuario=f"{prefijo}-auditor",
            nombre_mostrar="Auditor de tareas",
            hash_contrasena=generar_hash_contrasena(contrasena_auditor),
            activo=True,
            roles=[rol_auditor],
        )
        servidor = Servidor(
            nombre=f"{prefijo}-servidor",
            direccion="192.0.2.230",
            puerto_ssh=22,
            usuario_conexion="operador_tareas",
            sistema_operativo=SistemaOperativo.LINUX,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial=f"archivo:{prefijo}",
            huella_clave_host="SHA256:huellaTareasProgramadas1234",
            activo=True,
        )
        identidad = IdentidadMensajeria(
            usuario=administrador,
            canal=TipoCanalMensajeria.TELEGRAM,
            identificador_externo=str(int(uuid4().hex[:12], 16)),
            nombre_externo="destino_tareas",
            activo=True,
        )
        sesion.add_all([administrador, auditor, servidor, identidad])
        await sesion.commit()
        contexto = ContextoTareas(
            motor=motor,
            fabrica_sesiones=fabrica_sesiones,
            aplicacion=crear_aplicacion(configuracion, motor),
            configuracion=configuracion,
            prefijo=prefijo,
            usuario_admin=administrador.nombre_usuario,
            contrasena_admin=contrasena_admin,
            usuario_auditor=auditor.nombre_usuario,
            contrasena_auditor=contrasena_auditor,
            id_servidor=servidor.id_servidor,
            id_identidad=identidad.id_identidad_mensajeria,
            primer_registro_auditoria=primer_registro,
        )
        contexto.aplicacion.state.fabrica_transporte_remoto = TransporteTareaSimulado

    try:
        yield contexto
    finally:
        TransporteTareaSimulado.ejecuciones = 0
        async with fabrica_sesiones() as sesion:
            ids_tareas = list(
                await sesion.scalars(
                    select(TareaProgramada.id_tarea_programada).where(
                        TareaProgramada.nombre.like(f"{prefijo}%")
                    )
                )
            )
            if ids_tareas:
                ids_ejecuciones = list(
                    await sesion.scalars(
                        select(EjecucionTarea.id_ejecucion_tarea).where(
                            EjecucionTarea.id_tarea_programada.in_(ids_tareas)
                        )
                    )
                )
                if ids_ejecuciones:
                    await sesion.execute(
                        delete(NotificacionTarea).where(
                            NotificacionTarea.id_ejecucion_tarea.in_(ids_ejecuciones)
                        )
                    )
                await sesion.execute(
                    delete(EjecucionTarea).where(EjecucionTarea.id_tarea_programada.in_(ids_tareas))
                )
                await sesion.execute(
                    delete(TareaProgramada).where(
                        TareaProgramada.id_tarea_programada.in_(ids_tareas)
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
            await sesion.execute(
                delete(Servidor).where(Servidor.id_servidor == contexto.id_servidor)
            )
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario.like(f"{prefijo}%")))
            await sesion.commit()
        await motor.dispose()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_programa_ejecuta_una_sola_vez_notifica_y_cancela(
    contexto_tareas: ContextoTareas,
) -> None:
    autenticacion_admin = (contexto_tareas.usuario_admin, contexto_tareas.contrasena_admin)
    autenticacion_auditor = (contexto_tareas.usuario_auditor, contexto_tareas.contrasena_auditor)
    transporte = httpx.ASGITransport(app=contexto_tareas.aplicacion)
    datos = {
        "nombre": f"{contexto_tareas.prefijo}-unica",
        "codigo_accion": "obtener_identidad",
        "seleccion": {"ids_servidores": [contexto_tareas.id_servidor]},
        "tipo_programacion": "una_vez",
        "programada_para": datetime.now(UTC).isoformat(),
        "notificar_resultado": True,
    }
    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        denegada = await cliente.post("/api/v1/tareas", auth=autenticacion_auditor, json=datos)
        assert denegada.status_code == 403

        sensible = dict(datos)
        sensible.update(
            nombre=f"{contexto_tareas.prefijo}-sensible",
            codigo_accion="reiniciar_servidor",
            programada_para=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
        )
        sin_confirmar = await cliente.post(
            "/api/v1/tareas", auth=autenticacion_admin, json=sensible
        )
        assert sin_confirmar.status_code == 400
        assert sin_confirmar.json()["codigo"] == "confirmacion_requerida"

        creada = await cliente.post("/api/v1/tareas", auth=autenticacion_admin, json=datos)
        assert creada.status_code == 201, creada.text
        id_tarea = creada.json()["id_tarea_programada"]
        consulta = await cliente.get("/api/v1/tareas", auth=autenticacion_auditor)
        assert consulta.status_code == 200
        assert any(item["id_tarea_programada"] == id_tarea for item in consulta.json())

        lotes = await asyncio.gather(
            reclamar_tareas_vencidas(
                contexto_tareas.fabrica_sesiones, contexto_tareas.configuracion
            ),
            reclamar_tareas_vencidas(
                contexto_tareas.fabrica_sesiones, contexto_tareas.configuracion
            ),
        )
        trabajos = [trabajo for lote in lotes for trabajo in lote]
        assert len(trabajos) == 1

        estado = await ejecutar_trabajo(
            trabajos[0],
            asyncio.Semaphore(1),
            contexto_tareas.fabrica_sesiones,
            TransporteTareaSimulado,
            contexto_tareas.configuracion,
        )
        assert estado is EstadoEjecucionTarea.COMPLETADA
        assert TransporteTareaSimulado.ejecuciones == 1

        notificador = NotificadorTareaSimulado()
        resumen_entregas = await enviar_notificaciones_tareas_pendientes(
            contexto_tareas.fabrica_sesiones,
            {TipoCanalMensajeria.TELEGRAM: notificador},
            3,
        )
        assert resumen_entregas.enviadas == 1
        assert "Estado: completada" in notificador.mensajes[0][1]

        historial = await cliente.get(
            f"/api/v1/tareas/{id_tarea}/ejecuciones", auth=autenticacion_auditor
        )
        assert historial.status_code == 200
        assert len(historial.json()) == 1
        assert historial.json()[0]["resumen_resultado"]["servidores_completados"] == 1

        repeticion = await reclamar_tareas_vencidas(
            contexto_tareas.fabrica_sesiones, contexto_tareas.configuracion
        )
        assert repeticion == []

        periodica = dict(datos)
        periodica.update(
            nombre=f"{contexto_tareas.prefijo}-periodica",
            tipo_programacion="intervalo",
            programada_para=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            intervalo_segundos=300,
            notificar_resultado=False,
        )
        creada_periodica = await cliente.post(
            "/api/v1/tareas", auth=autenticacion_admin, json=periodica
        )
        assert creada_periodica.status_code == 201, creada_periodica.text
        id_periodica = creada_periodica.json()["id_tarea_programada"]
        sin_confirmar_cancelacion = await cliente.post(
            f"/api/v1/tareas/{id_periodica}/cancelar",
            auth=autenticacion_admin,
            json={"confirmar": False},
        )
        assert sin_confirmar_cancelacion.status_code == 400
        cancelada = await cliente.post(
            f"/api/v1/tareas/{id_periodica}/cancelar",
            auth=autenticacion_admin,
            json={"confirmar": True},
        )
        assert cancelada.status_code == 200
        assert cancelada.json()["estado"] == "cancelada"
