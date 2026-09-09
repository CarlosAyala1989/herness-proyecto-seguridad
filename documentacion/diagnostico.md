# Monitoreo y diagnóstico

El hito 6 añade una operación común de solo lectura para Linux y Windows Server.
La API y Telegram solicitan `obtener_diagnostico`; el motor comprueba el permiso
`consultar_diagnostico`, selecciona el adaptador del sistema declarado, ejecuta
un guion fijo por SSH y audita el resultado.

## Contrato normalizado

Una ejecución correcta devuelve estos datos:

| Campo | Tipo | Significado |
| --- | --- | --- |
| `estado` | texto | `disponible` cuando la conexión y la respuesta fueron válidas. |
| `cpu_porcentaje` | decimal o nulo | Uso de CPU entre 0 y 100. |
| `memoria_porcentaje` | decimal o nulo | Memoria física usada entre 0 y 100. |
| `disco_porcentaje` | decimal o nulo | Uso del disco raíz o del disco del sistema. |
| `tiempo_actividad_segundos` | entero o nulo | Segundos desde el último arranque. |
| `sistema` | texto o nulo | Familia o edición informada por el equipo. |
| `version` | texto o nulo | Versión del sistema o núcleo. |
| `nombre_equipo` | texto o nulo | Nombre remoto del equipo. |

Una métrica que el sistema no puede proporcionar se devuelve como `null` en la
API y como `No disponible` en Telegram. Esto no invalida las demás métricas. Si
SSH falla, la plataforma declarada no coincide o la respuesta no cumple el
contrato, la operación completa devuelve un error controlado y queda auditada.

## Recopilación por plataforma

Linux toma dos lecturas breves de `/proc/stat` para calcular el uso de CPU, usa
`MemTotal` y `MemAvailable` de `/proc/meminfo`, consulta la raíz con `df -Pk /`,
lee `/proc/uptime` y obtiene versión y equipo con `uname` y `hostname`.

Windows Server ejecuta un guion PowerShell no interactivo. Consulta
`Win32_Processor`, `Win32_OperatingSystem` y `Win32_LogicalDisk` con
`Get-CimInstance`; utiliza el disco indicado por `SystemDrive` y obtiene el
nombre mediante la API de entorno de .NET. El guion fijo se codifica como
UTF-16LE para `-EncodedCommand`, evitando construir una orden con entradas del
usuario.

La CPU es una lectura puntual, no un promedio histórico. El disco representa
solo la raíz de Linux o el volumen del sistema de Windows; la enumeración de
volúmenes adicionales queda fuera de este hito.

## Uso

Desde la API local:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/obtener_diagnostico
```

Desde una conversación privada ya autorizada en Telegram:

```text
/servidores
/seleccionar 1
/diagnostico
```

Ejemplo de presentación:

```text
Servidor: ubuntu-laboratorio
Sistema: Linux
Versión: 6.8.0
Equipo: ubuntu-laboratorio
Estado: Disponible
CPU: 18.12 %
RAM: 42.00 %
Disco: 63.00 %
Tiempo de actividad: 1 d, 1 h, 1 min
```

## Seguridad y límites

- No se acepta ningún parámetro ni comando libre.
- Los porcentajes deben ser finitos y pertenecer al intervalo de 0 a 100.
- La respuesta debe contener exactamente una vez todos los campos esperados.
- Los textos y el tiempo de actividad tienen límites antes de exponerse.
- Se mantienen los plazos y el límite de salida del transporte SSH.
- Administrador y operador de inventario reciben `consultar_diagnostico`; el
  auditor no lo recibe.
- Cada ejecución deja un registro por usuario, servidor y canal.

La gestión de servicios, la ejecución simultánea sobre grupos y las alertas
automáticas pertenecen respectivamente a los hitos 7, 8 y 10.

## Referencias técnicas

- [Interfaz `/proc` del núcleo Linux](https://www.kernel.org/doc/html/latest/filesystems/proc.html)
- [Estadísticas de CPU del núcleo Linux](https://docs.kernel.org/admin-guide/cpu-load.html)
- [Clase Win32_OperatingSystem](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem)
- [Clase Win32_Processor](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-processor)
- [Uso de Get-CimInstance](https://learn.microsoft.com/en-us/powershell/scripting/samples/getting-wmi-objects--get-ciminstance-)
