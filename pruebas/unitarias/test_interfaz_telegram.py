"""Pruebas de la interfaz Telegram sin conectarse a Telegram."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from aplicacion.acciones.registro import CodigoAccion
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorIdentidadMensajeriaNoAutorizada
from aplicacion.esquemas.acciones import (
    ResultadoAccionMultipleRespuesta,
    ResultadoAccionRespuesta,
    ResultadoServidorAccionMultiple,
    SeleccionServidores,
)
from aplicacion.esquemas.archivos import (
    CargaArchivoRespuesta,
    DescargaArchivo,
    InformacionArchivoRespuesta,
)
from aplicacion.esquemas.inventario import ServidorResumen
from aplicacion.interfaces.telegram.bot import (
    CLAVE_CONFIRMACION_REINICIO,
    CLAVE_SELECCION_SERVIDORES,
    CLAVE_SERVIDOR_SELECCIONADO,
    InterfazTelegram,
    crear_aplicacion_telegram,
)
from aplicacion.modelos.enumeraciones import SistemaOperativo
from aplicacion.servicios.gestor_telegram import GestorTelegram


@dataclass
class MensajeSimulado:
    """Captura respuestas sin usar la red de Telegram."""

    respuestas: list[tuple[str, object | None]] = field(default_factory=list)
    documentos: list[tuple[bytes, str]] = field(default_factory=list)
    reply_to_message: object | None = None

    async def reply_text(self, texto: str, reply_markup: object | None = None) -> None:
        self.respuestas.append((texto, reply_markup))

    async def reply_document(
        self,
        document: object,
        filename: str,
        caption: str,
    ) -> None:
        self.documentos.append((document.read(), filename))


@dataclass
class ArchivoTelegramSimulado:
    contenido: bytes

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self.contenido)


@dataclass
class DocumentoTelegramSimulado:
    contenido: bytes

    @property
    def file_size(self) -> int:
        return len(self.contenido)

    async def get_file(self) -> ArchivoTelegramSimulado:
        return ArchivoTelegramSimulado(self.contenido)


@dataclass
class ConsultaBotonSimulada:
    """Representa una pulsación de botón ya recibida."""

    data: str
    respondida: bool = False

    async def answer(self) -> None:
        self.respondida = True


def _actualizacion(
    mensaje: MensajeSimulado,
    *,
    id_usuario: int = 123_456,
    id_actualizacion: int = 900,
    tipo_conversacion: str = "private",
    consulta: ConsultaBotonSimulada | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        update_id=id_actualizacion,
        effective_user=SimpleNamespace(id=id_usuario),
        effective_chat=SimpleNamespace(type=tipo_conversacion),
        effective_message=mensaje,
        callback_query=consulta,
    )


def _contexto(*argumentos: str) -> SimpleNamespace:
    return SimpleNamespace(args=list(argumentos), user_data={}, error=None)


def _crear_valor_token_pruebas() -> str:
    return "123456789:" + "TokenDemostrativoSoloParaPruebas_12345"


@pytest.fixture
def configuracion_telegram() -> Configuracion:
    return Configuracion(
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_pruebas",
        telegram_habilitado=True,
        token_telegram=_crear_valor_token_pruebas(),
    )


@pytest.fixture
def interfaz_telegram(
    configuracion_telegram: Configuracion,
) -> tuple[InterfazTelegram, AsyncMock]:
    gestor = AsyncMock(spec=GestorTelegram)
    motor = AsyncMock(spec=AsyncEngine)
    return InterfazTelegram(gestor, configuracion_telegram, motor), gestor


def _servidor() -> ServidorResumen:
    return ServidorResumen(
        id_servidor=7,
        nombre="ubuntu-laboratorio",
        direccion="127.0.0.1",
        puerto_ssh=22,
        sistema_operativo=SistemaOperativo.LINUX,
        activo=True,
    )


def _resultado(codigo: CodigoAccion) -> ResultadoAccionRespuesta:
    datos: dict[str, object]
    if codigo is CodigoAccion.OBTENER_IDENTIDAD:
        datos = {"usuario": "operador", "nombre_equipo": "ubuntu-laboratorio"}
    elif codigo is CodigoAccion.CONSULTAR_PROCESO:
        datos = {"id_proceso": 1, "nombre_proceso": "systemd"}
    elif codigo is CodigoAccion.OBTENER_DIAGNOSTICO:
        datos = {
            "estado": "disponible",
            "cpu_porcentaje": 18.12,
            "memoria_porcentaje": 42.0,
            "disco_porcentaje": None,
            "tiempo_actividad_segundos": 90_061,
            "sistema": "Linux",
            "version": "6.8.0-prueba",
            "nombre_equipo": "ubuntu-laboratorio",
        }
    elif codigo in {
        CodigoAccion.CONSULTAR_SERVICIO,
        CodigoAccion.INICIAR_SERVICIO,
        CodigoAccion.DETENER_SERVICIO,
        CodigoAccion.REINICIAR_SERVICIO,
    }:
        acciones = {
            CodigoAccion.CONSULTAR_SERVICIO: "consulta",
            CodigoAccion.INICIAR_SERVICIO: "inicio",
            CodigoAccion.DETENER_SERVICIO: "detencion",
            CodigoAccion.REINICIAR_SERVICIO: "reinicio",
        }
        datos = {
            "nombre_servicio": "ssh.service",
            "estado": "activo",
            "estado_nativo": "active",
            "inicio_automatico": True,
            "accion_realizada": acciones[codigo],
        }
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
    elif codigo in {
        CodigoAccion.CREAR_USUARIO_SISTEMA,
        CodigoAccion.CAMBIAR_GRUPO_USUARIO_SISTEMA,
        CodigoAccion.BLOQUEAR_USUARIO_SISTEMA,
        CodigoAccion.DESBLOQUEAR_USUARIO_SISTEMA,
        CodigoAccion.ELIMINAR_USUARIO_SISTEMA,
    }:
        datos = {
            "nombre_usuario": "usuario_01",
            "estado": "deshabilitado",
            "cuenta_protegida": False,
            "nombre_grupo": None,
            "operacion_grupo": None,
            "accion_realizada": "creacion",
        }
    else:
        datos = {"reinicio_programado": True, "demora_segundos": 60}
    return ResultadoAccionRespuesta(
        id_servidor=7,
        nombre_servidor="ubuntu-laboratorio",
        sistema_operativo=SistemaOperativo.LINUX,
        accion=codigo,
        datos=datos,
        duracion_ms=12.5,
    )


def _resultado_multiple(codigo: CodigoAccion) -> ResultadoAccionMultipleRespuesta:
    return ResultadoAccionMultipleRespuesta(
        accion=codigo,
        estado="completada_con_errores",
        total_servidores=2,
        servidores_completados=1,
        servidores_fallidos=1,
        duracion_ms=25,
        resultados=[
            ResultadoServidorAccionMultiple(
                id_servidor=7,
                nombre_servidor="ubuntu-laboratorio",
                sistema_operativo=SistemaOperativo.LINUX,
                estado="completada",
                datos={"usuario": "operador", "nombre_equipo": "ubuntu-laboratorio"},
                duracion_ms=12,
            ),
            ResultadoServidorAccionMultiple(
                id_servidor=8,
                nombre_servidor="windows-desconectado",
                sistema_operativo=SistemaOperativo.WINDOWS_SERVER,
                estado="error",
                codigo_error="servidor_ssh_no_disponible",
                mensaje_error="El servidor no está disponible mediante SSH.",
                duracion_ms=13,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_consulta_descarga_y_carga_archivo_sin_sobrescribir(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.consultar_informacion_archivo.return_value = InformacionArchivoRespuesta(
        id_servidor=7,
        nombre_servidor="ubuntu-laboratorio",
        ruta_remota="/srv/hermes/intercambio/prueba.txt",
        nombre_archivo="prueba.txt",
        tipo="archivo",
        tamano_bytes=9,
        modificado_en=datetime.now(UTC),
    )
    gestor.descargar_archivo.return_value = DescargaArchivo(
        "prueba.txt", b"contenido", "/srv/hermes/intercambio/prueba.txt"
    )
    gestor.cargar_archivo.return_value = CargaArchivoRespuesta(
        id_servidor=7,
        nombre_servidor="ubuntu-laboratorio",
        ruta_remota="/srv/hermes/intercambio/nuevo.txt",
        tamano_bytes=5,
        sobrescrito=False,
    )
    mensaje = MensajeSimulado()
    contexto = _contexto("/srv/hermes/intercambio/prueba.txt")
    contexto.user_data[CLAVE_SELECCION_SERVIDORES] = SeleccionServidores(ids_servidores=[7])
    actualizacion = _actualizacion(mensaje)

    await interfaz.consultar_archivo(actualizacion, contexto)
    await interfaz.descargar_archivo(actualizacion, contexto)

    mensaje.reply_to_message = SimpleNamespace(document=DocumentoTelegramSimulado(b"nuevo"))
    contexto.args = ["/srv/hermes/intercambio/nuevo.txt"]
    await interfaz.cargar_archivo(actualizacion, contexto)

    assert "Tamaño: 9 bytes" in mensaje.respuestas[0][0]
    assert mensaje.documentos == [(b"contenido", "prueba.txt")]
    assert "No se sobrescribió" in mensaje.respuestas[-1][0]
    gestor.cargar_archivo.assert_awaited_once_with(
        123_456,
        900,
        7,
        "/srv/hermes/intercambio/nuevo.txt",
        b"nuevo",
    )


@pytest.mark.asyncio
async def test_rechaza_identidad_no_vinculada_e_informa_su_identificador(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.side_effect = ErrorIdentidadMensajeriaNoAutorizada()
    mensaje = MensajeSimulado()

    await interfaz.iniciar(_actualizacion(mensaje), _contexto())

    assert "Acceso denegado" in mensaje.respuestas[0][0]
    assert "123456" in mensaje.respuestas[0][0]
    gestor.consultar_servidores.assert_not_awaited()
    gestor.ejecutar_accion.assert_not_awaited()


@pytest.mark.asyncio
async def test_rechaza_conversaciones_no_privadas(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    mensaje = MensajeSimulado()

    await interfaz.mostrar_ayuda(
        _actualizacion(mensaje, tipo_conversacion="group"),
        _contexto(),
    )

    assert "solo atiende conversaciones privadas" in mensaje.respuestas[0][0]
    gestor.comprobar_acceso.assert_not_awaited()


@pytest.mark.asyncio
async def test_lista_selecciona_y_ejecuta_identidad(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.consultar_servidores.return_value = [_servidor()]
    gestor.consultar_servidor.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.OBTENER_IDENTIDAD)
    mensaje = MensajeSimulado()
    actualizacion = _actualizacion(mensaje)
    contexto = _contexto()

    await interfaz.mostrar_servidores(actualizacion, contexto)
    teclado = mensaje.respuestas[-1][1]
    assert teclado.inline_keyboard[0][0].callback_data == "seleccionar:7"

    contexto.args = ["7"]
    await interfaz.seleccionar_por_comando(actualizacion, contexto)
    assert contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] == 7

    await interfaz.obtener_identidad(actualizacion, contexto)
    assert "Usuario remoto: operador" in mensaje.respuestas[-1][0]
    datos = gestor.ejecutar_accion.await_args.args[4]
    assert datos.parametros == {}
    assert datos.confirmar is False


@pytest.mark.asyncio
async def test_selecciona_grupo_y_consolida_resultados_individuales(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_seleccion_multiple.return_value = 2
    gestor.ejecutar_accion_multiple.return_value = _resultado_multiple(
        CodigoAccion.OBTENER_IDENTIDAD
    )
    mensaje = MensajeSimulado()
    contexto = _contexto("12")

    await interfaz.seleccionar_grupo_por_comando(_actualizacion(mensaje), contexto)

    seleccion = contexto.user_data[CLAVE_SELECCION_SERVIDORES]
    assert seleccion.id_grupo == 12
    assert CLAVE_SERVIDOR_SELECCIONADO not in contexto.user_data

    await interfaz.obtener_identidad(_actualizacion(mensaje), contexto)

    textos = "\n".join(texto for texto, _ in mensaje.respuestas)
    assert "Completados: 1" in textos
    assert "ubuntu-laboratorio: completada" in textos
    assert "windows-desconectado: El servidor no está disponible" in textos
    solicitud = gestor.ejecutar_accion_multiple.await_args.args[3]
    assert solicitud.seleccion.id_grupo == 12
    gestor.ejecutar_accion.assert_not_awaited()


@pytest.mark.asyncio
async def test_selecciona_todos_sin_aceptar_argumentos(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_seleccion_multiple.return_value = 4
    mensaje = MensajeSimulado()
    contexto = _contexto()

    await interfaz.seleccionar_todos(_actualizacion(mensaje), contexto)

    seleccion = contexto.user_data[CLAVE_SELECCION_SERVIDORES]
    assert seleccion.todos is True
    assert "todos los servidores activos (4)" in mensaje.respuestas[-1][0]

    await interfaz.seleccionar_todos(_actualizacion(mensaje), _contexto("adicional"))
    assert mensaje.respuestas[-1][0] == "Uso correcto: /seleccionar_todos."
    assert gestor.comprobar_seleccion_multiple.await_count == 1


@pytest.mark.asyncio
async def test_muestra_diagnostico_uniforme_y_metricas_no_disponibles(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.OBTENER_DIAGNOSTICO)
    mensaje = MensajeSimulado()
    contexto = _contexto()
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.obtener_diagnostico(_actualizacion(mensaje), contexto)

    texto = mensaje.respuestas[-1][0]
    assert "Estado: Disponible" in texto
    assert "CPU: 18.12 %" in texto
    assert "RAM: 42.00 %" in texto
    assert "Disco: No disponible" in texto
    assert "Tiempo de actividad: 1 d, 1 h, 1 min" in texto
    assert gestor.ejecutar_accion.await_args.args[3] == "obtener_diagnostico"


@pytest.mark.asyncio
async def test_rechaza_identificador_de_proceso_con_texto(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    mensaje = MensajeSimulado()

    await interfaz.consultar_proceso(_actualizacion(mensaje), _contexto("1;id"))

    assert mensaje.respuestas[-1][0] == "Uso correcto: /proceso <id>."
    gestor.ejecutar_accion.assert_not_awaited()

    await interfaz.consultar_proceso(_actualizacion(mensaje), _contexto("9" * 5_000))
    assert mensaje.respuestas[-1][0] == "Uso correcto: /proceso <id>."
    gestor.ejecutar_accion.assert_not_awaited()


@pytest.mark.asyncio
async def test_reinicio_exige_boton_de_confirmacion_de_un_solo_uso(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_accion_sensible.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.REINICIAR_SERVIDOR)
    mensaje = MensajeSimulado()
    contexto = _contexto()
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.solicitar_reinicio(_actualizacion(mensaje), contexto)

    assert CLAVE_CONFIRMACION_REINICIO in contexto.user_data
    teclado = mensaje.respuestas[-1][1]
    datos_boton = teclado.inline_keyboard[0][0].callback_data
    consulta = ConsultaBotonSimulada(datos_boton)
    await interfaz.resolver_reinicio(
        _actualizacion(mensaje, id_actualizacion=901, consulta=consulta),
        contexto,
    )

    assert consulta.respondida is True
    assert CLAVE_CONFIRMACION_REINICIO not in contexto.user_data
    solicitud = gestor.ejecutar_accion.await_args.args[4]
    assert solicitud.confirmar is True
    assert "Reinicio programado" in mensaje.respuestas[-1][0]

    await interfaz.resolver_reinicio(
        _actualizacion(
            mensaje,
            id_actualizacion=902,
            consulta=ConsultaBotonSimulada(datos_boton),
        ),
        contexto,
    )
    assert "no es válida o ha caducado" in mensaje.respuestas[-1][0]
    assert gestor.ejecutar_accion.await_count == 1


@pytest.mark.asyncio
async def test_consulta_servicio_y_muestra_estado_normalizado(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.CONSULTAR_SERVICIO)
    mensaje = MensajeSimulado()
    contexto = _contexto("ssh.service")
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.consultar_servicio(_actualizacion(mensaje), contexto)

    texto = mensaje.respuestas[-1][0]
    assert "Servicio: ssh.service" in texto
    assert "Estado del servicio: Activo" in texto
    assert "Inicio automático: Sí" in texto
    solicitud = gestor.ejecutar_accion.await_args.args[4]
    assert solicitud.parametros == {"nombre_servicio": "ssh.service"}
    assert solicitud.confirmar is False


@pytest.mark.asyncio
async def test_gestion_servicio_exige_confirmacion_ligada_y_de_un_solo_uso(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_accion_sensible.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.REINICIAR_SERVICIO)
    mensaje = MensajeSimulado()
    contexto = _contexto("ssh.service")
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.reiniciar_servicio(_actualizacion(mensaje), contexto)

    teclado = mensaje.respuestas[-1][1]
    datos_boton = teclado.inline_keyboard[0][0].callback_data
    assert datos_boton.startswith("accion:confirmar:")
    consulta = ConsultaBotonSimulada(datos_boton)
    await interfaz.resolver_accion_sensible(
        _actualizacion(mensaje, id_actualizacion=903, consulta=consulta),
        contexto,
    )

    assert consulta.respondida is True
    solicitud = gestor.ejecutar_accion.await_args.args[4]
    assert solicitud.parametros == {"nombre_servicio": "ssh.service"}
    assert solicitud.confirmar is True
    assert "Operación: Reinicio" in mensaje.respuestas[-1][0]

    await interfaz.resolver_accion_sensible(
        _actualizacion(
            mensaje,
            id_actualizacion=904,
            consulta=ConsultaBotonSimulada(datos_boton),
        ),
        contexto,
    )
    assert "no es válida o ha caducado" in mensaje.respuestas[-1][0]
    assert gestor.ejecutar_accion.await_count == 1


@pytest.mark.asyncio
async def test_confirmacion_multiple_fija_destinos_antes_de_ejecutar(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_accion_sensible_multiple.return_value = (
        SeleccionServidores(ids_servidores=[7, 8]),
        2,
    )
    gestor.ejecutar_accion_multiple.return_value = _resultado_multiple(
        CodigoAccion.REINICIAR_SERVICIO
    )
    mensaje = MensajeSimulado()
    contexto = _contexto("ssh.service")
    contexto.user_data[CLAVE_SELECCION_SERVIDORES] = SeleccionServidores(id_grupo=12)

    await interfaz.reiniciar_servicio(_actualizacion(mensaje), contexto)

    assert "2 servidores" in mensaje.respuestas[-1][0]
    assert "destinos ya quedaron fijados" in mensaje.respuestas[-1][0]
    datos_boton = mensaje.respuestas[-1][1].inline_keyboard[0][0].callback_data
    await interfaz.resolver_accion_sensible(
        _actualizacion(
            mensaje,
            id_actualizacion=905,
            consulta=ConsultaBotonSimulada(datos_boton),
        ),
        contexto,
    )

    solicitud = gestor.ejecutar_accion_multiple.await_args.args[3]
    assert solicitud.seleccion.ids_servidores == [7, 8]
    assert solicitud.confirmar is True


@pytest.mark.asyncio
async def test_rechaza_sintaxis_de_servicio_antes_de_crear_confirmacion(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    mensaje = MensajeSimulado()

    await interfaz.detener_servicio(_actualizacion(mensaje), _contexto())

    assert mensaje.respuestas[-1][0] == "Uso correcto: /detener_servicio <nombre>."
    gestor.comprobar_accion_sensible.assert_not_awaited()


@pytest.mark.asyncio
async def test_lista_usuarios_locales_con_estado_y_grupos(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.LISTAR_USUARIOS_SISTEMA)
    mensaje = MensajeSimulado()
    contexto = _contexto()
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.mostrar_usuarios_sistema(_actualizacion(mensaje), contexto)

    texto = mensaje.respuestas[-1][0]
    assert "Usuarios del servidor: ubuntu-laboratorio" in texto
    assert "usuario_01 · id 1001 · habilitado" in texto
    assert "Grupos: operadores" in texto
    assert gestor.ejecutar_accion.await_args.args[3] == "listar_usuarios_sistema"


@pytest.mark.asyncio
async def test_creacion_usuario_no_recibe_contrasena_y_exige_confirmacion(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_accion_sensible.return_value = _servidor()
    gestor.ejecutar_accion.return_value = _resultado(CodigoAccion.CREAR_USUARIO_SISTEMA)
    mensaje = MensajeSimulado()
    contexto = _contexto("usuario_01", "Usuario", "de", "prueba")
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.crear_usuario_sistema(_actualizacion(mensaje), contexto)

    solicitud_previa = gestor.comprobar_accion_sensible.await_args.args[4]
    assert solicitud_previa.parametros == {
        "nombre_usuario": "usuario_01",
        "nombre_mostrar": "Usuario de prueba",
    }
    assert "contrasena" not in solicitud_previa.parametros
    datos_boton = mensaje.respuestas[-1][1].inline_keyboard[0][0].callback_data
    await interfaz.resolver_accion_sensible(
        _actualizacion(
            mensaje,
            id_actualizacion=906,
            consulta=ConsultaBotonSimulada(datos_boton),
        ),
        contexto,
    )

    solicitud_final = gestor.ejecutar_accion.await_args.args[4]
    assert solicitud_final.confirmar is True
    assert "Cuenta: usuario_01" in mensaje.respuestas[-1][0]


@pytest.mark.asyncio
async def test_grupo_con_espacios_se_envia_sin_habilitar_cuentas_protegidas(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    gestor.comprobar_accion_sensible.return_value = _servidor()
    contexto = _contexto("usuario_01", "soporte", "local")
    contexto.user_data[CLAVE_SERVIDOR_SELECCIONADO] = 7

    await interfaz.agregar_usuario_grupo(_actualizacion(MensajeSimulado()), contexto)

    solicitud = gestor.comprobar_accion_sensible.await_args.args[4]
    assert solicitud.parametros == {
        "nombre_usuario": "usuario_01",
        "nombre_grupo": "soporte local",
        "operacion_grupo": "agregar",
        "autorizar_cuenta_protegida": False,
    }


def test_configuracion_protege_y_exige_token_telegram() -> None:
    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes_pruebas",
            usuario_base_datos="usuario_pruebas",
            contrasena_base_datos="contrasena_pruebas",
            telegram_habilitado=True,
        )

    valor_token = _crear_valor_token_pruebas()
    configuracion = Configuracion(
        nombre_base_datos="hermes_pruebas",
        usuario_base_datos="usuario_pruebas",
        contrasena_base_datos="contrasena_pruebas",
        telegram_habilitado=True,
        token_telegram=valor_token,
    )
    assert valor_token not in repr(configuracion)

    with pytest.raises(ValidationError):
        Configuracion(
            nombre_base_datos="hermes_pruebas",
            usuario_base_datos="usuario_pruebas",
            contrasena_base_datos="contrasena_pruebas",
            telegram_habilitado=True,
            token_telegram=valor_token + "\nno_valido",
        )


def test_construye_cliente_sin_abrir_la_red(configuracion_telegram: Configuracion) -> None:
    gestor = AsyncMock(spec=GestorTelegram)
    motor = AsyncMock(spec=AsyncEngine)

    aplicacion = crear_aplicacion_telegram(configuracion_telegram, gestor, motor)

    assert aplicacion.bot.token.endswith("12345")
    assert len(aplicacion.handlers[0]) >= 10


@pytest.mark.asyncio
async def test_limita_solicitudes_antes_de_consultar_base_datos(
    interfaz_telegram: tuple[InterfazTelegram, AsyncMock],
) -> None:
    interfaz, gestor = interfaz_telegram
    gestor.comprobar_acceso.return_value = "Administrador"
    mensaje = MensajeSimulado()
    actualizacion = _actualizacion(mensaje)

    for _ in range(31):
        await interfaz.mostrar_ayuda(actualizacion, _contexto())

    assert "límite temporal" in mensaje.respuestas[-1][0]
    assert gestor.comprobar_acceso.await_count == 30
