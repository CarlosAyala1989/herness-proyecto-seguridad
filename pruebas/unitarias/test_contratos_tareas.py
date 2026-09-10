"""Pruebas de contratos temporales sin abrir red ni MariaDB."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aplicacion.configuracion import Configuracion
from aplicacion.esquemas.tareas import CrearTareaProgramada


def _datos_validos() -> dict[str, object]:
    return {
        "nombre": "Consulta periódica de identidad",
        "codigo_accion": "obtener_identidad",
        "seleccion": {"ids_servidores": [1, 2]},
        "tipo_programacion": "intervalo",
        "programada_para": datetime.now(UTC) + timedelta(minutes=1),
        "intervalo_segundos": 300,
    }


def test_normaliza_nombre_y_acepta_fecha_con_zona() -> None:
    datos = _datos_validos()
    datos["nombre"] = "  Consulta   periódica  "

    tarea = CrearTareaProgramada.model_validate(datos)

    assert tarea.nombre == "Consulta periódica"
    assert tarea.intervalo_segundos == 300


@pytest.mark.parametrize(
    "cambios",
    [
        {"programada_para": datetime.now()},
        {"tipo_programacion": "una_vez", "intervalo_segundos": 60},
        {"tipo_programacion": "intervalo", "intervalo_segundos": None},
        {"intervalo_segundos": 59},
        {"seleccion": {"ids_servidores": [1, 1]}},
        {"descripcion": "texto\x00no imprimible"},
        {"campo_ajeno": "comando libre"},
    ],
)
def test_rechaza_calendarios_y_campos_no_validos(cambios: dict[str, object]) -> None:
    datos = _datos_validos()
    datos.update(cambios)

    with pytest.raises(ValidationError):
        CrearTareaProgramada.model_validate(datos)


def test_exige_bloqueo_mayor_que_tiempo_limite() -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes_pruebas",
            usuario_base_datos="hermes_pruebas",
            contrasena_base_datos="solo-pruebas",
            tiempo_limite_accion_multiple_segundos=60,
            duracion_bloqueo_tarea_segundos=60,
        )
