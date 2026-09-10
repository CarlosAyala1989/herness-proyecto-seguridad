"""Recorrido integral de persistencia, permisos e inventario."""

import asyncio
from base64 import b64decode
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aplicacion.base_datos import crear_fabrica_sesiones, crear_motor_base_datos
from aplicacion.conexiones.errores import ErrorServidorSSHNoDisponible
from aplicacion.configuracion import Configuracion
from aplicacion.interfaces.transporte_remoto import ResultadoEjecucionRemota
from aplicacion.modelos.acceso import Permiso, Rol, Usuario
from aplicacion.modelos.grupo_servidor import GrupoServidor
from aplicacion.modelos.registro_auditoria import RegistroAuditoria
from aplicacion.modelos.servidor import Servidor
from aplicacion.principal import crear_aplicacion
from aplicacion.seguridad.contrasenas import generar_hash_contrasena


class TransporteRemotoSimulado:
    """Sustituye exclusivamente la red al probar la ruta protegida."""

    ejecuciones_activas = 0
    max_ejecuciones_activas = 0

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
        tipo_transporte = type(self)
        tipo_transporte.ejecuciones_activas += 1
        tipo_transporte.max_ejecuciones_activas = max(
            tipo_transporte.max_ejecuciones_activas,
            tipo_transporte.ejecuciones_activas,
        )
        try:
            await asyncio.sleep(0.4 if self.servidor.nombre.endswith("-servidor-3") else 0.005)
            if self.servidor.nombre.endswith("-servidor-4"):
                raise ErrorServidorSSHNoDisponible()
            assert comando
            assert tiempo_limite_segundos > 0
            assert limite_salida_bytes > 0
            comando_legible = comando
            if "-EncodedCommand" in comando:
                comando_legible = b64decode(comando.rsplit(maxsplit=1)[1]).decode("utf-16-le")
            if "HERMES_ACCION=obtener_identidad" in comando_legible:
                salida = (
                    f"HERMES_ACCION=obtener_identidad\noperador_pruebas\n{self.servidor.nombre}\n"
                )
            elif "HERMES_ACCION=consultar_proceso" in comando_legible:
                salida = (
                    "HERMES_ACCION=consultar_proceso\n123 python\n"
                    if self.servidor.sistema_operativo.value == "linux"
                    else "HERMES_ACCION=consultar_proceso\n123\npython\n"
                )
            elif "HERMES_ACCION=reiniciar_servidor" in comando_legible:
                salida = "HERMES_ACCION=reiniciar_servidor\nPROGRAMADO\n"
            elif any(
                f"HERMES_ACCION={accion}" in comando_legible
                for accion in (
                    "consultar_servicio",
                    "iniciar_servicio",
                    "detener_servicio",
                    "reiniciar_servicio",
                )
            ):
                codigo_accion = next(
                    accion
                    for accion in (
                        "consultar_servicio",
                        "iniciar_servicio",
                        "detener_servicio",
                        "reiniciar_servicio",
                    )
                    if f"HERMES_ACCION={accion}" in comando_legible
                )
                activo = codigo_accion != "detener_servicio"
                estado_nativo = (
                    "active"
                    if activo and self.servidor.sistema_operativo.value == "linux"
                    else "Running"
                    if activo
                    else "inactive"
                    if self.servidor.sistema_operativo.value == "linux"
                    else "Stopped"
                )
                salida = (
                    f"HERMES_ACCION={codigo_accion}\n"
                    "nombre_servicio=hermes-prueba.service\n"
                    f"estado={'activo' if activo else 'inactivo'}\n"
                    f"estado_nativo={estado_nativo}\n"
                    "inicio_automatico=true\n"
                )
            elif "HERMES_ACCION=listar_usuarios_sistema" in comando_legible:
                identificador = (
                    "1001" if self.servidor.sistema_operativo.value == "linux" else "S-1-5-21-1000"
                )
                salida = (
                    "HERMES_ACCION=listar_usuarios_sistema\n"
                    f"USUARIO|usuario_h12|{identificador}|habilitado|false\n"
                    "GRUPO|usuario_h12|operadores\n"
                )
            elif any(
                f"HERMES_ACCION={accion}" in comando_legible
                for accion in (
                    "crear_usuario_sistema",
                    "cambiar_grupo_usuario_sistema",
                    "bloquear_usuario_sistema",
                    "desbloquear_usuario_sistema",
                    "eliminar_usuario_sistema",
                )
            ):
                codigo_accion = next(
                    accion
                    for accion in (
                        "crear_usuario_sistema",
                        "cambiar_grupo_usuario_sistema",
                        "bloquear_usuario_sistema",
                        "desbloquear_usuario_sistema",
                        "eliminar_usuario_sistema",
                    )
                    if f"HERMES_ACCION={accion}" in comando_legible
                )
                estados = {
                    "crear_usuario_sistema": "deshabilitado",
                    "cambiar_grupo_usuario_sistema": "actualizado",
                    "bloquear_usuario_sistema": "bloqueado",
                    "desbloquear_usuario_sistema": "habilitado",
                    "eliminar_usuario_sistema": "eliminado",
                }
                es_grupo = codigo_accion == "cambiar_grupo_usuario_sistema"
                operacion = "agregar" if "operacion_grupo=agregar" in comando_legible else "quitar"
                salida = (
                    f"HERMES_ACCION={codigo_accion}\n"
                    "nombre_usuario=usuario_h12\n"
                    f"estado={estados[codigo_accion]}\n"
                    "cuenta_protegida=false\n"
                    f"nombre_grupo={'operadores' if es_grupo else 'no_aplica'}\n"
                    f"operacion_grupo={operacion if es_grupo else 'no_aplica'}\n"
                )
            elif "/proc/stat" in comando_legible or "Win32_Processor" in comando_legible:
                sistema = (
                    "Linux"
                    if self.servidor.sistema_operativo.value == "linux"
                    else "Microsoft Windows Server 2022 Standard"
                )
                salida = (
                    "HERMES_ACCION=obtener_diagnostico\n"
                    "estado=disponible\n"
                    "cpu_porcentaje=18.25\n"
                    "memoria_porcentaje=42.50\n"
                    "disco_porcentaje=63\n"
                    "tiempo_actividad_segundos=90061\n"
                    f"sistema={sistema}\n"
                    "version=version-prueba\n"
                    f"nombre_equipo={self.servidor.nombre}\n"
                )
            elif self.servidor.sistema_operativo.value == "linux":
                salida = "HERMES_SO=linux\nLinux\n6.8.0-prueba\nlinux-prueba\n"
            else:
                salida = (
                    "HERMES_SO=windows_server\nMicrosoft Windows Server 2022 Standard\n"
                    "10.0.20348\nWINDOWS-PRUEBA\n"
                )
            return ResultadoEjecucionRemota(0, salida, "", 0.01)
        finally:
            tipo_transporte.ejecuciones_activas -= 1

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
    usuario_gestor_limitado: str
    contrasena_gestor_limitado: str
    primer_registro_auditoria: int


