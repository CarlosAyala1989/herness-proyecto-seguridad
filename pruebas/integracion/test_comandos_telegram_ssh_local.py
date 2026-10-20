"""Recorrido opcional con el SSH real del anfitrión y MariaDB desechable."""

import os
from getpass import getuser
from types import SimpleNamespace
from uuid import uuid4

import asyncssh
import pytest
from sqlalchemy import delete, select

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.transporte_ssh import crear_transporte_ssh
from aplicacion.configuracion import Configuracion
from aplicacion.interfaces.telegram.bot import InterfazTelegram
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.despliegue import (
    AplicacionAdministrada,
    DespliegueAplicacion,
    PlantillaDespliegue,
)
from aplicacion.modelos.enumeraciones import (
    SistemaOperativo,
    TipoCredencialConexion,
    TipoPlantillaDespliegue,
)
from aplicacion.modelos.grupo_servidor import GrupoServidor
from aplicacion.modelos.ruta_archivo_permitida import RutaArchivoPermitida
from aplicacion.modelos.servidor import Servidor
from aplicacion.seguridad.contrasenas import generar_hash_contrasena
from aplicacion.servicios.gestor_identidades_mensajeria import vincular_identidad_telegram
from aplicacion.servicios.gestor_telegram import GestorTelegram
from pruebas.unitarias.test_interfaz_telegram import (
    ConsultaBotonSimulada,
    DocumentoTelegramSimulado,
    MensajeSimulado,
    _actualizacion,
    _contexto,
)


