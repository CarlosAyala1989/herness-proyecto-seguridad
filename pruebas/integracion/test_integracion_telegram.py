"""Integración de Telegram con identidades, permisos, acciones y auditoría."""

from base64 import b64decode
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.comandos import configurar_instalacion as asistente_instalacion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import (
    ErrorConflictoDatos,
    ErrorIdentidadMensajeriaNoAutorizada,
    ErrorPermisoDenegado,
    ErrorServidorInactivo,
)
from aplicacion.esquemas.acciones import (
    SeleccionServidores,
    SolicitudEjecucionAccion,
    SolicitudEjecucionMultiple,
)
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    SistemaOperativo,
    TipoCredencialConexion,
)
from aplicacion.modelos.grupo_servidor import GrupoServidor
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.contrasenas import generar_hash_contrasena
from aplicacion.servicios.gestor_identidades_mensajeria import (
    desactivar_identidad_telegram,
    vincular_identidad_slack,
    vincular_identidad_telegram,
)
from aplicacion.servicios.gestor_slack import GestorSlack
from aplicacion.servicios.gestor_telegram import GestorTelegram


class TransporteTelegramSimulado:
    """Sustituye la red SSH sin duplicar la interpretación del adaptador Linux."""

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
        comando_legible = comando
        if "-EncodedCommand" in comando:
            comando_legible = b64decode(comando.rsplit(maxsplit=1)[1]).decode("utf-16-le")
        if "HERMES_ACCION=consultar_servicio" in comando_legible:
            salida = (
                "HERMES_ACCION=consultar_servicio\n"
                "nombre_servicio=ssh.service\n"
                "estado=activo\n"
                "estado_nativo=active\n"
                "inicio_automatico=true\n"
            )
        elif "/proc/stat" in comando_legible:
            salida = (
                "HERMES_ACCION=obtener_diagnostico\n"
                "estado=disponible\n"
                "cpu_porcentaje=12.50\n"
                "memoria_porcentaje=45.25\n"
                "disco_porcentaje=no_disponible\n"
                "tiempo_actividad_segundos=3600\n"
                "sistema=Linux\n"
                "version=6.8.0-prueba\n"
                "nombre_equipo=ubuntu-telegram\n"
            )
        else:
            assert "HERMES_ACCION=obtener_identidad" in comando_legible
            salida = "HERMES_ACCION=obtener_identidad\noperador_telegram\nubuntu-telegram\n"
        return ResultadoEjecucionRemota(
            codigo_salida=0,
            salida=salida,
            error="",
            duracion_segundos=0.02,
        )

    async def cerrar(self) -> None:
        return None


@dataclass
class ContextoTelegramIntegracion:
    motor: AsyncEngine
    fabrica_sesiones: async_sessionmaker[AsyncSession]
    gestor: GestorTelegram
    gestor_slack: GestorSlack
    prefijo: str
    identificador_autorizado: int
    id_servidor_activo: int
    id_segundo_servidor_activo: int
    id_servidor_inactivo: int
    id_grupo: int
    identidad_slack: str
    primer_registro_auditoria: int


@pytest.mark.integracion
async def test_ia_exige_propietario_y_rol_administrador_vigente(contexto_telegram_integracion):
    contexto = contexto_telegram_integracion
    await contexto.gestor.registrar_ia(
        contexto.identificador_autorizado, 90001, "iniciada", "modelo-prueba", "low"
    )
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await contexto.gestor.registrar_ia(799999998, 90002, "autorizacion")
    async with contexto.fabrica_sesiones() as sesion:
        usuario = await sesion.scalar(
            select(Usuario).where(Usuario.nombre_usuario == f"{contexto.prefijo}-usuario")
        )
        usuario.roles = []
        await sesion.commit()
    with pytest.raises(ErrorPermisoDenegado):
        await contexto.gestor.registrar_ia(contexto.identificador_autorizado, 90003, "autorizacion")
    async with contexto.fabrica_sesiones() as sesion:
        registros = (
            await sesion.scalars(
                select(RegistroAuditoria).where(RegistroAuditoria.accion == "codex_ia")
            )
        ).all()
        assert any(
            "modelo=modelo-prueba; esfuerzo=low" in registro.detalle for registro in registros
        )
        assert any(registro.resultado.value == "denegado" for registro in registros)


