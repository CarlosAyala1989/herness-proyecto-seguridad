# Hermes

Hermes es una plataforma centralizada de administración de servidores Linux y
Windows Server mediante interfaces de mensajería. El proyecto se construye por
hitos y, por ahora, contiene únicamente la base del backend y del entorno local.

## Estado actual

Hito 1 en desarrollo. En este hito no se incluyen bots de Telegram o Slack ni
ejecución remota por SSH.

## Requisitos locales

- Ubuntu 24.04 o un sistema compatible.
- Python 3.12.
- Docker con Docker Compose.
- Git.

Las instrucciones completas de instalación y comprobación están en
[`documentacion/instalacion_local.md`](documentacion/instalacion_local.md).

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

