# Integración con Telegram

Telegram es una interfaz del backend común de Hermes; ofrece diagnóstico,
gestión confirmada de servicios, selección múltiple y, desde el hito 12,
administración controlada de cuentas locales. El bot no construye órdenes del
sistema, no se conecta por SSH directamente y no mantiene una lista de usuarios
dentro del código. Cada interacción consulta MariaDB y delega en los servicios
de inventario, permisos, acciones y auditoría.

Desde el hito 10, el proceso de monitoreo también puede enviar alertas y
recuperaciones al mismo usuario. La identidad debe estar vinculada, activa y
suscrita explícitamente mediante las rutas de monitoreo; recibir alertas no
elude los permisos de los comandos interactivos.

## Modelo de autorización

Hermes autentica con `User.id`, el identificador numérico que acompaña las
actualizaciones de la API oficial. El nombre de usuario de Telegram puede
cambiar y se guarda, si se desea, solo como referencia visual. El teléfono no se
utiliza: un bot no lo recibe por defecto y un contacto compartido no sustituye
la identidad de la actualización.

El bot obedece exclusivamente al propietario fijado en
`HERMES_ID_PROPIETARIO_TELEGRAM`. Otros usuarios quedan bloqueados aunque tengan
un vínculo activo y rol de administrador en MariaDB. Si el ID no está configurado,
el bot solo deniega el acceso e informa el ID del remitente para completar la
instalación; no ejecuta órdenes ni envía notificaciones automáticas.

La API del bot no indica quién lo creó en BotFather. El administrador del
servidor debe fijar explícitamente a esa persona desde la terminal. No se
autoriza mediante `@usuario`, nombre visible, mensajes reenviados ni por ser
el primero que escriba al bot. Una vez fijado el ID, cambiar el `@usuario` no
cambia los permisos. Los botones y comandos vuelven a comprobar el mismo ID.

Para aceptar una operación deben cumplirse todas estas condiciones:

1. La conversación es privada.
2. El identificador numérico coincide con el propietario configurado.
3. El identificador de Telegram tiene un vínculo activo en
   `identidades_mensajeria`.
4. El usuario de Hermes vinculado está activo.
5. Al menos uno de sus roles concede el permiso necesario.
6. La selección de servidores existe y respeta el máximo configurado.
7. Los parámetros cumplen el esquema cerrado de la acción.

Una identidad desconocida recibe una denegación y su propio identificador para
que el administrador pueda vincularla. El intento queda auditado sin copiar el
mensaje recibido.

## Crear y configurar el bot

1. Abre una conversación con la cuenta oficial `@BotFather`.
2. Crea un bot y copia el token entregado.
3. Guarda el token únicamente en `.env` y protege el archivo con permisos `600`.
4. No pegues el token en incidencias, mensajes, capturas, comandos Git ni
   documentación.

Configuración local:

```dotenv
HERMES_TELEGRAM_HABILITADO=true
HERMES_TOKEN_TELEGRAM=token_real_entregado_por_botfather
HERMES_ID_PROPIETARIO_TELEGRAM=
HERMES_TIEMPO_CONFIRMACION_TELEGRAM_SEGUNDOS=60
HERMES_MAX_SERVIDORES_MOSTRADOS_TELEGRAM=50
```

El valor demostrativo de `.env.ejemplo` no es una credencial válida. La
configuración representa el token mediante `SecretStr` para que su
representación no lo exponga accidentalmente.

## Preparar el usuario autorizado

Aplica primero todas las migraciones y crea un administrador si aún no existe:

```bash
source .venv/bin/activate
alembic -c alembic.ini upgrade head
python -m aplicacion.comandos.crear_administrador \
  --usuario administrador_local \
  --nombre "Administrador local"
```

Inicia temporalmente el bot:

```bash
python -m aplicacion.interfaces.telegram
```

Envía `/inicio` en privado. La primera denegación muestra el identificador
numérico de la cuenta. Desde otra terminal, vincúlalo con el usuario Hermes:

```bash
python -m aplicacion.comandos.vincular_usuario_telegram \
  --usuario administrador_local \
  --identificador-telegram 123456789 \
  --nombre-telegram nombre_visible_opcional
```

Sustituye el número del ejemplo por tu propio ID. El comando guarda el vínculo
en MariaDB y fija ese ID como propietario único en el `.env` privado. Reinicia
el bot para cargarlo y repite `/inicio`; ahora debe aparecer la ayuda.
El instalador hace este reinicio automáticamente al terminar. Para una instalación
ya iniciada como servicios, reinicia los procesos habilitados que utilizan Telegram:

```bash
sudo systemctl restart hermes-telegram
# Solo si están habilitados:
sudo systemctl restart hermes-monitoreo hermes-tareas
```

Si lo ejecutaste manualmente, detén y vuelve a iniciar el proceso de Python.
La vinculación y el propietario se conservan después del reinicio. Cambiar de
propietario requiere ejecutar de nuevo el comando local con el ID correcto y
reiniciar los procesos; editar datos o roles en MariaDB no autoriza a otro ID.
Revocar el vínculo del propietario no promueve automáticamente a otra persona.

Para revocar solo este canal:

```bash
python -m aplicacion.comandos.desvincular_usuario_telegram \
  --usuario administrador_local
```

Desactivar el usuario mediante la API local también bloquea Telegram, aunque el
vínculo externo continúe almacenado.

## Registrar el Ubuntu anfitrión

El equipo anfitrión se trata como cualquier servidor Linux. Verifica primero la
huella pública de OpenSSH y prepara `known_hosts` siguiendo
`conexiones_ssh.md`. Nunca confíes en la salida de `ssh-keyscan` sin compararla
por un medio independiente.

Comprueba además que el proceso del bot heredará un agente con una clave
autorizada:

```bash
ssh-add -l
ssh -o BatchMode=yes usuario_local@127.0.0.1 true
```

Con FastAPI iniciado en `127.0.0.1:8000`, registra el servidor sustituyendo el
usuario y la huella por los valores verificados:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "nombre": "ubuntu-laboratorio",
    "descripcion": "Ubuntu 24.04 anfitrión del laboratorio",
    "direccion": "127.0.0.1",
    "puerto_ssh": 22,
    "usuario_conexion": "usuario_local",
    "sistema_operativo": "linux",
    "tipo_credencial": "agente_ssh",
    "referencia_credencial": "agente:predeterminado",
    "huella_clave_host": "SHA256:huella_verificada",
    "activo": true
  }' \
  http://127.0.0.1:8000/api/v1/servidores