@pytest.fixture
async def contexto_telegram_integracion() -> AsyncIterator[ContextoTelegramIntegracion]:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"telegram-{uuid4().hex[:10]}"
    identificador_autorizado = 700_000_001
    configuracion.id_propietario_telegram = identificador_autorizado
    identificador_equipo_slack = "T012PRUEBA9"
    identificador_usuario_slack = "U012PRUEBA9"

    async with fabrica_sesiones() as sesion:
        primer_registro = await sesion.scalar(
            select(func.coalesce(func.max(RegistroAuditoria.id_registro_auditoria), 0))
        )
        rol_administrador = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
        assert rol_administrador is not None
        usuario = Usuario(
            nombre_usuario=f"{prefijo}-usuario",
            nombre_mostrar="Administrador Telegram",
            hash_contrasena=generar_hash_contrasena("contrasena-temporal-telegram"),
            activo=True,
            roles=[rol_administrador],
        )
        servidor_activo = Servidor(
            nombre=f"{prefijo}-activo",
            descripcion="Servidor Telegram de integración",
            direccion="192.0.2.70",
            puerto_ssh=22,
            usuario_conexion="operador_telegram",
            sistema_operativo=SistemaOperativo.LINUX,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial=f"archivo:{prefijo}-activo",
            huella_clave_host="SHA256:huellaTelegramActiva000000000000000000",
            activo=True,
            grupos=[],
        )
        servidor_inactivo = Servidor(
            nombre=f"{prefijo}-inactivo",
            descripcion="Servidor inactivo de integración",
            direccion="192.0.2.71",
            puerto_ssh=22,
            usuario_conexion="operador_telegram",
            sistema_operativo=SistemaOperativo.LINUX,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial=f"archivo:{prefijo}-inactivo",
            huella_clave_host="SHA256:huellaTelegramInactiva0000000000000000",
            activo=False,
            grupos=[],
        )
        segundo_servidor_activo = Servidor(
            nombre=f"{prefijo}-activo-2",
            descripcion="Segundo servidor Telegram de integración",
            direccion="192.0.2.72",
            puerto_ssh=22,
            usuario_conexion="operador_telegram",
            sistema_operativo=SistemaOperativo.WINDOWS_SERVER,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial=f"archivo:{prefijo}-activo-2",
            huella_clave_host="SHA256:huellaTelegramActivaDos0000000000000000",
            activo=True,
            grupos=[],
        )
        grupo = GrupoServidor(
            nombre=f"{prefijo}-grupo",
            descripcion="Grupo Telegram de integración",
            servidores=[servidor_activo, segundo_servidor_activo],
        )
        sesion.add_all([usuario, servidor_activo, servidor_inactivo, grupo])
        await sesion.commit()
        await vincular_identidad_telegram(
            sesion,
            usuario.nombre_usuario,
            identificador_autorizado,
            "usuario_telegram_pruebas",
        )
        await vincular_identidad_slack(
            sesion,
            usuario.nombre_usuario,
            identificador_equipo_slack,
            identificador_usuario_slack,
            "usuario_slack_pruebas",
        )
        id_servidor_activo = servidor_activo.id_servidor
        id_segundo_servidor_activo = segundo_servidor_activo.id_servidor
        id_servidor_inactivo = servidor_inactivo.id_servidor
        id_grupo = grupo.id_grupo

    gestor = GestorTelegram(
        fabrica_sesiones,
        lambda _: TransporteTelegramSimulado(),
        configuracion,
    )
    gestor_slack = GestorSlack(
        fabrica_sesiones,
        lambda _: TransporteTelegramSimulado(),
        configuracion,
    )
    contexto = ContextoTelegramIntegracion(
        motor=motor,
        fabrica_sesiones=fabrica_sesiones,
        gestor=gestor,
        gestor_slack=gestor_slack,
        prefijo=prefijo,
        identificador_autorizado=identificador_autorizado,
        id_servidor_activo=id_servidor_activo,
        id_segundo_servidor_activo=id_segundo_servidor_activo,
        id_servidor_inactivo=id_servidor_inactivo,
        id_grupo=id_grupo,
        identidad_slack=f"{identificador_equipo_slack}:{identificador_usuario_slack}",
        primer_registro_auditoria=int(primer_registro or 0),
    )
    try:
        yield contexto
    finally:
        async with fabrica_sesiones() as sesion:
            await sesion.execute(
                delete(RegistroAuditoria).where(
                    RegistroAuditoria.id_registro_auditoria > contexto.primer_registro_auditoria
                )
            )
            await sesion.execute(delete(Servidor).where(Servidor.nombre.like(f"{prefijo}%")))
            await sesion.execute(
                delete(GrupoServidor).where(GrupoServidor.nombre.like(f"{prefijo}%"))
            )
            await sesion.execute(
                delete(IdentidadMensajeria).where(
                    IdentidadMensajeria.identificador_externo == str(identificador_autorizado)
                )
            )
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario.like(f"{prefijo}%")))
            await sesion.commit()
        await motor.dispose()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_autoriza_por_identificador_y_reutiliza_motor_comun(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
) -> None:
    gestor = contexto_telegram_integracion.gestor

    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await gestor.comprobar_acceso(799_999_999, 1000)

    nombre = await gestor.comprobar_acceso(
        contexto_telegram_integracion.identificador_autorizado, 1001
    )
    assert nombre == "Administrador Telegram"

    servidores = await gestor.consultar_servidores(
        contexto_telegram_integracion.identificador_autorizado,
        1002,
    )
    assert {servidor.id_servidor for servidor in servidores} == {
        contexto_telegram_integracion.id_servidor_activo,
        contexto_telegram_integracion.id_segundo_servidor_activo,
    }

    grupos = await gestor.consultar_grupos(
        contexto_telegram_integracion.identificador_autorizado,
        1002,
    )
    assert {grupo.id_grupo for grupo in grupos} == {contexto_telegram_integracion.id_grupo}
    cantidad_grupo = await gestor.comprobar_seleccion_multiple(
        contexto_telegram_integracion.identificador_autorizado,
        1002,
        SeleccionServidores(id_grupo=contexto_telegram_integracion.id_grupo),
    )
    assert cantidad_grupo == 2

    resultado = await gestor.ejecutar_accion(
        contexto_telegram_integracion.identificador_autorizado,
        1003,
        contexto_telegram_integracion.id_servidor_activo,
        "obtener_identidad",
        SolicitudEjecucionAccion(),
    )
    assert resultado.datos == {
        "usuario": "operador_telegram",
        "nombre_equipo": "ubuntu-telegram",
    }

    diagnostico = await gestor.ejecutar_accion(
        contexto_telegram_integracion.identificador_autorizado,
        1004,
        contexto_telegram_integracion.id_servidor_activo,
        "obtener_diagnostico",
        SolicitudEjecucionAccion(),
    )
    assert diagnostico.datos["estado"] == "disponible"
    assert diagnostico.datos["cpu_porcentaje"] == 12.5
    assert diagnostico.datos["disco_porcentaje"] is None

    servicio = await gestor.ejecutar_accion(
        contexto_telegram_integracion.identificador_autorizado,
        1005,
        contexto_telegram_integracion.id_servidor_activo,
        "consultar_servicio",
        SolicitudEjecucionAccion(parametros={"nombre_servicio": "ssh.service"}),
    )
    assert servicio.datos["estado"] == "activo"
    assert servicio.datos["inicio_automatico"] is True

    resultado_multiple = await gestor.ejecutar_accion_multiple(
        contexto_telegram_integracion.identificador_autorizado,
        1006,
        "obtener_identidad",
        SolicitudEjecucionMultiple(
            seleccion=SeleccionServidores(id_grupo=contexto_telegram_integracion.id_grupo)
        ),
    )
    assert resultado_multiple.estado == "completada"
    assert resultado_multiple.total_servidores == 2
    assert {resultado.id_servidor for resultado in resultado_multiple.resultados} == {
        contexto_telegram_integracion.id_servidor_activo,
        contexto_telegram_integracion.id_segundo_servidor_activo,
    }

    with pytest.raises(ErrorServidorInactivo):
        await gestor.ejecutar_accion(
            contexto_telegram_integracion.identificador_autorizado,
            1009,
            contexto_telegram_integracion.id_servidor_inactivo,
            "obtener_identidad",
            SolicitudEjecucionAccion(),
        )

    async with contexto_telegram_integracion.fabrica_sesiones() as sesion:
        registros = list(
            (
                await sesion.scalars(
                    select(RegistroAuditoria).where(
                        RegistroAuditoria.id_registro_auditoria
                        > contexto_telegram_integracion.primer_registro_auditoria
                    )
                )
            ).all()
        )
    denegacion = next(
        registro for registro in registros if registro.accion == "autenticar_identidad_mensajeria"
    )
    ejecucion = next(
        registro for registro in registros if registro.accion == "ejecutar_accion_obtener_identidad"
    )
    assert denegacion.canal is CanalAuditoria.TELEGRAM
    assert denegacion.direccion_origen == "telegram:799999999"
    assert ejecucion.canal is CanalAuditoria.TELEGRAM
    assert ejecucion.identificador_solicitud == "tg:1003"
    ejecuciones_multiples = [
        registro
        for registro in registros
        if registro.accion == "ejecutar_accion_obtener_identidad"
        and registro.identificador_solicitud == "tg:1006"
    ]
    assert len(ejecuciones_multiples) == 2
    assert all(registro.canal is CanalAuditoria.TELEGRAM for registro in ejecuciones_multiples)


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_permiso_se_comprueba_tambien_antes_de_confirmar(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
) -> None:
    async with contexto_telegram_integracion.fabrica_sesiones() as sesion:
        identidad = await sesion.scalar(
            select(IdentidadMensajeria).where(
                IdentidadMensajeria.identificador_externo
                == str(contexto_telegram_integracion.identificador_autorizado)
            )
        )
        assert identidad is not None
        usuario = await sesion.get(Usuario, identidad.id_usuario)
        rol_operador = await sesion.scalar(select(Rol).where(Rol.nombre == "operador_inventario"))
        assert usuario is not None
        assert rol_operador is not None
        usuario.roles = [rol_operador]
        await sesion.commit()

    diagnostico = await contexto_telegram_integracion.gestor.ejecutar_accion(
        contexto_telegram_integracion.identificador_autorizado,
        1006,
        contexto_telegram_integracion.id_servidor_activo,
        "obtener_diagnostico",
        SolicitudEjecucionAccion(),
    )
    assert diagnostico.datos["estado"] == "disponible"

    servicio = await contexto_telegram_integracion.gestor.ejecutar_accion(
        contexto_telegram_integracion.identificador_autorizado,
        1007,
        contexto_telegram_integracion.id_servidor_activo,
        "consultar_servicio",
        SolicitudEjecucionAccion(parametros={"nombre_servicio": "ssh.service"}),
    )
    assert servicio.datos["estado"] == "activo"

    with pytest.raises(ErrorPermisoDenegado):
        await contexto_telegram_integracion.gestor.comprobar_accion_sensible(
            contexto_telegram_integracion.identificador_autorizado,
            1005,
            contexto_telegram_integracion.id_servidor_activo,
            "reiniciar_servidor",
        )

    with pytest.raises(ErrorPermisoDenegado):
        await contexto_telegram_integracion.gestor.comprobar_accion_sensible(
            contexto_telegram_integracion.identificador_autorizado,
            1008,
            contexto_telegram_integracion.id_servidor_activo,
            "detener_servicio",
            SolicitudEjecucionAccion(parametros={"nombre_servicio": "ssh.service"}),
        )


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_revoca_solo_el_acceso_de_telegram(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
) -> None:
    async with contexto_telegram_integracion.fabrica_sesiones() as sesion:
        await desactivar_identidad_telegram(
            sesion,
            f"{contexto_telegram_integracion.prefijo}-usuario",
        )

    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await contexto_telegram_integracion.gestor.comprobar_acceso(
            contexto_telegram_integracion.identificador_autorizado,
            1006,
        )

    nombre_slack = await contexto_telegram_integracion.gestor_slack.comprobar_acceso(
        contexto_telegram_integracion.identidad_slack,
        "revocacion",
    )
    assert nombre_slack == "Administrador Telegram"

    async with contexto_telegram_integracion.fabrica_sesiones() as sesion:
        usuario = await sesion.scalar(
            select(Usuario).where(
                Usuario.nombre_usuario == f"{contexto_telegram_integracion.prefijo}-usuario"
            )
        )
        assert usuario is not None
    assert usuario.activo is True


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_slack_y_telegram_reutilizan_inventario_acciones_y_auditoria(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
) -> None:
    resultado = await contexto_telegram_integracion.gestor_slack.ejecutar_accion(
        contexto_telegram_integracion.identidad_slack,
        "solicitud-slack-1",
        contexto_telegram_integracion.id_servidor_activo,
        "obtener_identidad",
        SolicitudEjecucionAccion(),
    )
    assert resultado.datos == {
        "usuario": "operador_telegram",
        "nombre_equipo": "ubuntu-telegram",
    }

    resultado_multiple = await contexto_telegram_integracion.gestor_slack.ejecutar_accion_multiple(
        contexto_telegram_integracion.identidad_slack,
        "solicitud-slack-2",
        "obtener_identidad",
        SolicitudEjecucionMultiple(
            seleccion=SeleccionServidores(id_grupo=contexto_telegram_integracion.id_grupo)
        ),
    )
    assert resultado_multiple.total_servidores == 2
    assert resultado_multiple.servidores_completados == 2

    async with contexto_telegram_integracion.fabrica_sesiones() as sesion:
        registros = list(
            (
                await sesion.scalars(
                    select(RegistroAuditoria).where(
                        RegistroAuditoria.identificador_solicitud.in_(
                            ["sl:solicitud-slack-1", "sl:solicitud-slack-2"]
                        )
                    )
                )
            ).all()
        )
    assert len(registros) == 3
    assert all(registro.canal is CanalAuditoria.SLACK for registro in registros)


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_rechaza_datos_de_vinculacion_fuera_de_limites(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
) -> None:
    async with contexto_telegram_integracion.fabrica_sesiones() as sesion:
        with pytest.raises(ErrorConflictoDatos):
            await vincular_identidad_telegram(
                sesion,
                f"{contexto_telegram_integracion.prefijo}-usuario",
                10**100,
            )
        with pytest.raises(ErrorConflictoDatos):
            await vincular_identidad_telegram(
                sesion,
                f"{contexto_telegram_integracion.prefijo}-usuario",
                contexto_telegram_integracion.identificador_autorizado,
                "x" * 101,
            )


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_asistente_recupera_y_conserva_ambas_identidades_persistentes(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    configuracion = Configuracion().model_copy(  # type: ignore[call-arg]
        update={"telegram_habilitado": True, "slack_habilitado": True}
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(asistente_instalacion, "obtener_configuracion", lambda: configuracion)
    nombre = f"{contexto_telegram_integracion.prefijo}-usuario"

    def responder_asistente(pregunta: str) -> str:
        if "Usuario administrador" in pregunta:
            return nombre
        assert "actual:" in pregunta
        return ""

    monkeypatch.setattr("builtins.input", responder_asistente)
    await asistente_instalacion.ofrecer_vinculos()
    salida = capsys.readouterr().out
    assert "Telegram: usuario autorizado" in salida
    assert "Slack: usuario autorizado" in salida
    assert str(contexto_telegram_integracion.identificador_autorizado) not in salida
    assert contexto_telegram_integracion.identidad_slack not in salida

    # La autorización sigue funcionando en los mismos gestores tras cerrar el asistente.
    assert (
        await contexto_telegram_integracion.gestor.comprobar_acceso(
            contexto_telegram_integracion.identificador_autorizado, 3001
        )
        == "Administrador Telegram"
    )
    assert (
        await contexto_telegram_integracion.gestor_slack.comprobar_acceso(
            contexto_telegram_integracion.identidad_slack, "asistente-conservado"
        )
        == "Administrador Telegram"
    )


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_rechaza_otro_telegram_aunque_este_vinculado_a_un_administrador(
    contexto_telegram_integracion: ContextoTelegramIntegracion,
) -> None:
    contexto = contexto_telegram_integracion
    segundo_id = 700_000_002
    # Otra cuenta con rol administrador puede estar vinculada, pero no es el propietario.
    async with contexto.fabrica_sesiones() as sesion:
        propietario = await sesion.scalar(
            select(Usuario).where(Usuario.nombre_usuario == f"{contexto.prefijo}-usuario")
        )
        assert propietario is not None
        otro = Usuario(
            nombre_usuario=f"{contexto.prefijo}-otro",
            nombre_mostrar="Otro administrador",
            hash_contrasena=propietario.hash_contrasena,
            activo=True,
            roles=list(propietario.roles),
        )
        sesion.add(otro)
        await sesion.commit()
        await vincular_identidad_telegram(sesion, otro.nombre_usuario, segundo_id)
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await contexto.gestor.comprobar_acceso(segundo_id, 3100)
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await contexto.gestor.ejecutar_accion(
            segundo_id,
            3101,
            contexto.id_servidor_activo,
            "obtener_identidad",
            SolicitudEjecucionAccion(),
        )
    assert (
        await contexto.gestor.comprobar_acceso(contexto.identificador_autorizado, 3104)
        == "Administrador Telegram"
    )
    # Quitar el vínculo del propietario tampoco promueve al otro ID.
    async with contexto.fabrica_sesiones() as sesion:
        await desactivar_identidad_telegram(sesion, f"{contexto.prefijo}-usuario")
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await contexto.gestor.comprobar_acceso(contexto.identificador_autorizado, 3102)
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await contexto.gestor.comprobar_acceso(segundo_id, 3103)
    async with contexto.fabrica_sesiones() as sesion:
        registros = list(
            (
                await sesion.scalars(
                    select(RegistroAuditoria).where(
                        RegistroAuditoria.identificador_solicitud.in_(
                            ["tg:3100", "tg:3101", "tg:3102", "tg:3103"]
                        )
                    )
                )
            ).all()
        )
    assert len(registros) == 4
