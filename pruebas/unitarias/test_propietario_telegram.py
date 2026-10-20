"""El propietario se fija localmente y ningún otro ID puede ejecutar órdenes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from aplicacion.comandos import vincular_usuario_telegram as comando
from aplicacion.configuracion import Configuracion
from aplicacion.configuracion_local import fijar_propietario_telegram
from aplicacion.errores import ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.esquemas.acciones import SolicitudEjecucionAccion
from aplicacion.monitoreo.notificaciones import NotificadorTelegram, crear_notificadores
from aplicacion.servicios.gestor_telegram import GestorTelegram


def configuracion(propietario):
    return Configuracion(
        _env_file=None,
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_pruebas",
        id_propietario_telegram=propietario,
    )


@pytest.mark.parametrize("valor", [0, -1, 2**63, "@usuario", True])
def test_configuracion_rechaza_propietarios_invalidos(valor):
    with pytest.raises(ValidationError):
        configuracion(valor)


@pytest.mark.parametrize("valor", [None, ""])
def test_sin_propietario_no_se_infiere_ninguno(valor):
    assert configuracion(valor).id_propietario_telegram is None


@pytest.mark.parametrize("propietario", [None, 123456789])
@pytest.mark.parametrize(
    "operacion", ["comprobar_acceso", "consultar_servidores", "ejecutar_accion"]
)
async def test_no_propietario_no_alcanza_permisos_ni_ssh(monkeypatch, propietario, operacion):
    sesion = AsyncMock(spec=AsyncSession)
    sesion.__aenter__.return_value = sesion
    resolver = AsyncMock(return_value=SimpleNamespace(nombre_mostrar="Administrador activo"))
    monkeypatch.setattr(
        "aplicacion.servicios.gestor_mensajeria.obtener_usuario_por_identidad", resolver
    )
    transporte = Mock()
    gestor = GestorTelegram(lambda: sesion, transporte, configuracion(propietario))
    argumentos = [987654321, 4010]
    if operacion == "ejecutar_accion":
        argumentos += [1, "obtener_identidad", SolicitudEjecucionAccion()]
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await getattr(gestor, operacion)(*argumentos)
    resolver.assert_not_awaited()
    transporte.assert_not_called()
    sesion.commit.assert_awaited_once()
    sesion.add.assert_called_once()


async def test_propietario_todavia_necesita_vinculo_activo(monkeypatch):
    sesion = AsyncMock(spec=AsyncSession)
    sesion.__aenter__.return_value = sesion
    resolver = AsyncMock(side_effect=ErrorIdentidadMensajeriaNoAutorizada())
    monkeypatch.setattr(
        "aplicacion.servicios.gestor_mensajeria.obtener_usuario_por_identidad", resolver
    )
    gestor = GestorTelegram(lambda: sesion, Mock(), configuracion(123456789))
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await gestor.comprobar_acceso(123456789, 4011)
    resolver.assert_awaited_once()


def test_guardar_propietario_conserva_secretos_y_permisos(tmp_path):
    ruta = tmp_path / ".env"
    original = "HERMES_TOKEN_TELEGRAM=token_local\n# conservar comentario\n"
    ruta.write_text(original)
    fijar_propietario_telegram(123456789, ruta)
    fijar_propietario_telegram(987654321, ruta)
    assert ruta.read_text().startswith(original)
    assert dotenv_values(ruta)["HERMES_ID_PROPIETARIO_TELEGRAM"] == "987654321"
    assert ruta.read_text().count("HERMES_ID_PROPIETARIO_TELEGRAM=") == 1
    assert ruta.stat().st_mode & 0o777 == 0o600


async def test_comando_local_fija_propietario_despues_de_vincular(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    sesion = AsyncMock(spec=AsyncSession)
    sesion.__aenter__.return_value = sesion
    motor = AsyncMock()
    monkeypatch.setattr(comando, "obtener_configuracion", lambda: configuracion(None))
    monkeypatch.setattr(comando, "crear_motor_base_datos", lambda _: motor)
    monkeypatch.setattr(comando, "crear_fabrica_sesiones", lambda _: lambda: sesion)
    vincular = AsyncMock(return_value=SimpleNamespace(id_identidad_mensajeria=1))
    monkeypatch.setattr(comando, "vincular_identidad_telegram", vincular)
    await comando.ejecutar("mi_admin", 123456789, None)
    assert dotenv_values(".env")["HERMES_ID_PROPIETARIO_TELEGRAM"] == "123456789"
    assert "Propietario único" in capsys.readouterr().out
    motor.dispose.assert_awaited_once()


@pytest.mark.parametrize("propietario", [None, 123456789])
async def test_alertas_no_se_envian_a_otros_usuarios(propietario):
    notificador = NotificadorTelegram("123456789:token_demostrativo_solo_pruebas", propietario)
    bot = AsyncMock()
    notificador._bot = bot
    with pytest.raises(ErrorIdentidadMensajeriaNoAutorizada):
        await notificador.enviar_mensaje("987654321", "Alerta privada")
    bot.initialize.assert_not_awaited()
    bot.send_message.assert_not_awaited()


async def test_alertas_solo_se_envian_al_propietario():
    notificador = NotificadorTelegram("123456789:token_demostrativo_solo_pruebas", 123456789)
    bot = AsyncMock()
    notificador._bot = bot
    await notificador.enviar_mensaje("123456789", "Alerta privada")
    bot.send_message.assert_awaited_once_with(chat_id=123456789, text="Alerta privada")


def test_sin_propietario_no_se_crea_notificador_telegram():
    cfg = configuracion(None).model_copy(
        update={
            "telegram_habilitado": True,
            "token_telegram": configuracion(None).contrasena_base_datos,
        }
    )
    assert crear_notificadores(cfg) == {}