@pytest.mark.integracion
async def test_comandos_de_inventario_archivos_y_despliegues_con_ssh_real(tmp_path):
    if os.environ.get("HERMES_VALIDAR_SSH_LOCAL") != "true":
        pytest.skip("Requiere habilitación explícita del laboratorio SSH local.")
    cfg = Configuracion()
    if not cfg.nombre_base_datos.startswith("hermes_validacion_"):
        pytest.skip("Este recorrido exige una base de validación desechable.")
    cfg.id_propietario_telegram = 700_000_002
    motor = crear_motor_base_datos(cfg)
    fabrica = crear_fabrica_sesiones(motor)
    nombre = f"validacion-{uuid4().hex[:8]}"
    destino = tmp_path / "aplicacion.txt"
    destino.write_bytes(b"version anterior")
    artefacto = tmp_path / "artefacto.txt"
    artefacto.write_bytes(b"version nueva")
    try:
        async with fabrica() as sesion:
            rol = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
            usuario = Usuario(
                nombre_usuario=nombre,
                nombre_mostrar="Validación SSH",
                hash_contrasena=generar_hash_contrasena(uuid4().hex),
                activo=True,
                roles=[rol],
            )
            grupo = GrupoServidor(nombre=nombre)
            servidor = Servidor(
                nombre=nombre,
                direccion="127.0.0.1",
                puerto_ssh=22,
                usuario_conexion=getuser(),
                sistema_operativo=SistemaOperativo.LINUX,
                tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
                referencia_credencial="archivo:hermes_maquina_local",
                huella_clave_host=asyncssh.read_public_key(
                    "/etc/ssh/ssh_host_ed25519_key.pub"
                ).get_fingerprint("sha256"),
                activo=True,
                grupos=[grupo],
            )
            plantilla = PlantillaDespliegue(
                nombre=nombre,
                sistema_operativo=SistemaOperativo.LINUX,
                tipo=TipoPlantillaDespliegue.ARCHIVO_UNICO,
                ruta_destino=str(destino),
                activo=True,
            )
            sesion.add_all([usuario, servidor, plantilla])
            await sesion.flush()
            aplicacion = AplicacionAdministrada(
                nombre=nombre,
                id_servidor=servidor.id_servidor,
                id_plantilla_despliegue=plantilla.id_plantilla_despliegue,
                activo=True,
            )
            sesion.add_all(
                [
                    aplicacion,
                    RutaArchivoPermitida(
                        id_servidor=servidor.id_servidor,
                        ruta=str(tmp_path),
                        permite_lectura=True,
                        permite_escritura=True,
                        activo=True,
                    ),
                ]
            )
            await sesion.commit()
            await vincular_identidad_telegram(sesion, nombre, cfg.id_propietario_telegram)
            id_servidor, id_grupo, id_app = (
                servidor.id_servidor,
                grupo.id_grupo,
                aplicacion.id_aplicacion_administrada,
            )
        gestor = GestorTelegram(fabrica, lambda servidor: crear_transporte_ssh(servidor, cfg), cfg)
        interfaz = InterfazTelegram(gestor, cfg, motor)
        mensaje = MensajeSimulado()
        contexto = _contexto()
        actualizacion = _actualizacion(mensaje, id_usuario=cfg.id_propietario_telegram)

        async def enviar(metodo, *argumentos):
            contexto.args = list(argumentos)
            await getattr(interfaz, metodo)(actualizacion, contexto)
            assert mensaje.respuestas
            respuesta = mensaje.respuestas[-1][0]
            assert not any(
                error in respuesta
                for error in (
                    "No fue posible",
                    "No se puede",
                    "Acceso denegado",
                    "Uso correcto",
                    "límite temporal",
                )
            ), respuesta
            return respuesta

        await enviar("mostrar_servidores")
        assert any(
            nombre in boton.text
            for fila in mensaje.respuestas[-1][1].inline_keyboard
            for boton in fila
        )
        await enviar("mostrar_grupos")
        assert any(
            nombre in boton.text
            for fila in mensaje.respuestas[-1][1].inline_keyboard
            for boton in fila
        )
        await enviar("seleccionar_grupo_por_comando", str(id_grupo))
        assert f"Grupo seleccionado: id {id_grupo}" in await enviar("mostrar_seleccion")
        await enviar("seleccionar_todos")
        await enviar("mostrar_seleccion")
        await enviar("seleccionar_por_comando", str(id_servidor))

        ruta_carga = tmp_path / "cargado.txt"
        mensaje.reply_to_message = SimpleNamespace(
            document=DocumentoTelegramSimulado(b"contenido de prueba")
        )
        assert "No se sobrescribió" in await enviar("cargar_archivo", str(ruta_carga))
        assert ruta_carga.read_bytes() == b"contenido de prueba"
        assert "Tamaño: 19 bytes" in await enviar("consultar_archivo", str(ruta_carga))
        await enviar("descargar_archivo", str(ruta_carga))
        assert mensaje.documentos[-1] == (b"contenido de prueba", "cargado.txt")
        assert nombre in await enviar("mostrar_aplicaciones")
        assert "Aplicación:" in await enviar("consultar_estado_aplicacion", str(id_app))

        async def confirmar():
            codigo = mensaje.respuestas[-1][1].inline_keyboard[0][0].callback_data
            await interfaz.resolver_confirmacion_despliegue(
                _actualizacion(
                    mensaje,
                    id_usuario=cfg.id_propietario_telegram,
                    consulta=ConsultaBotonSimulada(codigo),
                ),
                contexto,
            )

        await enviar("solicitar_despliegue", str(id_app), "1.0.0", str(artefacto))
        assert destino.read_bytes() == b"version anterior"
        await confirmar()
        assert "Despliegue completado" in mensaje.respuestas[-1][0]
        assert destino.read_bytes() == b"version nueva"
        assert "Integridad: verificada" in await enviar("consultar_estado_aplicacion", str(id_app))
        async with fabrica() as sesion:
            id_despliegue = await sesion.scalar(
                select(DespliegueAplicacion.id_despliegue_aplicacion).where(
                    DespliegueAplicacion.id_aplicacion_administrada == id_app
                )
            )
        await enviar("solicitar_reversion_despliegue", str(id_app), str(id_despliegue))
        await confirmar()
        assert "Reversión completada" in mensaje.respuestas[-1][0]
        assert destino.read_bytes() == b"version anterior"
    finally:
        async with fabrica() as sesion:
            await sesion.execute(delete(Servidor).where(Servidor.nombre == nombre))
            await sesion.execute(
                delete(PlantillaDespliegue).where(PlantillaDespliegue.nombre == nombre)
            )
            await sesion.execute(delete(GrupoServidor).where(GrupoServidor.nombre == nombre))
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario == nombre))
            await sesion.commit()
        await motor.dispose()
