"""Pruebas de la interfaz Telegram sin conectarse a Telegram."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from aplicacion.acciones.registro import CodigoAccion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.esquemas.acciones import ResultadoAccionRespuesta
from aplicacion.esquemas.inventario import ServidorResumen
from aplicacion.interfaces.telegram.bot import (
    CLAVE_CONFIRMACION_REINICIO,
    CLAVE_SERVIDOR_SELECCIONADO,
    InterfazTelegram,
    crear_aplicacion_telegram,
)
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.servicios.gestor_telegram import GestorTelegram


@dataclass
class MensajeSimulado:
    """Captura respuestas sin usar la red de Telegram."""

    respuestas: list[tuple[str, object | None]] = field(default_factory=list)

    async def reply_text(self, texto: str, reply_markup: object | None = None) -> None:
        self.respuestas.append((texto, reply_markup))


@dataclass
class ConsultaBotonSimulada:
    """Representa una pulsación de botón ya recibida."""

    data: str
    respondida: bool = False

    async def answer(self) -> None:
        self.respondida = True


def _actualizacion(
    mensaje: MensajeSimulado,
    *,
    id_usuario: int = 123_456,
    id_actualizacion: int = 900,
    tipo_conversacion: str = "private",
    consulta: ConsultaBotonSimulada | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        update_id=id_actualizacion,
        effective_user=SimpleNamespace(id=id_usuario),
        effective_chat=SimpleNamespace(type=tipo_conversacion),
        effective_message=mensaje,
        callback_query=consulta,
    )


def _contexto(*argumentos: str) -> SimpleNamespace:
    return SimpleNamespace(args=list(argumentos), user_data={}, error=None)


def _crear_valor_token_pruebas() -> str:
    return "123456789:" + "TokenDemostrativoSoloParaPruebas_12345"


@pytest.fixture
def configuracion_telegram() -> Configuracion:
    return Configuracion(
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_pruebas",
        telegram_habilitado=True,
        token_telegram=_crear_valor_token_pruebas(),
    )


@pytest.fixture
def interfaz_telegram(
    configuracion_telegram: Configuracion,
) -> tuple[InterfazTelegram, AsyncMock]:
    gestor = AsyncMock(spec=GestorTelegram)
    motor = AsyncMock(spec=AsyncEngine)
    return InterfazTelegram(gestor, configuracion_telegram, motor), gestor


def _servidor() -> ServidorResumen:
    return ServidorResumen(
        id_servidor=7,
        nombre="ubuntu-laboratorio",
        direccion="127.0.0.1",
        puerto_ssh=22,
        sistema_operativo=SistemaOperativo.LINUX,
        activo=True,
    )


def _resultado(codigo: CodigoAccion) -> ResultadoAccionRespuesta:
    datos: dict[str, str | int | bool]
    if codigo is CodigoAccion.OBTENER_IDENTIDAD:
        datos = {"usuario": "operador", "nombre_equipo": "ubuntu-laboratorio"}
    elif codigo is CodigoAccion.CONSULTAR_PROCESO:
        datos = {"id_proceso": 1, "nombre_proceso": "systemd"}
    else:
        datos = {"reinicio_programado": True, "demora_segundos": 60}
    return ResultadoAccionRespuesta(
        id_servidor=7,
        nombre_servidor="ubuntu-laboratorio",
        sistema_operativo=SistemaOperativo.LINUX,
        accion=codigo,
        datos=datos,
        duracion_ms=12.5,
    )


@pytest.mark.asyncio
async def test_rechaza_identidad_no_vinculada_e_informa_su_identificador(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.side_effect = ErrorIdentidadMensajeriaNoAutorizada()
    mensaje = MensajeSimulado()

    await interfaz.iniciar(_actualizacion(mensaje), _contexto())

    assert "Acceso denegado" in mensaje.respuestas[0][0]
    assert "123456" in mensaje.respuestas[0][0]
    gestor.consultar_servidores.assert_not_awaited()
    gestor.ejecutar_accion.assert_not_awaited()


@pytest.mark.asyncio
async def test_rechaza_conversaciones_no_privadas(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    mensaje = MensajeSimulado()

    await interfaz.mostrar_ayuda(
        _actualizacion(mensaje, tipo_conversacion="group"),
        _contexto(),
    )

    assert "solo atiende conversaciones privadas" in mensaje.respuestas[0][0]
    gestor.comprobar_acceso.assert_not_awaited()


@pytest.mark.asyncio
async def test_lista_selecciona_y_ejecuta_identidad(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.consultar_servidores.return_value = [_servidor()]
    gestor.consultar_servidor.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.OBTENER_IDENTIDAD)
    mensaje = MensajeSimulado()
    actualizacion = _actualizacion(mensaje)
    contexto = _contexto()

    await interfaz.mostrar_servidores(actualizacion, contexto)
    teclado = mensaje.respuestas[-1][1]
    assert teclado.inline_keyboard[0][0].callback_data == "seleccionar:7"

    contexto.args = ["7"]
    await interfaz.seleccionar_por_comando(actualizacion, contexto)
    assert contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] == 7

    await interfaz.obtener_identidad(actualizacion, contexto)
    assert "Usuario remoto: operador" in mensaje.respuestas[-1][0]
    datos = gestor.ejecutar_accion.await_args.args[4]
    assert datos.parametros == {}
    assert datos.confirmar is False


@pytest.mark.asyncio
async def test_rechaza_identificador_de_proceso_con_texto(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    mensaje = MensajeSimulado()

    await interfaz.consultar_proceso(_actualizacion(mensaje), _contexto("1;id"))

    assert mensaje.respuestas[-1][0] == "Uso correcto: /proceso <id>."
    gestor.ejecutar_accion.assert_not_awaited()


@pytest.mark.asyncio
async def test_reinicio_exige_boton_de_confirmacion_de_un_solo_uso(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_accion_sensible.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.REINICIAR_SERVIDOR)
    mensaje = MensajeSimulado()
    contexto = _contexto()
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.solicitar_reinicio(_actualizacion(mensaje), contexto)

    assert CLAVE_CONFIRMACION_REINICIO in contexto.user_data
    teclado = mensaje.respuestas[-1][1]
    datos_boton = teclado.inline_keyboard[0][0].callback_data
    consulta = ConsultaBotonSimulada(datos_boton)
    await interfaz.resolver_reinicio(
        _actualizacion(mensaje, id_actualizacion=901, consulta=consulta),
        contexto,
    )

    assert consulta.respondida is True
    assert CLAVE_CONFIRMACION_REINICIO not in contexto.user_data
    solicitud = gestor.ejecutar_accion.await_args.args[4]
    assert solicitud.confirmar is True
    assert "Reinicio programado" in mensaje.respuestas[-1][0]

    await interfaz.resolver_reinicio(
        _actualizacion(
            mensaje,
            id_actualizacion=902,
            consulta=ConsultaBotonSimulada(datos_boton),
        ),
        contexto,
    )
    assert "no es válida o ha caducado" in mensaje.respuestas[-1][0]
    assert gestor.ejecutar_accion.await_count == 1


def test_configuracion_protege_y_exige_token_telegram() -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes_pruebas",
            usuario_base_datos="usuario_pruebas",
            contrasena_base_datos="contrasena_pruebas",
            telegram_habilitado=True,
        )

    valor_token = _crear_valor_token_pruebas()
    configuracion = Configuracion(
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_pruebas",
        telegram_habilitado=True,
        token_telegram=valor_token,
    )
    assert valor_token not in repr(configuracion)


def test_construye_cliente_sin_abrir_la_red(configuracion_telegram: Configuracion) -> None:
    gestor = AsyncMock(spec=GestorTelegram)
    motor = AsyncMock(spec=AsyncEngine)

    aplicacion = crear_aplicacion_telegram(configuracion_telegram, gestor, motor)

    assert aplicacion.bot.token.endswith("12345")
    assert len(aplicacion.handlers[0]) >= 10