@pytest.fixture
async def contexto_integracion() -> AsyncIterator[ContextoIntegracion]:
    configuracion = Configuracion()  # type: ignore[call-arg]
    motor = crear_motor_base_datos(configuracion)
    fabrica_sesiones = crear_fabrica_sesiones(motor)
    prefijo = f"prueba-{uuid4().hex[:10]}"
    contrasena_administrador = "administrador-prueba-seguro"
    contrasena_lector = "lector-prueba-seguro"
    contrasena_gestor_limitado = "gestor-limitado-prueba-seguro"

    async with fabrica_sesiones() as sesion:
        primer_registro = await sesion.scalar(
            select(func.coalesce(func.max(RegistroAuditoria.id_registro_auditoria), 0))
        )
        rol_administrador = await sesion.scalar(select(Rol).where(Rol.nombre == "administrador"))
        rol_auditor = await sesion.scalar(select(Rol).where(Rol.nombre == "auditor"))
        assert rol_administrador is not None
        assert rol_auditor is not None
        permisos_gestion = list(
            (
                await sesion.scalars(
                    select(Permiso).where(
                        Permiso.codigo.in_(
                            {
                                "consultar_usuarios_sistema",
                                "gestionar_usuarios_sistema",
                                "eliminar_usuarios_sistema",
                            }
                        )
                    )
                )
            ).all()
        )
        assert len(permisos_gestion) == 3
        rol_gestor_limitado = Rol(
            nombre=f"{prefijo}-gestor-usuarios",
            descripcion="Gestión sin excepción para cuentas protegidas",
            es_sistema=False,
            permisos=permisos_gestion,
        )
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
        gestor_limitado = Usuario(
            nombre_usuario=f"{prefijo}-gestor-limitado",
            nombre_mostrar="Gestor limitado de integración",
            hash_contrasena=generar_hash_contrasena(contrasena_gestor_limitado),
            activo=True,
            roles=[rol_gestor_limitado],
        )
        sesion.add_all([administrador, lector, gestor_limitado])
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
        usuario_gestor_limitado=f"{prefijo}-gestor-limitado",
        contrasena_gestor_limitado=contrasena_gestor_limitado,
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
            await sesion.execute(delete(Rol).where(Rol.nombre.like(f"{prefijo}%")))
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
    autenticacion_gestor_limitado = (
        contexto_integracion.usuario_gestor_limitado,
        contexto_integracion.contrasena_gestor_limitado,
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
            "obtener_diagnostico",
            "consultar_servicio",
            "iniciar_servicio",
            "detener_servicio",
            "reiniciar_servicio",
            "listar_usuarios_sistema",
            "crear_usuario_sistema",
            "cambiar_grupo_usuario_sistema",
            "bloquear_usuario_sistema",
            "desbloquear_usuario_sistema",
            "eliminar_usuario_sistema",
        }
        assert acciones_lector.status_code == 200
        assert {item["codigo"] for item in acciones_lector.json()} == {"listar_usuarios_sistema"}

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

            diagnostico = await cliente.post(
                f"/api/v1/servidores/{servidor['id_servidor']}/acciones/obtener_diagnostico",
                auth=autenticacion_admin,
                json={},
            )
            assert diagnostico.status_code == 200, diagnostico.text
            assert diagnostico.json()["datos"]["estado"] == "disponible"
            assert diagnostico.json()["datos"]["cpu_porcentaje"] == 18.25
            assert diagnostico.json()["datos"]["tiempo_actividad_segundos"] == 90_061

            servicio = await cliente.post(
                f"/api/v1/servidores/{servidor['id_servidor']}/acciones/consultar_servicio",
                auth=autenticacion_admin,
                json={"parametros": {"nombre_servicio": "hermes-prueba.service"}},
            )
            assert servicio.status_code == 200, servicio.text
            assert servicio.json()["datos"]["estado"] == "activo"
            assert servicio.json()["datos"]["nombre_servicio"] == "hermes-prueba.service"

            usuarios = await cliente.post(
                f"/api/v1/servidores/{servidor['id_servidor']}/acciones/listar_usuarios_sistema",
                auth=autenticacion_lector,
                json={},
            )
            assert usuarios.status_code == 200, usuarios.text
            assert usuarios.json()["datos"]["total_usuarios"] == 1
            assert usuarios.json()["datos"]["usuarios"][0]["nombre_usuario"] == "usuario_h12"

            creacion_sin_confirmar = await cliente.post(
                f"/api/v1/servidores/{servidor['id_servidor']}/acciones/crear_usuario_sistema",
                auth=autenticacion_admin,
                json={"parametros": {"nombre_usuario": "usuario_h12"}},
            )
            assert creacion_sin_confirmar.status_code == 400
            assert creacion_sin_confirmar.json()["codigo"] == "confirmacion_requerida"

            for codigo_accion, parametros, estado_esperado in (
                (
                    "crear_usuario_sistema",
                    {"nombre_usuario": "usuario_h12", "nombre_mostrar": "Usuario Hito 12"},
                    "deshabilitado",
                ),
                (
                    "cambiar_grupo_usuario_sistema",
                    {
                        "nombre_usuario": "usuario_h12",
                        "nombre_grupo": "operadores",
                        "operacion_grupo": "agregar",
                        "autorizar_cuenta_protegida": False,
                    },
                    "actualizado",
                ),
                (
                    "bloquear_usuario_sistema",
                    {
                        "nombre_usuario": "usuario_h12",
                        "autorizar_cuenta_protegida": False,
                    },
                    "bloqueado",
                ),
                (
                    "desbloquear_usuario_sistema",
                    {
                        "nombre_usuario": "usuario_h12",
                        "autorizar_cuenta_protegida": False,
                    },
                    "habilitado",
                ),
                (
                    "eliminar_usuario_sistema",
                    {
                        "nombre_usuario": "usuario_h12",
                        "autorizar_cuenta_protegida": False,
                    },
                    "eliminado",
                ),
            ):
                mutacion = await cliente.post(
                    f"/api/v1/servidores/{servidor['id_servidor']}/acciones/{codigo_accion}",
                    auth=autenticacion_admin,
                    json={"parametros": parametros, "confirmar": True},
                )
                assert mutacion.status_code == 200, mutacion.text
                assert mutacion.json()["datos"]["estado"] == estado_esperado

        gestion_usuario_denegada = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/bloquear_usuario_sistema",
            auth=autenticacion_lector,
            json={
                "parametros": {"nombre_usuario": "usuario_h12"},
                "confirmar": True,
            },
        )
        assert gestion_usuario_denegada.status_code == 403

        usuario_malicioso = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/crear_usuario_sistema",
            auth=autenticacion_admin,
            json={
                "parametros": {"nombre_usuario": "usuario; id"},
                "confirmar": True,
            },
        )
        assert usuario_malicioso.status_code == 422

        gestion_limitada = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/bloquear_usuario_sistema",
            auth=autenticacion_gestor_limitado,
            json={
                "parametros": {
                    "nombre_usuario": "usuario_h12",
                    "autorizar_cuenta_protegida": False,
                },
                "confirmar": True,
            },
        )
        assert gestion_limitada.status_code == 200, gestion_limitada.text

        excepcion_protegida_denegada = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/bloquear_usuario_sistema",
            auth=autenticacion_gestor_limitado,
            json={
                "parametros": {
                    "nombre_usuario": "usuario_h12",
                    "autorizar_cuenta_protegida": True,
                },
                "confirmar": True,
            },
        )
        assert excepcion_protegida_denegada.status_code == 403

        grupo_multiple = await cliente.post(
            "/api/v1/grupos",
            auth=autenticacion_admin,
            json={
                "nombre": f"{contexto_integracion.prefijo}-grupo-multiple",
                "descripcion": "Cuatro servidores para operación concurrente",
            },
        )
        assert grupo_multiple.status_code == 201, grupo_multiple.text
        id_grupo_multiple = grupo_multiple.json()["id_grupo"]
        for servidor in servidores:
            asociacion_multiple = await cliente.put(
                f"/api/v1/grupos/{id_grupo_multiple}/servidores/{servidor['id_servidor']}",
                auth=autenticacion_admin,
            )
            assert asociacion_multiple.status_code == 200, asociacion_multiple.text

        TransporteRemotoSimulado.max_ejecuciones_activas = 0
        accion_multiple_denegada = await cliente.post(
            "/api/v1/acciones-multiples/obtener_identidad",
            auth=autenticacion_lector,
            json={"seleccion": {"id_grupo": id_grupo_multiple}},
        )
        assert accion_multiple_denegada.status_code == 403

        accion_multiple = await cliente.post(
            "/api/v1/acciones-multiples/obtener_identidad",
            auth=autenticacion_admin,
            json={
                "seleccion": {
                    "ids_servidores": [servidor["id_servidor"] for servidor in servidores]
                }
            },
        )
        assert accion_multiple.status_code == 200, accion_multiple.text
        resumen_multiple = accion_multiple.json()
        assert resumen_multiple["estado"] == "completada_con_errores"
        assert resumen_multiple["total_servidores"] == 4
        assert resumen_multiple["servidores_completados"] == 3
        assert resumen_multiple["servidores_fallidos"] == 1
        assert [resultado["id_servidor"] for resultado in resumen_multiple["resultados"]] == [
            servidor["id_servidor"] for servidor in servidores
        ]
        assert resumen_multiple["resultados"][3]["codigo_error"] == ("servidor_ssh_no_disponible")
        assert (
            2
            <= TransporteRemotoSimulado.max_ejecuciones_activas
            <= (
                contexto_integracion.aplicacion.state.configuracion.max_concurrencia_acciones_multiples
            )
        )

        identificador_accion_multiple = accion_multiple.headers["X-Identificador-Solicitud"]
        async with contexto_integracion.fabrica_sesiones() as sesion:
            auditoria_multiple = list(
                (
                    await sesion.scalars(
                        select(RegistroAuditoria).where(
                            RegistroAuditoria.identificador_solicitud
                            == identificador_accion_multiple
                        )
                    )
                ).all()
            )
        assert {registro.id_recurso for registro in auditoria_multiple} == {
            servidor["id_servidor"] for servidor in servidores
        }

        configuracion_aplicacion = contexto_integracion.aplicacion.state.configuracion
        tiempo_limite_anterior = configuracion_aplicacion.tiempo_limite_accion_multiple_segundos
        configuracion_aplicacion.tiempo_limite_accion_multiple_segundos = 0.2
        try:
            accion_grupo = await cliente.post(
                "/api/v1/acciones-multiples/obtener_diagnostico",
                auth=autenticacion_admin,
                json={"seleccion": {"id_grupo": id_grupo_multiple}},
            )
        finally:
            configuracion_aplicacion.tiempo_limite_accion_multiple_segundos = tiempo_limite_anterior
        assert accion_grupo.status_code == 200, accion_grupo.text
        resultados_grupo = accion_grupo.json()["resultados"]
        resultado_lento = next(
            resultado
            for resultado in resultados_grupo
            if resultado["id_servidor"] == servidores[2]["id_servidor"]
        )
        assert resultado_lento["codigo_error"] == "tiempo_limite_accion_multiple"
        assert sum(resultado["estado"] == "completada" for resultado in resultados_grupo) == 2

        desactivar_cuarto = await cliente.patch(
            f"/api/v1/servidores/{servidores[3]['id_servidor']}",
            auth=autenticacion_admin,
            json={"activo": False},
        )
        assert desactivar_cuarto.status_code == 200
        accion_todos = await cliente.post(
            "/api/v1/acciones-multiples/obtener_identidad",
            auth=autenticacion_admin,
            json={"seleccion": {"todos": True}},
        )
        assert accion_todos.status_code == 200, accion_todos.text
        ids_resultados_todos = {
            resultado["id_servidor"] for resultado in accion_todos.json()["resultados"]
        }
        assert {servidor["id_servidor"] for servidor in servidores[:3]}.issubset(
            ids_resultados_todos
        )
        assert servidores[3]["id_servidor"] not in ids_resultados_todos

        seleccion_ambigua = await cliente.post(
            "/api/v1/acciones-multiples/obtener_identidad",
            auth=autenticacion_admin,
            json={
                "seleccion": {
                    "ids_servidores": [servidores[0]["id_servidor"]],
                    "todos": True,
                }
            },
        )
        assert seleccion_ambigua.status_code == 422

        maximo_anterior = configuracion_aplicacion.max_servidores_accion_multiple
        configuracion_aplicacion.max_servidores_accion_multiple = 3
        try:
            seleccion_excesiva = await cliente.post(
                "/api/v1/acciones-multiples/obtener_identidad",
                auth=autenticacion_admin,
                json={
                    "seleccion": {
                        "ids_servidores": [servidor["id_servidor"] for servidor in servidores]
                    }
                },
            )
        finally:
            configuracion_aplicacion.max_servidores_accion_multiple = maximo_anterior
        assert seleccion_excesiva.status_code == 422
        assert seleccion_excesiva.json()["codigo"] == "limite_seleccion_servidores_superado"

        servicio_sin_confirmar = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/detener_servicio",
            auth=autenticacion_admin,
            json={"parametros": {"nombre_servicio": "hermes-prueba.service"}},
        )
        assert servicio_sin_confirmar.status_code == 400
        assert servicio_sin_confirmar.json()["codigo"] == "confirmacion_requerida"

        servicio_malicioso = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/consultar_servicio",
            auth=autenticacion_admin,
            json={"parametros": {"nombre_servicio": "ssh.service; id"}},
        )
        assert servicio_malicioso.status_code == 422
        assert servicio_malicioso.json()["codigo"] == "parametros_accion_no_validos"

        servicio_confirmado = await cliente.post(
            f"/api/v1/servidores/{id_primer_servidor}/acciones/detener_servicio",
            auth=autenticacion_admin,
            json={
                "parametros": {"nombre_servicio": "hermes-prueba.service"},
                "confirmar": True,
            },
        )
        assert servicio_confirmado.status_code == 200, servicio_confirmado.text
        assert servicio_confirmado.json()["datos"]["estado"] == "inactivo"

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
            "consultar_diagnostico",
            "consultar_servicios",
            "gestionar_servicios",
            "consultar_usuarios_sistema",
            "gestionar_usuarios_sistema",
            "gestionar_usuarios_protegidos",
            "eliminar_usuarios_sistema",
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

        auditoria = await cliente.get(
            "/api/v1/auditoria?limite=100",
            auth=autenticacion_admin,
        )
        assert auditoria.status_code == 200
        acciones = {item["accion"] for item in auditoria.json()}
        assert "crear_servidor" in acciones
        assert "comprobar_permiso" in acciones
        assert "comprobar_conexion_ssh" in acciones
        assert "ejecutar_accion_obtener_identidad" in acciones
        assert "ejecutar_accion_obtener_diagnostico" in acciones
        assert "ejecutar_accion_consultar_servicio" in acciones
        assert "ejecutar_accion_detener_servicio" in acciones
        assert "ejecutar_accion_reiniciar_servidor" in acciones
        assert "ejecutar_accion_listar_usuarios_sistema" in acciones
        assert "ejecutar_accion_crear_usuario_sistema" in acciones
        assert "ejecutar_accion_cambiar_grupo_usuario_sistema" in acciones
        assert "ejecutar_accion_bloquear_usuario_sistema" in acciones
        assert "ejecutar_accion_desbloquear_usuario_sistema" in acciones
        assert "ejecutar_accion_eliminar_usuario_sistema" in acciones

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
