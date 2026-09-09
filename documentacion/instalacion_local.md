# Instalación local

Esta guía permite iniciar y comprobar los hitos 1 a 10 de Hermes en Ubuntu 24.04.
Los servicios escuchan únicamente en el equipo local y no requieren una VPS.

## Versiones seleccionadas

El entorno comprobado utiliza `/usr/bin/python3.12` 3.12.3. El equipo también
tiene `/usr/local/bin/python3.12` y Python 3.14, pero no deben utilizarse: el
primero carece del módulo estándar `_ctypes` requerido por AsyncSSH actual y el
proyecto está acotado a Python 3.12.

Las dependencias directas están fijadas en `pyproject.toml`. MariaDB utiliza la
imagen oficial `mariadb:11.8.9`, perteneciente a la serie LTS 11.8. SQLAlchemy
usa su API asíncrona con el controlador `asyncmy`; Alembic mantiene el esquema y
`pwdlib` protege las contraseñas locales mediante Argon2.
AsyncSSH aporta el cliente asíncrono y reutilizable para Linux y Windows Server.
`python-telegram-bot` 22.8 proporciona la interfaz asíncrona con Telegram.
Slack Bolt 1.30.0 y `aiohttp` 3.14.3 proporcionan la interfaz asíncrona de
Socket Mode sin requerir un endpoint público.

Referencias de la selección:

