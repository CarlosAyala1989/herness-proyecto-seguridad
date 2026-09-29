# Auditoría de los hitos 1 a 14

Esta revisión contrasta el código, las migraciones, la documentación y las
pruebas disponibles con los criterios del proyecto. «Implementado» significa
que existe el flujo y se ha ejecutado su prueba local; no equivale a afirmar
que una integración externa o una VM no disponible se haya probado de verdad.
El hito 15 no forma parte de esta entrega.

| Hito | Evidencia local | Validación aún necesaria |
| --- | --- | --- |
| 1. Base | FastAPI, `/salud`, configuración, MariaDB local y arranque documentado | Ninguna para el entorno local comprobado |
| 2. Inventario | Alembic en `0011 (head)`, modelos, roles, grupos e integración con MariaDB | Ninguna para la persistencia local |
| 3. SSH | AsyncSSH y servidor Linux efímero real; adaptador Windows simulado | Conexión a una VM Windows Server autorizada |
| 4. Acciones | Catálogo cerrado, permisos, confirmaciones y auditoría en pruebas | Acciones administrativas reales en VMs con privilegios mínimos |
| 5. Telegram | Autorización por identidad vinculada y pruebas simuladas | Bot real con token e identidad del usuario |
| 6. Diagnóstico | Normalización Linux/Windows y errores parciales probados | Métricas reales de Windows Server |
| 7. Servicios | Adaptadores, permisos, confirmaciones y pruebas de comandos | Servicio de prueba en Linux y Windows Server reales |
| 8. Múltiples VPS | Cuatro destinos simulados, concurrencia, aislamiento y auditoría | Cuatro máquinas de laboratorio reales |
| 9. Slack | Socket Mode, autorización y pruebas simuladas | Aplicación y espacio de trabajo Slack con credenciales reales |
| 10. Alertas | Ciclos, deduplicación, recuperación, persistencia y reintentos probados | Entrega externa real por Telegram y Slack |
| 11. Tareas | Reclamo único, historial, cancelación, autorización y notificación simulada | Ejecución administrativa real sobre VMs |
| 12. Usuarios | Adaptadores y protecciones probados sin cambiar cuentas del anfitrión | Cuentas de prueba Linux y Windows Server en VMs |
| 13. Archivos | SFTP real contra servidor efímero Linux, controles de rutas y límites | SFTP y ACL reales de Windows Server |
| 14. Despliegues | Instalación y reversión sobre SSH efímero Linux; recorridos API simulados | Despliegue y reversión en VMs Linux y Windows Server |

## Correcciones de esta auditoría

- Las notificaciones de alertas y tareas ahora persisten el resultado de una
  entrega pendiente o fallida. Una entrega marcada como enviada no se vuelve a
  seleccionar en los ciclos posteriores; los reintentos permanecen acotados.
- El notificador Slack verifica con `auth.test` el espacio de trabajo asociado
  al token antes de entregar a un identificador `equipo:usuario`. Un equipo
  diferente se rechaza antes de `chat.postMessage`.
- Los rechazos repetidos de HTTP Basic se limitan antes de una nueva
  verificación Argon2. El límite es local al proceso, por origen de conexión,
  con valores configurables y respuesta `429`.
- En Linux, SFTP rechaza rutas cuyos directorios puedan ser modificados por
  otros usuarios según propietario y permisos POSIX. La prueba usa un servidor
  efímero y comprueba el rechazo de un directorio inseguro.
- Los despliegues verifican la huella de la versión vigente antes de crear un
  respaldo, comprueban la restauración automática y compensan escrituras
  parciales detectadas. La reversión manual también verifica la versión actual,
  el respaldo, el contenido restaurado y, cuando procede, el servicio; si
  falla, intenta conservar la versión que estaba vigente.

## Comprobaciones reproducibles

Desde la raíz, con `.venv` y MariaDB configurados:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/pytest -q -m integracion
.venv/bin/alembic -c alembic.ini current
docker compose --env-file .env -f infraestructura/compose.yaml ps
```

En la revisión del 29 de septiembre de 2026: 183 pruebas unitarias y 20 de
integración pasaron; `ruff check` pasó, MariaDB estaba saludable y Alembic
indicó `0011 (head)`. Las pruebas de integración utilizan MariaDB local y un
servidor SSH efímero Linux, además de transportes simulados. No se ejecutaron
acciones destructivas ni cambios de cuentas o servicios sobre el anfitrión.

## Límites que no deben ocultarse

- La validación real de Telegram y Slack espera los tokens y las identidades
  del laboratorio. Las pruebas con simulaciones no acreditan conectividad con
  esos proveedores.
- No hay evidencia de una VM Windows Server ni de cuatro VMs simultáneas en
  esta revisión. Se requiere prepararlas y ejecutar los recorridos indicados
  en las guías antes de afirmar aceptación de extremo a extremo.
- La comprobación de propietarios y permisos SFTP es específica de Linux. En
  Windows, el administrador debe asegurar que ningún usuario distinto de la
  cuenta operadora o administradores pueda modificar los componentes de la
  ruta mediante ACL NTFS. SFTP no ofrece una operación portátil y atómica que
  vincule `realpath` y la apertura posterior; una cuenta remota comprometida
  con permisos de escritura sobre los directorios sigue siendo un riesgo.
- La entrega de mensajería es de tipo «al menos una vez» si el proceso cae
  después de enviar y antes de guardar el acuse. Ejecutar un solo trabajador
  de notificaciones en este entorno evita competencia normal, pero no elimina
  esa ventana inherente a la red externa y la transacción local.
- Un despliegue usa escritura SFTP directa. Se recuperan errores capturados,
  pero una interrupción brusca del proceso puede dejar una escritura parcial;
  se debe verificar y restaurar desde el respaldo antes de repetir. La
  estrategia atómica con renombrado y recuperación tras reinicio requeriría
  una ampliación posterior, sin alterar el contrato de los canales.
- El limitador HTTP es por proceso y usa la dirección de conexión, no
  cabeceras de proxy. La API continúa restringida a `127.0.0.1` y HTTP Basic
  no debe publicarse sin TLS y un control de acceso apropiado.

Estas limitaciones son operativas y de infraestructura externa; no se
presentan como pruebas aprobadas. Las instrucciones de preparación están en
`instalacion_local.md`, `conexiones_ssh.md`, `servicios.md`, `archivos.md` y
`despliegues.md`.
