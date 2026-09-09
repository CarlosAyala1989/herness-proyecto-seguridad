# Instalación local

Esta guía permite iniciar y comprobar el hito 1 de Hermes en Ubuntu 24.04. Los
servicios escuchan únicamente en el equipo local y no requieren una VPS.

## Versiones seleccionadas

El entorno comprobado utiliza Python 3.12.3. Aunque el equipo también tenga una
versión de Python más reciente, se debe invocar explícitamente `python3.12` para
crear el entorno virtual.

Las dependencias directas están fijadas en `pyproject.toml`. MariaDB utiliza la
imagen oficial `mariadb:11.8.9`, perteneciente a la serie LTS 11.8. SQLAlchemy
usa su API asíncrona con el controlador `asyncmy` para no bloquear las futuras
operaciones concurrentes.

Referencias de la selección:

- [Versiones de FastAPI](https://fastapi.tiangolo.com/deployment/versions/)
- [SQLAlchemy asíncrono](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Dialectos MySQL y MariaDB de SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/mysql.html)
- [Configuración con Pydantic](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Variables de la imagen oficial de MariaDB](https://mariadb.com/docs/server/server-management/automated-mariadb-deployment-and-administration/docker-and-mariadb/mariadb-server-docker-official-image-environment-variables)

## 1. Preparar Python

Desde la raíz del proyecto:

```bash
python3.12 --version
python3.12 -m venv .venv
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

## 4. Iniciar el backend

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
  "version": "0.1.0",
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

Si MariaDB no está disponible, `/salud` responde con estado HTTP `503` y un
mensaje controlado. No devuelve la URL de conexión ni la contraseña.

## 5. Ejecutar comprobaciones

Pruebas unitarias, sin depender de Docker:

```bash
pytest --cov=aplicacion --cov-report=term-missing
```

Prueba real contra la MariaDB iniciada:

```bash
pytest -o addopts='' -m integracion -vv
```

Calidad y formato:

```bash
ruff check aplicacion pruebas
ruff format --check aplicacion pruebas
```

## Alcance del hito

El hito 1 confirma el proceso HTTP y la conectividad con MariaDB. No crea aún
tablas funcionales; el modelo, las migraciones, el inventario y los permisos
se incorporarán en el hito 2. SSH llegará en el hito 3 y Telegram en el hito 5.

Por ello todavía no debe intentarse administrar el Ubuntu anfitrión desde
Telegram. Cuando esos hitos estén implementados, el equipo se registrará como
un servidor Linux y se administrará por OpenSSH a través del mismo backend,
usando operaciones autorizadas y auditadas.

