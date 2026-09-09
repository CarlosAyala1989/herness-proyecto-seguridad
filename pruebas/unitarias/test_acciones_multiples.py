"""Pruebas de los contratos seguros para acciones sobre varios destinos."""

import pytest
from pydantic import ValidationError

from aplicacion.esquemas.acciones import (
    SeleccionServidores,
    SolicitudEjecucionMultiple,
)


@pytest.mark.parametrize(
    "seleccion",
    [
        {"ids_servidores": [1, 2, 3, 4]},
        {"id_grupo": 7},
        {"todos": True},
    ],
)
def test_acepta_una_unica_estrategia_de_seleccion(
    seleccion: dict[str, object],
) -> None:
    solicitud = SolicitudEjecucionMultiple(seleccion=seleccion)

    assert isinstance(solicitud.seleccion, SeleccionServidores)
    assert solicitud.como_solicitud_individual().parametros == {}


@pytest.mark.parametrize(
    "seleccion",
    [
        {},
        {"todos": False},
        {"todos": True, "id_grupo": 7},
        {"ids_servidores": [1], "id_grupo": 7},
        {"ids_servidores": [1, 1]},
        {"ids_servidores": []},
        {"ids_servidores": [True]},
        {"id_grupo": "7"},
        {"todos": "sí"},
    ],
)
def test_rechaza_selecciones_ambiguas_o_no_estrictas(
    seleccion: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SolicitudEjecucionMultiple(seleccion=seleccion)


def test_rechaza_campos_adicionales_en_solicitud_multiple() -> None:
    with pytest.raises(ValidationError):
        SolicitudEjecucionMultiple(
            seleccion={"todos": True},
            comando="id",
        )


def test_conserva_parametros_y_confirmacion_para_cada_destino() -> None:
    solicitud = SolicitudEjecucionMultiple(
        seleccion={"ids_servidores": [1, 2]},
        parametros={"nombre_servicio": "ssh.service"},
        confirmar=True,
    )

    individual = solicitud.como_solicitud_individual()

    assert individual.parametros == {"nombre_servicio": "ssh.service"}
    assert individual.confirmar is True
