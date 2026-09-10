"""Recorrido de API, permisos, rutas permitidas y auditoría de archivos."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import Configuracion
from aplicacion.errores import ErrorConflictoDatos, ErrorRecursoNoEncontrado
from aplicacion.interfaces.transporte_remoto import (
    InformacionArchivoRemoto,
    ResultadoEjecucionRemota,
)
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.enumeraciones import SistemaOperativo, TipoCredencialConexion
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena


class TransporteArchivosSimulado:
    """Simula solo SFTP conservando sus contratos de seguridad."""

    archivos: dict[str, bytes] = {}

    def __init__(self, servidor: Servidor) -> None:
        self.servidor = servidor

    async def comprobar_disponibilidad(self) -> bool:
        return True

    async def ejecutar_comando_controlado(
        self, comando: str, tiempo_limite_segundos: float, limite_salida_bytes: int
    ) -> ResultadoEjecucionRemota:
        return ResultadoEjecucionRemota(0, "", "", 0)

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
        self.archivos[ruta_remota] = contenido
        return existia

    async def cerrar(self) -> None:
        return None


@pytest.fixture
async def contexto_archivos() -> AsyncIterator[
    tuple[object, tuple[str, str], tuple[str, str], str]
]:
    configuracion = Configuracion(  # type: ignore[call-arg]
        limite_archivo_transferencia_bytes=1_024
    )
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"archivos-{uuid4().hex[:10]}"
    clave = "clave-segura-pruebas-archivos"
    async with fabrica_sesiones() as sesion:
        administrador = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
        auditor = await sesion.scalar(select(Rol).where(Rol.nombre == "auditor"))
        assert administrador is not None and auditor is not None
        usuario_admin = Usuario(
            nombre_usuario=f"{prefijo}-admin",
            nombre_mostrar="Administrador de archivos",
            hash_contrasena=generar_hash_contrasena(clave),
            activo=True,
            roles=[administrador],
        )
        usuario_auditor = Usuario(
            nombre_usuario=f"{prefijo}-auditor",
            nombre_mostrar="Auditor de archivos",
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
        sesion.add_all([usuario_admin, usuario_auditor, servidor])
        await sesion.commit()
        await sesion.refresh(servidor)
        id_servidor = servidor.id_servidor

    aplicacion = crear_aplicacion(configuracion, motor)
    aplicacion.state.fabrica_transporte_remoto = TransporteArchivosSimulado
    TransporteArchivosSimulado.archivos = {}
    try:
        yield (
            aplicacion,
            (f"{prefijo}-admin", clave),
            (f"{prefijo}-auditor", clave),
            str(id_servidor),
        )
    finally:
        async with fabrica_sesiones() as sesion:
            await sesion.execute(
                delete(RegistroAuditoria).where(
                    RegistroAuditoria.nombre_usuario.like(f"{prefijo}%")
                )
            )
            await sesion.execute(delete(Servidor).where(Servidor.nombre.like(f"{prefijo}%")))
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario.like(f"{prefijo}%")))
            await sesion.commit()
        await motor.dispose()


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_api_transfiere_restringe_y_audita_archivos(
    contexto_archivos: tuple[object, tuple[str, str], tuple[str, str], str],
) -> None:
    aplicacion, credencial_admin, credencial_auditor, id_servidor = contexto_archivos
    transporte_http = httpx.ASGITransport(app=aplicacion)  # type: ignore[arg-type]
    raiz = f"/api/v1/servidores/{id_servidor}"
    async with httpx.AsyncClient(transport=transporte_http, base_url="http://pruebas") as cliente:
        respuesta_ruta = await cliente.post(
            f"{raiz}/rutas-archivos-permitidas",
            auth=credencial_admin,
            json={
                "ruta": "/srv/hermes/intercambio",
                "permite_lectura": True,
                "permite_escritura": True,
            },
        )
        assert respuesta_ruta.status_code == 201

        destino = "/srv/hermes/intercambio/evidencia.txt"
        respuesta_carga = await cliente.put(
            f"{raiz}/archivos/cargar",
            params={"ruta_remota": destino},
            auth=credencial_admin,
            content=b"evidencia hito 13",
        )
        assert respuesta_carga.status_code == 200
        assert respuesta_carga.json()["sobrescrito"] is False

        respuesta_info = await cliente.get(
            f"{raiz}/archivos/informacion",
            params={"ruta_remota": destino},
            auth=credencial_auditor,
        )
        assert respuesta_info.status_code == 200
        assert respuesta_info.json()["tamano_bytes"] == len(b"evidencia hito 13")

        respuesta_descarga = await cliente.get(
            f"{raiz}/archivos/descargar",
            params={"ruta_remota": destino},
            auth=credencial_admin,
        )
        assert respuesta_descarga.status_code == 200
        assert respuesta_descarga.content == b"evidencia hito 13"
        assert respuesta_descarga.headers["x-content-type-options"] == "nosniff"

        respuesta_sin_permiso = await cliente.get(
            f"{raiz}/archivos/descargar",
            params={"ruta_remota": destino},
            auth=credencial_auditor,
        )
        assert respuesta_sin_permiso.status_code == 403

        respuesta_fuera = await cliente.get(
            f"{raiz}/archivos/informacion",
            params={"ruta_remota": "/etc/passwd"},
            auth=credencial_admin,
        )
        assert respuesta_fuera.status_code == 403
        assert respuesta_fuera.json()["codigo"] == "ruta_remota_no_permitida"

        respuesta_sobrescritura = await cliente.put(
            f"{raiz}/archivos/cargar",
            params={"ruta_remota": destino, "sobrescribir": "true"},
            auth=credencial_admin,
            content=b"cambio no confirmado",
        )
        assert respuesta_sobrescritura.status_code == 400

        respuesta_sobrescritura_confirmada = await cliente.put(
            f"{raiz}/archivos/cargar",
            params={
                "ruta_remota": destino,
                "sobrescribir": "true",
                "confirmar": "true",
            },
            auth=credencial_admin,
            content=b"cambio confirmado",
        )
        assert respuesta_sobrescritura_confirmada.status_code == 200
        assert respuesta_sobrescritura_confirmada.json()["sobrescrito"] is True

        respuesta_excedida = await cliente.put(
            f"{raiz}/archivos/cargar",
            params={"ruta_remota": "/srv/hermes/intercambio/grande.bin"},
            auth=credencial_admin,
            content=b"x" * 1_025,
        )
        assert respuesta_excedida.status_code == 413
        assert respuesta_excedida.json()["codigo"] == "limite_archivo_superado"

    fabrica_sesiones = aplicacion.state.fabrica_sesiones
    async with fabrica_sesiones() as sesion:
        acciones = list(
            (
                await sesion.scalars(
                    select(RegistroAuditoria.accion).where(
                        RegistroAuditoria.nombre_usuario.in_(
                            {credencial_admin[0], credencial_auditor[0]}
                        )
                    )
                )
            ).all()
        )
    assert "cargar_archivo" in acciones
    assert "descargar_archivo" in acciones
    assert "consultar_informacion_archivo" in acciones