```

El bot puede funcionar sin el proceso HTTP porque ambos usan directamente los
mismos servicios Python y la misma MariaDB. La API local sí resulta útil para
preparar el inventario y administrar usuarios.

## Comandos disponibles

| Comando | Función |
| --- | --- |
| `/inicio` | Comprueba el acceso y muestra la ayuda. |
| `/ayuda` | Muestra las operaciones disponibles. |
| `/tutorial` | Envía la guía completa como documento Markdown adjunto. |
| `/ia` | Selecciona modelo/esfuerzo y ejecuta Codex CLI en el anfitrión. |
| `/servidores` | Lista los servidores activos con botones de selección. |
| `/grupos` | Lista los grupos con botones de selección. |
| `/seleccionar <id>` | Selecciona un servidor mediante un entero validado. |
| `/seleccionar_grupo <id>` | Selecciona dinámicamente los miembros de un grupo. |
| `/seleccionar_todos` | Selecciona todos los servidores activos autorizados. |
| `/seleccion` | Vuelve a validar y muestra la selección actual. |
| `/diagnostico` | Muestra disponibilidad, CPU, RAM, disco, actividad, sistema y versión. |
| `/servicio <nombre>` | Consulta el estado exacto de un servicio. |
| `/iniciar_servicio <nombre>` | Solicita confirmación antes de iniciar un servicio. |
| `/detener_servicio <nombre>` | Solicita confirmación antes de detener un servicio. |
| `/reiniciar_servicio <nombre>` | Solicita confirmación antes de reiniciar un servicio. |
| `/usuarios` | Lista cuentas locales, estado, protección y grupos. |
| `/crear_usuario <cuenta> [nombre]` | Crea una cuenta local deshabilitada. |
| `/agregar_grupo <cuenta> <grupo>` | Agrega una cuenta a un grupo local. |
| `/quitar_grupo <cuenta> <grupo>` | Quita una cuenta de un grupo local. |
| `/bloquear_usuario <cuenta>` | Solicita bloquear o deshabilitar una cuenta. |
| `/desbloquear_usuario <cuenta>` | Solicita desbloquear o habilitar una cuenta. |
| `/eliminar_usuario <cuenta>` | Solicita eliminar una cuenta local. |
| `/archivo_info <ruta>` | Consulta tipo, tamaño y modificación mediante SFTP. |
| `/descargar_archivo <ruta>` | Entrega un archivo de una raíz de lectura permitida. |
| `/cargar_archivo <ruta>` | Carga sin sobrescribir el documento al que se responde. |
| `/aplicaciones` | Lista aplicaciones, servidor y versión vigente. |
| `/estado_aplicacion <id>` | Comprueba archivo, integridad y servicio opcional. |
| `/desplegar <id> <versión> <ruta>` | Solicita instalar un artefacto remoto. |
| `/revertir_despliegue <id_app> <id_despliegue>` | Solicita restaurar el estado anterior. |
| `/identidad` | Ejecuta `obtener_identidad` sobre la selección actual. |
| `/proceso <id>` | Ejecuta `consultar_proceso` con un identificador acotado. |
| `/reiniciar` | Solicita una confirmación efímera antes del reinicio. |
| `/cancelar` | Invalida la confirmación pendiente. |

Telegram envía `/start` al abrir ciertos enlaces del bot; Hermes lo admite como
alias técnico externo de `/inicio`, pero no lo publica en su menú en español.

Envía `/tutorial` sin argumentos para recibir `tutorial_hermes.md`, con sintaxis,
ejemplos, requisitos, confirmaciones y solución de problemas de todos los comandos.
Solo se entrega al propietario autorizado en un chat privado y no requiere
seleccionar un servidor ni preparar SFTP. El documento está incluido en la
instalación y puede consultarse también en
[`tutorial_telegram.md`](../aplicacion/interfaces/telegram/recursos/tutorial_telegram.md).

La función opcional `/ia` ejecuta instrucciones libres mediante el CLI instalado,
sin sandbox ni aprobaciones de Codex. Solo está disponible para el propietario
con rol administrador, sobre la máquina del bot y con los permisos de la cuenta
local. Sus requisitos y controles están en [`codex_local.md`](codex_local.md).

## Prueba segura desde Telegram

Con el bot, MariaDB, OpenSSH y el agente activos:

1. Envía `/servidores`.
2. Pulsa `ubuntu-laboratorio`.
3. Envía `/seleccion` y verifica nombre y sistema.
4. Envía `/diagnostico` y comprueba los recursos y datos reales del equipo.
5. Envía `/identidad` y comprueba el usuario remoto y el nombre del equipo.
6. Envía `/servicio ssh.service` en Linux o `/servicio sshd` en Windows y
   comprueba el estado. Esta consulta no cambia el servicio.
7. Envía `/proceso 1` y comprueba que se informa el proceso del sistema.
8. Envía `/usuarios` y comprueba las cuentas sin realizar cambios.
9. Consulta `/api/v1/auditoria` desde la API local y verifica que el canal sea
   `telegram`.

Para transferir un archivo, selecciona un único servidor y registra antes una
raíz siguiendo `archivos.md`. `/archivo_info` y `/descargar_archivo` reciben la
ruta completa. Para cargar, envía primero un documento al chat, responde a ese
mensaje con `/cargar_archivo /ruta/remota/nombre` y conserva la selección. El bot
rechaza tamaños desconocidos o superiores al límite y nunca reemplaza un archivo
existente.

Para administrar una aplicación ya preparada mediante la API y
`despliegues.md`, ejecuta:

```text
/aplicaciones
/estado_aplicacion 1
/desplegar 1 1.0.0 /srv/hermes/artefactos/api-1.0.0.bin
```

El último comando no escribe de inmediato: muestra botones, fija aplicación,
versión y ruta, y exige una confirmación no reutilizable. Consulta luego el
historial por la API. Para recuperar el estado previo, usa el identificador del
despliegue con `/revertir_despliegue 1 1` y confirma. Ambas operaciones cambian
archivos reales y pueden reiniciar el servicio de la plantilla; deben probarse
solo con una aplicación desechable del laboratorio.

Para una prueba múltiple de solo lectura, registra varios destinos de
laboratorio, asócialos a un grupo y ejecuta:

```text
/grupos
/seleccionar_grupo 1
/diagnostico
```

El resumen debe contener una línea independiente por servidor. Un destino
apagado debe aparecer como fallido sin impedir las respuestas de los demás.

No uses `/reiniciar` ni los comandos que modifican servicios o usuarios para
una demostración ordinaria. Sus botones autorizan cambios reales. Prueba las
cuentas sobre una VM o contenedor desechable siguiendo `usuarios_sistema.md`,
nunca sobre una cuenta necesaria del anfitrión.

## Controles operativos

- El bot usa sondeo saliente; no necesita webhook, dominio ni puertos públicos.
- Solo el ID del propietario configurado puede acceder a las operaciones y
  recibir alertas o resultados de tareas por Telegram.
- Las actualizaciones pendientes se descartan al iniciar para evitar acciones
  antiguas.
- Las actualizaciones de Telegram se procesan secuencialmente para conservar el
  estado conversacional; el orquestador del backend ejecuta internamente los
  destinos de una selección con concurrencia acotada.
- Se admiten 30 solicitudes por identidad y minuto.
- El limitador conserva como máximo 5 000 identidades recientes.
- Los identificadores de servidor y proceso están acotados antes de convertirlos.
- Cada confirmación sensible tiene un código aleatorio, queda ligada a su
  acción y selección fija de IDs, caduca y se consume una sola vez.
- Las confirmaciones de despliegue quedan ligadas a aplicación, versión,
  artefacto u operación de reversión y se vuelven a autorizar al consumirlas.
- Los grupos se resuelven de nuevo para las lecturas. Antes de confirmar una
  mutación, sus miembros se fijan para impedir que el alcance se amplíe mientras
  el usuario decide.
- Las respuestas múltiples se dividen respetando el límite de mensaje y no
  omiten silenciosamente resultados.
- El bot no recibe contraseñas y siempre conserva desactivada la excepción para
  cuentas protegidas; esa autorización reforzada queda limitada a la API local.
- Los registros solo incluyen el tipo de un error inesperado de Telegram; no
  incluyen el mensaje, la actualización ni el token.

Referencias oficiales:

- [API para bots de Telegram](https://core.telegram.org/bots/api)
- [python-telegram-bot 22.8](https://docs.python-telegram-bot.org/en/stable/)
- [Ciclo de vida asíncrono de Application](https://docs.python-telegram-bot.org/en/stable/telegram.ext.application.html)

## Estado de la comprobación externa

La interfaz, autorización, persistencia, permisos, auditoría y acciones se
prueban automáticamente con actualizaciones y transportes simulados. Como aún
no se dispone de un token real de laboratorio, no se afirma una conversación
real con Telegram. La prueba externa queda lista para ejecutarse siguiendo
esta guía cuando el usuario aporte el token y vincule su identidad.
