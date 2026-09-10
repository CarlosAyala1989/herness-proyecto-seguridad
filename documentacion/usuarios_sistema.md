# Administración de usuarios del sistema

El hito 12 incorpora operaciones comunes para cuentas locales Linux y Windows
Server. Telegram, Slack, la API y las tareas programadas entregan códigos y
parámetros al mismo motor; los canales no contienen órdenes del sistema.

## Operaciones disponibles

| Acción | Efecto | Confirmación |
| --- | --- | --- |
| `listar_usuarios_sistema` | Consulta cuentas, identificador, estado, protección y grupos. | No |
| `crear_usuario_sistema` | Crea una cuenta local inicialmente deshabilitada. | Sí |
| `cambiar_grupo_usuario_sistema` | Agrega o quita una cuenta de un grupo local existente. | Sí |
| `bloquear_usuario_sistema` | Bloquea en Linux o deshabilita en Windows. | Sí |
| `desbloquear_usuario_sistema` | Desbloquea en Linux o habilita en Windows. | Sí |
| `eliminar_usuario_sistema` | Elimina la cuenta y, en Linux, su directorio de usuario. | Sí |

La creación no acepta una contraseña, clave privada ni otro secreto. Linux crea
el directorio personal, asigna `/bin/bash` y deja la cuenta bloqueada y vencida.
Windows usa `New-LocalUser -NoPassword -Disabled`. Antes de habilitar una cuenta,
el administrador debe aprovisionar fuera de Hermes una credencial o una clave
SSH mediante un procedimiento seguro de la máquina administrada.

`nombre_usuario` admite entre 1 y 20 caracteres ASCII, comienza con una letra,
número o guion bajo y después admite punto, guion y guion bajo. No puede terminar
en punto o guion. El límite común de 20 caracteres conserva compatibilidad con
Windows. Los nombres de grupo admiten espacios porque Windows incluye nombres
como `Remote Desktop Users`, pero no admiten comillas, barras, comodines ni
metacaracteres de shell.

## Permisos

| Permiso | Administrador | Operador de inventario | Auditor |
| --- | --- | --- | --- |
| `consultar_usuarios_sistema` | Sí | Sí | Sí |
| `gestionar_usuarios_sistema` | Sí | No | No |
| `gestionar_usuarios_protegidos` | Sí | No | No |
| `eliminar_usuarios_sistema` | Sí | No | No |

Eliminar exige simultáneamente `eliminar_usuarios_sistema` y
`gestionar_usuarios_sistema`. Solicitar una excepción para una cuenta o grupo
protegido exige además `gestionar_usuarios_protegidos`. La autorización de
Hermes no sustituye los privilegios del sistema remoto.

## Protección reforzada

Sin la excepción explícita, Linux rechaza cambios sobre:

- cuentas con UID inferior a `UID_MIN` o con UID 65534;
- la cuenta usada por la conexión SSH;
- miembros de `sudo`, `wheel`, `root`, `adm`, `shadow` o `docker`;
- grupos con GID inferior a `GID_MIN` o cualquiera de los nombres anteriores.

Windows protege las cuentas integradas con RID inferior a 1000, la cuenta SSH
y los miembros de grupos integrados privilegiados identificados por SID. El uso
de SID evita depender del idioma instalado en Windows Server. Los grupos
integrados también quedan protegidos por su RID.

Hermes nunca permite cambiar el estado ni eliminar la cuenta que sostiene la
conexión SSH, incluso si se solicita la excepción. La excepción sí permite a un
administrador autorizado realizar otros cambios conscientes sobre cuentas o
grupos protegidos. Telegram y Slack siempre envían
`autorizar_cuenta_protegida=false`; esta excepción solo está disponible en la
API local y continúa exigiendo confirmación.

## Implementación Linux

El adaptador consulta `getent passwd`, `passwd -S` e `id`. Las mutaciones usan
`useradd`, `usermod`, `gpasswd` y `userdel`. Si la sesión remota no es `root`,
Hermes invoca `sudo -n`, que nunca abre una solicitud interactiva de contraseña.

No concedas `NOPASSWD: ALL` ni acceso genérico a todas las variantes de estas
herramientas. En una VM de laboratorio, permite únicamente las órdenes exactas
de las cuentas de prueba previstas. Para un inventario dinámico o un entorno
real, utiliza una política sudoers generada y revisada por objetivo o un
componente privilegiado local que vuelva a validar la solicitud. El
endurecimiento definitivo de esa política forma parte de la revisión integral
del hito 15.

La consulta puede ejecutarse sin privilegios, aunque un sistema puede ocultar
el estado de contraseña de otras cuentas; en ese caso Hermes devuelve
`desconocido` en lugar de elevar silenciosamente la lectura.

## Implementación Windows Server

El adaptador genera un guion PowerShell codificado y no interactivo con los
cmdlets del módulo `Microsoft.PowerShell.LocalAccounts`: `Get-LocalUser`,
`New-LocalUser`, `Disable-LocalUser`, `Enable-LocalUser`, `Remove-LocalUser`,
`Get-LocalGroupMember`, `Add-LocalGroupMember` y `Remove-LocalGroupMember`.

