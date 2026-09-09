"""Pruebas del catálogo cerrado y comandos de cada plataforma."""

import pytest

from aplicacion.acciones.errores import (
    ErrorAccionNoAutorizada,
    ErrorEjecucionAccion,
    ErrorParametrosAccion,
)
from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosConsultaProceso,
    ParametrosSinCampos,
    listar_definiciones_acciones,
    obtener_definicion_accion,
)
from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.adaptadores.windows import AdaptadorWindows
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota


def _resultado(salida: str, codigo: int = 0) -> ResultadoEjecucionRemota:
    return ResultadoEjecucionRemota(codigo, salida, "secreto-que-no-debe-salir", 0.01)


def test_catalogo_solo_contiene_acciones_predefinidas() -> None:
    definiciones = listar_definiciones_acciones()

    assert {item.codigo for item in definiciones} == set(CodigoAccion)
    with pytest.raises(ErrorAccionNoAutorizada):
        obtener_definicion_accion("id; apagar_servidor")


def test_valida_parametros_especificos_y_rechaza_campos_adicionales() -> None:
    definicion = obtener_definicion_accion(CodigoAccion.CONSULTAR_PROCESO)

    parametros = definicion.validar_parametros({"id_proceso": 123})
    assert isinstance(parametros, ParametrosConsultaProceso)
    assert parametros.id_proceso == 123

    with pytest.raises(ErrorParametrosAccion):
        definicion.validar_parametros({"id_proceso": "123; id"})
    with pytest.raises(ErrorParametrosAccion):
        definicion.validar_parametros({"id_proceso": 123, "comando": "id"})


@pytest.mark.parametrize("adaptador", [AdaptadorLinux(), AdaptadorWindows()])
def test_consulta_proceso_solo_interpola_un_entero_validado(adaptador: object) -> None:
    parametros = ParametrosConsultaProceso(id_proceso=321)

    accion = adaptador.preparar_accion(CodigoAccion.CONSULTAR_PROCESO, parametros)

    assert "321" in accion.comando
    assert "id_proceso" not in accion.comando


def test_linux_y_windows_utilizan_comandos_diferentes() -> None:
    parametros = ParametrosSinCampos()

    linux = AdaptadorLinux().preparar_accion(CodigoAccion.OBTENER_IDENTIDAD, parametros)
    windows = AdaptadorWindows().preparar_accion(
        CodigoAccion.OBTENER_IDENTIDAD,
        parametros,
    )

    assert "id -un" in linux.comando
    assert "powershell.exe" in windows.comando
    assert linux.comando != windows.comando


def test_normaliza_identidad_y_proceso_en_ambas_plataformas() -> None:
    identidad_linux = AdaptadorLinux().interpretar_accion(
        CodigoAccion.OBTENER_IDENTIDAD,
        _resultado("HERMES_ACCION=obtener_identidad\noperador\nlinux-01\n"),
    )
    identidad_windows = AdaptadorWindows().interpretar_accion(
        CodigoAccion.OBTENER_IDENTIDAD,
        _resultado("HERMES_ACCION=obtener_identidad\r\nOperador\r\nWIN-01\r\n"),
    )
    proceso_linux = AdaptadorLinux().interpretar_accion(
        CodigoAccion.CONSULTAR_PROCESO,
        _resultado("HERMES_ACCION=consultar_proceso\n123 python\n"),
    )
    proceso_windows = AdaptadorWindows().interpretar_accion(
        CodigoAccion.CONSULTAR_PROCESO,
        _resultado("HERMES_ACCION=consultar_proceso\r\n123\r\npython\r\n"),
    )

    assert identidad_linux == {"usuario": "operador", "nombre_equipo": "linux-01"}
    assert identidad_windows == {"usuario": "Operador", "nombre_equipo": "WIN-01"}
    assert proceso_linux == {"id_proceso": 123, "nombre_proceso": "python"}
    assert proceso_windows == {"id_proceso": 123, "nombre_proceso": "python"}


def test_error_remoto_no_expone_salida_de_error() -> None:
    with pytest.raises(ErrorEjecucionAccion) as captura:
        AdaptadorLinux().interpretar_accion(
            CodigoAccion.OBTENER_IDENTIDAD,
            _resultado("", codigo=7),
        )

    assert captura.value.detalles == [{"codigo_salida": "7"}]
    assert "secreto-que-no-debe-salir" not in captura.value.mensaje
