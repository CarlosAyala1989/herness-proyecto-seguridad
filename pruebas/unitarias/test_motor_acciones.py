"""Pruebas del catálogo cerrado y comandos de cada plataforma."""

from base64 import b64decode

import pytest

from aplicacion.acciones.errores import (
    ErrorAccionNoAutorizada,
    ErrorEjecucionAccion,
    ErrorParametrosAccion,
    ErrorRespuestaAccionNoValida,
    ErrorServicioNoEncontrado,
)
from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosConsultaProceso,
    ParametrosServicio,
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


@pytest.mark.parametrize(
    "nombre",
    [
        "ssh;id",
        "servicio con espacios",
        "servicio*",
        "../../servicio",
        "servicio'",
        "ñ-servicio",
        "x" * 129,
    ],
)
def test_rechaza_nombres_de_servicio_inseguros(nombre: str) -> None:
    definicion = obtener_definicion_accion(CodigoAccion.CONSULTAR_SERVICIO)

    with pytest.raises(ErrorParametrosAccion):
        definicion.validar_parametros({"nombre_servicio": nombre})


def test_acepta_nombres_internos_de_servicio_acotados() -> None:
    definicion = obtener_definicion_accion(CodigoAccion.CONSULTAR_SERVICIO)

    parametros = definicion.validar_parametros(
        {"nombre_servicio": "aplicacion-web@instancia_1.service"}
    )

    assert isinstance(parametros, ParametrosServicio)
    assert parametros.nombre_servicio == "aplicacion-web@instancia_1.service"


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


def test_diagnostico_utiliza_guiones_fijos_especificos_por_plataforma() -> None:
    parametros = ParametrosSinCampos()

    linux = AdaptadorLinux().preparar_accion(CodigoAccion.OBTENER_DIAGNOSTICO, parametros)
    windows = AdaptadorWindows().preparar_accion(
        CodigoAccion.OBTENER_DIAGNOSTICO,
        parametros,
    )
    guion_windows = b64decode(windows.comando.rsplit(maxsplit=1)[1]).decode("utf-16-le")

    assert "/proc/stat" in linux.comando
    assert "/proc/meminfo" in linux.comando
    assert "df -Pk /" in linux.comando
    assert "Get-CimInstance Win32_Processor" in guion_windows
    assert "Get-CimInstance Win32_OperatingSystem" in guion_windows
    assert "Get-CimInstance Win32_LogicalDisk" in guion_windows
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


@pytest.mark.parametrize("adaptador", [AdaptadorLinux(), AdaptadorWindows()])
def test_diagnostico_normaliza_metricas_y_campos_no_disponibles(adaptador: object) -> None:
    salida = (
        "HERMES_ACCION=obtener_diagnostico\n"
        "estado=disponible\n"
        "cpu_porcentaje=18.126\n"
        "memoria_porcentaje=42\n"
        "disco_porcentaje=no_disponible\n"
        "tiempo_actividad_segundos=90061\n"
        "sistema=Linux\n"
        "version=6.8.0-prueba\n"
        "nombre_equipo=servidor-prueba\n"
    )

    datos = adaptador.interpretar_accion(
        CodigoAccion.OBTENER_DIAGNOSTICO,
        _resultado(salida),
    )

    assert datos == {
        "estado": "disponible",
        "cpu_porcentaje": 18.13,
        "memoria_porcentaje": 42.0,
        "disco_porcentaje": None,
        "tiempo_actividad_segundos": 90061,
        "sistema": "Linux",
        "version": "6.8.0-prueba",
        "nombre_equipo": "servidor-prueba",
    }


@pytest.mark.parametrize(
    "salida",
    [
        "HERMES_ACCION=obtener_diagnostico\nestado=disponible\n",
        (
            "HERMES_ACCION=obtener_diagnostico\n"
            "estado=disponible\n"
            "cpu_porcentaje=101\n"
            "memoria_porcentaje=42\n"
            "disco_porcentaje=63\n"
            "tiempo_actividad_segundos=100\n"
            "sistema=Linux\n"
            "version=6.8\n"
            "nombre_equipo=equipo\n"
        ),
        (
            "HERMES_ACCION=obtener_diagnostico\n"
            "estado=disponible\n"
            "cpu_porcentaje=nan\n"
            "memoria_porcentaje=42\n"
            "disco_porcentaje=63\n"
            "tiempo_actividad_segundos=100\n"
            "sistema=Linux\n"
            "version=6.8\n"
            "nombre_equipo=equipo\n"
        ),
    ],
)
def test_diagnostico_rechaza_respuestas_incompletas_o_fuera_de_rango(
    salida: str,
) -> None:
    with pytest.raises(ErrorRespuestaAccionNoValida):
        AdaptadorLinux().interpretar_accion(
            CodigoAccion.OBTENER_DIAGNOSTICO,
            _resultado(salida),
        )


