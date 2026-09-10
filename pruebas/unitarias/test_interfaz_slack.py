"""Pruebas de Slack Bolt sin abrir conexiones con Slack."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from aplicacion.acciones.registro import CodigoAccion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.esquemas.acciones import (
    ResultadoAccionMultipleRespuesta,
    ResultadoAccionRespuesta,
    ResultadoServidorAccionMultiple,
    SeleccionServidores,
)
from aplicacion.esquemas.archivos import DescargaArchivo, InformacionArchivoRespuesta
from aplicacion.esquemas.inventario import ServidorResumen
from aplicacion.interfaces.slack.bot import InterfazSlack, crear_aplicacion_slack
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.servicios.gestor_slack import GestorSlack


@dataclass
class RespuestasSlack:
    """Captura llamadas compatibles con `ack` y `respond`."""

    llamadas: list[dict[str, object]] = field(default_factory=list)

    async def __call__(self, **datos: object) -> None:
        self.llamadas.append(datos)


def _configuracion() -> Configuracion:
    token_bot = "xoxb-12345678901234567890"
    token_aplicacion = "xapp-12345678901234567890"
    return Configuracion(
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_pruebas",
        slack_habilitado=True,
        token_bot_slack=token_bot,
        token_aplicacion_slack=token_aplicacion,
    )


def _comando(texto: str, canal: str = "D012ABCDEF") -> dict[str, str]:
    return {
        "command": "/hermes",
        "text": texto,
        "team_id": "T012ABCDEF",
        "user_id": "U012ABCDEF",
        "channel_id": canal,
    }


def _servidor() -> ServidorResumen:
    return ServidorResumen(
        id_servidor=7,
        nombre="ubuntu-laboratorio",
        direccion="127.0.0.1",
        puerto_ssh=22,
        sistema_operativo=SistemaOperativo.LINUX,
        activo=True,
    )


def _resultado_individual(codigo: CodigoAccion) -> ResultadoAccionRespuesta:
    datos: dict[str, object]
    if codigo is CodigoAccion.OBTENER_IDENTIDAD:
        datos = {"usuario": "operador", "nombre_equipo": "ubuntu-laboratorio"}
    elif codigo is CodigoAccion.LISTAR_USUARIOS_SISTEMA:
        datos = {
            "usuarios": [
                {
                    "nombre_usuario": "usuario_01",
                    "identificador": "1001",
                    "estado": "habilitado",
                    "cuenta_protegida": False,
                    "grupos": ["operadores"],
                }
            ],
            "total_usuarios": 1,
        }
    elif codigo is CodigoAccion.BLOQUEAR_USUARIO_SISTEMA:
        datos = {
            "nombre_usuario": "usuario_01",
            "estado": "bloqueado",
            "cuenta_protegida": False,
            "nombre_grupo": None,
            "operacion_grupo": None,
            "accion_realizada": "bloqueo",
        }
    else:
        datos = {"reinicio_programado": True, "demora_segundos": 60}
    return ResultadoAccionRespuesta(
        id_servidor=7,
        nombre_servidor="ubuntu-laboratorio",
        sistema_operativo=SistemaOperativo.LINUX,
        accion=codigo,
        datos=datos,
        duracion_ms=12,
    )


def _resultado_multiple(codigo: CodigoAccion) -> ResultadoAccionMultipleRespuesta:
    return ResultadoAccionMultipleRespuesta(
        accion=codigo,
        estado="completada_con_errores",
        total_servidores=2,
        servidores_completados=1,
        servidores_fallidos=1,
        duracion_ms=20,
        resultados=[
            ResultadoServidorAccionMultiple(
                id_servidor=7,
                nombre_servidor="ubuntu-laboratorio",
                sistema_operativo=SistemaOperativo.LINUX,
                estado="completada",
                datos={"estado": "activo"},
                duracion_ms=10,
            ),
            ResultadoServidorAccionMultiple(
                id_servidor=8,
                nombre_servidor="windows-desconectado",
                sistema_operativo=SistemaOperativo.WINDOWS_SERVER,
                estado="error",
                codigo_error="servidor_ssh_no_disponible",
                mensaje_error="El servidor no está disponible mediante SSH.",
                duracion_ms=10,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_slack_consulta_y_entrega_archivo_en_mensaje_directo(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.consultar_servidor.return_value = _servidor()
    gestor.consultar_informacion_archivo.return_value = InformacionArchivoRespuesta(
        id_servidor=7,
        nombre_servidor="ubuntu-laboratorio",
        ruta_remota="/srv/hermes/intercambio/prueba.bin",
        nombre_archivo="prueba.bin",
        tipo="archivo",
        tamano_bytes=4,
        modificado_en=datetime.now(UTC),
    )
    gestor.descargar_archivo.return_value = DescargaArchivo(
        "prueba.bin", b"dato", "/srv/hermes/intercambio/prueba.bin"
    )
    cliente_slack = SimpleNamespace(files_upload_v2=AsyncMock())
    adaptador._aplicacion = SimpleNamespace(client=cliente_slack)  # type: ignore[assignment]
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(RespuestasSlack(), _comando("seleccionar 7"), respuestas)
    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("archivo_info /srv/hermes/intercambio/prueba.bin"),
        respuestas,
    )
    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("descargar_archivo /srv/hermes/intercambio/prueba.bin"),
        respuestas,
    )

    assert "Tamaño: 4 bytes" in respuestas.llamadas[-2]["text"]
    cliente_slack.files_upload_v2.assert_awaited_once()
    assert cliente_slack.files_upload_v2.await_args.kwargs["content"] == b"dato"
    assert "se envió" in respuestas.llamadas[-1]["text"]


@pytest.fixture
def interfaz() -> tuple[InterfazSlack, AsyncMock]:
    gestor = AsyncMock(spec=GestorSlack)
    gestor.comprobar_acceso.return_value = "Administrador"
    return InterfazSlack(gestor, _configuracion()), gestor


@pytest.mark.asyncio
async def test_reconoce_antes_de_autenticar_y_restringe_a_mensaje_directo(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    orden: list[str] = []

    async def reconocer(**_: object) -> None:
        orden.append("reconocida")

    async def comprobar(*_: object) -> str:
        orden.append("autenticada")
        return "Administrador"

    gestor.comprobar_acceso.side_effect = comprobar
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(reconocer, _comando("ayuda"), respuestas)

    assert orden[:2] == ["reconocida", "autenticada"]
    assert "Uso: /hermes" in respuestas.llamadas[-1]["text"]

    await adaptador.recibir_comando(reconocer, _comando("ayuda", "C012ABCDEF"), respuestas)
    assert "solo atiende mensajes directos" in respuestas.llamadas[-1]["text"]
    assert gestor.comprobar_acceso.await_count == 1


@pytest.mark.asyncio
async def test_identidad_no_vinculada_informa_ids_sin_ejecutar(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.comprobar_acceso.side_effect = ErrorIdentidadMensajeriaNoAutorizada()
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(RespuestasSlack(), _comando("servidores"), respuestas)

    texto = respuestas.llamadas[-1]["text"]
    assert "Acceso denegado" in texto
    assert "T012ABCDEF" in texto
    assert "U012ABCDEF" in texto
    gestor.consultar_servidores.assert_not_awaited()


@pytest.mark.asyncio
async def test_seleccion_individual_reutiliza_motor_comun(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.consultar_servidor.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado_individual(CodigoAccion.OBTENER_IDENTIDAD)
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("seleccionar 7"),
        respuestas,
    )
    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("identidad"),
        respuestas,
    )

    assert "Usuario remoto: operador" in respuestas.llamadas[-1]["text"]
    argumentos = gestor.ejecutar_accion.await_args.args
    assert argumentos[0] == "T012ABCDEF:U012ABCDEF"
    assert argumentos[2:4] == (7, "obtener_identidad")


@pytest.mark.asyncio
async def test_grupo_consolida_exitos_y_fallos(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.comprobar_seleccion_multiple.return_value = 2
    gestor.ejecutar_accion_multiple.return_value = _resultado_multiple(
        CodigoAccion.OBTENER_DIAGNOSTICO
    )
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("seleccionar_grupo 3"),
        respuestas,
    )
    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("diagnostico"),
        respuestas,
    )

    texto = respuestas.llamadas[-1]["text"]
    assert "Completados: 1" in texto
    assert "OK · ubuntu-laboratorio" in texto
    assert "ERROR · windows-desconectado" in texto
    datos = gestor.ejecutar_accion_multiple.await_args.args[3]
    assert datos.seleccion.id_grupo == 3


@pytest.mark.asyncio
async def test_confirmacion_multiple_es_de_un_solo_uso_y_fija_destinos(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.comprobar_seleccion_multiple.return_value = 2
    gestor.comprobar_accion_sensible_multiple.return_value = (
        SeleccionServidores(ids_servidores=[7, 8]),
        2,
    )
    gestor.ejecutar_accion_multiple.return_value = _resultado_multiple(
        CodigoAccion.REINICIAR_SERVICIO
    )
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("seleccionar_grupo 3"),
        respuestas,
    )
    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("reiniciar_servicio ssh.service"),
        respuestas,
    )
    bloques = respuestas.llamadas[-1]["blocks"]
    codigo = bloques[1]["elements"][0]["value"]
    cuerpo = {
        "team": {"id": "T012ABCDEF"},
        "user": {"id": "U012ABCDEF"},
        "channel": {"id": "D012ABCDEF"},
        "actions": [{"action_id": "hermes_confirmar", "value": codigo}],
    }

    await adaptador.resolver_confirmacion(RespuestasSlack(), cuerpo, respuestas)

    datos = gestor.ejecutar_accion_multiple.await_args.args[3]
    assert datos.seleccion.ids_servidores == [7, 8]
    assert datos.confirmar is True

    await adaptador.resolver_confirmacion(RespuestasSlack(), cuerpo, respuestas)
    assert "no es válida o ha caducado" in respuestas.llamadas[-1]["text"]
    assert gestor.ejecutar_accion_multiple.await_count == 1


@pytest.mark.asyncio
async def test_slack_lista_usuarios_mediante_el_motor_comun(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.consultar_servidor.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado_individual(
        CodigoAccion.LISTAR_USUARIOS_SISTEMA
    )
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("seleccionar 7"),
        respuestas,
    )
    await adaptador.recibir_comando(RespuestasSlack(), _comando("usuarios"), respuestas)

    assert "usuario_01 · id 1001 · habilitado" in respuestas.llamadas[-1]["text"]
    assert gestor.ejecutar_accion.await_args.args[3] == "listar_usuarios_sistema"


@pytest.mark.asyncio
async def test_slack_bloqueo_usuario_exige_confirmacion_y_no_eleva_protegidos(
    interfaz: tuple[InterfazSlack, AsyncMock],
) -> None:
    adaptador, gestor = interfaz
    gestor.consultar_servidor.return_value = _servidor()
    gestor.comprobar_accion_sensible.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado_individual(
        CodigoAccion.BLOQUEAR_USUARIO_SISTEMA
    )
    respuestas = RespuestasSlack()

    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("seleccionar 7"),
        respuestas,
    )
    await adaptador.recibir_comando(
        RespuestasSlack(),
        _comando("bloquear_usuario usuario_01"),
        respuestas,
    )

    solicitud_previa = gestor.comprobar_accion_sensible.await_args.args[4]
    assert solicitud_previa.parametros == {
        "nombre_usuario": "usuario_01",
        "autorizar_cuenta_protegida": False,
    }
    bloques = respuestas.llamadas[-1]["blocks"]
    codigo = bloques[1]["elements"][0]["value"]
    cuerpo = {
        "team": {"id": "T012ABCDEF"},
        "user": {"id": "U012ABCDEF"},
        "channel": {"id": "D012ABCDEF"},
        "actions": [{"action_id": "hermes_confirmar", "value": codigo}],
    }
    await adaptador.resolver_confirmacion(RespuestasSlack(), cuerpo, respuestas)

    assert gestor.ejecutar_accion.await_args.args[4].confirmar is True
    assert "Estado: bloqueado" in respuestas.llamadas[-1]["text"]


def test_configuracion_slack_exige_tokens_y_los_protege() -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes_pruebas",
            usuario_base_datos="usuario_pruebas",
            contrasena_base_datos="contrasena_pruebas",
            slack_habilitado=True,
        )

    configuracion = _configuracion()
    assert "xoxb-123456789" not in repr(configuracion)
    assert "xapp-123456789" not in repr(configuracion)


def test_construye_bolt_asincrono_sin_abrir_la_red() -> None:
    gestor = AsyncMock(spec=GestorSlack)

    aplicacion = crear_aplicacion_slack(_configuracion(), gestor)

    assert len(aplicacion._async_listeners) == 3
