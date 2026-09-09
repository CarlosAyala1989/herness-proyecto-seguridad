# Hermes

Hermes es una plataforma centralizada de administración de servidores Linux y
Windows Server mediante interfaces de mensajería. El proyecto se construye por
hitos y, por ahora, contiene únicamente la base del backend y del entorno local.

## Estado actual

Hito 1 completado. La base actual proporciona:

- backend FastAPI con ciclo de vida controlado;
- configuración validada mediante variables de entorno;
- MariaDB 11.8.9 LTS aislada en Docker;
- comprobación de salud real de la base de datos;
- respuestas de error y registros centralizados en español;
- pruebas unitarias y una prueba de integración con MariaDB;
- contratos iniciales para mensajería y transporte remoto.

Todavía no se incluyen bots de Telegram o Slack, inventario persistente ni
ejecución remota por SSH; corresponden a hitos posteriores.

## Requisitos locales

- Ubuntu 24.04 o un sistema compatible.
- Python 3.12.
- Docker con Docker Compose.
- Git.

Las instrucciones completas de instalación y comprobación están en
[`documentacion/instalacion_local.md`](documentacion/instalacion_local.md).

## Inicio rápido

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[desarrollo]'
cp .env.ejemplo .env
chmod 600 .env
```

Edita `.env` y cambia las dos contraseñas demostrativas. Luego inicia MariaDB:

```bash
docker compose --env-file .env -f infraestructura/compose.yaml up -d
docker compose --env-file .env -f infraestructura/compose.yaml ps
```

Inicia el backend, limitado al equipo local:

```bash
uvicorn aplicacion.principal:aplicacion --host 127.0.0.1 --port 8000 --reload
```

Comprueba el servicio en otra terminal:

```bash
curl http://127.0.0.1:8000/salud
```

La documentación interactiva queda disponible en
`http://127.0.0.1:8000/documentacion`.

## Estructura

```text
aplicacion/       Backend FastAPI y contratos internos
infraestructura/  Servicios locales aislados mediante Docker Compose
pruebas/          Pruebas unitarias y de integración
documentacion/    Instalación, arquitectura y decisiones técnicas
```

## Seguridad del entorno

La base de datos de desarrollo se publica solamente en la interfaz local
`127.0.0.1`. El archivo `.env` está excluido de Git; `.env.ejemplo` contiene
únicamente valores demostrativos que deben cambiarse antes de iniciar los
servicios.

Consulta [`documentacion/arquitectura.md`](documentacion/arquitectura.md) para
conocer los límites entre módulos y las decisiones que preparan los siguientes
hitos.
