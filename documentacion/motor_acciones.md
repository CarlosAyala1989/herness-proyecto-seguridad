# Motor de acciones controladas

El hito 4 permite ejecutar un conjunto pequeño y explícito de operaciones sobre
un servidor del inventario. La API nunca acepta texto para una shell: recibe un
código de acción y parámetros estructurados, y el adaptador de cada sistema
operativo selecciona una orden definida dentro de Hermes.

## Flujo de ejecución

```text
solicitud autenticada
        │
        ▼
catálogo inmutable ── acción desconocida ──► rechazo controlado
        │
        ▼
permiso persistente ── permiso ausente ────► 403 y auditoría
        │
        ▼
inventario y validación exacta de parámetros
        │
        ▼
confirmación, cuando la acción es sensible
        │
        ▼
adaptador Linux o Windows Server
        │
        ▼
transporte SSH seguro y resultado normalizado
        │
        ▼
auditoría por usuario, servidor, canal y resultado
```

El fallo de validación, la falta de confirmación y los errores de ejecución
también dejan un registro cuando ya se identificaron el usuario y el servidor.
Los parámetros y la salida remota no se copian al detalle de auditoría.

## Catálogo disponible

| Código | Permiso | Parámetros | Confirmación | Resultado normalizado |
| --- | --- | --- | --- | --- |
| `obtener_identidad` | `ejecutar_acciones_lectura` | Ninguno | No | Usuario remoto y nombre del equipo. |
| `consultar_proceso` | `ejecutar_acciones_lectura` | `id_proceso`, entero entre 1 y 4 194 304 | No | Identificador y nombre del proceso. |
| `reiniciar_servidor` | `reiniciar_servidor` | Ninguno | Sí | Reinicio programado con 60 segundos de margen. |

Linux usa herramientas del sistema y Windows Server invoca PowerShell de forma
no interactiva. Ambos adaptadores producen los mismos campos de respuesta. Un
sistema operativo distinto al declarado en el inventario se rechaza antes de
considerar válida la operación.

## Uso desde la API local

Inicia Hermes en `127.0.0.1` y consulta el catálogo visible para el usuario:

```bash
curl --user administrador_local \
  http://127.0.0.1:8000/api/v1/acciones
```

Obtén la identidad de un servidor ya registrado:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/obtener_identidad
```

Consulta un proceso mediante un identificador numérico:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{"parametros":{"id_proceso":1}}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/consultar_proceso
```

La respuesta contiene servidor, sistema operativo, acción, estado, datos
normalizados y duración. No expone la orden remota ni la salida de error.

## Operación sensible de reinicio

`reiniciar_servidor` programa un reinicio real. Se rechaza si el cuerpo no
incluye `"confirmar": true`, aunque el usuario tenga permiso. La forma de la
solicitud es:

```json
{
  "confirmar": true
}
```

No ejecutes esta acción sobre el Ubuntu anfitrión ni sobre otra máquina sin una
ventana de mantenimiento acordada. Las pruebas automatizadas usan un transporte
simulado y no reinician el sistema local.

## Respuestas y controles

- `401`: faltan credenciales válidas para la API local.
- `403`: el usuario no posee el permiso específico.
- `404`: no existe el servidor solicitado.
- `400`: falta la confirmación de una acción sensible.
- `422`: el código de la ruta o el cuerpo no cumple el contrato; los parámetros
  específicos inválidos se devuelven como un error controlado del motor.
- Los códigos desconocidos nunca se interpretan como órdenes.
- Los campos adicionales están prohibidos tanto en la solicitud como en el
  esquema particular de cada acción.
- La ejecución conserva los plazos, límites de salida y verificaciones de host
  definidos por el transporte SSH del hito 3.

## Comprobaciones realizadas en el laboratorio

Las acciones de lectura se ejecutaron a través de la API completa contra el
Ubuntu 24.04 anfitrión por OpenSSH en `127.0.0.1`. Se verificaron la identidad
remota y el proceso con identificador 1. Los datos temporales del inventario se
eliminaron al terminar.

No hay una máquina virtual Windows Server disponible en este laboratorio. El
adaptador PowerShell y la normalización se validan mediante pruebas automatizadas,
pero no se afirma una conexión real a Windows. Esa prueba queda pendiente de una
máquina de laboratorio autorizada.

## Extensión en hitos posteriores

Una operación nueva debe incorporar su código al catálogo, un esquema de
parámetros estricto, un permiso persistente cuando corresponda y una
implementación en ambos adaptadores. Telegram ya convierte la interacción del
usuario en estas solicitudes sin contener órdenes SSH ni reglas de autorización
propias. Slack seguirá el mismo contrato en el hito 9.
