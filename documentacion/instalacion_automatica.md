# Instalación con un comando

En **Ubuntu 24.04 con systemd**, abre una terminal y ejecuta con tu usuario
normal, desde cualquier carpeta:

```bash
curl -fsSL https://raw.githubusercontent.com/CarlosAyala1989/herness-proyecto-seguridad/main/instalar.sh | bash
```

El usuario necesita permiso para usar `sudo`. El asistente lo solicitará cuando
sea necesario; no ejecutes el instalador completo como root. Se necesita
Internet y `curl` para iniciar la descarga. Si falta `curl`, instálalo con
`sudo apt-get update` y `sudo apt-get install -y curl ca-certificates`.
El script instala Git si hace falta y descarga el código completo por HTTPS
desde el repositorio público, sin solicitar una cuenta ni claves de GitHub.

La carpeta predeterminada es `~/.local/share/hermes`. El instalador reconecta la
entrada a `/dev/tty` para solicitar las credenciales: no intenta leerlas desde
la tubería que contiene su propio código. Mantén la carpeta de instalación en
su ubicación definitiva: los servicios se ejecutarán desde ella.

## Instancia propia de cada usuario

Cada instalación usa el bot de Telegram y la aplicación de Slack creados por
su propietario. El backend, MariaDB, las credenciales, el inventario y la
auditoría permanecen en el servidor donde se ejecuta el instalador. Hermes no
requiere un servidor central del desarrollador ni una cuenta en un servicio
Hermes. El nombre, usuario y avatar del bot se configuran en BotFather; el
nombre y la imagen de la aplicación Slack se configuran en su propia aplicación.

Se necesitan tres tokens si se utilizan las dos plataformas: uno de Telegram
y dos de Slack (`xoxb-` para el bot y `xapp-` con `connections:write` para Socket
Mode), de la misma aplicación instalada en el espacio de trabajo del usuario.
Usa el manifiesto incluido para crear el comando `/hermes`, sus permisos y la
interactividad. Un API key genérico de Slack no sustituye estos dos tokens.

El asistente solicita las credenciales y permite autorizar a su propietario
en ambos canales durante la misma instalación. Los tokens identifican al bot;
los identificadores de usuario determinan quién puede administrarlo. Por eso
hay que completar también esa autorización, además de crear el administrador
local. No se concede acceso automáticamente al primer desconocido que escriba.

Telegram admite un único propietario. El asistente guarda su ID numérico como
`HERMES_ID_PROPIETARIO_TELEGRAM` en `.env`. Un `@usuario` no concede acceso, y
otras identidades de Telegram vinculadas a Hermes tampoco pueden ejecutar
órdenes ni recibir alertas. Al terminar, el instalador reinicia Telegram y los
trabajadores habilitados para cargar el propietario. Si no lo configuras, el
bot permanece bloqueado hasta completar la vinculación desde la terminal.

Telegram y Slack siguen siendo los proveedores de mensajería: los mensajes y
respuestas pasan por sus servicios. Durante la instalación se descargan el
código y las dependencias desde sus repositorios. «Autohospedado» significa que
Hermes y su base de datos se ejecutan en el servidor del usuario; no significa
que Telegram o Slack funcionen sin su propia infraestructura.

Para distribuir este comando, publica tanto `instalar.sh` como
`infraestructura/instalar_local.sh` y el resto de los cambios en la rama
`main`. Una URL a un archivo todavía no publicado no instala el programa.

Si ya descargaste el proyecto, puedes ejecutar `bash instalar.sh` en su
carpeta. En ese caso usa directamente la copia local, sin actualizarla por Git.

## Carpeta y versión opcionales

```bash
curl -fsSL https://raw.githubusercontent.com/CarlosAyala1989/herness-proyecto-seguridad/main/instalar.sh \
  | HERMES_DIRECTORIO_INSTALACION="$HOME/hermes" bash
```

