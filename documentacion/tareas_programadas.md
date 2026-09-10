# Tareas administrativas programadas

El hito 11 permite guardar una acción del catálogo para una fecha concreta o
repetirla por intervalo. MariaDB conserva la definición, cada ocurrencia, su
resultado resumido y las entregas opcionales a Telegram o Slack.

No existe una segunda implementación de las acciones: el trabajador llama al
mismo motor autorizado, sus adaptadores Linux/Windows, AsyncSSH y la auditoría
que usan FastAPI y los bots.

## Flujo

```text
API local ─► validar permiso, acción, parámetros y confirmación
                    │
                    ▼
            congelar IDs de servidores
                    │
                    ▼
          tareas_programadas (MariaDB)
                    │
              trabajador periódico
                    │
         reclamo condicional + ocurrencia única
                    │
                    ▼
        reautorizar creador ─► motor de acciones múltiples
                    │
                    ├──► ejecuciones_tareas
                    └──► notificaciones_tareas ─► Telegram / Slack
```

## Crear una tarea

Aplica primero la migración `0008` e inicia FastAPI. Todas las fechas deben ser
ISO 8601 e incluir zona horaria; Hermes las normaliza internamente a UTC.

Este ejemplo consulta una vez la identidad remota del servidor 1. Sustituye la
fecha por un instante actual o futuro:

```bash
curl --user administrador_local \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "nombre": "Identidad nocturna",
    "descripcion": "Comprobación única del laboratorio",
    "codigo_accion": "obtener_identidad",
    "seleccion": {"ids_servidores": [1]},
    "parametros": {},
    "tipo_programacion": "una_vez",
    "programada_para": "2030-01-15T22:30:00-05:00",
    "notificar_resultado": true
  }' \
  http://127.0.0.1:8000/api/v1/tareas
```

Para ejecutar sobre un grupo se admite `{"id_grupo": 2}` y para todos los
servidores activos, `{"todos": true}`. La selección se resuelve al crear la
tarea y se guardan los identificadores exactos. Agregar después un servidor al
grupo no lo incorpora silenciosamente a una tarea ya confirmada.

Una tarea periódica requiere un intervalo de 60 segundos a un año:

```bash
curl --user administrador_local \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "nombre": "Diagnóstico cada cinco minutos",
    "codigo_accion": "obtener_diagnostico",
    "seleccion": {"id_grupo": 2},
    "tipo_programacion": "intervalo",
    "programada_para": "2030-01-15T22:30:00-05:00",
    "intervalo_segundos": 300,
    "notificar_resultado": false
  }' \
  http://127.0.0.1:8000/api/v1/tareas
```

Las acciones sensibles, como reiniciar un servicio, exigen `"confirmar": true`
al programarlas. El indicador queda asociado a la definición exacta, sus
parámetros y sus destinos congelados. No habilita comandos libres ni acciones
distintas en el futuro.

## Ejecutar el trabajador

Prueba primero un solo ciclo:

```bash
source .venv/bin/activate
python -m aplicacion.tareas --una-vez
```

Para mantenerlo activo configura `.env`:

```dotenv
HERMES_TAREAS_HABILITADAS=true
HERMES_INTERVALO_REVISION_TAREAS_SEGUNDOS=15
HERMES_DURACION_BLOQUEO_TAREA_SEGUNDOS=600
HERMES_MAX_TAREAS_POR_CICLO=20
HERMES_MAX_CONCURRENCIA_TAREAS=2
HERMES_MAX_INTENTOS_NOTIFICACION_TAREA=3
```

Después inicia un proceso en una terminal dedicada:

```bash
python -m aplicacion.tareas
```

El bloqueo debe durar más que
`HERMES_TIEMPO_LIMITE_ACCION_MULTIPLE_SEGUNDOS`; la configuración se rechaza si
no se cumple. Varias instalaciones del trabajador pueden competir sin reclamar
la misma ocurrencia, aunque para el laboratorio se recomienda mantener una
sola. Un límite de concurrencia independiente evita que muchas tareas vencidas
agoten de golpe las conexiones SSH.

## Consultar y cancelar

Los roles administrador, operador de inventario y auditor poseen
`consultar_tareas`. Administrador y operador poseen `gestionar_tareas`, pero
crear una definición también exige el permiso propio de la acción. Por ejemplo,
un operador no puede programar `reiniciar_servidor` solo por gestionar tareas.

```bash
curl --user administrador_local \
  'http://127.0.0.1:8000/api/v1/tareas?estado=activa'

curl --user administrador_local \
  http://127.0.0.1:8000/api/v1/tareas/1/ejecuciones

curl --user administrador_local \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"confirmar":true}' \
  http://127.0.0.1:8000/api/v1/tareas/1/cancelar
```

La cancelación elimina solo ocurrencias futuras. Si una ejecución ya fue
reclamada, se deja finalizar y queda en el historial. Las tareas completadas o
ya canceladas no pueden cancelarse otra vez.

## Entrega de resultados

Con `notificar_resultado=true`, Hermes materializa una entrega para cada
identidad Telegram o Slack activa del creador. El usuario y la identidad se
vuelven a validar al enviar. Un canal deshabilitado conserva la entrega
pendiente; un fallo se reintenta hasta el máximo configurado sin guardar la
respuesta del proveedor ni ningún token.

La notificación contiene el nombre, la acción, el estado y los recuentos de
servidores completados y fallidos. El detalle completo permanece en la API para
evitar mensajes excesivos.

## Prevención de duplicados y fallos

Cada ocurrencia tiene una restricción única por `id_tarea_programada` y
`programada_para`. El reclamo actualiza condicionalmente la próxima fecha y crea
el historial en la misma transacción. Los intervalos atrasados saltan los
instantes ya vencidos en vez de generar una ráfaga de ejecuciones.

Una acción remota no puede ofrecer atomicidad distribuida junto con MariaDB: el
servidor podría aceptar la orden justo antes de que el trabajador se interrumpa.
Para priorizar la ausencia de duplicados, Hermes aplica semántica de como máximo
una vez. Una ocurrencia abandonada pasa a `interrumpida` cuando vence su bloqueo
y no se reintenta automáticamente. El administrador debe consultar la auditoría
y el estado real del servidor antes de decidir una nueva acción manual.

Justo antes de conectar, el trabajador carga de nuevo al creador y sus permisos.
Una cuenta desactivada o un permiso revocado produce una ejecución `fallida` sin
abrir SSH. Los fallos de un servidor permanecen aislados por el motor múltiple y
no detienen los demás destinos ni las tareas siguientes.

## Alcance

Este hito admite fecha única e intervalo fijo persistente. Desde el hito 12, las
acciones de usuarios también pueden programarse porque pertenecen al catálogo
común; conservan sus permisos adicionales y confirmaciones. No se incorporan
todavía expresiones cron, calendarios complejos, transferencia de archivos ni
despliegues.
