"""Configuración privada y recuperación del instalador sin modificar el host."""

import os
import pty
import shutil
import subprocess
from getpass import getuser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dotenv import dotenv_values

from aplicacion.comandos import configurar_instalacion as asistente

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def entorno_asistente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for nombre in os.environ:
        if nombre.startswith("HERMES_"):
            monkeypatch.delenv(nombre)
    shutil.copyfile(RAIZ / ".env.ejemplo", tmp_path / ".env.ejemplo")
    return tmp_path


def responder(monkeypatch, respuestas):
    entradas = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _: next(entradas))


def test_genera_secretos_privados_y_conserva_configuracion_al_repetir(
    entorno_asistente, monkeypatch
):
    responder(monkeypatch, ["n", "n", "", ""])
    asistente.configurar()
    ruta = entorno_asistente / ".env"
    original = ruta.read_bytes()
    valores = dotenv_values(ruta)
    contrasena = valores["HERMES_CONTRASENA_BASE_DATOS"]
    assert len(contrasena) == 64
    assert contrasena != valores["HERMES_CONTRASENA_RAIZ_BASE_DATOS"]
    assert valores["HERMES_ENTORNO"] == "produccion"
    assert valores["HERMES_TELEGRAM_HABILITADO"] == "false"
    assert valores["HERMES_MONITOREO_HABILITADO"] == "true"
    assert ruta.stat().st_mode & 0o777 == 0o600
    clave = entorno_asistente / ".secretos/claves_ssh/mi_clave"
    clave.write_text("clave existente", encoding="utf-8")
    responder(monkeypatch, ["n", "n"])
    asistente.configurar()
    assert ruta.read_bytes() == original
    assert clave.read_text() == "clave existente"
    assert (entorno_asistente / ".secretos/hosts_conocidos").exists()


def test_token_no_se_imprime_y_se_reintenta_formato_invalido(
    entorno_asistente, monkeypatch, capsys
):
    token = "123456789:" + "A" * 35
    secretos = iter(["invalido", token])
    monkeypatch.setattr(asistente, "getpass", lambda _: next(secretos))
    responder(monkeypatch, ["s", "n", "n", "n"])
    asistente.configurar()
    valores = dotenv_values(".env")
    assert valores["HERMES_TOKEN_TELEGRAM"] == token
    assert valores["HERMES_TELEGRAM_HABILITADO"] == "true"
    salida = capsys.readouterr()
    assert token not in salida.out + salida.err
    assert "invalido" not in salida.out + salida.err


def test_no_cambia_credenciales_demostrativas_de_volumen_existente(entorno_asistente):
    shutil.copyfile(".env.ejemplo", ".env")
    original = Path(".env").read_bytes()
    with pytest.raises(ValueError, match="volumen ya inicializado"):
        asistente.configurar()
    assert Path(".env").read_bytes() == original


def test_no_reemplaza_env_por_enlace_simbolico(entorno_asistente):
    destino = entorno_asistente / "configuracion_ajena"
    destino.write_text("no modificar", encoding="utf-8")
    Path(".env").symlink_to(destino)
    with pytest.raises(ValueError, match="enlace simbólico"):
        asistente.configurar()
    assert destino.read_text() == "no modificar"


def test_configuracion_invalida_no_reemplaza_env_existente(entorno_asistente, monkeypatch):
    responder(monkeypatch, ["n", "n", "n", "n"])
    asistente.configurar()
    ruta = Path(".env")
    ruta.write_text(ruta.read_text().replace("HERMES_PUERTO_API=8000", "HERMES_PUERTO_API=99999"))
    original = ruta.read_bytes()
    responder(monkeypatch, ["n", "n"])
    with pytest.raises(asistente.ValidationError):
        asistente.configurar()
    assert ruta.read_bytes() == original