- [Versiones de FastAPI](https://fastapi.tiangolo.com/deployment/versions/)
- [SQLAlchemy asíncrono](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Dialectos MySQL y MariaDB de SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/mysql.html)
- [Migraciones asíncronas con Alembic](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic)
- [Hash de contraseñas en FastAPI](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/#hash-and-verify-the-passwords)
- [Documentación de pwdlib](https://frankie567.github.io/pwdlib/)
- [Documentación de AsyncSSH](https://asyncssh.readthedocs.io/en/stable/)
- [Documentación de python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/)
- [API oficial para bots de Telegram](https://core.telegram.org/bots/api)
- [Slack Bolt para Python](https://docs.slack.dev/tools/bolt-python/)
- [Socket Mode con Slack Bolt](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/)
- [Configuración con Pydantic](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Variables de la imagen oficial de MariaDB](https://mariadb.com/docs/server/server-management/automated-mariadb-deployment-and-administration/docker-and-mariadb/mariadb-server-docker-official-image-environment-variables)

## 1. Preparar Python

Desde la raíz del proyecto:

```bash
/usr/bin/python3.12 --version
/usr/bin/python3.12 -c 'import ctypes'
/usr/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[desarrollo]'
```

El intervalo declarado para Python es `>=3.12,<3.13`; esto evita instalar el
proyecto accidentalmente con otra de las versiones presentes en el equipo.

## 2. Preparar la configuración local

```bash
cp .env.ejemplo .env
chmod 600 .env
```

Abre `.env` con tu editor y sustituye, como mínimo:

```dotenv
HERMES_CONTRASENA_BASE_DATOS=una_contrasena_local_distinta
HERMES_CONTRASENA_RAIZ_BASE_DATOS=otra_contrasena_local_distinta
```

Las operaciones múltiples disponen de límites locales conservadores. Para el
laboratorio pueden mantenerse los valores de `.env.ejemplo`:

```dotenv
HERMES_MAX_CONCURRENCIA_ACCIONES_MULTIPLES=4
HERMES_MAX_SERVIDORES_ACCION_MULTIPLE=100
HERMES_TIEMPO_LIMITE_ACCION_MULTIPLE_SEGUNDOS=45
```

No confirmes `.env` en Git. Puedes verificarlo con:

```bash
git check-ignore -v .env
```

## 3. Iniciar la MariaDB de Hermes

```bash
docker compose --env-file .env -f infraestructura/compose.yaml up -d
docker compose --env-file .env -f infraestructura/compose.yaml ps
```

El contenedor se llama `hermes-base-datos`, mantiene sus datos en el volumen
`hermes-datos-mariadb` y publica `127.0.0.1:3378`. La vinculación a la interfaz
local impide conexiones directas desde otras máquinas.

El servicio de Hermes es independiente de otras instalaciones de MySQL o
MariaDB. Para comprobar los puertos sin consultar credenciales ajenas:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

Detener el servicio conserva sus datos:

```bash
docker compose --env-file .env -f infraestructura/compose.yaml down
```

Cambiar las variables de inicialización no modifica usuarios o contraseñas de
un volumen que ya fue creado. Si fuera necesario rotarlas más adelante, deberá
realizarse mediante sentencias administrativas controladas o recreando
conscientemente el laboratorio; no se debe borrar el volumen por rutina.

## 4. Aplicar las migraciones

Con MariaDB disponible y el entorno virtual activo:

```bash
alembic -c alembic.ini upgrade head
alembic -c alembic.ini current
```

La revisión esperada es `0007 (head)`. Las migraciones crean el inventario, los
usuarios, los roles, los permisos y la auditoría; además registran los roles y
permisos iniciales de forma reproducible. La segunda revisión incorpora el
permiso `comprobar_conexion`.
La tercera incorpora permisos separados para lectura remota y reinicio.
La cuarta añade las identidades externas autorizadas para mensajería.
La quinta incorpora el permiso de diagnóstico para administrador y operador.
La sexta separa la consulta de servicios de las operaciones que cambian su
estado.
La séptima incorpora configuraciones de monitoreo, servicios críticos, alertas,
suscripciones, entregas y permisos de consulta y administración.

## 5. Crear el primer administrador

```bash
python -m aplicacion.comandos.crear_administrador \
  --usuario administrador_local \
  --nombre "Administrador local"
```

El comando solicita y confirma la contraseña de manera interactiva. No la
incluyas como argumento ni la escribas en un archivo versionado. La cuenta
recibe el rol `administrador`, necesario para gestionar el inventario inicial.

Para consultar las opciones sin modificar datos:

```bash
python -m aplicacion.comandos.crear_administrador --help
```

## 6. Preparar SSH

Hermes admite dos mecanismos:

- `agente_ssh` con la referencia exacta `agente:predeterminado`, recomendado
  cuando el proceso dispone de `SSH_AUTH_SOCK`;
- `clave_ssh` con una referencia como `archivo:ubuntu_laboratorio`, que se
  resuelve dentro de `HERMES_DIRECTORIO_CREDENCIALES_SSH`.

Una clave guardada en archivo debe pertenecer al usuario que ejecuta Hermes,
tener permisos `600` o más restrictivos y no ser un enlace simbólico. El
archivo indicado por `HERMES_ARCHIVO_HOSTS_CONOCIDOS_SSH` debe existir antes de
conectar. Consulta `documentacion/conexiones_ssh.md` para verificar y registrar
claves de host sin confiar automáticamente en ellas.

La consulta de servicios no requiere elevación adicional en una instalación
normal de systemd. Para iniciar, detener o reiniciar, prepara una cuenta con
privilegios restringidos siguiendo `documentacion/servicios.md`; no concedas
`sudo` general a la cuenta SSH.

## 7. Iniciar el backend

Con el entorno virtual activo:

```bash
uvicorn aplicacion.principal:aplicacion \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

La API no se expone a la red local con esta configuración. En otra terminal:

```bash
curl --include http://127.0.0.1:8000/salud
```

Una respuesta correcta tiene este formato; el tiempo cambia en cada consulta:

```json
{
  "aplicacion": "Hermes",
  "version": "0.10.0",
  "estado": "saludable",
  "base_datos": {
    "estado": "disponible",
    "tiempo_respuesta_ms": 3.2
  }
}
```

Cada respuesta incluye la cabecera `X-Identificador-Solicitud`, que permite
relacionar una respuesta con sus registros sin revelar información sensible.
La interfaz OpenAPI está en `http://127.0.0.1:8000/documentacion`.

Las rutas de `/api/v1` utilizan HTTP Basic en este laboratorio local. Por
ejemplo, este comando solicita la contraseña sin dejarla en el historial:

```bash
curl --user administrador_local http://127.0.0.1:8000/api/v1/servidores
```

Consulta las acciones disponibles y ejecuta una operación de lectura:

```bash
curl --user administrador_local http://127.0.0.1:8000/api/v1/acciones

curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/obtener_identidad

curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/obtener_diagnostico

curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{"parametros":{"nombre_servicio":"ssh.service"}}' \
  http://127.0.0.1:8000/api/v1/servidores/1/acciones/consultar_servicio

curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{"seleccion":{"ids_servidores":[1,2,3,4]}}' \
  http://127.0.0.1:8000/api/v1/acciones-multiples/obtener_diagnostico
```

No inicies el backend con `--host 0.0.0.0`: HTTP Basic debe quedar limitado a
`127.0.0.1` mientras no exista una terminación TLS. Telegram utiliza su propia
identidad persistente y delega los permisos al mismo backend; Slack aplica el
mismo principio.

Si MariaDB no está disponible, `/salud` responde con estado HTTP `503` y un
mensaje controlado. No devuelve la URL de conexión ni la contraseña.

## 8. Activar Telegram

Crea un bot con la cuenta oficial `@BotFather` y conserva el token únicamente
en el `.env` local. Modifica estas variables sin compartir su valor:

```dotenv
HERMES_TELEGRAM_HABILITADO=true
HERMES_TOKEN_TELEGRAM=token_real_entregado_por_botfather
```

Inicia el bot en una terminal dedicada:

```bash
source .venv/bin/activate
python -m aplicacion.interfaces.telegram
```

Hermes usa sondeo saliente, de modo que no necesita dominio, webhook ni un
puerto público. En una conversación privada con el bot, envía `/inicio`. Si la
cuenta todavía no está vinculada, la respuesta mostrará tu identificador
numérico de Telegram. Autorízalo desde otra terminal:

```bash
python -m aplicacion.comandos.vincular_usuario_telegram \
  --usuario administrador_local \
  --identificador-telegram 123456789 \
  --nombre-telegram nombre_visible_opcional
```

Sustituye `123456789` por el identificador mostrado. El nombre visible es solo
una referencia; Hermes siempre autentica con el identificador numérico. Para
revocar el acceso de Telegram sin desactivar el usuario local:

```bash
python -m aplicacion.comandos.desvincular_usuario_telegram \
  --usuario administrador_local
```

El bot y FastAPI son procesos distintos que importan los mismos servicios del
backend y usan la misma MariaDB. No es obligatorio mantener FastAPI iniciado
para usar Telegram, pero MariaDB, OpenSSH y `ssh-agent` sí deben estar
disponibles cuando la referencia del servidor los requiera.

Consulta `documentacion/telegram.md` para registrar el Ubuntu anfitrión y probar
los comandos sin ejecutar un reinicio.

## 9. Activar Slack

Crea una aplicación de laboratorio mediante
`infraestructura/manifiesto_slack.ejemplo.yaml`, instala el bot y guarda los
tokens únicamente en `.env`:

```dotenv
HERMES_SLACK_HABILITADO=true
HERMES_TOKEN_BOT_SLACK=xoxb_token_real_del_laboratorio
HERMES_TOKEN_APLICACION_SLACK=xapp_token_real_del_laboratorio
```

Inicia el canal en una terminal dedicada:

```bash
source .venv/bin/activate
python -m aplicacion.interfaces.slack
```

Envía `/hermes ayuda` por mensaje directo. Usa los identificadores indicados en
la denegación inicial para autorizar la cuenta desde otra terminal:

```bash
python -m aplicacion.comandos.vincular_usuario_slack \
  --usuario administrador_local \
  --identificador-equipo T012ABCDEF \
  --identificador-usuario U012ABCDEF
```

Slack utiliza Socket Mode saliente: no abras puertos del router ni expongas el
backend. Consulta `documentacion/slack.md` para crear la aplicación con permisos
mínimos, probar comandos y revocar una vinculación.

## 10. Activar el monitoreo automático

Configura primero las políticas y suscripciones mediante la API siguiendo
`documentacion/monitoreo_automatico.md`. Ejecuta después una sola vuelta segura:

```bash
source .venv/bin/activate
python -m aplicacion.monitoreo --una-vez
```

Para mantener el proceso periódico, activa sus límites en `.env`:

```dotenv
HERMES_MONITOREO_HABILITADO=true
HERMES_INTERVALO_MONITOREO_SEGUNDOS=60
HERMES_MAX_CONCURRENCIA_MONITOREO=4
HERMES_TIEMPO_LIMITE_SONDEO_SEGUNDOS=45
HERMES_MAX_INTENTOS_NOTIFICACION_ALERTA=3
```

Inicia un único proceso en una terminal dedicada:

```bash
python -m aplicacion.monitoreo
```

Este proceso necesita MariaDB y acceso SSH, pero no requiere mantener FastAPI,
Telegram o Slack Bolt ejecutándose. Usa directamente los tokens configurados
para las entregas salientes.

## 11. Ejecutar comprobaciones

Pruebas unitarias, sin depender de Docker:

```bash
pytest --cov=aplicacion --cov-report=term-missing
```

Pruebas reales contra MariaDB y un servidor SSH efímero local:

```bash
pytest -o addopts='' -m integracion -vv
```

Calidad y formato:

```bash
ruff check aplicacion migraciones pruebas
ruff format --check aplicacion migraciones pruebas
```

## Alcance del hito

El hito 10 añade políticas persistentes por servidor, sondeos concurrentes,
episodios deduplicados, recuperación y entregas reintentables. El proceso
reutiliza inventario, adaptadores, SSH y MariaDB sin convertir los canales de
mensajería en backends independientes.

Las acciones de lectura pueden probarse desde Telegram cuando exista un token,
un usuario vinculado y servidores activos. El reinicio requiere permiso y una
confirmación efímera; no debe probarse sobre el anfitrión salvo que haya sido
planificado expresamente. Las mutaciones de servicios también exigen permiso,
confirmación y privilegios remotos limitados. El monitoreo automático y las
alertas ya están disponibles. La programación persistente de tareas
administrativas corresponde al hito 11.
