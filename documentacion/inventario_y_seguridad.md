# Inventario y seguridad

Este documento describe el inventario y el modelo de acceso incorporados desde
el hito 2 y ampliados hasta el hito 10. Todas las rutas HTTP funcionales usan el
prefijo `/api/v1`, requieren un usuario activo y comprueban el permiso
correspondiente en MariaDB.

## Modelo persistente

```text
usuarios ──< usuarios_roles >── roles ──< roles_permisos >── permisos
   │
   ├──< registros_auditoria
   └──< identidades_mensajeria

servidores ──< servidores_grupos >── grupos_servidores
     │
     ├── configuraciones_monitoreo ──< servicios_criticos_monitoreo
     └──< alertas ──< notificaciones_alertas

identidades_mensajeria ── suscripciones_alertas
```

- `servidores` admite equipos `linux` y `windows_server`, una dirección y un
  puerto SSH únicos en conjunto, el usuario de conexión y datos de verificación
  de identidad.
- `grupos_servidores` organiza cualquier cantidad de servidores. Eliminar un
  grupo no elimina sus integrantes.
- `usuarios`, `roles` y `permisos` implementan el control de acceso persistente.
- `registros_auditoria` conserva actor, acción, recurso, resultado, canal,
  origen e identificador de solicitud.
- `identidades_mensajeria` vincula como máximo una identidad de cada canal con
  cada usuario. El identificador externo no puede pertenecer a dos usuarios.
  Telegram conserva su identificador numérico; Slack conserva la combinación
  `team_id:user_id`, por lo que una cuenta de otro espacio no hereda acceso.
- `configuraciones_monitoreo` y `servicios_criticos_monitoreo` definen las
  comprobaciones de lectura de cada servidor.
- `alertas` conserva episodios activos y recuperados; `notificaciones_alertas`
  registra entregas y reintentos por destinatario.
- `suscripciones_alertas` exige una habilitación explícita antes de enviar una
  alerta a una identidad vinculada.

Las migraciones versionadas son la fuente de verdad del esquema. Se aplican con:

```bash
alembic -c alembic.ini upgrade head
```

## Referencias de credenciales

Un servidor no contiene una contraseña SSH ni una clave privada. El campo
`referencia_credencial` identifica material externo mediante el formato
`proveedor:identificador`; por ejemplo, `archivo:ubuntu_laboratorio` es un
identificador demostrativo, no una ruta ni un secreto.

Los tipos admitidos son `clave_ssh` y `agente_ssh`. El motor del hito 3 resuelve
la referencia de forma confinada, exige permisos seguros y verifica
`huella_clave_host` además del archivo `known_hosts`.

## Roles y permisos iniciales

La migración registra estos permisos:

| Permiso | Capacidad |
| --- | --- |
| `consultar_inventario` | Consultar servidores y grupos. |
| `gestionar_inventario` | Crear, editar, asociar y eliminar inventario. |
| `gestionar_acceso` | Administrar usuarios y asignaciones de roles. |
| `consultar_auditoria` | Consultar el historial de auditoría. |
| `comprobar_conexion` | Comprobar SSH y plataforma mediante saludos fijos. |
| `ejecutar_acciones_lectura` | Ejecutar acciones remotas predefinidas de solo lectura. |
| `reiniciar_servidor` | Programar el reinicio confirmado de un servidor. |
| `consultar_diagnostico` | Consultar disponibilidad, recursos y datos normalizados del sistema. |
| `consultar_servicios` | Consultar el estado de servicios remotos. |
| `gestionar_servicios` | Iniciar, detener y reiniciar servicios remotos confirmados. |
| `consultar_monitoreo` | Consultar políticas, destinos y episodios de alerta. |
| `gestionar_monitoreo` | Configurar umbrales, servicios críticos y suscripciones. |

Los roles iniciales son `administrador`, `operador_inventario` y `auditor`. El
administrador reúne todos los permisos; el operador puede consultar y gestionar
el inventario, comprobar conexiones, ejecutar las acciones de lectura, obtener
diagnósticos, servicios y monitoreo; el auditor puede consultar inventario,
auditoría y monitoreo. Únicamente el administrador recibe los permisos de
reinicio, gestión de servicios y configuración del monitoreo.

El primer administrador se crea mediante el comando interactivo documentado en
`instalacion_local.md`. Hermes impide retirar el último rol administrador activo
para no dejar el sistema sin una vía de administración.

## Rutas disponibles

