"""Pruebas de validación y adaptación de usuarios locales remotos."""

from base64 import b64decode

import pytest

from aplicacion.acciones.errores import (
    ErrorCuentaOperadorSSH,
    ErrorCuentaSistemaProtegida,
    ErrorGestorUsuariosNoDisponible,
    ErrorGrupoSistemaNoEncontrado,
    ErrorParametrosAccion,
    ErrorRespuestaAccionNoValida,
    ErrorUsuarioSistemaNoEncontrado,
    ErrorUsuarioSistemaYaExiste,
)
from aplicacion.acciones.registro import (
    CodigoAccion,
    ParametrosCambioGrupoUsuarioSistema,
    ParametrosCrearUsuarioSistema,
    ParametrosNombreUsuarioSistema,
    ParametrosSinCampos,
    obtener_definicion_accion,
)
from aplicacion.adaptadores.linux import AdaptadorLinux
from aplicacion.adaptadores.windows import AdaptadorWindows
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota


def _resultado(salida: str, codigo: int = 0) -> ResultadoEjecucionRemota:
    return ResultadoEjecucionRemota(codigo, salida, "detalle interno reservado", 0.01)


def _decodificar_powershell(comando: str) -> str:
    return b64decode(comando.rsplit(maxsplit=1)[1]).decode("utf-16-le")


@pytest.mark.parametrize(
    "nombre_usuario",
    [
        "usuario;id",
        "usuario con espacio",
        "../usuario",
        "usuario*",
        "usuario'",
        "usuario-",
        "usuario.",
        "ñusuario",
        "u" * 21,
    ],
)
def test_rechaza_nombres_de_usuario_inseguros_o_no_portables(
    nombre_usuario: str,
) -> None:
    definicion = obtener_definicion_accion(CodigoAccion.BLOQUEAR_USUARIO_SISTEMA)

    with pytest.raises(ErrorParametrosAccion):
        definicion.validar_parametros({"nombre_usuario": nombre_usuario})


def test_normaliza_datos_no_secretos_de_creacion() -> None:
    definicion = obtener_definicion_accion(CodigoAccion.CREAR_USUARIO_SISTEMA)

    parametros = definicion.validar_parametros(
        {"nombre_usuario": "operador_02", "nombre_mostrar": "  Operador   de pruebas  "}
    )

    assert isinstance(parametros, ParametrosCrearUsuarioSistema)
    assert parametros.nombre_mostrar == "Operador de pruebas"
    with pytest.raises(ErrorParametrosAccion):
        definicion.validar_parametros(
            {"nombre_usuario": "operador_02", "contrasena": "secreto-no-admitido"}
        )


def test_autorizacion_de_cuenta_protegida_exige_booleano_estricto_y_permiso() -> None:
    definicion = obtener_definicion_accion(CodigoAccion.ELIMINAR_USUARIO_SISTEMA)

    parametros = definicion.validar_parametros(
        {"nombre_usuario": "usuario_01", "autorizar_cuenta_protegida": True}
    )

    assert isinstance(parametros, ParametrosNombreUsuarioSistema)
    assert definicion.obtener_permisos_adicionales(parametros) == (
        "gestionar_usuarios_sistema",
        "gestionar_usuarios_protegidos",
    )
    with pytest.raises(ErrorParametrosAccion):
        definicion.validar_parametros(
            {"nombre_usuario": "usuario_01", "autorizar_cuenta_protegida": "true"}
        )


def test_todas_las_mutaciones_requieren_confirmacion() -> None:
    mutaciones = {
        CodigoAccion.CREAR_USUARIO_SISTEMA,
        CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
        CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
        CodigoAccion.ELIMINAR_USUARIO_SISTEMA,
    }

    assert all(obtener_definicion_accion(codigo).requiere_confirmacion for codigo in mutaciones)
    assert not obtener_definicion_accion(CodigoAccion.LISTAR_USUARIOS_SISTEMA).requiere_confirmacion


def test_linux_prepara_operaciones_controladas_sin_recibir_contrasenas() -> None:
    adaptador = AdaptadorLinux()
    creacion = adaptador.preparar_accion(
        CodigoAccion.CREAR_USUARIO_SISTEMA,
        ParametrosCrearUsuarioSistema(
            nombre_usuario="usuario_01", nombre_mostrar="Usuario de prueba"
        ),
    ).comando
    agregar = adaptador.preparar_accion(
        CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        ParametrosCambioGrupoUsuarioSistema(
            nombre_usuario="usuario_01",
            nombre_grupo="operadores",
            operacion_grupo="agregar",
        ),
    ).comando
    bloqueo = adaptador.preparar_accion(
        CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
        ParametrosNombreUsuarioSistema(nombre_usuario="usuario_01"),
    ).comando
    eliminacion = adaptador.preparar_accion(
        CodigoAccion.ELIMINAR_USUARIO_SISTEMA,
        ParametrosNombreUsuarioSistema(nombre_usuario="usuario_01"),
    ).comando

    assert "useradd" in creacion and "--expiredate 1" in creacion
    assert "usermod --append --groups" in agregar
    assert "usermod --lock --expiredate 1" in bloqueo
    assert "userdel --remove" in eliminacion
    assert "shell=True" not in "\n".join((creacion, agregar, bloqueo, eliminacion))


