# Operaciones sobre varios servidores

El hito 8 permite aplicar una acción existente a servidores individuales, a un
grupo o a todos los servidores activos. No añade órdenes remotas nuevas: cada
destino sigue pasando por el catálogo cerrado, los permisos, el adaptador de su
sistema operativo, el transporte SSH seguro y la auditoría del backend común.

## Estrategias de selección

Una solicitud debe contener exactamente una de estas formas:

```json
{"seleccion":{"ids_servidores":[1,2,3,4]}}
```

```json
{"seleccion":{"id_grupo":2}}
```

```json
{"seleccion":{"todos":true}}
```

Los identificadores explícitos conservan su orden y no pueden repetirse. Un
identificador inexistente produce un resultado de error para ese elemento sin
cancelar los demás. La selección por grupo se resuelve al iniciar la operación
y conserva sus miembros inactivos como resultados rechazados. `todos` incluye
únicamente servidores activos.

El modelo de permisos actual es global por acción: un usuario que posee el
permiso puede operar los servidores activos del inventario. Todavía no existe
una lista de control de acceso distinta para cada servidor. Por ello, “todos
los autorizados” significa todos los servidores activos para los que el rol
concede la acción solicitada.

## Flujo concurrente y aislamiento

```text
selección validada
       │
       ▼
resolución de destinos y límite por solicitud
       │
       ▼
semáforo de concurrencia
       │
       ├──► sesión SQL propia ─► adaptador Linux   ─► SSH ─► resultado 1
       ├──► sesión SQL propia ─► adaptador Windows ─► SSH ─► resultado 2
       ├──► sesión SQL propia ─► adaptador Linux   ─► SSH ─► error 3
       └──► ...
       │
       ▼
respuesta consolidada y auditoría individual
```

No se comparte una sesión de SQLAlchemy entre tareas asíncronas. Un semáforo
limita las conexiones activas y cada destino tiene un plazo total propio,
además de los plazos de conexión, autenticación y operación de AsyncSSH. Un
fallo, una desconexión o un plazo agotado se convierte en el resultado de ese
servidor y no cancela las demás tareas.

Variables disponibles:

```dotenv
HERMES_MAX_CONCURRENCIA_ACCIONES_MULTIPLES=4
HERMES_MAX_SERVIDORES_ACCION_MULTIPLE=100
HERMES_TIEMPO_LIMITE_ACCION_MULTIPLE_SEGUNDOS=45
```

El máximo por solicitud es un control de recursos; no limita el tamaño del
inventario. Para operar más equipos se pueden utilizar solicitudes separadas.
El plazo total debe ser mayor que los tiempos normales de conexión y ejecución
configurados para SSH.

## Uso desde la API local

Diagnóstico sobre cuatro identificadores:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{"seleccion":{"ids_servidores":[1,2,3,4]}}' \
  http://127.0.0.1:8000/api/v1/acciones-multiples/obtener_diagnostico
```

Consulta de un servicio sobre un grupo:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "seleccion":{"id_grupo":2},
    "parametros":{"nombre_servicio":"hermes-prueba.service"}
  }' \
  http://127.0.0.1:8000/api/v1/acciones-multiples/consultar_servicio
```

Una mutación sensible añade una confirmación para toda la selección:

```json
{
  "seleccion": {"id_grupo": 2},
  "parametros": {"nombre_servicio": "hermes-prueba.service"},
  "confirmar": true
}
```

La respuesta indica el estado global, los totales y un elemento por destino:

```json
{
  "accion": "obtener_identidad",
  "estado": "completada_con_errores",
  "total_servidores": 4,
  "servidores_completados": 3,
  "servidores_fallidos": 1,
  "duracion_ms": 182.4,
  "resultados": [
    {
      "id_servidor": 1,
      "nombre_servidor": "linux-01",
      "sistema_operativo": "linux",
      "estado": "completada",
      "datos": {"usuario": "operador", "nombre_equipo": "linux-01"},
      "duracion_ms": 81.2,
      "codigo_error": null,
      "mensaje_error": null
    }
  ]
}
```

No se devuelve el comando remoto, `stderr`, credenciales ni excepciones
internas. Cada resultado genera auditoría con el mismo identificador de
solicitud y un `id_recurso` distinto.

## Uso desde Telegram

```text
/grupos
/seleccionar_grupo 2
/seleccion
/diagnostico
```

Para trabajar con todos los servidores activos:

```text
/seleccionar_todos
/servicio hermes-prueba.service
```

Hermes envía un resumen y una línea por servidor. Si el resultado supera el
límite de Telegram, se divide en varios mensajes sin descartar destinos. Las
acciones sensibles muestran una sola confirmación; antes de presentar el botón,
Hermes convierte el grupo o la selección dinámica en una lista fija de
identificadores. Así, un cambio posterior en el grupo no amplía silenciosamente
la operación ya confirmada.

## Comprobación del laboratorio

Las pruebas de integración crean cuatro servidores temporales, alternando Linux
y Windows Server, y los asocian a un grupo. El transporte simulado permite tres
respuestas y hace que el cuarto servidor no esté disponible. Se comprueba que:

- los cuatro destinos se inician concurrentemente dentro del máximo configurado;
- los tres destinos disponibles terminan aunque el cuarto falle;
- un servidor lento agota solo su propio plazo;
- el resultado mantiene el orden y el detalle por servidor;
- el usuario sin permiso recibe una denegación;
- la auditoría contiene un registro por servidor;
- Telegram reutiliza el mismo orquestador y conserva el canal de auditoría.

Estas pruebas no contactan servidores reales ni alteran servicios del
anfitrión. La comprobación con cuatro máquinas virtuales reales queda pendiente
de disponer del laboratorio Linux y Windows Server autorizado.

Slack, el monitoreo automático y las alertas reutilizan este orquestador desde
los hitos 9 y 10.
