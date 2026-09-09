# Integración con Slack

Slack es una segunda interfaz del backend común de Hermes. Usa Slack Bolt
asíncrono mediante Socket Mode: el proceso abre una conexión saliente con
Slack y no publica un webhook, dominio ni puerto adicional. El canal interpreta
`/hermes`, pero inventario, permisos, acciones, SSH y auditoría permanecen en
los mismos servicios utilizados por FastAPI y Telegram.

Desde el hito 10, el proceso de monitoreo puede entregar alertas y
recuperaciones mediante `chat.postMessage`. La identidad debe continuar activa
y tener una suscripción habilitada por un administrador. El envío automático
no abre Socket Mode ni concede permisos administrativos adicionales.

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

Los únicos alcances de bot declarados son `commands` y `chat:write`. El alcance
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
/hermes reiniciar
/hermes cancelar
```

La selección individual, por grupo y total tiene el mismo significado que en
Telegram. Una operación múltiple se ejecuta con la concurrencia acotada del
backend, presenta un resultado por servidor y conserva los fallos de manera
independiente. Reinicios y cambios de servicio siempre requieren el botón de
confirmación y el permiso correspondiente.

El estado conversacional es deliberadamente efímero y se pierde al reiniciar
el proceso; inventario, usuarios, vínculos, permisos y auditoría sí permanecen
en MariaDB.

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
