# Integración con Slack

Slack es una segunda interfaz del backend común de Hermes. Usa Slack Bolt
asíncrono mediante Socket Mode: el proceso abre una conexión saliente con
Slack y no publica un webhook, dominio ni puerto adicional. El canal interpreta
`/hermes`, pero inventario, permisos, acciones, SSH y auditoría permanecen en
los mismos servicios utilizados por FastAPI y Telegram. Desde el hito 12 también
expone las operaciones comunes de cuentas locales sin incorporar PowerShell ni
órdenes Linux al canal.

Desde el hito 10, el proceso de monitoreo puede entregar alertas y
recuperaciones mediante `chat.postMessage`. La identidad debe continuar activa
y tener una suscripción habilitada por un administrador. El envío automático
no abre Socket Mode ni concede permisos administrativos adicionales.
Antes de la primera notificación, Hermes consulta `auth.test` con el token de
bot y exige que su `team_id` coincida con el equipo de la identidad vinculada.
Un destino de otro espacio de trabajo se rechaza antes de enviar el mensaje.

## Controles de acceso

Hermes no autoriza por nombre visible, correo ni teléfono. La identidad
persistente combina el identificador del espacio de trabajo (`team_id`) y el
identificador inmutable del usuario (`user_id`), por ejemplo
`T012ABCDEF:U012ABCDEF`. Cada interacción vuelve a consultar MariaDB y exige:

1. un mensaje directo al bot;
2. un espacio y usuario con formato válido;
3. un vínculo Slack activo en `identidades_mensajeria`;
4. un usuario Hermes activo;
5. el permiso persistente de la operación;
6. una selección y parámetros válidos.

Bolt valida los sobres recibidos por la conexión autenticada de Socket Mode.
La adaptación confirma cada comando o botón con `ack()` antes de consultar la
base de datos o iniciar SSH. Además, limita a 30 solicitudes por identidad y
minuto, conserva como máximo 5 000 estados efímeros y no registra el contenido
de los mensajes ni los tokens.

Las operaciones sensibles muestran botones `Confirmar` y `Cancelar`. El reto
aleatorio caduca, solo puede consumirse una vez y está ligado al espacio,
usuario, acción, parámetros y conjunto exacto de servidores ya autorizados.

## Crear la aplicación de Slack

El archivo
[`infraestructura/manifiesto_slack.ejemplo.yaml`](../infraestructura/manifiesto_slack.ejemplo.yaml)
declara el comando, la interactividad y los permisos mínimos controlados por
Hermes. En la administración oficial de Slack:

1. crea una aplicación desde un manifiesto y revisa sus campos antes de
   aceptarlo;
2. instala la aplicación en el espacio de laboratorio;
3. conserva el token de bot `xoxb-...`;
4. crea un token de aplicación `xapp-...` con el alcance
   `connections:write`;
5. comprueba que Socket Mode y la interactividad estén habilitados.

Los alcances de bot declarados son `commands`, `chat:write` y `files:write`. Este
último permite entregar al usuario una descarga ya autorizada. El alcance
`connections:write` pertenece al token de aplicación, no al token del bot.
No pegues ninguno de los tokens en Git, capturas, incidencias o comandos del
historial.

Configura exclusivamente el `.env` local:

```dotenv
HERMES_SLACK_HABILITADO=true
HERMES_TOKEN_BOT_SLACK=xoxb_token_real_del_laboratorio
HERMES_TOKEN_APLICACION_SLACK=xapp_token_real_del_laboratorio
HERMES_TIEMPO_CONFIRMACION_SLACK_SEGUNDOS=60
HERMES_MAX_SERVIDORES_MOSTRADOS_SLACK=50
```

Los valores de `.env.ejemplo` son marcadores sin validez. Hermes representa
ambos secretos con `SecretStr` y rechaza al iniciar tokens vacíos, con espacios
o con un prefijo incompatible.

## Vincular un usuario

Si usas `curl | bash`, el asistente de instalación también ofrece esta
vinculación: después de iniciar los servicios, introduce el ID de equipo y de
usuario mostrados por `/hermes ayuda` en un mensaje directo al bot. No necesitas
ejecutar el comando manual siguiente. Al repetir la instalación, puedes conservar
un vínculo activo o introducir otros identificadores explícitamente.

Inicia primero Slack sin vinculación:

```bash
source .venv/bin/activate
python -m aplicacion.interfaces.slack
```

En un mensaje directo al bot, ejecuta `/hermes ayuda`. La denegación muestra el
identificador del equipo y el usuario necesarios para la vinculación. Desde una
terminal local autorizada:

```bash
python -m aplicacion.comandos.vincular_usuario_slack \
  --usuario administrador_local \
  --identificador-equipo T012ABCDEF \
  --identificador-usuario U012ABCDEF \
  --nombre-slack nombre_visible_opcional
```

Sustituye ambos identificadores por los mostrados por el bot. El nombre es solo
una referencia visual. Para revocar Slack sin modificar Telegram ni desactivar
el usuario Hermes:

```bash
python -m aplicacion.comandos.desvincular_usuario_slack \
  --usuario administrador_local
```

## Comandos disponibles

Todos los comandos se envían por mensaje directo:

```text
/hermes ayuda
/hermes servidores
/hermes grupos
/hermes seleccionar 1
/hermes seleccionar_grupo 2
/hermes seleccionar_todos
/hermes seleccion
/hermes diagnostico
/hermes identidad
/hermes proceso 1
/hermes servicio hermes-prueba.service
/hermes iniciar_servicio hermes-prueba.service
/hermes detener_servicio hermes-prueba.service
/hermes reiniciar_servicio hermes-prueba.service
/hermes usuarios
/hermes crear_usuario hermes_prueba Cuenta de prueba Hermes
/hermes agregar_grupo hermes_prueba operadores
/hermes quitar_grupo hermes_prueba operadores
/hermes bloquear_usuario hermes_prueba
/hermes desbloquear_usuario hermes_prueba
/hermes eliminar_usuario hermes_prueba
/hermes archivo_info /srv/hermes/intercambio/prueba.txt
/hermes descargar_archivo /srv/hermes/intercambio/prueba.txt
/hermes aplicaciones
/hermes estado_aplicacion 1
/hermes desplegar 1 1.0.0 /srv/hermes/artefactos/api-1.0.0.bin
/hermes revertir_despliegue 1 1
/hermes reiniciar
/hermes cancelar
```

La selección individual, por grupo y total tiene el mismo significado que en
Telegram. Una operación múltiple se ejecuta con la concurrencia acotada del
backend, presenta un resultado por servidor y conserva los fallos de manera
independiente. Reinicios y cambios de servicio o usuario siempre requieren el
botón de confirmación y el permiso correspondiente. Slack no acepta contraseñas
ni permite activar la excepción para cuentas protegidas.

El estado conversacional es deliberadamente efímero y se pierde al reiniciar
el proceso; inventario, usuarios, vínculos, permisos y auditoría sí permanecen
en MariaDB.

Las operaciones de archivo exigen una selección individual. Slack consulta y
entrega descargas mediante `files_upload_v2`; no recibe cargas hacia el servidor
en este hito porque un comando de barra no transporta adjuntos. Las cargas están
disponibles por la API local y Telegram. El contenido sigue limitado por la
configuración común y nunca se persiste en MariaDB.

Los artefactos para desplegar también deben cargarse previamente mediante la
API o Telegram. Slack puede listar aplicaciones, consultar su integridad e
iniciar un despliegue o una reversión. Las dos mutaciones muestran botones
caducables de un solo uso y vuelven a comprobar el permiso antes de entrar al
gestor común. Consulta `despliegues.md` para preparar plantillas y rutas.

## Auditoría y procesos

Slack, Telegram y FastAPI pueden ejecutarse como procesos separados, pero
importan el mismo backend y se conectan a la misma MariaDB. Una acción iniciada
en Slack crea un registro por servidor con canal `slack`, origen acotado e
identificador de solicitud con prefijo `sl:`. No es obligatorio mantener
FastAPI o Telegram activos para usar Slack.

Para una comprobación no destructiva sobre el Ubuntu del laboratorio:

```text
/hermes servidores
/hermes seleccionar 1
/hermes identidad
/hermes diagnostico
```

No pruebes `reiniciar` ni cambios sobre servicios esenciales del anfitrión.
Utiliza únicamente la unidad de laboratorio descrita en `servicios.md`.

## Referencias oficiales

- [Socket Mode con Slack Bolt](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/)
- [Aplicaciones asíncronas](https://docs.slack.dev/tools/bolt-python/concepts/async/)
- [Comandos de barra](https://docs.slack.dev/tools/bolt-python/concepts/commands/)
- [Acciones y botones](https://docs.slack.dev/tools/bolt-python/concepts/actions/)
- [Confirmación de solicitudes](https://docs.slack.dev/tools/bolt-python/concepts/acknowledge/)
- [Comprobación de identidad del token](https://docs.slack.dev/reference/methods/auth.test/)

La conversación y la entrega reales quedan pendientes de los tokens del
laboratorio; la autorización y el rechazo entre espacios se prueban con
clientes simulados.
