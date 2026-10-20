# Hermes

Hermes es una plataforma centralizada de administración de servidores Linux y
Windows Server mediante interfaces de mensajería. El proyecto se construye por
hitos y actualmente dispone de inventario, seguridad, transporte SSH, un motor
de acciones administrativas controladas, diagnóstico, administración de
servicios, operaciones múltiples, alertas, tareas programadas persistentes,
administración controlada de cuentas locales remotas y transferencias SFTP.
También dispone de despliegues de archivo único con verificación y reversión.

## Estado actual

Hitos 1 a 14 implementados y comprobados mediante pruebas locales. La
aceptación con servicios externos y máquinas virtuales reales sigue los
pendientes descritos en
[`documentacion/auditoria_hitos_1_14.md`](documentacion/auditoria_hitos_1_14.md).
Hermes 0.14.1 proporciona:

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
  disponibles representadas explícitamente, sin detener las demás lecturas;
- consulta, inicio, detención y reinicio normalizados de servicios;
- `systemctl` en Linux y cmdlets de PowerShell en Windows Server;
- permisos separados y confirmación de un solo uso para cada cambio de estado;
- selección individual, por grupo o de todos los servidores activos;
- operaciones concurrentes con máximo y plazo individual configurables;
- aislamiento de fallos, resultados consolidados y auditoría por servidor;
- selección múltiple y respuestas divididas de forma segura en Telegram;
- Slack Bolt asíncrono mediante Socket Mode saliente;
- comando `/hermes` con selección y acciones equivalentes a Telegram;
- autorización por espacio de trabajo y usuario Slack vinculados en MariaDB;
- confirmaciones interactivas, límites y auditoría identificada como Slack;
- monitoreo periódico concurrente de disponibilidad, CPU, memoria y disco;
- comprobación de servicios críticos configurables por servidor;
- alertas persistentes y deduplicadas con registro de recuperación;
- suscripciones explícitas y entregas reintentables por Telegram y Slack;
- tareas de fecha única o intervalo fijo persistidas en MariaDB;
- selección de destinos congelada, reautorización al ejecutar y confirmación
  para acciones sensibles programadas;
- historial de ocurrencias, cancelación de ejecuciones futuras y protección
  transaccional contra duplicados;
- notificación opcional de resultados a las identidades activas del creador;
- consulta normalizada de cuentas locales, estado y grupos en Linux y Windows;
- creación inicialmente deshabilitada, sin recibir ni persistir contraseñas;
- cambios de grupo, bloqueo, habilitación y eliminación con confirmación;
- permisos reforzados para eliminación y cuentas o grupos protegidos;
- protección de la cuenta SSH operadora, cuentas del sistema y miembros de
  grupos privilegiados;
- comandos equivalentes de usuarios en Telegram y Slack, siempre delegados al
  backend común.
- raíces de archivos permitidas por servidor, separadas para lectura y escritura;
- validación de rutas absolutas Linux y Windows Server y comprobación canónica
  remota para impedir escapes y enlaces hacia ubicaciones externas;
- consulta, carga y descarga SFTP con plazo, bloques y tamaño máximo configurables;
- creación exclusiva predeterminada y confirmación expresa para sobrescrituras API;
- permisos independientes y auditoría por servidor sin registrar contenidos;
- carga y descarga desde Telegram y consulta y descarga desde Slack, siempre sobre
  un único servidor seleccionado;
- plantillas cerradas de despliegue por sistema operativo, sin guiones aportados
  por usuarios;
- aplicaciones asociadas a inventario, versión vigente e historial persistente;
- instalación SFTP con respaldo previo, verificación SHA-256 y reinicio opcional
  de servicios mediante los adaptadores Linux y Windows Server;
- reversión explícita y restauración automática ante fallos de instalación;
- permisos separados, bloqueo por aplicación y auditoría de cada resultado;
- consulta, despliegue y reversión desde Telegram y Slack con confirmaciones
  efímeras de un solo uso.

