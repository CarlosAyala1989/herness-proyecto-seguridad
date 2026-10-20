"""Adaptación del Codex CLI instalado, sin shell ni credenciales propias."""

import asyncio
import json
import os
import re
import signal
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from aplicacion.configuracion import Configuracion


class ErrorCodexLocal(Exception):
    """Fallo comunicable sin volcar la salida interna del CLI ni sus secretos."""


@dataclass(frozen=True)
class ModeloCodex:
    identificador: str
    nombre: str
    esfuerzos: tuple[str, ...]


class CodexLocal:
    """Ejecuta una tarea cada vez con los permisos del usuario del servicio."""

    def __init__(self, configuracion: Configuracion) -> None:
        self.configuracion = configuracion
        self._ocupado = False

    @property
    def ocupado(self) -> bool:
        return self._ocupado

    @staticmethod
    def _entorno() -> dict[str, str]:
        # La autenticación sigue en CODEX_HOME; el hijo no necesita tokens de Hermes
        # ni identificadores internos de la conversación que arrancó el servicio.
        return {
            clave: valor
            for clave, valor in os.environ.items()
            if not clave.startswith("HERMES_")
            and (not clave.startswith("CODEX_") or clave == "CODEX_HOME")
        }

    async def _consultar(self, *argumentos: str) -> bytes:
        proceso = None
        try:
            proceso = await asyncio.create_subprocess_exec(
                self.configuracion.ejecutable_codex,
                *argumentos,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=self._entorno(),
                start_new_session=True,
            )
            salida, _ = await asyncio.wait_for(proceso.communicate(), timeout=30)
            if proceso.returncode or len(salida) > 2_000_000:
                raise ErrorCodexLocal(
                    "Codex no está disponible. Revisa su instalación y codex login desde la terminal."
                )
            return salida
        except (OSError, TimeoutError) as error:
            raise ErrorCodexLocal(
                "No se pudo consultar Codex CLI. Revisa la ruta, Node.js y la autenticación local."
            ) from error
        finally:
            if proceso is not None and proceso.returncode is None:
                await self._terminar(proceso)

    async def listar_modelos(self) -> list[ModeloCodex]:
        await self._consultar("login", "status")
        salida = await self._consultar("debug", "models")
        try:
            catalogo = json.loads(salida)
            modelos = []
            for modelo in catalogo["models"]:
                if modelo.get("visibility") != "list":
                    continue
                identificador = modelo["slug"]
                esfuerzos = tuple(nivel["effort"] for nivel in modelo["supported_reasoning_levels"])
                if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}", identificador):
                    continue
                if not esfuerzos or not all(
                    re.fullmatch(r"[a-z_]{1,20}", valor) for valor in esfuerzos
                ):
                    continue
                modelos.append(
                    ModeloCodex(identificador, modelo.get("display_name", identificador), esfuerzos)
                )
            if not modelos:
                raise ValueError("catálogo vacío")
            return modelos[:30]
        except (ValueError, KeyError, TypeError) as error:
            raise ErrorCodexLocal(
                "La versión de Codex no devuelve un catálogo compatible de modelos."
            ) from error

    @staticmethod
    async def _terminar(proceso: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(proceso.pid, signal.SIGTERM)
        except ProcessLookupError:
            await proceso.wait()
            return
        try:
            await asyncio.wait_for(proceso.wait(), timeout=5)
        except TimeoutError:
            pass
        finally:
            # Un hijo puede ignorar SIGTERM aunque el proceso Codex ya haya salido.
            try:
                os.killpg(proceso.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proceso.wait()

    async def ejecutar(self, modelo: ModeloCodex, esfuerzo: str, instruccion: str) -> str:
        if esfuerzo not in modelo.esfuerzos:
            raise ErrorCodexLocal("El esfuerzo no está disponible para ese modelo.")
        if not instruccion.strip() or len(instruccion) > 16_000:
            raise ErrorCodexLocal("La instrucción debe contener entre 1 y 16000 caracteres.")
        if self._ocupado:
            raise ErrorCodexLocal(
                "Ya hay una tarea de IA en curso. Usa /ia detener antes de iniciar otra."
            )
        self._ocupado = True
        proceso = None
        try:
            with TemporaryDirectory(prefix="hermes-codex-") as temporal:
                destino = Path(temporal) / "respuesta.txt"
                proceso = await asyncio.create_subprocess_exec(
                    self.configuracion.ejecutable_codex,
                    "exec",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "--color",
                    "never",
                    "--model",
                    modelo.identificador,
                    "--config",
                    f'model_reasoning_effort="{esfuerzo}"',
                    "--cd",
                    str(self.configuracion.directorio_trabajo_ia),
                    "--output-last-message",
                    str(destino),
                    "-",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=self._entorno(),
                    start_new_session=True,
                )
                try:
                    await asyncio.wait_for(
                        proceso.communicate(input=instruccion.encode("utf-8")),
                        timeout=self.configuracion.tiempo_limite_ia_segundos,
                    )
                finally:
                    if proceso.returncode is None:
                        await self._terminar(proceso)
                if proceso.returncode:
                    raise ErrorCodexLocal(
                        "Codex terminó con un error. Comprueba autenticación, cuota y compatibilidad del modelo desde la terminal."
                    )
                with destino.open("rb") as respuesta:
                    contenido = respuesta.read(65_537)
                texto = contenido[:65_536].decode("utf-8", errors="replace").strip()
                if len(contenido) > 65_536:
                    texto += "\n[Respuesta recortada a 64 KiB.]"
                return texto or "Codex completó la tarea sin respuesta de texto."
        except TimeoutError as error:
            raise ErrorCodexLocal(
                "La tarea alcanzó su tiempo límite y se detuvo. Los cambios ya realizados se conservan."
            ) from error
        except OSError as error:
            raise ErrorCodexLocal(
                "No se pudo ejecutar Codex o leer su respuesta. Revisa la instalación local."
            ) from error
        finally:
            self._ocupado = False
