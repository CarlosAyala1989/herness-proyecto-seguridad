# Integración con Telegram

Telegram es una interfaz del backend común de Hermes; ofrece diagnóstico desde
el hito 6, gestión confirmada de servicios desde el hito 7 y selección múltiple
desde el hito 8. El bot no construye órdenes del sistema, no se conecta por SSH
directamente y no mantiene una lista de usuarios dentro del código. Cada
interacción consulta MariaDB y delega en los servicios de inventario, permisos,
acciones y auditoría.

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

Para aceptar una operación deben cumplirse todas estas condiciones:

1. La conversación es privada.
2. El identificador de Telegram tiene un vínculo activo en
   `identidades_mensajeria`.
3. El usuario de Hermes vinculado está activo.
4. Al menos uno de sus roles concede el permiso necesario.
5. La selección de servidores existe y respeta el máximo configurado.
6. Los parámetros cumplen el esquema cerrado de la acción.

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

Sustituye el número del ejemplo. Repite `/inicio`; ahora debe aparecer la ayuda.
La vinculación es persistente después de reiniciar el bot.

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
| `/identidad` | Ejecuta `obtener_identidad` sobre la selección actual. |
| `/proceso <id>` | Ejecuta `consultar_proceso` con un identificador acotado. |
| `/reiniciar` | Solicita una confirmación efímera antes del reinicio. |
| `/cancelar` | Invalida la confirmación pendiente. |

Telegram envía `/start` al abrir ciertos enlaces del bot; Hermes lo admite como
alias técnico externo de `/inicio`, pero no lo publica en su menú en español.

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
8. Consulta `/api/v1/auditoria` desde la API local y verifica que el canal sea
   `telegram`.

Para una prueba múltiple de solo lectura, registra varios destinos de
laboratorio, asócialos a un grupo y ejecuta:

```text
/grupos
/seleccionar_grupo 1
/diagnostico
```

El resumen debe contener una línea independiente por servidor. Un destino
apagado debe aparecer como fallido sin impedir las respuestas de los demás.

No uses `/reiniciar` ni los comandos que modifican servicios para una
demostración ordinaria. Sus botones autorizan cambios reales. Las pruebas
automatizadas de mutación sustituyen el transporte y nunca alteran el
anfitrión.

## Controles operativos

- El bot usa sondeo saliente; no necesita webhook, dominio ni puertos públicos.
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
- Los grupos se resuelven de nuevo para las lecturas. Antes de confirmar una
  mutación, sus miembros se fijan para impedir que el alcance se amplíe mientras
  el usuario decide.
- Las respuestas múltiples se dividen respetando el límite de mensaje y no
  omiten silenciosamente resultados.
- Los registros solo incluyen el tipo de un error inesperado de Telegram; no
  incluyen el mensaje, la actualización ni el token.

Referencias oficiales:

- [API para bots de Telegram](https://core.telegram.org/bots/api)
- [python-telegram-bot 22.8](https://docs.python-telegram-bot.org/en/stable/)
- [Ciclo de vida asíncrono de Application](https://docs.python-telegram-bot.org/en/stable/telegram.ext.application.html)

## Estado de la comprobación externa

La interfaz, autorización, persistencia, permisos, auditoría y acciones se
prueban automáticamente con actualizaciones y transportes simulados. En este
entorno todavía no existe un token real, un usuario persistente ni un servidor
persistente, por lo que no se afirma una conversación real con Telegram. La
prueba externa queda lista para ejecutarse siguiendo esta guía cuando el usuario
aporte su token y cree sus credenciales locales.