@pytest.fixture
def cuenta_simulada(monkeypatch):
    motor = AsyncMock()
    sesion = AsyncMock()
    sesion.__aenter__.return_value = sesion
    monkeypatch.setattr(
        asistente, "obtener_configuracion", lambda: SimpleNamespace(telegram_habilitado=True)
    )
    monkeypatch.setattr(asistente, "crear_motor_base_datos", lambda _: motor)
    monkeypatch.setattr(asistente, "crear_fabrica_sesiones", lambda _: lambda: sesion)
    crear = AsyncMock(return_value=0)
    monkeypatch.setattr(asistente, "crear_administrador", crear)
    return motor, sesion, crear


async def test_no_cambia_contrasena_de_administrador_existente(cuenta_simulada, monkeypatch):
    motor, sesion, crear = cuenta_simulada
    sesion.scalar.return_value = SimpleNamespace(
        activo=True, roles=[SimpleNamespace(nombre="administrador")]
    )
    responder(monkeypatch, [""])
    assert await asistente.preparar_administrador() == 0
    crear.assert_not_awaited()
    motor.dispose.assert_awaited_once()


@pytest.mark.parametrize("activo,roles", [(False, ["administrador"]), (True, ["operador"])])
async def test_no_promueve_usuarios_existentes(cuenta_simulada, monkeypatch, activo, roles):
    motor, sesion, crear = cuenta_simulada
    sesion.scalar.return_value = SimpleNamespace(
        activo=activo, roles=[SimpleNamespace(nombre=nombre) for nombre in roles]
    )
    responder(monkeypatch, ["operador"])
    with pytest.raises(ValueError, match="administrador activo"):
        await asistente.preparar_administrador()
    crear.assert_not_awaited()
    motor.dispose.assert_awaited_once()


async def test_crea_primera_cuenta_con_el_flujo_existente(cuenta_simulada, monkeypatch):
    _, sesion, crear = cuenta_simulada
    sesion.scalar.return_value = None
    responder(monkeypatch, ["mi_admin", "Mi administrador"])
    assert await asistente.preparar_administrador() == 0
    crear.assert_awaited_once_with("mi_admin", "Mi administrador")


@pytest.mark.parametrize("identificador", ["", "123456789"])
async def test_vincula_telegram_solo_con_un_id_explicito(
    cuenta_simulada, monkeypatch, identificador
):
    vincular = AsyncMock()
    monkeypatch.setattr(asistente, "vincular_telegram", vincular)
    responder(monkeypatch, [identificador, "mi_admin"])
    await asistente.ofrecer_vinculo()
    if identificador:
        vincular.assert_awaited_once_with("mi_admin", 123456789, None)
    else:
        vincular.assert_not_awaited()


