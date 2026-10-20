"""Recorrido de despliegue, verificación, reversión, permisos y auditoría."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.errores import ErrorServidorSSHNoDisponible
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorConflictoDatos, ErrorRecursoNoEncontrado
from aplicacion.esquemas.despliegues import SolicitudDespliegue
from aplicacion.interfaces.transporte_remoto import (
    InformacionArchivoRemoto,
    ResultadoEjecucionRemota,
)
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.despliegue import PlantillaDespliegue
from aplicacion.modelos.enumeraciones import (
    CanalAuditoria,
    SistemaOperativo,
    TipoCanalMensajeria,
    TipoCredencialConexion,
)
from aplicacion.modelos.identidad_mensajeria import IdentidadMensajeria
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena
from aplicacion.servicios.gestor_telegram import GestorTelegram


class TransporteDespliegueSimulado:
    """Simula archivos persistentes y un servicio Linux normalizado."""

    archivos: dict[str, bytes] = {}
    fallar_proximo_reinicio = False
    ruta_carga_parcial: str | None = None
    reinicios = 0

    def __init__(self, servidor: Servidor) -> None:
        self.servidor = servidor

    async def comprobar_disponibilidad(self) -> bool:
        return True

    async def ejecutar_comando_controlado(
        self, comando: str, tiempo_limite_segundos: float, limite_salida_bytes: int
    ) -> ResultadoEjecucionRemota:
        assert tiempo_limite_segundos > 0
        assert limite_salida_bytes > 0
        accion = "reiniciar_servicio" if "reiniciar_servicio" in comando else "consultar_servicio"
        activo = True
        if accion == "reiniciar_servicio":
            type(self).reinicios += 1
            if type(self).fallar_proximo_reinicio:
                type(self).fallar_proximo_reinicio = False
                activo = False
        salida = (
            f"HERMES_ACCION={accion}\n"
            "nombre_servicio=api-hermes.service\n"
            f"estado={'activo' if activo else 'inactivo'}\n"
            f"estado_nativo={'active' if activo else 'inactive'}\n"
            "inicio_automatico=true\n"
        )
        return ResultadoEjecucionRemota(0, salida, "", 0.01)

    async def consultar_informacion_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
    ) -> InformacionArchivoRemoto:
        if ruta_remota not in self.archivos:
            raise ErrorRecursoNoEncontrado("archivo remoto")
        return InformacionArchivoRemoto(
            ruta_remota=ruta_remota,
            nombre_archivo=ruta_remota.rsplit("/", maxsplit=1)[-1],
            tipo="archivo",
            tamano_bytes=len(self.archivos[ruta_remota]),
            modificado_en=datetime.now(UTC),
        )

    async def descargar_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
        limite_bytes: int,
        tamano_bloque_bytes: int,
    ) -> tuple[InformacionArchivoRemoto, bytes]:
        informacion = await self.consultar_informacion_archivo(
            ruta_remota, rutas_permitidas, tiempo_limite_segundos
        )
        return informacion, self.archivos[ruta_remota]

    async def cargar_archivo(
        self,
        ruta_remota: str,
        contenido: bytes,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
        tamano_bloque_bytes: int,
        sobrescribir: bool,
    ) -> bool:
        existia = ruta_remota in self.archivos
        if existia and not sobrescribir:
            raise ErrorConflictoDatos("El archivo remoto ya existe.")
        if ruta_remota == type(self).ruta_carga_parcial:
            type(self).ruta_carga_parcial = None
            self.archivos[ruta_remota] = contenido[:3]
            raise ErrorServidorSSHNoDisponible()
        self.archivos[ruta_remota] = contenido
        return existia

    async def eliminar_archivo(
        self,
        ruta_remota: str,
        rutas_permitidas: tuple[str, ...],
        tiempo_limite_segundos: float,
    ) -> None:
        if ruta_remota not in self.archivos:
            raise ErrorRecursoNoEncontrado("archivo remoto")
        del self.archivos[ruta_remota]

    async def cerrar(self) -> None:
        return None


@pytest.fixture
async def contexto_despliegues() -> AsyncIterator[
    tuple[object, tuple[str, str], tuple[str, str], int, str, int]
]:
    configuracion = Configuracion(limite_archivo_transferencia_bytes=4_096)  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"despliegues-{uuid4().hex[:10]}"
    clave = "clave-segura-pruebas-despliegues"
    identificador_telegram = 700_000_000_000 + int(prefijo[-8:], 16)
    async with fabrica_sesiones() as sesion:
        administrador = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
        auditor = await sesion.scalar(select(Rol).where(Rol.nombre == "auditor"))
        assert administrador is not None and auditor is not None
        usuario_admin = Usuario(
            nombre_usuario=f"{prefijo}-admin",
            nombre_mostrar="Administrador de despliegues",
            hash_contrasena=generar_hash_contrasena(clave),
            activo=True,
            roles=[administrador],
        )
        usuario_auditor = Usuario(
            nombre_usuario=f"{prefijo}-auditor",
            nombre_mostrar="Auditor de despliegues",
            hash_contrasena=generar_hash_contrasena(clave),
            activo=True,
            roles=[auditor],
        )
        servidor = Servidor(
            nombre=f"{prefijo}-linux",
            direccion=f"{prefijo}.local",
            puerto_ssh=22,
            usuario_conexion="operador_hermes",
            sistema_operativo=SistemaOperativo.LINUX,
            tipo_credencial=TipoCredencialConexion.CLAVE_SSH,
            referencia_credencial="archivo:clave_prueba",
            activo=True,
        )
        identidad_telegram = IdentidadMensajeria(
            usuario=usuario_admin,
            canal=TipoCanalMensajeria.TELEGRAM,
            identificador_externo=str(identificador_telegram),
            nombre_externo="administrador_despliegues",
            activo=True,
        )
        sesion.add_all([usuario_admin, usuario_auditor, servidor, identidad_telegram])
        await sesion.commit()
        await sesion.refresh(servidor)
        id_servidor = servidor.id_servidor

    aplicacion = crear_aplicacion(configuracion, motor)
    aplicacion.state.fabrica_transporte_remoto = TransporteDespliegueSimulado
    TransporteDespliegueSimulado.archivos = {}
    TransporteDespliegueSimulado.fallar_proximo_reinicio = False
    TransporteDespliegueSimulado.ruta_carga_parcial = None
    TransporteDespliegueSimulado.reinicios = 0
    try:
        yield (
            aplicacion,
            (f"{prefijo}-admin", clave),
            (f"{prefijo}-auditor", clave),
            id_servidor,
            prefijo,
            identificador_telegram,
        )
    finally:
        async with fabrica_sesiones() as sesion:
            await sesion.execute(
                delete(RegistroAuditoria).where(
                    RegistroAuditoria.nombre_usuario.like(f"{prefijo}%")
                )
            )
            await sesion.execute(delete(Servidor).where(Servidor.nombre.like(f"{prefijo}%")))
            await sesion.execute(
                delete(PlantillaDespliegue).where(PlantillaDespliegue.nombre.like(f"{prefijo}%"))
            )
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario.like(f"{prefijo}%")))
            await sesion.commit()
        await motor.dispose()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_despliega_verifica_revierte_y_restaurar_ante_fallo(
    contexto_despliegues: tuple[object, tuple[str, str], tuple[str, str], int, str, int],
) -> None:
    (
        aplicacion,
        credencial_admin,
        credencial_auditor,
        id_servidor,
        prefijo,
        identificador_telegram,
    ) = contexto_despliegues
    transporte_http = httpx.ASGITransport(app=aplicacion)  # type: ignore[arg-type]
    raiz_servidor = f"/api/v1/servidores/{id_servidor}"
    destino = "/srv/hermes/aplicaciones/api.bin"
    artefacto_v1 = "/srv/hermes/artefactos/api-1.0.bin"
    artefacto_v2 = "/srv/hermes/artefactos/api-2.0.bin"
    artefacto_fallido = "/srv/hermes/artefactos/api-3.0.bin"
    artefacto_telegram = "/srv/hermes/artefactos/api-4.0.bin"

    async with httpx.AsyncClient(transport=transporte_http, base_url="http://pruebas") as cliente:
        respuesta_ruta = await cliente.post(
            f"{raiz_servidor}/rutas-archivos-permitidas",
            auth=credencial_admin,
            json={
                "ruta": "/srv/hermes",
                "permite_lectura": True,
                "permite_escritura": True,
            },
        )
        assert respuesta_ruta.status_code == 201

        respuesta_plantilla = await cliente.post(
            "/api/v1/plantillas-despliegue",
            auth=credencial_admin,
            json={
                "nombre": f"{prefijo}-plantilla",
                "sistema_operativo": "linux",
                "ruta_destino": destino,
                "nombre_servicio": "api-hermes.service",
            },
        )
        assert respuesta_plantilla.status_code == 201
        id_plantilla = respuesta_plantilla.json()["id_plantilla_despliegue"]

        plantilla_windows = await cliente.post(
            "/api/v1/plantillas-despliegue",
            auth=credencial_admin,
            json={
                "nombre": f"{prefijo}-plantilla-windows",
                "sistema_operativo": "windows_server",
                "ruta_destino": "C:/Hermes/aplicaciones/api.exe",
            },
        )
        assert plantilla_windows.status_code == 201
        asociacion_incompatible = await cliente.post(
            "/api/v1/aplicaciones-administradas",
            auth=credencial_admin,
            json={
                "nombre": f"{prefijo}-api-incompatible",
                "id_servidor": id_servidor,
                "id_plantilla_despliegue": plantilla_windows.json()["id_plantilla_despliegue"],
            },
        )
        assert asociacion_incompatible.status_code == 409
        assert asociacion_incompatible.json()["codigo"] == "plantilla_despliegue_incompatible"

        respuesta_aplicacion = await cliente.post(
            "/api/v1/aplicaciones-administradas",
            auth=credencial_admin,
            json={
                "nombre": f"{prefijo}-api",
                "id_servidor": id_servidor,
                "id_plantilla_despliegue": id_plantilla,
            },
        )
        assert respuesta_aplicacion.status_code == 201
        id_aplicacion = respuesta_aplicacion.json()["id_aplicacion_administrada"]
        raiz_despliegue = f"/api/v1/aplicaciones-administradas/{id_aplicacion}"
        TransporteDespliegueSimulado.archivos[destino] = b"archivo no gestionado"

        estado_inicial = await cliente.get(f"{raiz_despliegue}/estado", auth=credencial_auditor)
        assert estado_inicial.status_code == 200
        assert estado_inicial.json()["estado"] == "no_desplegada"
        assert estado_inicial.json()["integridad_verificada"] is None

        for ruta, contenido in (
            (artefacto_v1, b"version uno"),
            (artefacto_v2, b"version dos"),
            (artefacto_fallido, b"version defectuosa"),
            (artefacto_telegram, b"version telegram"),
        ):
            respuesta_carga = await cliente.put(
                f"{raiz_servidor}/archivos/cargar",
                params={"ruta_remota": ruta},
                auth=credencial_admin,
                content=contenido,
            )
            assert respuesta_carga.status_code == 200

        sin_confirmar = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_admin,
            json={"version": "1.0.0", "ruta_artefacto": artefacto_v1},
        )
        assert sin_confirmar.status_code == 400
        assert sin_confirmar.json()["codigo"] == "confirmacion_requerida"

        sin_permiso = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_auditor,
            json={"version": "1.0.0", "ruta_artefacto": artefacto_v1, "confirmar": True},
        )
        assert sin_permiso.status_code == 403

        version_uno = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_admin,
            json={"version": "1.0.0", "ruta_artefacto": artefacto_v1, "confirmar": True},
        )
        assert version_uno.status_code == 201
        assert version_uno.json()["estado"] == "completado"
        assert TransporteDespliegueSimulado.archivos[destino] == b"version uno"

        estado = await cliente.get(f"{raiz_despliegue}/estado", auth=credencial_auditor)
        assert estado.status_code == 200
        assert estado.json()["estado"] == "operativa"
        assert estado.json()["integridad_verificada"] is True

        TransporteDespliegueSimulado.archivos[destino] = b"alteracion externa"
        version_alterada = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_admin,
            json={"version": "2.0.0", "ruta_artefacto": artefacto_v2, "confirmar": True},
        )
        assert version_alterada.status_code == 502
        assert TransporteDespliegueSimulado.archivos[destino] == b"alteracion externa"
        TransporteDespliegueSimulado.archivos[destino] = b"version uno"

        version_dos = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_admin,
            json={"version": "2.0.0", "ruta_artefacto": artefacto_v2, "confirmar": True},
        )
        assert version_dos.status_code == 201
        id_version_dos = version_dos.json()["id_despliegue_aplicacion"]
        assert TransporteDespliegueSimulado.archivos[destino] == b"version dos"

        ruta_respaldo = f"{destino}.hermes-respaldo-{id_version_dos}"
        TransporteDespliegueSimulado.archivos[ruta_respaldo] = b"respaldo alterado"
        reversion_alterada = await cliente.post(
            f"{raiz_despliegue}/despliegues/{id_version_dos}/revertir",
            auth=credencial_admin,
            json={"confirmar": True},
        )
        assert reversion_alterada.status_code == 502
        assert reversion_alterada.json()["codigo"] == "aplicacion_no_operativa"
        assert TransporteDespliegueSimulado.archivos[destino] == b"version dos"
        TransporteDespliegueSimulado.archivos[ruta_respaldo] = b"version uno"

        TransporteDespliegueSimulado.ruta_carga_parcial = destino
        reversion_parcial = await cliente.post(
            f"{raiz_despliegue}/despliegues/{id_version_dos}/revertir",
            auth=credencial_admin,
            json={"confirmar": True},
        )
        assert reversion_parcial.status_code == 503
        assert TransporteDespliegueSimulado.archivos[destino] == b"version dos"

        TransporteDespliegueSimulado.fallar_proximo_reinicio = True
        reversion_sin_servicio = await cliente.post(
            f"{raiz_despliegue}/despliegues/{id_version_dos}/revertir",
            auth=credencial_admin,
            json={"confirmar": True},
        )
        assert reversion_sin_servicio.status_code == 502
        assert TransporteDespliegueSimulado.archivos[destino] == b"version dos"

        reversion = await cliente.post(
            f"{raiz_despliegue}/despliegues/{id_version_dos}/revertir",
            auth=credencial_admin,
            json={"confirmar": True},
        )
        assert reversion.status_code == 200
        assert reversion.json()["estado"] == "revertido"
        assert TransporteDespliegueSimulado.archivos[destino] == b"version uno"

        TransporteDespliegueSimulado.ruta_carga_parcial = destino
        instalacion_parcial = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_admin,
            json={"version": "3.0.0", "ruta_artefacto": artefacto_fallido, "confirmar": True},
        )
        assert instalacion_parcial.status_code == 503
        assert TransporteDespliegueSimulado.archivos[destino] == b"version uno"

        TransporteDespliegueSimulado.fallar_proximo_reinicio = True
        fallido = await cliente.post(
            f"{raiz_despliegue}/despliegues",
            auth=credencial_admin,
            json={
                "version": "3.0.0",
                "ruta_artefacto": artefacto_fallido,
                "confirmar": True,
            },
        )
        assert fallido.status_code == 502
        assert fallido.json()["codigo"] == "aplicacion_no_operativa"
        assert TransporteDespliegueSimulado.archivos[destino] == b"version uno"

        historial = await cliente.get(f"{raiz_despliegue}/despliegues", auth=credencial_auditor)
        assert historial.status_code == 200
        estados = [item["estado"] for item in historial.json()]
        assert estados == ["fallido", "fallido", "revertido", "fallido", "completado"]

    aplicacion.state.configuracion.id_propietario_telegram = identificador_telegram
    gestor_telegram = GestorTelegram(
        aplicacion.state.fabrica_sesiones,
        TransporteDespliegueSimulado,
        aplicacion.state.configuracion,
    )
    aplicaciones = await gestor_telegram.consultar_aplicaciones(identificador_telegram, 1_400)
    assert any(item.id_aplicacion_administrada == id_aplicacion for item in aplicaciones)
    preparado = await gestor_telegram.comprobar_despliegue(
        identificador_telegram,
        1_401,
        id_aplicacion,
        SolicitudDespliegue(
            version="4.0.0",
            ruta_artefacto=artefacto_telegram,
        ),
    )
    assert preparado.nombre == f"{prefijo}-api"
    despliegue_telegram = await gestor_telegram.desplegar_aplicacion(
        identificador_telegram,
        1_402,
        id_aplicacion,
        SolicitudDespliegue(
            version="4.0.0",
            ruta_artefacto=artefacto_telegram,
            confirmar=True,
        ),
    )
    assert despliegue_telegram.estado.value == "completado"
    assert TransporteDespliegueSimulado.archivos[destino] == b"version telegram"

    async with aplicacion.state.fabrica_sesiones() as sesion:
        registros = list(
            (
                await sesion.scalars(
                    select(RegistroAuditoria).where(
                        RegistroAuditoria.nombre_usuario == credencial_admin[0]
                    )
                )
            ).all()
        )
    acciones = [registro.accion for registro in registros]
    assert "crear_plantilla_despliegue" in acciones
    assert "crear_aplicacion_administrada" in acciones
    assert acciones.count("desplegar_aplicacion") == 6
    assert "revertir_despliegue" in acciones
    assert any(
        registro.accion == "desplegar_aplicacion" and registro.canal is CanalAuditoria.TELEGRAM
        for registro in registros
    )
    assert TransporteDespliegueSimulado.reinicios >= 5
