# Codex CLI local desde Telegram

`/ia` usa el Codex CLI instalado en la misma máquina del bot. No instala otro
agente, no usa los servidores de Hermes de terceros y conserva la autenticación
local del CLI. Las instrucciones se procesan con el proveedor configurado en
Codex; si usas ChatGPT, requieren conexión con OpenAI y cuota disponible.

## Preparación

Como el mismo usuario que ejecuta `hermes-telegram`, verifica:

```bash
command -v codex
command -v node
codex --version
codex login status
codex debug models
```

Si falta la autenticación, ejecuta `codex login` desde la terminal. No envíes
credenciales de OpenAI por Telegram. Se requiere una versión que ofrezca
`debug models`, `exec`, `--ephemeral` y `--output-last-message`.

En el `.env` privado de Hermes configura las rutas de esa instalación:

```dotenv
HERMES_IA_HABILITADA=true
HERMES_EJECUTABLE_CODEX=/ruta/absoluta/bin/codex
HERMES_DIRECTORIO_TRABAJO_IA=/home/tu_usuario
HERMES_TIEMPO_LIMITE_IA_SEGUNDOS=1800
```

No basta con que el CLI exista en el PATH de tu terminal. El servicio también
debe encontrar Node.js si `codex` lo usa mediante `/usr/bin/env node`. Añade su
directorio al `Environment=PATH=...` de una configuración complementaria de
systemd y reinicia el servicio. Mantén el HOME del usuario que inició sesión
en Codex. Si usas `CODEX_HOME`, conserva ese valor para el servicio.

El instalador genera Telegram con `NoNewPrivileges=false` para permitir usar
los privilegios ya preparados para esa cuenta. En instalaciones anteriores,
establece ese valor mediante `systemctl edit hermes-telegram`; para servicios
de usuario usa `systemctl --user edit hermes-telegram`. Recarga systemd y
reinicia la unidad correspondiente. Hermes no configura `sudo` sin contraseña.

## Uso

1. `/ia`: abre los modelos visibles que devuelve el CLI autenticado.
2. Pulsa el modelo y después un esfuerzo admitido por ese modelo.
3. Envía `/ia <instrucción>` o escribe un mensaje normal.
4. `/ia estado`: muestra modelo, esfuerzo, directorio y estado de ejecución.
5. `/ia modelos`: cambia la selección; los menús caducan a los cinco minutos.
6. `/ia detener`: termina la tarea activa y los procesos de su grupo.
7. `/ia salir`: deja de dirigir mensajes normales a Codex.

Ejemplo de lectura después de elegir modelo y esfuerzo:

```text
/ia Consulta la versión del sistema y el espacio libre sin cambiar archivos.
```

Solo se admite una tarea a la vez. Cada instrucción comienza una ejecución
independiente sin historial persistido por Hermes. La selección de modelo se
pierde al reiniciar el bot. Las respuestas de más de 3900 caracteres llegan
como archivo Markdown; se limita la respuesta capturada a 64 KiB.

## Permisos y alcance

La implementación usa `codex exec --dangerously-bypass-approvals-and-sandbox`,
`--model` y `-c model_reasoning_effort=...`, según la
[referencia oficial del CLI](https://developers.openai.com/codex/cli/reference/).
No hay confirmaciones adicionales de Hermes para cada operación que genere IA.
Tiene acceso a archivos, programas y red con los permisos del usuario del
servicio; no equivale a root ni evita los requisitos de sudo del sistema.
Las restricciones organizativas del propio Codex siguen siendo aplicables.

Se ejecuta en el anfitrión de Hermes, sin relación con `/seleccionar` ni con
las raíces SFTP. Detenerla o alcanzar el plazo no deshace cambios; procesos
desacoplados o trabajos ya enviados pueden continuar fuera del grupo terminado.

Cada interacción exige chat privado, propietario único, vínculo activo, cuenta
activa y rol administrador. Se vuelve a comprobar la autorización antes de
entregar el resultado. Inicio, final, error e interrupción quedan auditados,
sin guardar prompts ni respuestas. No se imprimen los errores internos del CLI
en el chat. Los argumentos se pasan sin shell y las instrucciones por stdin.
El proceso no hereda los tokens `HERMES_*` del entorno; el acceso completo al
sistema sigue permitiéndole leer los archivos accesibles para esa cuenta.