@pytest.fixture
def instalacion_simulada(tmp_path):
    """Ejecuta el Bash real con paquetes, Docker y systemd sustituidos."""

    if os.geteuid() == 0:
        pytest.skip("El instalador requiere un usuario normal.")
    raiz = tmp_path / "hermes"
    raiz.mkdir()
    binarios = raiz / "bin"
    binarios.mkdir()
    unidades = raiz / "unidades"
    unidades.mkdir()
    (raiz / "systemd").mkdir()
    (raiz / "os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    (raiz / "pyproject.toml").touch()
    (raiz / ".env.ejemplo").touch()
    (raiz / ".env").write_text("configuracion que se conserva\n")
    venv = raiz / ".venv/bin"
    venv.mkdir(parents=True)
    ejecutable = binarios / "simular"
    ejecutable.write_text(
        "#!/usr/bin/python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "nombre = Path(sys.argv[0]).name\n"
        "argumentos = sys.argv[1:]\n"
        "with open(os.environ['REGISTRO_INSTALADOR'], 'a') as archivo:\n"
        "    archivo.write(nombre + ' ' + ' '.join(argumentos) + '\\n')\n"
        "if nombre == 'sudo':\n"
        "    if argumentos == ['-v']: sys.exit(0)\n"
        "    os.execvp(argumentos[0], argumentos)\n"
        "if nombre == 'docker' and 'up' in argumentos and os.getenv('FALLO') == 'base': sys.exit(1)\n"
        "if nombre == 'alembic' and os.getenv('FALLO') == 'migracion': sys.exit(1)\n"
        "if nombre == 'curl' and os.getenv('FALLO') == 'salud': sys.exit(1)\n"
        "if nombre == 'systemctl' and 'is-active' in argumentos and os.getenv('FALLO') == 'servicio': sys.exit(1)\n"
        "if nombre == 'python':\n"
        "    if '--puerto-api' in argumentos: print('8123')\n"
        "    if '--servicios' in argumentos: print('api true\\ntelegram true\\nslack false\\nmonitoreo true\\ntareas true')\n"
    )
    ejecutable.chmod(0o755)
    for nombre in ("sudo", "apt-get", "systemctl", "docker", "curl", "sleep"):
        (binarios / nombre).symlink_to(ejecutable)
    for nombre in ("python", "alembic", "uvicorn"):
        (venv / nombre).symlink_to(ejecutable)
    script = (RAIZ / "infraestructura/instalar_local.sh").read_text()
    for original, reemplazo in (
        ("/etc/os-release", str(raiz / "os-release")),
        ("/run/systemd/system", str(raiz / "systemd")),
        ("/etc/systemd/system", str(unidades)),
        ("/usr/bin/python3.12", str(venv / "python")),
    ):
        script = script.replace(original, reemplazo)
    (raiz / "infraestructura").mkdir()
    (raiz / "infraestructura/instalar_local.sh").write_text(script)
    entorno = dict(
        os.environ,
        PATH=f"{binarios}:{os.environ['PATH']}",
        REGISTRO_INSTALADOR=str(raiz / "registro"),
    )
    return raiz, entorno


def ejecutar_instalador(raiz, entorno):
    maestro, esclavo = pty.openpty()
    try:
        resultado = subprocess.run(  # noqa: S603
            ["/bin/bash", str(raiz / "infraestructura/instalar_local.sh")],
            stdin=esclavo,
            stdout=esclavo,
            stderr=esclavo,
            env=entorno,
            timeout=20,
            check=False,
        )
        os.close(esclavo)
        esclavo = -1
        salida = os.read(maestro, 65536).decode()
        return resultado.returncode, salida, (raiz / "registro").read_text()
    finally:
        os.close(maestro)
        if esclavo != -1:
            os.close(esclavo)


def test_bash_instala_servicios_y_puede_repetirse(instalacion_simulada):
    raiz, entorno = instalacion_simulada
    for _ in range(2):
        codigo, salida, registro = ejecutar_instalador(raiz, entorno)
        assert codigo == 0, salida
        assert "systemctl restart hermes-telegram.service" in registro
        assert "systemctl disable --now hermes-slack.service" in registro
        assert "compose --env-file .env -f infraestructura/compose.yaml up -d --wait" in registro
        assert "http://127.0.0.1:8123/salud" in registro
        unidad = (raiz / "unidades/hermes-api.service").read_text()
        assert "--host 127.0.0.1 --port 8123" in unidad
        assert f"User={getuser()}" in unidad
        assert "--reload" not in unidad
        assert (raiz / ".env").read_text() == "configuracion que se conserva\n"


@pytest.mark.parametrize("fallo", ["base", "migracion", "salud", "servicio"])
def test_bash_no_declara_exito_si_falla_una_etapa(instalacion_simulada, fallo):
    raiz, entorno = instalacion_simulada
    codigo, salida, registro = ejecutar_instalador(raiz, dict(entorno, FALLO=fallo))
    assert codigo != 0
    assert "Hermes instalado." not in salida
    if fallo == "base":
        assert "alembic -c alembic.ini upgrade head" not in registro
    if fallo in {"base", "migracion"}:
        assert "systemctl restart hermes-api.service" not in registro
