# Monitoreo automático y alertas

El hito 10 incorpora un proceso local independiente que consulta periódicamente
los servidores configurados. Reutiliza el catálogo cerrado, los adaptadores
Linux y Windows Server y el transporte AsyncSSH. No construye comandos desde
los umbrales, los nombres de servidores ni los mensajes recibidos.

## Flujo

```text
configuraciones_monitoreo ──► objetivos activos
                                     │
                              concurrencia acotada
                                     │
                   ┌─────────────────┴─────────────────┐
                   ▼                                   ▼
           diagnóstico normalizado             servicios críticos
                   │                                   │
                   └─────────────────┬─────────────────┘
                                     ▼
                         evaluación de condiciones
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
             apertura deduplicada                 recuperación
                    │                                 │
                    └────────────────┬────────────────┘
                                     ▼
                         entregas Telegram / Slack
```

Cada servidor usa su propia sesión de MariaDB, su propio transporte y un plazo
total de sondeo. El máximo de conexiones simultáneas se configura mediante
`HERMES_MAX_CONCURRENCIA_MONITOREO`; no limita la cantidad total de servidores
del inventario.

## Configurar una política

Aplica primero la migración `0007` y mantén FastAPI sobre la interfaz local:

```bash
source .venv/bin/activate
alembic -c alembic.ini upgrade head
uvicorn aplicacion.principal:aplicacion --host 127.0.0.1 --port 8000
```

Un administrador puede crear o reemplazar la política del servidor 1:

```bash
curl --user administrador_local \
  --request PUT \
  --header 'Content-Type: application/json' \
  --data '{
    "activo": true,
    "umbral_cpu": 85,
    "umbral_memoria": 90,
    "umbral_disco": 90,
    "servicios_criticos": ["hermes-prueba.service"]
  }' \
  http://127.0.0.1:8000/api/v1/monitoreo/servidores/1
```

Los porcentajes admiten valores entre 0 y 100. Un valor `null` deshabilita solo
ese umbral, sin desactivar la comprobación de disponibilidad ni las demás
métricas. Se permiten como máximo 20 servicios por servidor y cada nombre usa
la misma validación cerrada de la administración de servicios.

Para detener el sondeo de un servidor sin borrar su historial, cambia `activo`
a `false`. En el siguiente ciclo Hermes cerrará los episodios abiertos con una
recuperación que indica que el monitoreo fue desactivado.

Consulta todas las políticas:

```bash
curl --user administrador_local \
  http://127.0.0.1:8000/api/v1/monitoreo/configuraciones
```

## Suscribir Telegram y Slack

Los destinos proceden exclusivamente de identidades previamente vinculadas.
Una identidad no recibe alertas hasta que un administrador activa su
suscripción.

Lista los identificadores internos elegibles:

```bash
curl --user administrador_local \
  http://127.0.0.1:8000/api/v1/monitoreo/destinos
```

Activa, por ejemplo, la identidad 3:

```bash
curl --user administrador_local \
  --request PUT \
  --header 'Content-Type: application/json' \
  --data '{"activo":true}' \
  http://127.0.0.1:8000/api/v1/monitoreo/destinos/3
```

El usuario Hermes, la identidad y la suscripción deben continuar activos al
momento del envío. Telegram requiere que el usuario haya iniciado antes una
conversación con el bot. Slack entrega mediante `chat.postMessage` al usuario
del mismo espacio registrado. Los canales deshabilitados conservan sus
entregas pendientes sin exponer ni copiar tokens.

## Ejecutar el monitor

Prueba un solo ciclo antes de habilitar la periodicidad:

```bash
python -m aplicacion.monitoreo --una-vez
```

Esta modalidad respeta políticas, conexiones y suscripciones, pero permite la
ejecución aunque `HERMES_MONITOREO_HABILITADO` sea `false`.

Para mantenerlo activo, configura `.env`:

```dotenv
HERMES_MONITOREO_HABILITADO=true
HERMES_INTERVALO_MONITOREO_SEGUNDOS=60
HERMES_MAX_CONCURRENCIA_MONITOREO=4
HERMES_TIEMPO_LIMITE_SONDEO_SEGUNDOS=45
HERMES_MAX_INTENTOS_NOTIFICACION_ALERTA=3
```

Luego inicia un único proceso en una terminal dedicada:

```bash
python -m aplicacion.monitoreo
```

El intervalo comienza después de completar cada ciclo. La persistencia de
tareas administrativas con fecha o frecuencia pertenece al hito 11; este
proceso periódico no permite programar comandos ni mutaciones remotas.

## Condiciones y recuperación

Hermes abre episodios para:

- servidor no disponible para el diagnóstico seguro;
- CPU igual o superior a su umbral;
- memoria igual o superior a su umbral;
- disco del sistema igual o superior a su umbral;
- servicio crítico en estado distinto de `activo` o no consultable.

Una métrica `no_disponible` no abre una alerta de umbral y tampoco se interpreta
como recuperación de un episodio existente. Si el diagnóstico completo falla,
Hermes abre únicamente la indisponibilidad y conserva los otros episodios hasta
que las métricas vuelvan a evaluarse.

`alertas.clave_activa` garantiza una sola fila activa por servidor, tipo y
objetivo. Los ciclos sucesivos actualizan la última observación sin crear ni
reenviar otra alerta. Cuando la condición desaparece, la fila pasa a
`recuperada`, libera la clave y puede existir un episodio nuevo en el futuro.

La recuperación se envía únicamente a identidades que recibieron la apertura.
Cada entrega se registra en `notificaciones_alertas`; los fallos se reintentan
en ciclos posteriores hasta el máximo configurado. Los errores almacenados son
genéricos y nunca incluyen respuestas del proveedor ni secretos.

## Consultar alertas

Administradores, operadores y auditores pueden consultar el historial:

```bash
curl --user administrador_local \
  'http://127.0.0.1:8000/api/v1/alertas?estado=activa'

curl --user administrador_local \
  'http://127.0.0.1:8000/api/v1/alertas?estado=recuperada'
```

Solo el rol administrador recibe `gestionar_monitoreo`. Los roles administrador,
operador de inventario y auditor reciben `consultar_monitoreo`. Cada apertura,
recuperación y cambio de configuración queda auditado; las salidas SSH y los
tokens no se almacenan en alertas ni auditoría.

## Prueba segura en laboratorio

Para comprobar una alerta sin afectar al anfitrión, configura temporalmente un
umbral inferior al uso actual o utiliza la unidad aislada descrita en
`servicios.md`. Ejecuta dos ciclos y verifica que el segundo no duplica la
alerta. Después eleva el umbral o inicia la unidad de prueba y ejecuta otro ciclo
para registrar la recuperación.

No detengas `ssh.service`, MariaDB, Docker ni servicios necesarios para la
conectividad. No uses el reinicio del servidor como prueba de monitoreo.

## Referencias técnicas

- [Tareas asíncronas de Python](https://docs.python.org/3.12/library/asyncio-task.html)
- [Sesiones asíncronas concurrentes de SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks)
- [Método `chat.postMessage` de Slack](https://docs.slack.dev/reference/methods/chat.postMessage)
- [Método `send_message` de python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/telegram.bot.html#telegram.Bot.send_message)
