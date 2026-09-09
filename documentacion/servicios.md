# Administración de servicios

El hito 7 incorpora cuatro operaciones comunes sin trasladar órdenes del
sistema operativo a Telegram ni a la API:

- `consultar_servicio`;
- `iniciar_servicio`;
- `detener_servicio`;
- `reiniciar_servicio`.

El motor valida el nombre, comprueba el permiso, exige confirmación para las
tres mutaciones, selecciona el adaptador, ejecuta la operación por SSH y
registra el resultado en auditoría.

## Nombres y resultados

`nombre_servicio` acepta entre 1 y 128 caracteres ASCII. Debe comenzar con una
letra o un número y solo puede contener letras, números, punto, guion, guion
bajo y arroba. No se admiten espacios, comillas, rutas, comodines ni
metacaracteres de shell.

En Linux se usa el nombre de unidad, por ejemplo `nginx.service`. En Windows se
usa el nombre interno, por ejemplo `sshd`, y no su nombre visible traducido.

Los adaptadores devuelven el mismo contrato:

| Campo | Significado |
| --- | --- |
| `nombre_servicio` | Nombre exacto solicitado. |
| `estado` | `activo`, `inactivo`, `iniciando`, `deteniendo`, `pausado`, `fallido`, `recargando` o `desconocido`. |
| `estado_nativo` | Estado original informado por systemd o Windows. |
| `inicio_automatico` | `true`, `false` o `null` cuando no se puede determinar. |
| `accion_realizada` | `consulta`, `inicio`, `detencion` o `reinicio`. |

Un nombre válido que no existe produce `servicio_no_encontrado`. Un Linux sin
`systemctl` produce `gestor_servicios_no_disponible`; Hermes no intenta usar un
gestor incompatible.

## Implementación Linux

El adaptador consulta `LoadState`, `ActiveState` y `UnitFileState` mediante
`systemctl show`. Inicio, detención y reinicio utilizan respectivamente
`systemctl start`, `systemctl stop` y `systemctl restart`. No se usa `--force`.

Las consultas normalmente funcionan sin elevación. Para cambiar el estado, el
adaptador usa directamente `systemctl` si la cuenta remota es `root`; en otro
caso usa `sudo -n`, que nunca solicita una contraseña de forma interactiva.

No concedas acceso general a `systemctl`. En una máquina de laboratorio, define
con `visudo` cada servicio y operación autorizados. Este ejemplo permite
administrar únicamente una unidad de prueba; sustituye `usuario_hermes` y
verifica primero la ruta con `command -v systemctl`:

```sudoers
Cmnd_Alias HERMES_SERVICIO_PRUEBA = /usr/bin/systemctl start -- hermes-prueba.service, \
    /usr/bin/systemctl stop -- hermes-prueba.service, \
    /usr/bin/systemctl restart -- hermes-prueba.service
usuario_hermes ALL=(root) NOPASSWD: HERMES_SERVICIO_PRUEBA
```

Para una prueba aislada puede crearse en una VM autorizada una unidad sin
efectos externos:

```ini
[Unit]
Description=Servicio temporal de prueba para Hermes

[Service]
Type=oneshot
ExecStart=/usr/bin/true
RemainAfterExit=yes
```

Guárdala como `/etc/systemd/system/hermes-prueba.service`, ejecuta
`sudo systemctl daemon-reload` y concede solamente las tres órdenes anteriores.
Al terminar, detén la unidad, elimina el archivo y vuelve a ejecutar
`sudo systemctl daemon-reload`. No uses SSH, red, base de datos ni otro servicio
crítico como objetivo de una demostración.

## Implementación Windows Server

El adaptador invoca PowerShell de forma no interactiva. `Get-Service` localiza
el servicio exacto; `Start-Service`, `Stop-Service` y `Restart-Service` cambian
su estado. Después se vuelve a consultar el servicio y se obtiene `StartMode`
mediante `Win32_Service`. La detención y el reinicio no usan `-Force`, por lo
que Hermes no ordena detener dependencias automáticamente.

La cuenta OpenSSH debe poder consultar servicios y recibir solo los permisos
necesarios sobre el servicio de laboratorio. Para una primera comprobación en
una VM Windows aislada puede utilizarse una cuenta administrativa dedicada;
antes de producción deben limitarse sus derechos con las ACL del Administrador
de control de servicios. No pruebes sobre `sshd`, WinRM, el registro de eventos
ni servicios necesarios para la conectividad de la VM.

## Permisos Hermes

| Permiso | Administrador | Operador de inventario | Auditor |
| --- | --- | --- | --- |
| `consultar_servicios` | Sí | Sí | No |
| `gestionar_servicios` | Sí | No | No |

La autorización de Hermes no sustituye los permisos del sistema remoto. Deben
cumplirse ambos controles. Las mutaciones también requieren `confirmar=true` en
la API o un botón efímero de un solo uso en Telegram.

## Uso desde la API

Consulta:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{"parametros":{"nombre_servicio":"hermes-prueba.service"}}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/consultar_servicio
```

Inicio confirmado:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "parametros":{"nombre_servicio":"hermes-prueba.service"},
    "confirmar":true
  }' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/iniciar_servicio
```

Para detener o reiniciar cambia el último segmento por `detener_servicio` o
`reiniciar_servicio`. Una solicitud sin confirmación se rechaza antes de abrir
la conexión SSH.

## Uso desde Telegram

```text
/servicio hermes-prueba.service
/iniciar_servicio hermes-prueba.service
/detener_servicio hermes-prueba.service
/reiniciar_servicio hermes-prueba.service
```

Los últimos tres comandos presentan botones de confirmación y cancelación. El
desafío caduca, solo puede consumirse una vez y queda ligado al usuario,
selección, acción y nombre previamente validados. Para grupos o todos los
servidores, Hermes fija los IDs antes de mostrar la confirmación.

## Alcance de las pruebas

La consulta de `ssh.service` se comprueba de forma real contra el Ubuntu
anfitrión mediante AsyncSSH, sin alterar su estado. Inicio, detención y reinicio
se prueban con transportes simulados porque la cuenta SSH local no dispone de
`sudo` sin interacción y no existe una VM de servicios autorizada disponible.
Windows Server se valida con guiones PowerShell y respuestas simuladas hasta
que se conecte una VM de laboratorio.

Referencias oficiales:

- [Manual fuente de systemctl](https://github.com/systemd/systemd/blob/main/man/systemctl.xml)
- [Get-Service](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-service)
- [Start-Service](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-service)
- [Stop-Service](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/stop-service)
- [Restart-Service](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/restart-service)
