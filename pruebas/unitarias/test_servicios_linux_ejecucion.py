"""Ejecuta los guiones reales contra herramientas aisladas, sin servicios del host."""

import os
import subprocess

import pytest

from aplicacion.acciones.errores import ErrorEjecucionAccion
from aplicacion.acciones.registro import CodigoAccion, ParametrosServicio
from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota


@pytest.fixture
def herramientas_servicios(tmp_path):
    guiones = {
        "id": '#!/bin/sh\nprintf "%s\\n" "$HERMES_PRUEBA_UID"\n',
        "sudo": '#!/bin/sh\nshift\nexec "$@"\n',
        "systemctl": """#!/bin/sh
case "$1" in
 start|stop|restart)
    [ "$HERMES_PRUEBA_FALLO" = 0 ] || exit 42
    estado=active
    [ "$1" != stop ] || estado=inactive
    printf '%s' "$estado" > "$HERMES_PRUEBA_ESTADO"
    ;;
 show)
    printf 'LoadState=loaded\\nActiveState=%s\\nUnitFileState=disabled\\n' "$(cat "$HERMES_PRUEBA_ESTADO")"
    ;;
 *) exit 99 ;;
esac
""",
    }
    for nombre, contenido in guiones.items():
        ruta = tmp_path / nombre
        ruta.write_text(contenido)
        ruta.chmod(0o700)
    estado = tmp_path / "estado"
    estado.write_text("active")
    return tmp_path, estado


@pytest.mark.parametrize("uid", ["0", "1000"])
@pytest.mark.parametrize("fallar", [False, True])
@pytest.mark.parametrize(
    "codigo",
    [CodigoAccion.INICIAR_SERVICIO, CodigoAccion.DETENER_SERVICIO, CodigoAccion.REINICIAR_SERVICIO],
)
def test_servicios_solo_informan_exito_si_la_operacion_lo_tuvo(
    herramientas_servicios, uid, fallar, codigo
):
    directorio, archivo_estado = herramientas_servicios
    entorno = dict(os.environ)
    entorno.update(
        PATH=f"{directorio}:/usr/bin:/bin",
        HERMES_PRUEBA_UID=uid,
        HERMES_PRUEBA_FALLO="1" if fallar else "0",
        HERMES_PRUEBA_ESTADO=str(archivo_estado),
    )
    adaptador = AdaptadorLinux()
    accion = adaptador.preparar_accion(
        codigo, ParametrosServicio(nombre_servicio="hermes-prueba.service")
    )
    proceso = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", accion.comando], env=entorno, capture_output=True, text=True, check=False
    )
    resultado = ResultadoEjecucionRemota(proceso.returncode, proceso.stdout, proceso.stderr, 0.01)
    if fallar:
        with pytest.raises(ErrorEjecucionAccion):
            adaptador.interpretar_accion(codigo, resultado)
        assert proceso.returncode == 42
        assert "HERMES_ACCION=" not in proceso.stdout
    else:
        datos = adaptador.interpretar_accion(codigo, resultado)
        assert datos["estado"] == (
            "inactivo" if codigo == CodigoAccion.DETENER_SERVICIO else "activo"
        )