| Método y ruta | Permiso | Finalidad |
| --- | --- | --- |
| `GET /api/v1/servidores` | `consultar_inventario` | Listar servidores por páginas. |
| `POST /api/v1/servidores` | `gestionar_inventario` | Registrar un servidor. |
| `GET /api/v1/servidores/{id_servidor}` | `consultar_inventario` | Consultar un servidor. |
| `PATCH /api/v1/servidores/{id_servidor}` | `gestionar_inventario` | Modificar un servidor. |
| `DELETE /api/v1/servidores/{id_servidor}` | `gestionar_inventario` | Eliminar con `confirmar=true`. |
| `GET/POST /api/v1/grupos` | Según la operación | Consultar o crear grupos. |
| `GET/PATCH/DELETE /api/v1/grupos/{id_grupo}` | Según la operación | Consultar, editar o eliminar un grupo. |
| `PUT/DELETE /api/v1/grupos/{id_grupo}/servidores/{id_servidor}` | `gestionar_inventario` | Asociar o retirar un servidor. |
| `GET/POST /api/v1/usuarios` | `gestionar_acceso` | Consultar o crear usuarios. |
| `PATCH /api/v1/usuarios/{id_usuario}` | `gestionar_acceso` | Modificar datos, contraseña o estado. |
| `PUT/DELETE /api/v1/usuarios/{id_usuario}/roles/{id_rol}` | `gestionar_acceso` | Asignar o retirar un rol. |
| `GET /api/v1/roles` | `gestionar_acceso` | Consultar roles y sus permisos. |
| `GET /api/v1/permisos` | `gestionar_acceso` | Consultar permisos. |
| `GET /api/v1/auditoria` | `consultar_auditoria` | Consultar registros recientes. |
| `POST /api/v1/servidores/{id_servidor}/comprobar-conexion` | `comprobar_conexion` | Verificar identidad, autenticación y plataforma. |
| `GET /api/v1/acciones` | Según cada acción | Mostrar solo las acciones permitidas al usuario. |
| `POST /api/v1/servidores/{id_servidor}/acciones/{codigo_accion}` | Según la acción | Validar, ejecutar, normalizar y auditar una acción registrada. |
| `GET /api/v1/monitoreo/configuraciones` | `consultar_monitoreo` | Consultar umbrales y servicios críticos. |
| `PUT /api/v1/monitoreo/servidores/{id_servidor}` | `gestionar_monitoreo` | Crear o reemplazar una política. |
| `GET /api/v1/monitoreo/destinos` | `gestionar_monitoreo` | Listar identidades elegibles y suscripciones. |
| `PUT /api/v1/monitoreo/destinos/{id_identidad}` | `gestionar_monitoreo` | Activar o desactivar una suscripción. |
| `GET /api/v1/alertas` | `consultar_monitoreo` | Consultar episodios activos o recuperados. |

Las colecciones aceptan `desplazamiento` y `limite`; el límite por página es
100, pero no existe un máximo fijo de servidores almacenados.

## Registrar un servidor de laboratorio

Con el backend iniciado, este ejemplo solicita la contraseña del usuario local
y registra el Ubuntu anfitrión solo como dato de inventario:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "nombre": "ubuntu-laboratorio",
    "descripcion": "Ubuntu 24.04 del laboratorio autorizado",
    "direccion": "127.0.0.1",
    "puerto_ssh": 22,
    "usuario_conexion": "usuario_laboratorio",
    "sistema_operativo": "linux",
    "tipo_credencial": "agente_ssh",
    "referencia_credencial": "agente:predeterminado",
    "huella_clave_host": "SHA256:ReemplaceEstaHuellaVerificada0000000000000",
    "activo": true
  }' \
  http://127.0.0.1:8000/api/v1/servidores
```

Sustituye usuario y huella por valores verificados. Después se puede solicitar
la comprobación segura:

```bash
curl --user administrador_local --request POST \
  http://127.0.0.1:8000/api/v1/servidores/1/comprobar-conexion
```

Esta ruta solo ejecuta el saludo interno del adaptador. Las acciones se
documentan en `motor_acciones.md` y su uso desde Telegram en `telegram.md`.

## Comportamiento de seguridad

- Una solicitud sin credenciales obtiene `401`; una cuenta sin permiso obtiene
  `403` y no alcanza el caso de uso protegido.
- Las contraseñas locales se validan contra hashes Argon2 y nunca forman parte
  de un esquema de respuesta.
- Nombres, direcciones, puertos, usuarios y referencias se validan antes de
  persistirse; los duplicados producen una respuesta controlada `409`.
- Las eliminaciones de servidores y grupos necesitan confirmación explícita.
- Los errores enviados al cliente no incluyen credenciales ni detalles de la
  conexión a MariaDB.
- Telegram exige simultáneamente una identidad vinculada activa, un usuario
  activo y el permiso de la acción. El nombre visible y el número telefónico no
  participan en la autenticación.
- La auditoría distingue los canales `api`, `sistema`, `telegram` y `slack`.
  Telegram ya está implementado; Slack permanece reservado para el hito 9.

La autenticación HTTP Basic es exclusivamente una adaptación del laboratorio
local. El backend debe permanecer en `127.0.0.1`; no se debe exponer esta API a
una red sin TLS y controles de despliegue adecuados.