`HERMES_VERSION` selecciona una rama, etiqueta o commit publicado del programa;
de forma predeterminada usa `main`. Se coloca también a la derecha de la
tubería, antes de `bash`. La versión seleccionada debe incluir el instalador
completo. Cuando se publique una versión estable con etiqueta, se pueden fijar
tanto la URL del script como `HERMES_VERSION` a esa misma etiqueta. El asistente
muestra el commit descargado.

## Lo que hace el instalador

1. Comprueba Ubuntu 24.04 y systemd, descarga el programa y valida que contenga
   los archivos necesarios. La primera descarga se prepara en una carpeta
   temporal y solo se instala si termina correctamente.
2. Instala Python 3.12, su soporte de entornos virtuales, certificados, curl y
   Docker Compose. Reutiliza Docker si ya está instalado.
3. Prepara `.venv` e instala Hermes con sus dependencias de ejecución.
4. Crea `.env` con permisos `600` y contraseñas aleatorias independientes para
   MariaDB. No es necesario inventar ni introducir esas contraseñas.
5. Ofrece configurar Telegram y Slack con tokens introducidos de forma oculta.
   Se pueden omitir y configurar más adelante repitiendo el comando.
6. Ofrece activar monitoreo y tareas programadas. La configuración de los
   servidores, suscripciones y tareas se realiza después; activar sus procesos
   no crea operaciones ni destinatarios de alertas.
7. Inicia MariaDB, espera su estado saludable y aplica las migraciones.
8. Solicita usuario, nombre y contraseña del administrador local. La contraseña
   debe tener de 12 a 128 caracteres y se pide dos veces sin mostrarla.
9. Instala servicios systemd, habilita el arranque automático y comprueba la
   salud de la API. Hermes se ejecuta como el usuario que inició el instalador;
   la unidad que inicia Docker Compose se ejecuta como root.
10. Autoriza al propietario de los canales habilitados desde el mismo asistente:
    envía `/inicio` en privado a tu bot de Telegram y `/hermes ayuda` en un mensaje
    directo a tu bot de Slack; sus respuestas iniciales muestran los IDs que
    debes introducir. Si hay un solo administrador activo, se utiliza esa cuenta;
    si hay varios, el asistente solicita elegirla. Al repetir la instalación,
    Enter permite conservar los vínculos activos existentes. Si omites un vínculo
    nuevo, se informa «autorización pendiente» y el bot seguirá denegando el acceso.
    El ID de Telegram elegido queda fijado como propietario único; no se intenta
    descubrir automáticamente al creador de BotFather ni resolver personas por `@`.

El instalador no ejecuta `.env` como código ni imprime los tokens. No inicia
Uvicorn en modo de recarga. La API queda en `127.0.0.1`, con el puerto definido
en `HERMES_PUERTO_API` (8000 de forma predeterminada). MariaDB queda publicada
solo en `127.0.0.1`, con su puerto local configurado (3378 por defecto).

## Credenciales que aporta el usuario

| Integración | Datos necesarios |
| --- | --- |
| Telegram, opcional | Token del bot creado con `@BotFather` e ID numérico del usuario que se autorizará |
| Slack, opcional | Tokens `xoxb-` y `xapp-` de una aplicación preparada para Socket Mode e IDs de espacio de trabajo y usuario para autorizar al propietario desde el asistente |
| Servidores administrados | Dirección, sistema operativo, usuario SSH, clave autorizada y huella de host verificada |

Hermes no necesita una clave de OpenAI para estas funciones. El token de
Telegram identifica al bot; el ID vinculado y los roles de Hermes autorizan al
usuario. Los tokens no se comprueban contra sus proveedores durante la
configuración: el formato se valida localmente y la conexión real se debe
comprobar enviando `/inicio` y consultando los registros.

Telegram y Slack abren conexiones salientes: no requieren un dominio ni un
puerto entrante para mensajería. El servidor necesita salida HTTPS hacia sus
proveedores y acceso SSH a los equipos de destino.

