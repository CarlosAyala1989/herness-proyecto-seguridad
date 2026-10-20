# Verificación de comandos — 19 de octubre de 2026

Se comprobó el catálogo operativo de Telegram, sin limitar la validación a
los comandos de ayuda. Se ejecutaron pruebas unitarias, integración con una
MariaDB desechable migrada desde cero, SSH/SFTP local, un contenedor Ubuntu
24.04 desechable y Codex CLI real autenticado.

Resultado final: **309 pruebas aprobadas, sin fallos ni pruebas omitidas**, en
33,43 segundos. También pasaron Ruff, la sintaxis del instalador Bash y la
comprobación de que el paquete distribuible incluye `/ia` y el tutorial.

La matriz indica el alcance comprobado; una simulación de reinicio no demuestra
un arranque real. Los mensajes entrantes, botones y adjuntos de las pruebas de
interfaz se representaron con objetos de prueba. Las consultas a MariaDB y las
operaciones SSH/SFTP indicadas como reales sí se ejecutaron. El bot de producción
se valida además por su servicio y el menú publicado en la API de Telegram.

## Matriz operativa

| Comando | Comprobación |
| --- | --- |
| `/servidores` | Inventario real y botones con el ID/nombre correcto. |
| `/grupos` | Grupos reales de prueba y botones asociados. |
| `/seleccionar` | Selección por ID contra inventario real; lectura de esta laptop. |
| `/seleccionar_grupo` | Resolución real de miembros del grupo en MariaDB de prueba. |
| `/seleccionar_todos` | Selección de activos y comprobación real de sus límites. |
| `/seleccion` | Revalidación real de servidor, grupo y selección de activos. |
| `/diagnostico` | SSH real a esta laptop; CPU, memoria, disco, actividad y sistema. |
| `/identidad` | SSH real; usuario remoto y nombre de equipo. |
| `/proceso` | PID 1 consultado por SSH real; rechazo de parámetros inválidos. |
| `/servicio` | Consulta real de `ssh.service`; contratos Linux/Windows automatizados. |
| `/iniciar_servicio` | Botón, confirmación y un solo uso; guion ejecutado con herramientas aisladas, tanto éxito como rechazo. |
| `/detener_servicio` | Botón, confirmación y un solo uso; guion ejecutado con herramientas aisladas, tanto éxito como rechazo. |
| `/reiniciar_servicio` | Botón, confirmación y un solo uso; guion ejecutado con herramientas aisladas, tanto éxito como rechazo. |
| `/usuarios` | Listado por SSH real en esta laptop y cuentas reales de Ubuntu desechable. |
| `/crear_usuario` | Confirmación y creación real deshabilitada en Ubuntu desechable. |
| `/agregar_grupo` | Confirmación y pertenencia real a un grupo de prueba en Ubuntu desechable. |
| `/quitar_grupo` | Confirmación, retirada real y comprobación del listado en Ubuntu desechable. |
| `/bloquear_usuario` | Confirmación y bloqueo real de cuenta desechable. |
| `/desbloquear_usuario` | Confirmación y habilitación real de cuenta desechable, tras preparar una credencial externa. |
| `/eliminar_usuario` | Confirmación y eliminación real de cuenta desechable; ausencia comprobada al listar. |
| `/archivo_info` | Metadatos de archivo real por SFTP en localhost. |
| `/descargar_archivo` | Lectura SFTP real; contenido exacto del adjunto comprobado en la interfaz simulada. |
| `/cargar_archivo` | Escritura SFTP real; bytes comprobados en disco y rechazo de sobrescrituras en pruebas existentes. |
| `/aplicaciones` | Catálogo real de aplicación de prueba en MariaDB. |
| `/estado_aplicacion` | Comprobación real del archivo y SHA-256 después del despliegue. |
| `/desplegar` | Confirmación, instalación SFTP real de archivo temporal y verificación de contenido. |
| `/revertir_despliegue` | Confirmación y restauración SFTP real del contenido anterior. |
| `/reiniciar` | Confirmación, consumo único y contrato remoto simulados; no se reinició el anfitrión. |
| `/cancelar` | Confirmación descartada y botón anterior rechazado sin ejecutar la acción. |
| `/ia` | Catálogo/modelo/esfuerzo, autorización, tareas, estado, parada, salida, revocación y respuestas largas automatizados; ejecución adicional de Codex real. |

