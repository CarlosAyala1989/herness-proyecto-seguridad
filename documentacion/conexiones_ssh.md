# Conexiones SSH seguras

El hito 3 implementa un único transporte AsyncSSH para Linux y Windows Server.
La API no recibe comandos: la ruta de comprobación selecciona un saludo fijo
del adaptador registrado y devuelve únicamente datos normalizados.

## Flujo de comprobación

```text
usuario con permiso comprobar_conexion
                │
                ▼
servidor activo del inventario
                │
                ├── referencia de clave o ssh-agent
                ├── entrada previa en known_hosts
                └── huella SHA-256 fijada
                │
                ▼
            AsyncSSH
                │
        ┌───────┴────────┐
        ▼                ▼
 saludo Linux      saludo PowerShell
        │                │
        └───────┬────────┘
                ▼
     resultado normalizado y auditoría
```

La conexión falla antes de ejecutar el saludo si el host no es conocido, la
huella cambió, la credencial fue rechazada o venció un plazo. Los errores hacia
la API son controlados y no contienen direcciones de archivos, claves ni
detalles internos de autenticación.

## Verificar la identidad de un servidor

La huella se debe obtener por un canal confiable, por ejemplo desde la consola
de la VM. En Ubuntu, sobre el propio servidor:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

En Windows Server, desde PowerShell con privilegios administrativos, identifica
la clave pública de host dentro de `C:\ProgramData\ssh` y comprueba su huella
con `ssh-keygen.exe -lf`. Compara el valor `SHA256:...` antes de agregar la clave
al archivo de hosts conocidos de Hermes.

`ssh-keyscan` puede recopilar la clave pública, pero no demuestra por sí solo
que pertenezca al servidor correcto. Primero compara la huella por consola y
solo después conserva la entrada resultante en el archivo configurado:

```dotenv
HERMES_ARCHIVO_HOSTS_CONOCIDOS_SSH=.secretos/hosts_conocidos
```

Hermes no incluye una opción equivalente a `StrictHostKeyChecking=no` y nunca
agrega automáticamente una clave desconocida.

## Credenciales de usuario

### Agente SSH

Carga una clave autorizada en el servidor antes de iniciar Hermes:

```bash
ssh-add ~/.ssh/id_ed25519
ssh-add -l
```

Registra el servidor con:

```json
{
  "tipo_credencial": "agente_ssh",
  "referencia_credencial": "agente:predeterminado"
}
```

Hermes usa el socket indicado por `SSH_AUTH_SOCK`; no exporta ni almacena la
clave privada.

### Archivo confinado

Configura un directorio exclusivo y coloca allí la clave con permisos `600`:

```dotenv
HERMES_DIRECTORIO_CREDENCIALES_SSH=.secretos/claves_ssh
```

Una referencia `archivo:linux/servidor_01` se resuelve únicamente como
`.secretos/claves_ssh/linux/servidor_01`. Se rechazan escapes del directorio,
enlaces simbólicos, propietarios distintos, permisos de grupo o de terceros y
archivos anormalmente grandes.

Las claves cifradas deben cargarse previamente en `ssh-agent`; Hermes no guarda
frases de paso ni las solicita mediante la API.

## Preparar Linux

- Instala y habilita OpenSSH Server dentro de la máquina autorizada.
- Crea preferentemente una cuenta dedicada sin acceso administrativo general.
- Autoriza solo la clave de Hermes y limita su origen cuando la red sea fija.
- No concedas `sudo` global. Los permisos mínimos para acciones concretas se
  definirán junto con el registro de comandos del hito 4.

Para el ensayo sobre este Ubuntu se reutilizó temporalmente el usuario local
porque no hay autorización `sudo` no interactiva para crear una cuenta nueva.
Su `authorized_keys` contiene una entrada identificada como
`hermes-laboratorio-local`, restringida a `127.0.0.1` y `::1` con la opción
`restrict`. No se modificaron `sshd_config`, el cortafuegos ni la clave privada.

La entrada se puede retirar posteriormente editando
`/home/carlos-daniel/.ssh/authorized_keys` y eliminando exclusivamente la línea
que termina en `hermes-laboratorio-local`.

## Preparar Windows Server

El adaptador presupone Windows Server 2019 o posterior con OpenSSH Server y
PowerShell disponibles. Microsoft documenta OpenSSH como característica del
sistema y permite configurar PowerShell como shell predeterminado; Hermes
invoca `powershell.exe` explícitamente para no depender de esa preferencia.

La VM debe prepararse desde su consola administrativa:

1. Instalar o habilitar OpenSSH Server y arrancar el servicio `sshd`.
2. Restringir el acceso a una cuenta de laboratorio autorizada.
3. Instalar la clave pública del usuario según las reglas de OpenSSH de Windows.
4. Verificar por consola la huella de host.
5. Registrar `sistema_operativo` como `windows_server` y ejecutar la misma ruta
   de comprobación usada para Linux.

Referencias oficiales:

- [Introducción a OpenSSH para Windows](https://learn.microsoft.com/es-es/windows-server/administration/openssh/openssh_install_firstuse)
- [Configuración de OpenSSH Server](https://learn.microsoft.com/es-es/windows-server/administration/openssh/openssh-server-configuration)

## Límites configurables

| Variable | Valor inicial | Protección |
| --- | ---: | --- |
| `HERMES_TIEMPO_CONEXION_SSH_SEGUNDOS` | 10 | Limita la apertura TCP y SSH. |
| `HERMES_TIEMPO_AUTENTICACION_SSH_SEGUNDOS` | 10 | Limita el intercambio de autenticación. |
| `HERMES_TIEMPO_OPERACION_SSH_SEGUNDOS` | 15 | Interrumpe el saludo remoto. |
| `HERMES_LIMITE_SALIDA_SSH_BYTES` | 65536 | Acota stdout y stderr en conjunto. |
| `HERMES_INTERVALO_MANTENIMIENTO_SSH_SEGUNDOS` | 15 | Detecta conexiones inactivas rotas. |
| `HERMES_MAX_INTENTOS_MANTENIMIENTO_SSH` | 3 | Cierra pares que no responden. |

Los límites tienen rangos adicionales validados por Pydantic. No se permite
deshabilitarlos con cero.

## Resultado del laboratorio

La conexión real al Ubuntu anfitrión se comprobó con AsyncSSH, `ssh-agent`, la
entrada existente de `known_hosts` y la huella Ed25519 verificada. El adaptador
detectó `linux`, el kernel `7.0.0-30-generic` y el nombre del equipo. Además, las
pruebas levantan un servidor SSH efímero y verifican rechazo de huella, rechazo
de credencial, exceso de salida y tiempo agotado.

No había una VM Windows Server en ejecución ni `virsh` instalado en el
anfitrión. El adaptador Windows y su salida PowerShell están cubiertos mediante
pruebas automatizadas, pero no se declara una conexión real a Windows. Esa
evidencia deberá completarse cuando se facilite la VM de laboratorio.
