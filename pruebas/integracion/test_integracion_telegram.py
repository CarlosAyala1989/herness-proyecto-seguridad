"""Integración de Telegram con identidades, permisos, acciones y auditoría."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import Configuracion
from aplicacion.errores import (
    ErrorConflictoDatos,
    ErrorIdentidadMensajeriaNoAutorizada,
    ErrorPermisoDenegado,
    ErrorServidorInactivo,
)
from aplicacion.esquemas.acciones import SolicitudEjecucionAccion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    SistemaOperativo,
    TipoCredencialConexion,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.contrasenas import generar_hash_contrasena
from aplicacion.servicios.gestor_identidades_mensajeria import (
    desactivar_identidad_telegram,
    vincular_identidad_telegram,
)
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
        if "/proc/stat" in comando:
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
            assert "HERMES_ACCION=obtener_identidad" in comando
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
    prefijo: str
    identificador_autorizado: int
    id_servidor_activo: int
    id_servidor_inactivo: int
    primer_registro_auditoria: int


@pytest.fixture
async def contexto_telegram_integracion() -> AsyncIterator[ContextoTelegramIntegracion]:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"telegram-{uuid4().hex[:10]}"
    identificador_autorizado = 700_000_001

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
        sesion.add_all([usuario, servidor_activo, servidor_inactivo])
        await sesion.commit()
        await vincular_identidad_telegram(
            sesion,
            usuario.nombre_usuario,
            identificador_autorizado,
            "usuario_telegram_pruebas",
        )
        id_servidor_activo = servidor_activo.id_servidor
        id_servidor_inactivo = servidor_inactivo.id_servidor

    gestor = GestorTelegram(
        fabrica_sesiones,
        lambda _: TransporteTelegramSimulado(),
        configuracion,
    )
    contexto = ContextoTelegramIntegracion(
        motor=motor,
        fabrica_sesiones=fabrica_sesiones,
        gestor=gestor,
        prefijo=prefijo,
        identificador_autorizado=identificador_autorizado,
        id_servidor_activo=id_servidor_activo,
        id_servidor_inactivo=id_servidor_inactivo,
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
        contexto_telegram_integracion.id_servidor_activo
    }

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

    with pytest.raises(ErrorServidorInactivo):
        await gestor.ejecutar_accion(
            contexto_telegram_integracion.identificador_autorizado,
            1005,
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

    with pytest.raises(ErrorPermisoDenegado):
        await contexto_telegram_integracion.gestor.comprobar_accion_sensible(
            contexto_telegram_integracion.identificador_autorizado,
            1005,
            contexto_telegram_integracion.id_servidor_activo,
            "reiniciar_servidor",
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