## Preparar los servidores

La instalación deja Hermes funcionando, pero no presupone qué equipos tienes
autorización para administrar. Después registra el inventario mediante la API
local y prepara OpenSSH en cada destino siguiendo
[`conexiones_ssh.md`](conexiones_ssh.md).

Para los servicios que arrancan al reiniciar, utiliza preferentemente claves
de archivo dentro de `.secretos/claves_ssh`, propiedad del usuario que ejecutó
el instalador y con permisos `600` o `400`. El directorio se crea vacío: el
instalador no genera ni autoriza claves remotas por su cuenta. Registra cada
huella verificada y su entrada en `.secretos/hosts_conocidos` antes de conectar.

Un servicio systemd no hereda automáticamente el `ssh-agent` de una terminal.
Si necesitas claves cifradas y un agente, prepara un agente persistente y
configura explícitamente `SSH_AUTH_SOCK` mediante un override de los servicios.
Consulta [`telegram.md`](telegram.md) para la vinculación y prueba del bot.

## Estado y mantenimiento

```bash
sudo systemctl status hermes-api hermes-base-datos
sudo journalctl -u hermes-telegram -f
curl http://127.0.0.1:8000/salud
```

Las unidades instaladas son `hermes-base-datos`, `hermes-api`,
`hermes-telegram`, `hermes-slack`, `hermes-monitoreo` y `hermes-tareas`. Los
canales y trabajadores deshabilitados en `.env` quedan detenidos y no arrancan
con el sistema. Las unidades habilitadas se reinician tras un fallo.

Para cambiar tokens, habilitar canales o completar una instalación interrumpida,
edita `~/.local/share/hermes/.env` o vuelve a ejecutar el comando de descarga.
Para reutilizar el código ya instalado sin descargar actualizaciones:

```bash
bash "$HOME/.local/share/hermes/instalar.sh"
```

Al repetir el comando remoto se descarga la versión seleccionada y se actualiza
el código de la instalación, conservando `.env`, `.secretos`, `.venv` y el volumen
de MariaDB. Se detienen los procesos Hermes antes de cambiar su código.
Si la carpeta pertenece a otro repositorio o contiene cambios locales o archivos
sin seguimiento que Git no ignora, la actualización se detiene para conservarlos.
Los procesos que ya se hayan detenido permanecen así si falla la instalación;
puedes corregir el problema y repetirla.

Un administrador existente se reutiliza sin cambiar su contraseña. El
instalador rechaza contraseñas demostrativas en un `.env` existente: si ya hay
datos, utiliza las credenciales reales del volumen, ya que cambiar el archivo
no modifica los usuarios de MariaDB. La ejecución repetida vuelve a instalar
dependencias, detiene los procesos Hermes antes de migrar y los reinicia; prevé
una interrupción breve y respalda los datos antes de actualizar el código.

No se reemplazan unidades que apunten a otra carpeta. Solo se admite una
instalación con estos nombres de servicios y contenedor por equipo. El
instalador no elimina volúmenes ni modifica reglas del cortafuegos, cuentas
remotas o permisos SSH. Los puertos configurados deben estar libres.

## Alcance de la verificación

Las pruebas automatizadas comprueban la generación y conservación de secretos,
los permisos del archivo, las interrupciones y el flujo Bash con Docker, apt y
systemd simulados. Otras pruebas ejecutan `curl | bash` con un servidor HTTP
local, Git real sobre un repositorio de prueba y una terminal PTY: comprueban
la descarga, las respuestas del asistente, las actualizaciones y la conservación
de secretos. Instalar desde cero en una VM Ubuntu 24.04, reiniciarla y validar
los proveedores con credenciales reales sigue siendo la prueba de aceptación
del instalador. Las guías manuales continúan disponibles en
[`instalacion_local.md`](instalacion_local.md).
