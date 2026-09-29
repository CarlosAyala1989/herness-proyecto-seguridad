"""Límite local y acotado de rechazos HTTP antes de verificar contraseñas."""

from collections import deque
from time import monotonic

from aplicacion.errores import ErrorDemasiadosIntentosAutenticacion


class LimitadorIntentosAutenticacion:
    """Bloquea temporalmente un origen tras repetidos fallos de acceso."""

    def __init__(self, max_intentos: int, ventana_segundos: int) -> None:
        self.max_intentos = max_intentos
        self.ventana_segundos = ventana_segundos
        self._fallos: dict[str, deque[float]] = {}
        self._max_origenes = 1_024

    def comprobar(self, origen: str) -> None:
        ahora = monotonic()
        fallos = self._fallos.get(origen)
        if fallos is None:
            return
        while fallos and ahora - fallos[0] >= self.ventana_segundos:
            fallos.popleft()
        if not fallos:
            self._fallos.pop(origen, None)
        elif len(fallos) >= self.max_intentos:
            raise ErrorDemasiadosIntentosAutenticacion(self.ventana_segundos)

    def registrar_fallo(self, origen: str) -> None:
        self.comprobar(origen)
        if origen not in self._fallos and len(self._fallos) >= self._max_origenes:
            self._fallos.pop(next(iter(self._fallos)))
        self._fallos.setdefault(origen, deque()).append(monotonic())

    def registrar_exito(self, origen: str) -> None:
        self._fallos.pop(origen, None)
