"""Límites de acceso HTTP sin depender de servicios externos."""

import pytest

from aplicacion.errores import ErrorDemasiadosIntentosAutenticacion
from aplicacion.seguridad import limite_autenticacion
from aplicacion.seguridad.limite_autenticacion import LimitadorIntentosAutenticacion


def test_bloquea_fallos_y_restaura_cupo_tras_ventana(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instante = 100.0
    monkeypatch.setattr(limite_autenticacion, "monotonic", lambda: instante)
    limitador = LimitadorIntentosAutenticacion(2, 60)
    limitador.registrar_fallo("127.0.0.1")
    limitador.registrar_fallo("127.0.0.1")
    with pytest.raises(ErrorDemasiadosIntentosAutenticacion):
        limitador.comprobar("127.0.0.1")
    limitador.comprobar("192.0.2.10")

    instante += 61
    limitador.comprobar("127.0.0.1")
    limitador.registrar_fallo("127.0.0.1")
    limitador.registrar_exito("127.0.0.1")
    limitador.comprobar("127.0.0.1")