Las acciones disponibles son `obtener_identidad`, `consultar_proceso`,
`obtener_diagnostico`, `consultar_servicio`, `iniciar_servicio`,
`detener_servicio`, `reiniciar_servicio`, `reiniciar_servidor`,
`listar_usuarios_sistema`, `crear_usuario_sistema`,
`cambiar_grupo_usuario_sistema`, `bloquear_usuario_sistema`,
`desbloquear_usuario_sistema` y `eliminar_usuario_sistema`. Telegram y Slack
reutilizan esas acciones sobre un servidor, un grupo o todos los servidores
activos.

## Sitio público estático

La portada de Hermes está en [`index.html`](index.html) y
[`estilos.css`](estilos.css). No usa JavaScript, dependencias externas ni
credenciales; `.nojekyll` evita un procesamiento innecesario. GitHub Pages puede
servirla directamente desde la raíz de
`main`. En el repositorio de GitHub, abre **Settings → Pages**, selecciona
**Deploy from a branch**, rama **main** y carpeta **/(root)**, y guarda.
Después de subir este commit, la dirección prevista será
`https://carlosayala1989.github.io/herness-proyecto-seguridad/`.

Para verla sin publicarla:

```bash
python3.12 -m http.server 8765 --bind 127.0.0.1
```

Abre `http://127.0.0.1:8765/`. La web describe el proyecto, pero no expone la
API de administración ni pretende validar Telegram, Slack o VMs reales.

## Requisitos locales

- Ubuntu 24.04 o un sistema compatible.
- Python 3.12.
- Docker con Docker Compose.
- Git.

## Instalación automática

En Ubuntu 24.04 con systemd, desde una terminal y con un usuario normal que
tenga acceso a `sudo`:

```bash
curl -fsSL https://raw.githubusercontent.com/CarlosAyala1989/herness-proyecto-seguridad/main/instalar.sh | bash
```

El comando descarga Hermes por HTTPS en `~/.local/share/hermes`, instala las
dependencias, genera las contraseñas de MariaDB, crea el administrador y
configura el arranque automático. Puedes introducir los tokens de Telegram y
Slack de forma oculta o hacerlo después. Al repetirlo, actualiza el código y
conserva la configuración y los datos. Después registra los servidores y sus
claves SSH. El instalador y sus archivos deben estar publicados en `main` para
que la URL funcione.

Si ya descargaste el repositorio, también puedes usar `bash instalar.sh` desde
su carpeta: utiliza directamente esa copia, sin descargar otra.

Cada usuario aporta su propio bot de Telegram y su aplicación Slack. Hermes y
MariaDB se ejecutan en su servidor, sin un servidor central de Hermes. El
asistente solicita los tokens y permite autorizar al propietario en ambos
canales; Telegram y Slack continúan prestando el servicio de mensajería.
Telegram solo acepta órdenes del ID numérico de su propietario, configurado
desde la terminal, incluso si hay otros usuarios vinculados en Hermes.

Consulta [`documentacion/instalacion_automatica.md`](documentacion/instalacion_automatica.md)
para los requisitos, credenciales, servicios y alcance de la verificación.

## Instalación manual

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
La creación, vinculación y uso de la aplicación Slack se explica en
[`documentacion/slack.md`](documentacion/slack.md).
La obtención y normalización de métricas se detalla en
[`documentacion/diagnostico.md`](documentacion/diagnostico.md).
La preparación de cuentas y administración de servicios se explica en
[`documentacion/servicios.md`](documentacion/servicios.md).
La selección, concurrencia y consolidación se detallan en
[`documentacion/operaciones_multiples.md`](documentacion/operaciones_multiples.md).
Los umbrales, suscripciones, alertas y proceso periódico se detallan en
[`documentacion/monitoreo_automatico.md`](documentacion/monitoreo_automatico.md).
La creación, ejecución, consulta y cancelación de tareas se describe en
[`documentacion/tareas_programadas.md`](documentacion/tareas_programadas.md).
La gestión controlada de cuentas locales se describe en
[`documentacion/usuarios_sistema.md`](documentacion/usuarios_sistema.md).
La lista blanca de rutas y las transferencias SFTP se explican en
[`documentacion/archivos.md`](documentacion/archivos.md).
Las plantillas, versiones, comprobaciones y reversiones se describen en
[`documentacion/despliegues.md`](documentacion/despliegues.md).
