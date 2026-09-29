"""Pruebas del sondeo y contratos del monitor sin abrir red ni MariaDB."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from aplicacion.conexiones.errores import ErrorServidorSSHNoDisponible
from aplicacion.configuracion import Configuracion
from aplicacion.esquemas.monitoreo import ConfigurarMonitoreoServidor
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.enumeraciones import SistemaOperativo, TipoAlerta, TipoCredencialConexion
from aplicacion.modelos.monitoreo import Alerta
from aplicacion.modelos.servidor import Servidor
from aplicacion.monitoreo.evaluador import construir_condiciones
from aplicacion.monitoreo.notificaciones import NotificadorSlack, NotificadorTelegram
from aplicacion.monitoreo.sondeador import ObjetivoMonitoreo, ResultadoSondeo, sondear_objetivo


class TransporteSondeoSimulado:
    """Devuelve una secuencia cerrada de respuestas o errores."""

    def __init__(self, resultados: list[ResultadoEjecucionRemota | Exception]) -> None:
        self.resultados = resultados
        self.cerrado = False

    async def comprobar_disponibilidad(self) -> bool:
        return True

    async def ejecutar_comando_controlado(
        self,
        comando: str,
        tiempo_limite_segundos: float,
        limite_salida_bytes: int,
    ) -> ResultadoEjecucionRemota:
        assert comando
        assert tiempo_limite_segundos > 0
        assert limite_salida_bytes >= 1_024
        resultado = self.resultados.pop(0)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    async def cerrar(self) -> None:
        self.cerrado = True


def _servidor() -> Servidor:
    return Servidor(
        id_servidor=7,
        nombre="ubuntu-monitoreo",
        direccion="192.0.2.70",
        puerto_ssh=22,
        usuario_conexion="operador",
        sistema_operativo=SistemaOperativo.LINUX,
        tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
        referencia_credencial="archivo:pruebas",
        huella_clave_host="SHA256:huellaMonitoreoPruebas1234",
        activo=True,
    )


def _objetivo(**cambios: object) -> ObjetivoMonitoreo:
    datos = {
        "servidor": _servidor(),
        "activo": True,
        "umbral_cpu": 80.0,
        "umbral_memoria": 90.0,
        "umbral_disco": 90.0,
        "servicios_criticos": ("hermes-prueba.service",),
    }
    datos.update(cambios)
    return ObjetivoMonitoreo(**datos)  # type: ignore[arg-type]


def _diagnostico(cpu: float = 20.0) -> ResultadoEjecucionRemota:
    return ResultadoEjecucionRemota(
        codigo_salida=0,
        salida=(
            "HERMES_ACCION=obtener_diagnostico\n"
            "estado=disponible\n"
            f"cpu_porcentaje={cpu}\n"
            "memoria_porcentaje=40.0\n"
            "disco_porcentaje=50.0\n"
            "tiempo_actividad_segundos=3600\n"
            "sistema=Linux\n"
            "version=6.8.0\n"
            "nombre_equipo=ubuntu-monitoreo\n"
        ),
        error="",
        duracion_segundos=0.01,
    )


def _servicio(estado: str = "activo") -> ResultadoEjecucionRemota:
    return ResultadoEjecucionRemota(
        codigo_salida=0,
        salida=(
            "HERMES_ACCION=consultar_servicio\n"
            "nombre_servicio=hermes-prueba.service\n"
            f"estado={estado}\n"
            "estado_nativo=active\n"
            "inicio_automatico=true\n"
        ),
        error="",
        duracion_segundos=0.01,
    )


@pytest.mark.parametrize(
    "servicios",
    [
        ["nombre con espacios"],
        ["servicio.service", "servicio.service"],
        ["a.service"] * 21,
    ],
)
def test_rechaza_servicios_criticos_inseguros_o_duplicados(servicios: list[str]) -> None:
    with pytest.raises(ValidationError):
        ConfigurarMonitoreoServidor(servicios_criticos=servicios)


def test_permite_desactivar_un_umbral_sin_desactivar_el_sondeo() -> None:
    datos = ConfigurarMonitoreoServidor(
        umbral_cpu=None,
        servicios_criticos=["sshd", "hermes-prueba.service"],
    )

    assert datos.umbral_cpu is None
    assert datos.servicios_criticos == ["hermes-prueba.service", "sshd"]


@pytest.mark.asyncio
async def test_sondea_diagnostico_y_servicio_con_una_conexion_reutilizada(
    configuracion_pruebas: Configuracion,
) -> None:
    transporte = TransporteSondeoSimulado([_diagnostico(), _servicio()])

    resultado = await sondear_objetivo(
        _objetivo(),
        lambda _: transporte,
        configuracion_pruebas,
    )

    assert resultado.disponible is True
    assert resultado.diagnostico["cpu_porcentaje"] == 20.0
    assert resultado.estados_servicios == {"hermes-prueba.service": "activo"}
    assert transporte.resultados == []
    assert transporte.cerrado is True


@pytest.mark.asyncio
async def test_convierte_fallo_ssh_en_indisponibilidad_controlada(
    configuracion_pruebas: Configuracion,
) -> None:
    transporte = TransporteSondeoSimulado([ErrorServidorSSHNoDisponible()])

    resultado = await sondear_objetivo(
        _objetivo(),
        lambda _: transporte,
        configuracion_pruebas,
    )

    assert resultado.disponible is False
    assert resultado.codigo_error == "servidor_ssh_no_disponible"
    assert transporte.cerrado is True


@pytest.mark.asyncio
async def test_fallo_de_servicio_no_descarta_diagnostico_valido(
    configuracion_pruebas: Configuracion,
) -> None:
    transporte = TransporteSondeoSimulado([_diagnostico(), ErrorServidorSSHNoDisponible()])

    resultado = await sondear_objetivo(
        _objetivo(),
        lambda _: transporte,
        configuracion_pruebas,
    )

    assert resultado.disponible is True
    assert resultado.estados_servicios["hermes-prueba.service"].startswith("no_consultable:")


def test_evalua_umbral_y_servicio_sin_recuperar_metricas_no_disponibles() -> None:
    objetivo = _objetivo()
    resultado = ResultadoSondeo(
        id_servidor=7,
        nombre_servidor="ubuntu-monitoreo",
        disponible=True,
        diagnostico={
            "cpu_porcentaje": 85.5,
            "memoria_porcentaje": None,
            "disco_porcentaje": 20.0,
        },
        estados_servicios={"hermes-prueba.service": "inactivo"},
    )

    condiciones = construir_condiciones(objetivo, resultado, [])
    por_tipo = {condicion.tipo: condicion for condicion in condiciones}

    assert por_tipo[TipoAlerta.CPU_ALTA].incumplida is True
    assert por_tipo[TipoAlerta.MEMORIA_ALTA].incumplida is None
    assert por_tipo[TipoAlerta.DISCO_ALTO].incumplida is False
    assert por_tipo[TipoAlerta.SERVICIO_CRITICO_NO_ACTIVO].incumplida is True


def test_servicio_retirado_genera_condicion_de_cierre() -> None:
    alerta = Alerta(
        id_servidor=7,
        nombre_servidor="ubuntu-monitoreo",
        tipo=TipoAlerta.SERVICIO_CRITICO_NO_ACTIVO,
        identificador_objetivo="servicio-retirado.service",
        estado="activa",
        mensaje_apertura="Servicio detenido.",
    )
    resultado = ResultadoSondeo(
        id_servidor=7,
        nombre_servidor="ubuntu-monitoreo",
        disponible=True,
        diagnostico={},
        estados_servicios={},
    )

    condiciones = construir_condiciones(
        _objetivo(servicios_criticos=()),
        resultado,
        [alerta],
    )

    retirada = next(
        condicion for condicion in condiciones if condicion.objetivo == "servicio-retirado.service"
    )
    assert retirada.incumplida is False


@pytest.mark.asyncio
async def test_notificador_slack_extrae_usuario_y_rechaza_destino_invalido() -> None:
    notificador = NotificadorSlack("xoxb-token-solo-pruebas")
    cliente = AsyncMock()
    cliente.auth_test.return_value = {"team_id": "T012PRUEBA"}
    notificador._cliente = cliente

    await notificador.enviar_mensaje("T012PRUEBA:U012PRUEBA", "Alerta de prueba")
    cliente.chat_postMessage.assert_awaited_once_with(
        channel="U012PRUEBA",
        text="Alerta de prueba",
    )
    cliente.auth_test.assert_awaited_once_with()

    with pytest.raises(ValueError, match="otro espacio"):
        await notificador.enviar_mensaje("T999OTRO:U012PRUEBA", "Alerta privada")
    cliente.chat_postMessage.assert_awaited_once()

    with pytest.raises(ValueError):
        await notificador.enviar_mensaje("destino-invalido", "Alerta")


@pytest.mark.asyncio
async def test_notificador_telegram_rechaza_destino_antes_de_abrir_red() -> None:
    notificador = NotificadorTelegram("123456789:token_demostrativo_solo_pruebas")

    with pytest.raises(ValueError):
        await notificador.enviar_mensaje("usuario", "Alerta")
