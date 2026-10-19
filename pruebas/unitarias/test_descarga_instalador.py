"""Descarga mediante curl real y Git local, con un asistente en una PTY."""

import fcntl
import os
import pty
import select
import shlex
import signal
import subprocess
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
REPOSITORIO = "https://github.com/CarlosAyala1989/herness-proyecto-seguridad.git"


def git_local(ruta, *argumentos):
    return subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(ruta), *argumentos],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def descarga_simulada(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("El instalador requiere un usuario normal.")
    repositorio = tmp_path / "origen"
    repositorio.mkdir()
    git_local(repositorio, "init", "--quiet", "--initial-branch=main")
    git_local(repositorio, "config", "user.name", "Pruebas Hermes")
    git_local(repositorio, "config", "user.email", "pruebas@example.invalid")
    (repositorio / "infraestructura").mkdir()
    (repositorio / ".gitignore").write_text(".env\n.secretos/\n.venv/\n")
    (repositorio / "pyproject.toml").write_text("version inicial\n")
    (repositorio / ".env.ejemplo").write_text("CONFIGURACION=ejemplo\n")
    (repositorio / "infraestructura/instalar_local.sh").write_text(
        '#!/bin/bash\nset -eu\ncd "$(dirname "$0")/.."\n'
        "[[ -t 0 ]] || exit 7\n"
        'printf "ASISTENTE_LISTO\\n"\n'
        "IFS= read -r respuesta\n"
        'printf "RESPUESTA:%s\\n" "$respuesta"\n'
        'if [[ ! -f .env ]]; then printf "secreto local\\n" > .env; fi\n'
        "mkdir -p .secretos .venv\n"
        'printf "INSTALACION_SIMULADA_COMPLETA\\n"\n'
    )
    git_local(repositorio, "add", ".")
    git_local(repositorio, "commit", "--quiet", "-m", "Versión inicial de prueba")
    binarios = tmp_path / "bin"
    binarios.mkdir()
    redireccion = f"url.{repositorio.as_uri()}.insteadOf={REPOSITORIO}"
    (binarios / "git").write_text(
        f'#!/bin/bash\nexec /usr/bin/git -c {shlex.quote(redireccion)} "$@"\n'
    )
    (binarios / "git").chmod(0o755)
    # Cualquier intento de instalar paquetes o alterar servicios falla en la prueba.
    (binarios / "sudo").write_text("#!/bin/bash\nexit 99\n")
    (binarios / "sudo").chmod(0o755)
    (tmp_path / "systemd").mkdir()
    (tmp_path / "unidades").mkdir()
    (tmp_path / "os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    script = (RAIZ / "instalar.sh").read_text()
    for original, reemplazo in (
        ("/etc/os-release", str(tmp_path / "os-release")),
        ("/run/systemd/system", str(tmp_path / "systemd")),
        ("/etc/systemd/system", str(tmp_path / "unidades")),
    ):
        script = script.replace(original, reemplazo)

    class ServidorInstalador(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            contenido = script.rsplit("}", 1)[0] if self.path.endswith("?incompleto=1") else script
            self.wfile.write(contenido.encode())

        def log_message(self, *_):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), ServidorInstalador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    entorno = dict(
        os.environ,
        PATH=f"{binarios}:{os.environ['PATH']}",
        HERMES_DIRECTORIO_INSTALACION=str(tmp_path / "instalacion"),
        HERMES_VERSION="main",
        HERMES_PRUEBA_URL=f"http://127.0.0.1:{servidor.server_port}/instalar.sh",
    )
    try:
        yield repositorio, tmp_path / "instalacion", entorno
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=2)


def ejecutar_por_curl(entorno):
    maestro, esclavo = pty.openpty()

    def terminal_controladora():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proceso = subprocess.Popen(  # noqa: S603
        ["/bin/bash", "-c", 'set -o pipefail; curl -fsSL "$HERMES_PRUEBA_URL" | bash'],
        stdin=esclavo,
        stdout=esclavo,
        stderr=esclavo,
        env=entorno,
        preexec_fn=terminal_controladora,
    )
    os.close(esclavo)
    salida = b""
    respuesta_enviada = False
    limite = time.monotonic() + 15
    try:
        while time.monotonic() < limite:
            if select.select([maestro], [], [], 0.1)[0]:
                try:
                    fragmento = os.read(maestro, 65536)
                except OSError:
                    break
                if not fragmento:
                    break
                salida += fragmento
                if b"ASISTENTE_LISTO" in salida and not respuesta_enviada:
                    os.write(maestro, b"respuesta-desde-terminal\n")
                    respuesta_enviada = True
            elif proceso.poll() is not None:
                break
        try:
            return proceso.wait(timeout=2), salida.decode()
        except subprocess.TimeoutExpired as error:
            raise AssertionError(f"El instalador quedó esperando:\n{salida.decode()}") from error
    finally:
        if proceso.poll() is None:
            os.killpg(proceso.pid, signal.SIGKILL)
            proceso.wait(timeout=2)
        os.close(maestro)


def test_curl_descarga_programa_y_asistente_lee_terminal(descarga_simulada):
    _, destino, entorno = descarga_simulada
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo == 0, salida
    assert "RESPUESTA:respuesta-desde-terminal" in salida
    assert "INSTALACION_SIMULADA_COMPLETA" in salida
    assert (destino / ".env").read_text() == "secreto local\n"
    assert git_local(destino, "remote", "get-url", "origin") == REPOSITORIO


def test_repetir_descarga_actualiza_codigo_y_conserva_secretos(descarga_simulada):
    origen, destino, entorno = descarga_simulada
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo == 0, salida
    clave = destino / ".secretos/clave"
    clave.write_text("clave que se conserva\n")
    entorno_virtual = destino / ".venv/conservar"
    entorno_virtual.touch()
    (origen / "pyproject.toml").write_text("version siguiente\n")
    git_local(origen, "add", ".")
    git_local(origen, "commit", "--quiet", "-m", "Actualizar versión de prueba")
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo == 0, salida
    assert git_local(origen, "rev-parse", "HEAD") == git_local(destino, "rev-parse", "HEAD")
    assert (destino / "pyproject.toml").read_text() == "version siguiente\n"
    assert (destino / ".env").read_text() == "secreto local\n"
    assert clave.read_text() == "clave que se conserva\n"
    assert entorno_virtual.exists()


def test_no_sobrescribe_cambios_locales(descarga_simulada):
    _, destino, entorno = descarga_simulada
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo == 0, salida
    ruta = destino / "pyproject.toml"
    ruta.write_text("cambio del usuario\n")
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo != 0
    assert "cambios locales" in salida
    assert ruta.read_text() == "cambio del usuario\n"
    assert "ASISTENTE_LISTO" not in salida


def test_descarga_fallida_no_deja_instalacion_parcial(descarga_simulada):
    _, destino, entorno = descarga_simulada
    codigo, salida = ejecutar_por_curl(dict(entorno, HERMES_VERSION="version-inexistente"))
    assert codigo != 0
    assert "ASISTENTE_LISTO" not in salida
    assert not destino.exists()
    assert not list(destino.parent.glob(".hermes-descarga.*"))


def test_version_sin_instalador_se_rechaza(descarga_simulada):
    origen, destino, entorno = descarga_simulada
    git_local(origen, "rm", "infraestructura/instalar_local.sh")
    git_local(origen, "commit", "--quiet", "-m", "Simular versión antigua")
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo != 0
    assert "instalador completo" in salida
    assert not destino.exists()


def test_no_admite_secretos_versionados(descarga_simulada):
    origen, destino, entorno = descarga_simulada
    (origen / ".env").write_text("no distribuir secretos\n")
    git_local(origen, "add", "--force", ".env")
    git_local(origen, "commit", "--quiet", "-m", "Simular versión con ruta reservada")
    codigo, salida = ejecutar_por_curl(entorno)
    assert codigo != 0
    assert "ruta local reservada" in salida
    assert not destino.exists()


def test_descarga_por_commit_explicito(descarga_simulada):
    origen, destino, entorno = descarga_simulada
    commit = git_local(origen, "rev-parse", "HEAD")
    codigo, salida = ejecutar_por_curl(dict(entorno, HERMES_VERSION=commit))
    assert codigo == 0, salida
    assert git_local(destino, "rev-parse", "HEAD") == commit


def test_script_truncado_no_ejecuta_la_instalacion(descarga_simulada):
    _, destino, entorno = descarga_simulada
    codigo, salida = ejecutar_por_curl(
        dict(entorno, HERMES_PRUEBA_URL=entorno["HERMES_PRUEBA_URL"] + "?incompleto=1")
    )
    assert codigo != 0
    assert "ASISTENTE_LISTO" not in salida
    assert not destino.exists()