@pytest.mark.parametrize(
    ("codigo", "orden_linux", "orden_windows"),
    [
        (CodigoAccion.CONSULTAR_SERVICIO, "systemctl show", "Get-Service"),
        (CodigoAccion.INICIAR_SERVICIO, "systemctl start", "Start-Service"),
        (CodigoAccion.DETENER_SERVICIO, "systemctl stop", "Stop-Service"),
        (CodigoAccion.REINICIAR_SERVICIO, "systemctl restart", "Restart-Service"),
    ],
)
def test_servicios_generan_ordenes_especificas_sin_forzar_dependencias(
    codigo: CodigoAccion,
    orden_linux: str,
    orden_windows: str,
) -> None:
    parametros = ParametrosServicio(nombre_servicio="hermes-prueba.service")

    linux = AdaptadorLinux().preparar_accion(codigo, parametros)
    windows = AdaptadorWindows().preparar_accion(codigo, parametros)
    guion_windows = b64decode(windows.comando.rsplit(maxsplit=1)[1]).decode("utf-16-le")

    assert orden_linux in linux.comando
    assert orden_windows in guion_windows
    assert "hermes-prueba.service" in linux.comando
    assert "hermes-prueba.service" in guion_windows
    assert " -Force" not in guion_windows


@pytest.mark.parametrize(
    ("adaptador", "estado_nativo"),
    [
        (AdaptadorLinux(), "active"),
        (AdaptadorWindows(), "Running"),
    ],
)
@pytest.mark.parametrize(
    ("codigo", "accion_realizada"),
    [
        (CodigoAccion.CONSULTAR_SERVICIO, "consulta"),
        (CodigoAccion.INICIAR_SERVICIO, "inicio"),
        (CodigoAccion.DETENER_SERVICIO, "detencion"),
        (CodigoAccion.REINICIAR_SERVICIO, "reinicio"),
    ],
)
def test_normaliza_resultados_de_servicios_en_ambas_plataformas(
    adaptador: object,
    estado_nativo: str,
    codigo: CodigoAccion,
    accion_realizada: str,
) -> None:
    salida = (
        f"HERMES_ACCION={codigo.value}\n"
        "nombre_servicio=hermes-prueba.service\n"
        "estado=activo\n"
        f"estado_nativo={estado_nativo}\n"
        "inicio_automatico=true\n"
    )

    datos = adaptador.interpretar_accion(codigo, _resultado(salida))

    assert datos == {
        "nombre_servicio": "hermes-prueba.service",
        "estado": "activo",
        "estado_nativo": estado_nativo,
        "inicio_automatico": True,
        "accion_realizada": accion_realizada,
    }


def test_informa_servicio_inexistente_sin_exponer_salida_interna() -> None:
    with pytest.raises(ErrorServicioNoEncontrado) as captura:
        AdaptadorLinux().interpretar_accion(
            CodigoAccion.CONSULTAR_SERVICIO,
            _resultado("HERMES_ERROR=servicio_no_encontrado\n"),
        )

    assert captura.value.codigo == "servicio_no_encontrado"
    assert "secreto-que-no-debe-salir" not in captura.value.mensaje


@pytest.mark.parametrize(
    "salida",
    [
        "HERMES_ACCION=consultar_servicio\nnombre_servicio=servicio\n",
        (
            "HERMES_ACCION=consultar_servicio\n"
            "nombre_servicio=servicio;id\n"
            "estado=activo\n"
            "estado_nativo=active\n"
            "inicio_automatico=true\n"
        ),
        (
            "HERMES_ACCION=consultar_servicio\n"
            "nombre_servicio=servicio\n"
            "estado=inventado\n"
            "estado_nativo=active\n"
            "inicio_automatico=true\n"
        ),
    ],
)
def test_rechaza_respuestas_de_servicio_no_validas(salida: str) -> None:
    with pytest.raises(ErrorRespuestaAccionNoValida):
        AdaptadorLinux().interpretar_accion(
            CodigoAccion.CONSULTAR_SERVICIO,
            _resultado(salida),
        )
