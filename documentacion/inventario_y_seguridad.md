# Inventario y seguridad

Este documento describe las capacidades incorporadas en el hito 2. Todas las
rutas funcionales usan el prefijo `/api/v1`, requieren un usuario activo y
comprueban el permiso correspondiente en MariaDB.

## Modelo persistente

```text
usuarios ──< usuarios_roles >── roles ──< roles_permisos >── permisos
   │
   └──< registros_auditoria

servidores ──< servidores_grupos >── grupos_servidores
```

- `servidores` admite equipos `linux` y `windows_server`, una dirección y un
  puerto SSH únicos en conjunto, el usuario de conexión y datos de verificación
  de identidad.
- `grupos_servidores` organiza cualquier cantidad de servidores. Eliminar un
  grupo no elimina sus integrantes.
- `usuarios`, `roles` y `permisos` implementan el control de acceso persistente.
- `registros_auditoria` conserva actor, acción, recurso, resultado, canal,
  origen e identificador de solicitud.

La migración `0001` es la fuente de verdad del esquema. Se aplica con:

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

Los roles iniciales son `administrador`, `operador_inventario` y `auditor`. El
administrador reúne todos los permisos; el operador puede consultar y gestionar
el inventario; el auditor solo puede consultar inventario y auditoría.

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

Esta ruta solo ejecuta el saludo interno del adaptador. Antes del hito 5 todavía
no existe un bot de Telegram.

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
- La auditoría contempla desde ahora los canales `api`, `sistema`, `telegram` y
  `slack`, aunque los dos últimos todavía no estén implementados.

La autenticación HTTP Basic es exclusivamente una adaptación del laboratorio
local. El backend debe permanecer en `127.0.0.1`; no se debe exponer esta API a
una red sin TLS y controles de despliegue adecuados.