La VM debe ser Windows Server 2016 o posterior, tener OpenSSH Server habilitado
y ejecutar Windows PowerShell de 64 bits. El módulo LocalAccounts no está
disponible en PowerShell de 32 bits sobre un sistema de 64 bits. Un controlador
de dominio no posee el mismo modelo de cuentas locales y queda fuera del
alcance; Hermes responde `gestor_usuarios_no_disponible` si faltan los cmdlets.

En el laboratorio puede utilizarse una cuenta administrativa dedicada dentro
de la VM. No reutilices una cuenta personal ni pruebes con Administrator,
`sshd`, servicios de dominio o cuentas necesarias para recuperar el equipo.

## Uso desde la API local

Consulta las cuentas del servidor 1:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/listar_usuarios_sistema
```

Crea una cuenta deshabilitada:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "parametros": {
      "nombre_usuario": "hermes_prueba",
      "nombre_mostrar": "Cuenta de prueba Hermes"
    },
    "confirmar": true
  }' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/crear_usuario_sistema
```

Agrega la cuenta a un grupo no protegido:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "parametros": {
      "nombre_usuario": "hermes_prueba",
      "nombre_grupo": "operadores",
      "operacion_grupo": "agregar",
      "autorizar_cuenta_protegida": false
    },
    "confirmar": true
  }' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/cambiar_grupo_usuario_sistema
```

Para quitarla cambia `operacion_grupo` a `quitar`. Bloqueo, habilitación y
eliminación usan el mismo cuerpo base y su ruta correspondiente:

```json
{
  "parametros": {
    "nombre_usuario": "hermes_prueba",
    "autorizar_cuenta_protegida": false
  },
  "confirmar": true
}
```

Las rutas son `bloquear_usuario_sistema`, `desbloquear_usuario_sistema` y
`eliminar_usuario_sistema`. Una petición sin confirmación se rechaza antes de
abrir SSH. Un nombre malicioso o un campo adicional produce
`parametros_accion_no_validos`.

## Uso desde Telegram y Slack

Después de seleccionar un servidor, grupo o todos los servidores:

```text
/usuarios
/crear_usuario hermes_prueba Cuenta de prueba Hermes
/agregar_grupo hermes_prueba operadores
/quitar_grupo hermes_prueba operadores
/bloquear_usuario hermes_prueba
/desbloquear_usuario hermes_prueba
/eliminar_usuario hermes_prueba
```

En Slack agrega el prefijo `/hermes`, por ejemplo:

```text
/hermes usuarios
/hermes crear_usuario hermes_prueba Cuenta de prueba Hermes
/hermes agregar_grupo hermes_prueba Remote Desktop Users
/hermes bloquear_usuario hermes_prueba
```

Todas las mutaciones presentan botones de confirmación y fijan los destinos
antes de esperar la decisión. Una máquina fallida no detiene las demás y la
auditoría conserva un registro por servidor con el canal de origen.

## Pruebas

La prueba Linux real se ejecuta exclusivamente dentro de un contenedor Ubuntu
24.04 desechable. Requiere que la imagen esté presente localmente:

```bash
docker pull ubuntu:24.04
pytest -o addopts='' -m integracion -vv \
  pruebas/integracion/test_usuarios_linux_contenedor.py
```

La prueba crea el grupo y la cuenta `hermes_h12`, simula de forma interna el
aprovisionamiento externo de una credencial efímera, habilita, agrupa, bloquea,
vuelve a habilitar y elimina. El contenedor usa `--rm` y se detiene incluso si
una aserción falla; no modifica usuarios del anfitrión.

La API y MariaDB prueban ambos adaptadores con un transporte simulado:

```bash
pytest -o addopts='' -m integracion -vv \
  pruebas/integracion/test_inventario_y_acceso.py
```

Los guiones Windows, la normalización y los errores se comprueban de forma
automatizada, pero aún no existe una VM Windows Server conectada en este
laboratorio. Por tanto, no se afirma una mutación real en Windows. Cuando la VM
esté disponible, crea una cuenta desechable, recorre las seis acciones, consulta
la auditoría y elimina la cuenta antes de cerrar la evidencia.

## Alcance

Este hito administra cuentas y pertenencia a grupos locales. No crea grupos, no
administra Active Directory y no distribuye contraseñas, claves SSH ni perfiles.
Tampoco implementa transferencia de archivos; esa función corresponde al hito
13.

Referencias oficiales:

- [useradd de Ubuntu 24.04](https://manpages.ubuntu.com/manpages/noble/man8/useradd.8.html)
- [usermod de Ubuntu 24.04](https://manpages.ubuntu.com/manpages/noble/man8/usermod.8.html)
- [gpasswd de Ubuntu 24.04](https://manpages.ubuntu.com/manpages/noble/man1/gpasswd.1.html)
- [New-LocalUser](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.localaccounts/new-localuser?view=powershell-5.1)
- [Get-LocalGroupMember](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.localaccounts/get-localgroupmember?view=powershell-5.1)
- [Add-LocalGroupMember](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.localaccounts/add-localgroupmember?view=powershell-5.1)
- [Remove-LocalGroupMember](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.localaccounts/remove-localgroupmember?view=powershell-5.1)
