"""Presentación común y acotada de usuarios remotos para mensajería."""

from aplicacion.modelos.enumeraciones import SistemaOperativo


def _nombre_sistema(sistema: SistemaOperativo) -> str:
    return "Linux" if sistema is SistemaOperativo.LINUX else "Windows Server"


def _fragmentar_parrafos(parrafos: list[str], limite: int) -> list[str]:
    mensajes: list[str] = []
    actual = ""
    for parrafo in parrafos:
        pendientes = [parrafo]
        if len(parrafo) > limite:
            pendientes = [
                parrafo[inicio : inicio + limite] for inicio in range(0, len(parrafo), limite)
            ]
        for parte in pendientes:
            candidato = f"{actual}\n{parte}" if actual else parte
            if len(candidato) > limite and actual:
                mensajes.append(actual)
                actual = parte
            else:
                actual = candidato
    if actual:
        mensajes.append(actual)
    return mensajes


def formatear_listado_usuarios(
    nombre_servidor: str,
    sistema: SistemaOperativo,
    datos: dict[str, object],
    limite: int,
) -> list[str]:
    """Conserva todas las cuentas y divide la respuesta según el canal."""

    usuarios = datos.get("usuarios")
    total = datos.get("total_usuarios")
    encabezado = (
        f"Usuarios del servidor: {nombre_servidor}\n"
        f"Sistema: {_nombre_sistema(sistema)}\n"
        f"Total: {total if isinstance(total, int) else 0}"
    )
    if not isinstance(usuarios, list) or not usuarios:
        return [encabezado + "\nNo se encontraron cuentas locales."]

    parrafos = [encabezado]
    for usuario in usuarios:
        if not isinstance(usuario, dict):
            continue
        nombre = usuario.get("nombre_usuario", "No disponible")
        identificador = usuario.get("identificador", "No disponible")
        estado = usuario.get("estado", "desconocido")
        protegida = "sí" if usuario.get("cuenta_protegida") is True else "no"
        grupos = usuario.get("grupos")
        texto_grupos = (
            ", ".join(str(grupo) for grupo in grupos)
            if isinstance(grupos, list) and grupos
            else "ninguno"
        )
        parrafos.append(
            f"• {nombre} · id {identificador} · {estado} · protegida: {protegida}\n"
            f"  Grupos: {texto_grupos}"
        )
    return _fragmentar_parrafos(parrafos, limite)


def formatear_mutacion_usuario(
    nombre_servidor: str,
    sistema: SistemaOperativo,
    datos: dict[str, object],
) -> str:
    """Muestra únicamente el resultado normalizado de una mutación."""

    lineas = [
        f"Servidor: {nombre_servidor}",
        f"Sistema: {_nombre_sistema(sistema)}",
        f"Cuenta: {datos.get('nombre_usuario', 'No disponible')}",
        f"Operación: {datos.get('accion_realizada', 'actualizacion')}",
        f"Estado: {datos.get('estado', 'desconocido')}",
    ]
    nombre_grupo = datos.get("nombre_grupo")
    operacion_grupo = datos.get("operacion_grupo")
    if isinstance(nombre_grupo, str) and isinstance(operacion_grupo, str):
        lineas.extend(
            [
                f"Grupo: {nombre_grupo}",
                f"Cambio de grupo: {operacion_grupo}",
            ]
        )
    return "\n".join(lineas)
