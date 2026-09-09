"""Funciones seguras para contraseñas de usuarios de Hermes."""

from pwdlib import PasswordHash

gestor_hash = PasswordHash.recommended()
hash_simulado = gestor_hash.hash("contrasena_simulada_para_igualar_tiempos")


def generar_hash_contrasena(contrasena: str) -> str:
    """Genera un hash Argon2 con los parámetros recomendados por la biblioteca."""

    return gestor_hash.hash(contrasena)


def verificar_contrasena(contrasena: str, hash_almacenado: str) -> bool:
    """Comprueba una contraseña sin recuperar nunca su valor desde el hash."""

    return gestor_hash.verify(contrasena, hash_almacenado)


def ejecutar_verificacion_simulada(contrasena: str) -> None:
    """Reduce diferencias temporales cuando el usuario consultado no existe."""

    gestor_hash.verify(contrasena, hash_simulado)