def test_windows_prepara_cmdlets_locales_documentados() -> None:
    adaptador = AdaptadorWindows()
    listado = _decodificar_powershell(
        adaptador.preparar_accion(
            CodigoAccion.LISTAR_USUARIOS_SISTEMA, ParametrosSinCampos()
        ).comando
    )
    creacion = _decodificar_powershell(
        adaptador.preparar_accion(
            CodigoAccion.CREAR_USUARIO_SISTEMA,
            ParametrosCrearUsuarioSistema(nombre_usuario="usuario_01"),
        ).comando
    )
    cambio = _decodificar_powershell(
        adaptador.preparar_accion(
            CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
            ParametrosCambioGrupoUsuarioSistema(
                nombre_usuario="usuario_01",
                nombre_grupo="Remote Desktop Users",
                operacion_grupo="quitar",
            ),
        ).comando
    )
    desbloqueo = _decodificar_powershell(
        adaptador.preparar_accion(
            CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
            ParametrosNombreUsuarioSistema(nombre_usuario="usuario_01"),
        ).comando
    )

    assert "Get-LocalUser" in listado
    assert "Get-LocalGroupMember -Group $_" in listado
    assert "New-LocalUser" in creacion
    assert "-NoPassword" in creacion and "-Disabled" in creacion
    assert "Remove-LocalGroupMember -Group $grupo" in cambio
    assert "Enable-LocalUser -InputObject $usuario" in desbloqueo


@pytest.mark.parametrize("adaptador", [AdaptadorLinux(), AdaptadorWindows()])
def test_normaliza_listado_de_usuarios_y_grupos(adaptador: object) -> None:
    salida = (
        "HERMES_ACCION=listar_usuarios_sistema\n"
        "USUARIO|root|0|bloqueado|true\n"
        "GRUPO|root|root\n"
        "USUARIO|operador_01|1001|habilitado|false\n"
        "GRUPO|operador_01|operadores\n"
        "GRUPO|operador_01|soporte local\n"
    )

    datos = adaptador.interpretar_accion(
        CodigoAccion.LISTAR_USUARIOS_SISTEMA,
        _resultado(salida),
    )

    assert datos == {
        "usuarios": [
            {
                "nombre_usuario": "root",
                "identificador": "0",
                "estado": "bloqueado",
                "cuenta_protegida": True,
                "grupos": ["root"],
            },
            {
                "nombre_usuario": "operador_01",
                "identificador": "1001",
                "estado": "habilitado",
                "cuenta_protegida": False,
                "grupos": ["operadores", "soporte local"],
            },
        ],
        "total_usuarios": 2,
    }


@pytest.mark.parametrize("adaptador", [AdaptadorLinux(), AdaptadorWindows()])
def test_normaliza_resultado_de_mutacion(adaptador: object) -> None:
    salida = (
        "HERMES_ACCION=cambiar_grupo_usuario_sistema\n"
        "nombre_usuario=usuario_01\n"
        "estado=actualizado\n"
        "cuenta_protegida=false\n"
        "nombre_grupo=operadores\n"
        "operacion_grupo=agregar\n"
    )

    datos = adaptador.interpretar_accion(
        CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        _resultado(salida),
    )

    assert datos["accion_realizada"] == "cambio_grupo"
    assert datos["nombre_usuario"] == "usuario_01"
    assert datos["nombre_grupo"] == "operadores"
    assert datos["operacion_grupo"] == "agregar"


@pytest.mark.parametrize(
    ("marcador", "tipo_error"),
    [
        ("usuario_sistema_no_encontrado", ErrorUsuarioSistemaNoEncontrado),
        ("usuario_sistema_ya_existe", ErrorUsuarioSistemaYaExiste),
        ("grupo_sistema_no_encontrado", ErrorGrupoSistemaNoEncontrado),
        ("gestor_usuarios_no_disponible", ErrorGestorUsuariosNoDisponible),
        ("cuenta_sistema_protegida", ErrorCuentaSistemaProtegida),
        ("cuenta_operador_ssh", ErrorCuentaOperadorSSH),
    ],
)
def test_interpreta_errores_controlados_sin_exponer_stderr(
    marcador: str,
    tipo_error: type[Exception],
) -> None:
    with pytest.raises(tipo_error):
        AdaptadorLinux().interpretar_accion(
            CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
            _resultado(f"HERMES_ERROR={marcador}\n"),
        )


def test_rechaza_respuestas_de_usuario_ambiguas_o_incompletas() -> None:
    salida = (
        "HERMES_ACCION=crear_usuario_sistema\nnombre_usuario=usuario_01\nestado=deshabilitado\n"
    )

    with pytest.raises(ErrorRespuestaAccionNoValida):
        AdaptadorLinux().interpretar_accion(
            CodigoAccion.CREAR_USUARIO_SISTEMA,
            _resultado(salida),
        )
