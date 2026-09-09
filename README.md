# Hermes

Hermes es una plataforma centralizada de administración de servidores Linux y
Windows Server mediante interfaces de mensajería. El proyecto se construye por
hitos y actualmente dispone de inventario, seguridad, transporte SSH, un motor
de acciones administrativas controladas, diagnóstico y una interfaz Telegram.

## Estado actual

Hitos 1 a 6 completados. Hermes 0.6.0 proporciona:

- backend FastAPI con ciclo de vida controlado;
- configuración validada mediante variables de entorno;
- MariaDB 11.8.9 LTS aislada en Docker;
- comprobación de salud real de la base de datos;
- respuestas de error y registros centralizados en español;
- pruebas unitarias y pruebas de integración con MariaDB;
- migraciones reproducibles mediante Alembic;
- inventario persistente de servidores y grupos, sin límite fijo de equipos;
- usuarios, roles y permisos almacenados en MariaDB;
- contraseñas de acceso local protegidas con Argon2;
- autorización por permiso y auditoría persistente;
- conexiones concurrentes mediante AsyncSSH;
- autenticación remota exclusivamente por claves o `ssh-agent`;
- doble verificación de identidad mediante `known_hosts` y huella SHA-256;
- tiempos de espera, mantenimiento de conexión y salida acotada;
- detección normalizada mediante adaptadores Linux y Windows Server;
- catálogo cerrado de acciones remotas, sin ejecución arbitraria;
- autorización y validación específica por acción;
- confirmación obligatoria para reinicios;
- resultados normalizados y auditoría por servidor;
- bot Telegram mediante sondeo saliente, sin publicar puertos adicionales;
- autorización por identificador numérico de Telegram vinculado en MariaDB;
- selección de servidor, comandos de lectura y confirmación interactiva;
- revocación local, límite de frecuencia y restricción a chats privados;
- diagnóstico uniforme de disponibilidad, CPU, RAM, disco, tiempo de actividad,
  sistema, versión y nombre del equipo;
- recopiladores independientes para Linux y Windows Server con métricas no
  disponibles representadas explícitamente, sin detener las demás lecturas.

Las acciones disponibles son `obtener_identidad`, `consultar_proceso`,
`obtener_diagnostico` y `reiniciar_servidor`. Telegram ya reutiliza esas
acciones. La administración de servicios corresponde al hito 7 y Slack se
incorporará en el hito 9.

## Requisitos locales

- Ubuntu 24.04 o un sistema compatible.
- Python 3.12.
- Docker con Docker Compose.
- Git.

Las instrucciones completas de instalación y comprobación están en
[`documentacion/instalacion_local.md`](documentacion/instalacion_local.md).

## Inicio rápido

```bash
/usr/bin/python3.12 -m venv .venv
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
alembic -c alembic.ini upgrade head
python -m aplicacion.comandos.crear_administrador \
  --usuario administrador_local \
  --nombre "Administrador local"
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

Las rutas bajo `/api/v1` requieren las credenciales del administrador local.
La contraseña se solicita interactivamente al crear la cuenta y no aparece en
los argumentos del proceso, los registros ni el repositorio.

## Estructura

```text
aplicacion/       Backend FastAPI, modelos, servicios y contratos internos
infraestructura/  Servicios locales aislados mediante Docker Compose
migraciones/      Historial versionado del esquema de MariaDB
pruebas/          Pruebas unitarias y de integración
documentacion/    Instalación, arquitectura y decisiones técnicas
.secretos/        Claves y hosts conocidos locales, siempre ignorados por Git
```

## Seguridad del entorno

La base de datos de desarrollo se publica solamente en la interfaz local
`127.0.0.1`. El backend también se inicia sobre esa interfaz porque la
autenticación HTTP Basic del laboratorio no sustituye a TLS. El archivo `.env`
está excluido de Git; `.env.ejemplo` contiene únicamente valores demostrativos
que deben cambiarse antes de iniciar los servicios.

El inventario guarda referencias a credenciales, nunca contraseñas SSH ni
claves privadas. El motor rechaza hosts desconocidos, huellas distintas,
archivos de clave con permisos inseguros y autenticación por contraseña.

Consulta [`documentacion/arquitectura.md`](documentacion/arquitectura.md) para
conocer los límites entre módulos y
[`documentacion/inventario_y_seguridad.md`](documentacion/inventario_y_seguridad.md)
para usar el inventario y el modelo de acceso. La preparación y comprobación de
servidores está en
[`documentacion/conexiones_ssh.md`](documentacion/conexiones_ssh.md).
El catálogo y sus controles se describen en
[`documentacion/motor_acciones.md`](documentacion/motor_acciones.md).
La activación y el uso del bot se explican en
[`documentacion/telegram.md`](documentacion/telegram.md).
La obtención y normalización de métricas se detalla en
[`documentacion/diagnostico.md`](documentacion/diagnostico.md).
