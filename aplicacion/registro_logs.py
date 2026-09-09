"""Configuración central de registros de la aplicación."""

import logging
import sys


def configurar_logs(nivel: str) -> None:
    """Configura una salida legible y uniforme hacia la salida estándar."""

    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # Evita que bibliotecas externas registren direcciones, usuarios o comandos.
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