## Fallo encontrado y corregido

Los guiones Linux de inicio, detención y reinicio de servicios continuaban
consultando el estado después de una orden `systemctl` o `sudo` fallida. Eso
permitía informar una operación como completada pese al rechazo de la orden.

Se reprodujo con seis casos fallidos: tres operaciones, con cuenta root
simulada y con sudo simulado. Ahora se conserva el código de salida y se
interrumpe el guion antes de publicar un marcador de éxito. Las doce variantes
de éxito y error pasan después de la corrección.

## Comprobación de Codex

Se utilizó `codex-cli 0.162.1`, ya instalado y autenticado mediante ChatGPT.
El catálogo se obtuvo de `codex debug models`, sin fijar una lista de modelos
en el código. Cada selector de esfuerzo usa los valores admitidos por su modelo.

Una tarea real con `gpt-6.1-sol` y esfuerzo `low` ejecutó `uname -s`, `id -un`
y creó un archivo temporal con el contenido esperado. El archivo se comprobó
y el directorio temporal se eliminó al terminar. Se usó la misma adaptación
`CodexLocal` que invoca el bot, con ejecución sin sandbox ni aprobaciones.

Las pruebas automatizadas comprueban también argumentos separados, instrucciones
por stdin, ausencia de tokens Hermes en el entorno del hijo, errores sin revelar
salida interna, plazo máximo, exclusión de tareas simultáneas y cancelación de
un hijo que ignora SIGTERM. No se ejecutó cada combinación de modelo/esfuerzo
contra OpenAI: el catálogo valida su selección y el CLI comunica incompatibilidad,
autenticación o cuota cuando no puede completar una tarea.

## Límites de esta aceptación

- No se efectuó un reinicio físico de la laptop ni se interrumpió SSH o MariaDB.
- Las modificaciones de servicios se probaron con herramientas aisladas; queda
  pendiente la aceptación sobre un servicio systemd prescindible de una VM.
- No se utilizó una VM Windows Server real. Sus adaptadores y contratos se
  comprobaron con pruebas automatizadas.
- La cuenta de esta laptop requiere contraseña para `sudo`. Los comandos
  administrativos privilegiados necesitan preparar permisos del sistema.
  `/ia` elimina las restricciones de Codex, pero no convierte la cuenta en root.
- Los recursos temporales de archivos/aplicaciones se registraron en la base
  desechable. El inventario productivo necesita sus propias raíces y plantillas
  para usar esos comandos con archivos y aplicaciones permanentes.

## Repetir las comprobaciones

La suite requiere Python 3.12 y las dependencias de desarrollo. Ejecuta Alembic
contra una base de datos independiente con nombre `hermes_validacion_...` y pasa
esa configuración mediante el entorno, sin reemplazar el `.env` productivo.
Deshabilita los canales externos y la IA por defecto durante la suite:

```bash
HERMES_TELEGRAM_HABILITADO=false HERMES_TOKEN_TELEGRAM= \
HERMES_ID_PROPIETARIO_TELEGRAM= HERMES_IA_HABILITADA=false \
HERMES_SLACK_HABILITADO=false HERMES_TOKEN_BOT_SLACK= \
HERMES_TOKEN_APLICACION_SLACK= \
.venv/bin/pytest -q -o 'addopts=-ra --strict-markers'
```

El recorrido opcional `test_comandos_telegram_ssh_local.py` necesita además
`HERMES_VALIDAR_SSH_LOCAL=true`, la clave de prueba local ya preparada,
`known_hosts` verificado y OpenSSH escuchando en localhost. Ese recorrido
comprueba el prefijo de la base para impedir usarlo accidentalmente en producción.
Las pruebas de cuentas Linux requieren la imagen Docker local `ubuntu:24.04`.
