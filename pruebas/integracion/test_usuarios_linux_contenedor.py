"""Recorrido administrativo real dentro de un Ubuntu 24.04 desechable."""

import secrets
import shutil
import subprocess
from collections.abc import Iterator
from uuid import uuid4

import pytest

from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosAccion,
    ParametrosCambioGrupoUsuarioSistema,
    ParametrosCrearUsuarioSistema,
    ParametrosNombreUsuarioSistema,
    ParametrosSinCampos,
)
from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota

IMAGEN_UBUNTU_PRUEBAS = "ubuntu:24.04"


@pytest.fixture
def contenedor_ubuntu() -> Iterator[tuple[str, str]]:
    """Inicia un contenedor exacto y garantiza su eliminación al terminar."""

    ruta_docker = shutil.which("docker")
    if ruta_docker is None:
        pytest.skip("Docker no está disponible para la prueba Linux aislada.")
    imagen = subprocess.run(  # noqa: S603
        [ruta_docker, "image", "inspect", IMAGEN_UBUNTU_PRUEBAS],
        capture_output=True,
        text=True,
        check=False,
    )
    if imagen.returncode != 0:
        pytest.skip("La imagen local ubuntu:24.04 no está disponible.")

    nombre = f"hermes-h12-{uuid4().hex[:10]}"
    subprocess.run(  # noqa: S603
        [
            ruta_docker,
            "run",
            "--rm",
            "--name",
            nombre,
            "-d",
            IMAGEN_UBUNTU_PRUEBAS,
            "sleep",
            "infinity",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        yield ruta_docker, nombre
    finally:
        subprocess.run(  # noqa: S603
            [ruta_docker, "stop", "--time", "1", nombre],
            capture_output=True,
            text=True,
            check=False,
        )


def _ejecutar_accion(
    ruta_docker: str,
    nombre_contenedor: str,
    codigo: CodigoAccion,
    parametros: ParametrosAccion,
) -> dict[str, object]:
    adaptador = AdaptadorLinux()
    accion = adaptador.preparar_accion(codigo, parametros)
    proceso = subprocess.run(  # noqa: S603
        [ruta_docker, "exec", nombre_contenedor, "sh", "-c", accion.comando],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return adaptador.interpretar_accion(
        codigo,
        ResultadoEjecucionRemota(
            proceso.returncode,
            proceso.stdout,
            proceso.stderr,
            0.01,
        ),
    )


@pytest.mark.integracion
def test_ciclo_real_de_usuario_en_ubuntu_24_04(
    contenedor_ubuntu: tuple[str, str],
) -> None:
    """Crea, agrupa, bloquea, habilita y elimina sin tocar el anfitrión."""

    ruta_docker, nombre_contenedor = contenedor_ubuntu
    subprocess.run(  # noqa: S603
        [
            ruta_docker,
            "exec",
            nombre_contenedor,
            "groupadd",
            "--gid",
            "2001",
            "operadores",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    creacion = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.CREAR_USUARIO_SISTEMA,
        ParametrosCrearUsuarioSistema(
            nombre_usuario="hermes_h12",
            nombre_mostrar="Hermes Hito 12",
        ),
    )
    assert creacion["estado"] == "deshabilitado"

    # Simula el aprovisionamiento externo de una credencial que Hermes nunca recibe.
    clave_efimera = secrets.token_urlsafe(24)
    subprocess.run(  # noqa: S603
        [ruta_docker, "exec", "-i", nombre_contenedor, "chpasswd"],
        input=f"hermes_h12:{clave_efimera}\n",
        capture_output=True,
        text=True,
        check=True,
    )
    clave_efimera = ""

    desbloqueo = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
        ParametrosNombreUsuarioSistema(nombre_usuario="hermes_h12"),
    )
    assert desbloqueo["estado"] == "habilitado"

    cambio_grupo = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        ParametrosCambioGrupoUsuarioSistema(
            nombre_usuario="hermes_h12",
            nombre_grupo="operadores",
            operacion_grupo="agregar",
        ),
    )
    assert cambio_grupo["operacion_grupo"] == "agregar"

    bloqueo = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
        ParametrosNombreUsuarioSistema(nombre_usuario="hermes_h12"),
    )
    assert bloqueo["estado"] == "bloqueado"

    _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
        ParametrosNombreUsuarioSistema(nombre_usuario="hermes_h12"),
    )
    listado = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.LISTAR_USUARIOS_SISTEMA,
        ParametrosSinCampos(),
    )
    usuarios = listado["usuarios"]
    assert isinstance(usuarios, list)
    cuenta = next(item for item in usuarios if item["nombre_usuario"] == "hermes_h12")
    assert cuenta["estado"] == "habilitado"
    assert "operadores" in cuenta["grupos"]

    eliminacion = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.ELIMINAR_USUARIO_SISTEMA,
        ParametrosNombreUsuarioSistema(nombre_usuario="hermes_h12"),
    )
    assert eliminacion["estado"] == "eliminado"
    listado_final = _ejecutar_accion(
        ruta_docker,
        nombre_contenedor,
        CodigoAccion.LISTAR_USUARIOS_SISTEMA,
        ParametrosSinCampos(),
    )
    usuarios_finales = listado_final["usuarios"]
    assert isinstance(usuarios_finales, list)
    assert all(item["nombre_usuario"] != "hermes_h12" for item in usuarios_finales)
