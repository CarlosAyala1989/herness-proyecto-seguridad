"""Recorrido integral de persistencia, permisos e inventario."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.configuracion import Configuracion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.grupo_servidor import GrupoServidor
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena


class TransporteRemotoSimulado:
    """Sustituye exclusivamente la red al probar la ruta protegida."""

    def __init__(self, servidor: Servidor) -> None:
        self.servidor = servidor

    async def comprobar_disponibilidad(self) -> bool:
        return True

    async def ejecutar_comando_controlado(
        self,
        comando: str,
        tiempo_limite_segundos: float,
        limite_salida_bytes: int,
    ) -> ResultadoEjecucionRemota:
        assert comando
        assert tiempo_limite_segundos > 0
        assert limite_salida_bytes > 0
        if "HERMES_ACCION=obtener_identidad" in comando:
            salida = f"HERMES_ACCION=obtener_identidad\noperador_pruebas\n{self.servidor.nombre}\n"
        elif "HERMES_ACCION=consultar_proceso" in comando:
            salida = (
                "HERMES_ACCION=consultar_proceso\n123 python\n"
                if self.servidor.sistema_operativo.value == "linux"
                else "HERMES_ACCION=consultar_proceso\n123\npython\n"
            )
        elif "HERMES_ACCION=reiniciar_servidor" in comando:
            salida = "HERMES_ACCION=reiniciar_servidor\nPROGRAMADO\n"
        elif self.servidor.sistema_operativo.value == "linux":
            salida = "HERMES_SO=linux\nLinux\n6.8.0-prueba\nlinux-prueba\n"
        else:
            salida = (
                "HERMES_SO=windows_server\nMicrosoft Windows Server 2022 Standard\n"
                "10.0.20348\nWINDOWS-PRUEBA\n"
            )
        return ResultadoEjecucionRemota(0, salida, "", 0.01)

    async def cerrar(self) -> None:
        return None


@dataclass
class ContextoIntegracion:
    """Recursos efímeros utilizados por el recorrido integral."""

    motor: AsyncEngine
    fabrica_sesiones: async_sessionmaker[AsyncSession]
    aplicacion: object
    prefijo: str
    usuario_administrador: str
    contrasena_administrador: str
    usuario_lector: str
    contrasena_lector: str
    primer_registro_auditoria: int


@pytest.fixture
async def contexto_integracion() -> AsyncIterator[ContextoIntegracion]:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"prueba-{uuid4().hex[:10]}"
    contrasena_administrador = "administrador-prueba-seguro"
    contrasena_lector = "lector-prueba-seguro"

    async with fabrica_sesiones() as sesion:
        primer_registro = await sesion.scalar(
            select(func.coalesce(func.max(RegistroAuditoria.id_registro_auditoria), 0))
        )
        rol_administrador = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
        rol_auditor = await sesion.scalar(select(Rol).where(Rol.nombre == "auditor"))
        assert rol_administrador is not None
        assert rol_auditor is not None
        administrador = Usuario(
            nombre_usuario=f"{prefijo}-admin",
            nombre_mostrar="Administrador de integración",
            hash_contrasena=generar_hash_contrasena(contrasena_administrador),
            activo=True,
            roles=[rol_administrador],
        )
        lector = Usuario(
            nombre_usuario=f"{prefijo}-lector",
            nombre_mostrar="Lector de integración",
            hash_contrasena=generar_hash_contrasena(contrasena_lector),
            activo=True,
            roles=[rol_auditor],
        )
        sesion.add_all([administrador, lector])
        await sesion.commit()

    aplicacion = crear_aplicacion(configuracion, motor)
    aplicacion.state.fabrica_transporte_remoto = TransporteRemotoSimulado
    contexto = ContextoIntegracion(
        motor=motor,
        fabrica_sesiones=fabrica_sesiones,
        aplicacion=aplicacion,
        prefijo=prefijo,
        usuario_administrador=f"{prefijo}-admin",
        contrasena_administrador=contrasena_administrador,
        usuario_lector=f"{prefijo}-lector",
        contrasena_lector=contrasena_lector,
        primer_registro_auditoria=int(primer_registro or 0),
    )
    try:
        yield contexto
    finally:
        async with fabrica_sesiones() as sesion:
            await sesion.execute(
                delete(RegistroAuditoria).where(
                    RegistroAuditoria.id_registro_auditoria > contexto.primer_registro_auditoria
                )
            )
            await sesion.execute(delete(Servidor).where(Servidor.nombre.like(f"{prefijo}%")))
            await sesion.execute(
                delete(GrupoServidor).where(GrupoServidor.nombre.like(f"{prefijo}%"))
            )
            await sesion.execute(delete(Usuario).where(Usuario.nombre_usuario.like(f"{prefijo}%")))
            await sesion.commit()
        await motor.dispose()


def _datos_servidor(prefijo: str, numero: int) -> dict[str, object]:
    return {
        "nombre": f"{prefijo}-servidor-{numero}",
        "descripcion": f"Servidor autorizado de prueba {numero}",
        "direccion": f"192.0.2.{numero + 10}",
        "puerto_ssh": 22,
        "usuario_conexion": "operador_pruebas",
        "sistema_operativo": "linux" if numero % 2 else "windows_server",
        "tipo_credencial": "clave_ssh",
        "referencia_credencial": f"archivo:claves/{prefijo}-{numero}",
        "huella_clave_host": f"SHA256:huellaDePruebaSegura{numero:02d}",
        "activo": True,
    }


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_crud_persistente_permisos_y_auditoria(
    contexto_integracion: ContextoIntegracion,
) -> None:
    transporte = httpx.ASGITransport(app=contexto_integracion.aplicacion)
    autenticacion_admin = (
        contexto_integracion.usuario_administrador,
        contexto_integracion.contrasena_administrador,
    )
    autenticacion_lector = (
        contexto_integracion.usuario_lector,
        contexto_integracion.contrasena_lector,
    )

    async with httpx.AsyncClient(transport=transporte, base_url="http://pruebas") as cliente:
        sin_credenciales = await cliente.get("/api/v1/servidores")
        assert sin_credenciales.status_code == 401
        assert sin_credenciales.json()["codigo"] == "credenciales_no_validas"

        consulta_lector = await cliente.get(
            "/api/v1/servidores",
            auth=autenticacion_lector,
        )
        assert consulta_lector.status_code == 200
        denegacion = await cliente.post(
            "/api/v1/servidores",
            auth=autenticacion_lector,
            json=_datos_servidor(contexto_integracion.prefijo, 9),
        )
        assert denegacion.status_code == 403
        assert denegacion.json()["codigo"] == "permiso_denegado"

        servidores = []
        for numero in range(1, 5):
            respuesta = await cliente.post(
                "/api/v1/servidores",
                auth=autenticacion_admin,
                json=_datos_servidor(contexto_integracion.prefijo, numero),
            )
            assert respuesta.status_code == 201, respuesta.text
            assert "contrasena" not in respuesta.text
            servidores.append(respuesta.json())

        consulta_persistente = await cliente.get(
            "/api/v1/servidores",
            auth=autenticacion_admin,
        )
        nombres = {item["nombre"] for item in consulta_persistente.json()}
        assert {item["nombre"] for item in servidores}.issubset(nombres)

        motor_reiniciado = crear_motor_base_datos(Configuracion())  # type: ignore[call-arg]
        aplicacion_reiniciada = crear_aplicacion(Configuracion(), motor_reiniciado)  # type: ignore[call-arg]
        transporte_reiniciado = httpx.ASGITransport(app=aplicacion_reiniciada)
        async with httpx.AsyncClient(
            transport=transporte_reiniciado,
            base_url="http://reinicio-pruebas",
        ) as cliente_reiniciado:
            respuesta_reinicio = await cliente_reiniciado.get(
                "/api/v1/servidores",
                auth=autenticacion_admin,
            )
        await motor_reiniciado.dispose()
        assert respuesta_reinicio.status_code == 200
        nombres_reinicio = {item["nombre"] for item in respuesta_reinicio.json()}
        assert {item["nombre"] for item in servidores}.issubset(nombres_reinicio)

        duplicado = await cliente.post(
            "/api/v1/servidores",
            auth=autenticacion_admin,
            json=_datos_servidor(contexto_integracion.prefijo, 1),
        )
        assert duplicado.status_code == 409

        id_primer_servidor = servidores[0]["id_servidor"]

        conexion_denegada = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/comprobar-conexion",
            auth=autenticacion_lector,
        )
        assert conexion_denegada.status_code == 403

        for servidor in servidores[:2]:
            conexion = await cliente.post(
                f"/api/v1/servidores/{servidor['id_servidor']}/comprobar-conexion",
                auth=autenticacion_admin,
            )
            assert conexion.status_code == 200, conexion.text
            assert conexion.json()["estado"] == "disponible"
            assert conexion.json()["sistema_detectado"] == servidor["sistema_operativo"]

        acciones_admin = await cliente.get("/api/v1/acciones", auth=autenticacion_admin)
        acciones_lector = await cliente.get("/api/v1/acciones", auth=autenticacion_lector)
        assert acciones_admin.status_code == 200
        assert {item["codigo"] for item in acciones_admin.json()} == {
            "obtener_identidad",
            "consultar_proceso",
            "reiniciar_servidor",
        }
        assert acciones_lector.status_code == 200
        assert acciones_lector.json() == []

        accion_denegada = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/obtener_identidad",
            auth=autenticacion_lector,
            json={},
        )
        assert accion_denegada.status_code == 403

        for servidor in servidores[:2]:
            identidad = await cliente.post(
                f"/api/v1/servidores/{servidor['id_servidor']}/acciones/obtener_identidad",
                auth=autenticacion_admin,
                json={},
            )
            assert identidad.status_code == 200, identidad.text
            assert identidad.json()["estado"] == "completada"
            assert identidad.json()["datos"]["usuario"] == "operador_pruebas"

        parametros_maliciosos = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/consultar_proceso",
            auth=autenticacion_admin,
            json={"parametros": {"id_proceso": "123; id"}},
        )
        assert parametros_maliciosos.status_code == 422
        assert parametros_maliciosos.json()["codigo"] == "parametros_accion_no_validos"

        proceso = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/consultar_proceso",
            auth=autenticacion_admin,
            json={"parametros": {"id_proceso": 123}},
        )
        assert proceso.status_code == 200
        assert proceso.json()["datos"] == {"id_proceso": 123, "nombre_proceso": "python"}

        reinicio_sin_confirmar = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/reiniciar_servidor",
            auth=autenticacion_admin,
            json={},
        )
        assert reinicio_sin_confirmar.status_code == 400
        assert reinicio_sin_confirmar.json()["codigo"] == "confirmacion_requerida"

        reinicio_confirmado_simulado = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/reiniciar_servidor",
            auth=autenticacion_admin,
            json={"confirmar": True},
        )
        assert reinicio_confirmado_simulado.status_code == 200
        assert reinicio_confirmado_simulado.json()["datos"]["reinicio_programado"] is True

        actualizacion = await cliente.patch(
            f"/api/v1/servidores/{id_primer_servidor}",
            auth=autenticacion_admin,
            json={"activo": False, "descripcion": "Servidor actualizado"},
        )
        assert actualizacion.status_code == 200
        assert actualizacion.json()["activo"] is False

        grupo = await cliente.post(
            "/api/v1/grupos",
            auth=autenticacion_admin,
            json={
                "nombre": f"{contexto_integracion.prefijo}-grupo",
                "descripcion": "Grupo de integración",
            },
        )
        assert grupo.status_code == 201, grupo.text
        id_grupo = grupo.json()["id_grupo"]

        asociacion = await cliente.put(
            f"/api/v1/grupos/{id_grupo}/servidores/{id_primer_servidor}",
            auth=autenticacion_admin,
        )
        assert asociacion.status_code == 200, asociacion.text
        assert asociacion.json()["servidores"][0]["id_servidor"] == id_primer_servidor

        edicion_grupo = await cliente.patch(
            f"/api/v1/grupos/{id_grupo}",
            auth=autenticacion_admin,
            json={"descripcion": "Grupo actualizado"},
        )
        assert edicion_grupo.status_code == 200
        assert edicion_grupo.json()["descripcion"] == "Grupo actualizado"

        roles = await cliente.get("/api/v1/roles", auth=autenticacion_admin)
        permisos = await cliente.get("/api/v1/permisos", auth=autenticacion_admin)
        assert roles.status_code == 200
        assert permisos.status_code == 200
        assert {item["nombre"] for item in roles.json()} >= {
            "administrador",
            "operador_inventario",
            "auditor",
        }
        assert {item["codigo"] for item in permisos.json()} >= {
            "consultar_inventario",
            "gestionar_inventario",
            "gestionar_acceso",
            "consultar_auditoria",
            "comprobar_conexion",
        }

        rol_auditor = next(item for item in roles.json() if item["nombre"] == "auditor")
        usuario_nuevo = await cliente.post(
            "/api/v1/usuarios",
            auth=autenticacion_admin,
            json={
                "nombre_usuario": f"{contexto_integracion.prefijo}-nuevo",
                "nombre_mostrar": "Usuario nuevo",
                "contrasena": "usuario-nuevo-prueba-seguro",
                "ids_roles": [rol_auditor["id_rol"]],
            },
        )
        assert usuario_nuevo.status_code == 201, usuario_nuevo.text
        assert "hash_contrasena" not in usuario_nuevo.text
        assert "usuario-nuevo-prueba-seguro" not in usuario_nuevo.text

        auditoria = await cliente.get("/api/v1/auditoria", auth=autenticacion_admin)
        assert auditoria.status_code == 200
        acciones = {item["accion"] for item in auditoria.json()}
        assert "crear_servidor" in acciones
        assert "comprobar_permiso" in acciones
        assert "comprobar_conexion_ssh" in acciones
        assert "ejecutar_accion_obtener_identidad" in acciones
        assert "ejecutar_accion_reiniciar_servidor" in acciones

        sin_confirmacion = await cliente.delete(
            f"/api/v1/servidores/{servidores[1]['id_servidor']}",
            auth=autenticacion_admin,
        )
        assert sin_confirmacion.status_code == 400
        borrado = await cliente.delete(
            f"/api/v1/servidores/{servidores[1]['id_servidor']}?confirmar=true",
            auth=autenticacion_admin,
        )
        assert borrado.status_code == 204

        retiro = await cliente.delete(
            f"/api/v1/grupos/{id_grupo}/servidores/{id_primer_servidor}",
            auth=autenticacion_admin,
        )
        assert retiro.status_code == 204
        borrado_grupo = await cliente.delete(
            f"/api/v1/grupos/{id_grupo}?confirmar=true",
            auth=autenticacion_admin,
        )
        assert borrado_grupo.status_code == 204
