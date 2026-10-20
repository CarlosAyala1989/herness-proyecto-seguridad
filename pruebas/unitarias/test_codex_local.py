"""Pruebas del puente a Codex con procesos reales de prueba y sin consumir cuota."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorPermisoDenegado
from aplicacion.interfaces.telegram.ia import CLAVE_IA, InterfazIATelegram
from aplicacion.servicios.codex_local import CodexLocal, ErrorCodexLocal, ModeloCodex

MODELO = ModeloCodex("modelo-prueba", "Modelo de prueba", ("low", "high"))


@pytest.fixture
def configuracion_ia(tmp_path: Path) -> Configuracion:
    ejecutable = tmp_path / "codex-pruebas"
    ejecutable.write_text(
        """#!/usr/bin/python3
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
if args == ["login", "status"]:
    print("autenticado")
elif args == ["debug", "models"]:
    print(json.dumps({"models": [
        {"slug":"modelo-prueba", "display_name":"Modelo de prueba", "visibility":"list",
         "supported_reasoning_levels":[{"effort":"low"},{"effort":"high"}]},
        {"slug":"oculto", "visibility":"hide"}
    ]}))
else:
    prompt = sys.stdin.read()
    if prompt == "esperar":
        time.sleep(60)
    if prompt == "hijo":
        ruta = pathlib.Path(args[args.index("--cd") + 1]) / "hijo.pid"
        subprocess.Popen([sys.executable, "-c", "import os, pathlib, signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)", str(ruta)])
        time.sleep(60)
    if prompt == "fallar":
        print("secreto interno", file=sys.stderr)
        sys.exit(2)
    destino = pathlib.Path(args[args.index("--output-last-message") + 1])
    destino.write_text(json.dumps({"argumentos":args, "prompt":prompt,
        "hermes_en_entorno":any(k.startswith("HERMES_") for k in os.environ)}, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    ejecutable.chmod(0o700)
    return Configuracion(
        _env_file=None,
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="pruebas",
        contrasena_base_datos="pruebas",
        ia_habilitada=True,
        id_propietario_telegram=123456,
        ejecutable_codex=str(ejecutable),
        directorio_trabajo_ia=tmp_path,
    )


async def test_catalogo_y_ejecucion_respetan_modelo_esfuerzo_stdin_y_permisos(
    configuracion_ia, monkeypatch
):
    codex = CodexLocal(configuracion_ia)
    monkeypatch.setenv("HERMES_TOKEN_TELEGRAM", "no-heredar")
    assert await codex.listar_modelos() == [MODELO]
    instruccion = "--model ajeno; $(touch NO_CREAR) `touch TAMPOCO`"
    respuesta = json.loads(await codex.ejecutar(MODELO, "high", instruccion))
    assert respuesta["prompt"] == instruccion
    assert respuesta["hermes_en_entorno"] is False
    argumentos = respuesta["argumentos"]
    assert "--dangerously-bypass-approvals-and-sandbox" in argumentos
    assert argumentos[argumentos.index("--model") + 1] == MODELO.identificador
    assert 'model_reasoning_effort="high"' in argumentos
    assert argumentos[-1] == "-"
    assert not (configuracion_ia.directorio_trabajo_ia / "NO_CREAR").exists()
    assert codex.ocupado is False


async def test_fallo_cli_no_expone_su_salida(configuracion_ia):
    codex = CodexLocal(configuracion_ia)
    with pytest.raises(ErrorCodexLocal, match="terminó con un error") as error:
        await codex.ejecutar(MODELO, "low", "fallar")
    assert "secreto interno" not in str(error.value)
    assert not codex.ocupado


async def test_tiempo_limite_termina_el_proceso_y_libera_ocupacion(configuracion_ia):
    cfg = configuracion_ia.model_copy(update={"tiempo_limite_ia_segundos": 0.1})
    codex = CodexLocal(cfg)
    with pytest.raises(ErrorCodexLocal, match="tiempo límite"):
        await codex.ejecutar(MODELO, "low", "esperar")
    assert not codex.ocupado
    assert json.loads(await codex.ejecutar(MODELO, "low", "otra tarea"))["prompt"] == "otra tarea"


async def test_cancelacion_interrumpe_y_no_admite_tareas_simultaneas(configuracion_ia):
    codex = CodexLocal(configuracion_ia)
    tarea = asyncio.create_task(codex.ejecutar(MODELO, "low", "esperar"))
    await asyncio.sleep(0)
    assert codex.ocupado
    with pytest.raises(ErrorCodexLocal, match="Ya hay una tarea"):
        await codex.ejecutar(MODELO, "low", "segunda")
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea
    assert not codex.ocupado


async def test_cancelar_termina_tambien_un_hijo_que_ignora_sigterm(configuracion_ia):
    codex = CodexLocal(configuracion_ia)
    tarea = asyncio.create_task(codex.ejecutar(MODELO, "low", "hijo"))
    archivo_pid = configuracion_ia.directorio_trabajo_ia / "hijo.pid"
    try:
        for _ in range(100):
            if archivo_pid.exists():
                break
            await asyncio.sleep(0.01)
        assert archivo_pid.exists()
        pid = int(archivo_pid.read_text())
    finally:
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    def terminado():
        estado = Path(f"/proc/{pid}/stat")
        return not estado.exists() or estado.read_text().split()[2] == "Z"

    for _ in range(100):
        if await asyncio.to_thread(terminado):
            break
        await asyncio.sleep(0.01)
    assert await asyncio.to_thread(terminado)


@pytest.mark.parametrize("esfuerzo,prompt", [("ultra", "hola"), ("low", " "), ("low", "a" * 16001)])
async def test_valida_entrada_sin_arrancar_cli(configuracion_ia, esfuerzo, prompt):
    codex = CodexLocal(configuracion_ia)
    with pytest.raises(ErrorCodexLocal):
        await codex.ejecutar(MODELO, esfuerzo, prompt)
    assert not codex.ocupado


async def test_binario_ausente_da_error_comprensible(configuracion_ia):
    configuracion_ia.ejecutable_codex = "/no-existe/codex"
    with pytest.raises(ErrorCodexLocal, match="ruta, Node.js"):
        await CodexLocal(configuracion_ia).listar_modelos()


@pytest.fixture
def interfaz_ia(configuracion_ia):
    gestor = SimpleNamespace(registrar_ia=AsyncMock())
    autorizar = AsyncMock(return_value=(123456, 900, "Administrador"))
    interfaz = InterfazIATelegram(gestor, configuracion_ia, autorizar)
    mensaje = SimpleNamespace(
        reply_text=AsyncMock(), reply_document=AsyncMock(), text="texto libre"
    )
    actualizacion = SimpleNamespace(effective_message=mensaje, callback_query=None)
    contexto = SimpleNamespace(args=[], user_data={})
    return interfaz, gestor, autorizar, actualizacion, contexto


async def _elegir_modelo_y_esfuerzo(interfaz, actualizacion, contexto):
    await interfaz.comando(actualizacion, contexto)
    boton = actualizacion.effective_message.reply_text.call_args.kwargs[
        "reply_markup"
    ].inline_keyboard[0][0]
    actualizacion.callback_query = SimpleNamespace(data=boton.callback_data, answer=AsyncMock())
    await interfaz.elegir(actualizacion, contexto)
    boton = actualizacion.effective_message.reply_text.call_args.kwargs[
        "reply_markup"
    ].inline_keyboard[1][0]
    actualizacion.callback_query.data = boton.callback_data
    await interfaz.elegir(actualizacion, contexto)
    assert contexto.user_data[CLAVE_IA] == (MODELO, "high")


async def test_menu_modelo_esfuerzo_tarea_y_salida(interfaz_ia):
    interfaz, gestor, autorizar, actualizacion, contexto = interfaz_ia
    await _elegir_modelo_y_esfuerzo(interfaz, actualizacion, contexto)
    contexto.args = ["Consulta", "Ubuntu"]
    await interfaz.comando(actualizacion, contexto)
    await interfaz._tarea
    assert (
        '"prompt": "Consulta Ubuntu"'
        in actualizacion.effective_message.reply_text.call_args.args[0]
    )
    assert gestor.registrar_ia.call_args.args[2] == "completada"
    contexto.args = ["salir"]
    await interfaz.comando(actualizacion, contexto)
    assert CLAVE_IA not in contexto.user_data
    autorizar.assert_awaited()


@pytest.mark.parametrize("denegacion", ["sin_vinculo", "sin_rol", "deshabilitada"])
async def test_denegacion_no_consulta_modelos_ni_ejecuta(interfaz_ia, denegacion):
    interfaz, gestor, autorizar, actualizacion, contexto = interfaz_ia
    interfaz._codex.listar_modelos = AsyncMock()
    if denegacion == "sin_vinculo":
        autorizar.return_value = None
    elif denegacion == "sin_rol":
        gestor.registrar_ia.side_effect = ErrorPermisoDenegado("administrador_ia")
    else:
        interfaz._configuracion.ia_habilitada = False
    await interfaz.comando(actualizacion, contexto)
    interfaz._codex.listar_modelos.assert_not_awaited()
    assert interfaz._tarea is None


async def test_botones_viejos_y_mensajes_fuera_del_modo_no_ejecutan(interfaz_ia):
    interfaz, gestor, autorizar, actualizacion, contexto = interfaz_ia
    await interfaz.texto(actualizacion, contexto)
    autorizar.assert_not_awaited()
    actualizacion.callback_query = SimpleNamespace(data="ia:viejo:modelo:0", answer=AsyncMock())
    await interfaz.elegir(actualizacion, contexto)
    assert "caducó" in actualizacion.effective_message.reply_text.call_args.args[0]
    assert interfaz._tarea is None


async def test_texto_libre_estado_y_detener_mantienen_bot_receptivo(interfaz_ia):
    interfaz, gestor, autorizar, actualizacion, contexto = interfaz_ia
    contexto.user_data[CLAVE_IA] = (MODELO, "low")
    actualizacion.effective_message.text = "esperar"
    await interfaz.texto(actualizacion, contexto)
    tarea = interfaz._tarea
    contexto.args = ["estado"]
    await interfaz.comando(actualizacion, contexto)
    assert "en ejecución" in actualizacion.effective_message.reply_text.call_args.args[0]
    contexto.args = ["detener"]
    await interfaz.comando(actualizacion, contexto)
    assert tarea.cancelled()
    assert "detenida" in actualizacion.effective_message.reply_text.call_args.args[0]


async def test_no_entrega_respuesta_si_se_revoca_acceso_durante_tarea(interfaz_ia):
    interfaz, gestor, autorizar, actualizacion, contexto = interfaz_ia
    interfaz._codex.ejecutar = AsyncMock(return_value="respuesta privada")
    gestor.registrar_ia.side_effect = ErrorPermisoDenegado("administrador_ia")
    await interfaz._ejecutar(
        actualizacion, (123456, 900, "Administrador"), MODELO, "low", "consulta"
    )
    actualizacion.effective_message.reply_text.assert_not_awaited()
    actualizacion.effective_message.reply_document.assert_not_awaited()


async def test_respuesta_larga_se_entrega_como_markdown(interfaz_ia):
    interfaz, gestor, autorizar, actualizacion, contexto = interfaz_ia
    interfaz._codex.ejecutar = AsyncMock(return_value="respuesta " * 600)
    await interfaz._ejecutar(
        actualizacion, (123456, 900, "Administrador"), MODELO, "low", "consulta"
    )
    assert (
        actualizacion.effective_message.reply_document.call_args.kwargs["filename"]
        == "respuesta_codex.md"
    )
