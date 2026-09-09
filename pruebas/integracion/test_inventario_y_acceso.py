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
from aplicacion.modelos.acceso import Rol, Usuario
from aplicacion.modelos.grupo_servidor import GrupoServidor
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena


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

        duplicado = await cliente.post(
            "/api/v1/servidores",
            auth=autenticacion_admin,
            json=_datos_servidor(contexto_integracion.prefijo, 1),
        )
        assert duplicado.status_code == 409

        id_primer_servidor = servidores[0]["id_servidor"]
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
