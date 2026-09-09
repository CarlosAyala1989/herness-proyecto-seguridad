# Arquitectura de Hermes

## Objetivo actual

La base separa configuración, transporte HTTP, autenticación, casos de uso,
persistencia y contratos externos. El hito 4 añade el catálogo autorizado y la
orquestación de acciones sin trasladar lógica hacia Telegram o Slack.

## Componentes actuales

```text
Solicitud HTTP
      │
      ▼
aplicacion/principal.py
      │
      ├── identificación y registro de la solicitud
      ├── manejo centralizado de errores
      │
      ├──► rutas/salud.py ────────────────────────┐
      │                                           │
      └──► rutas/{inventario,acceso,auditoria,conexiones}.py
                  │                               │
                  ▼                               │
       autenticación y permisos                   │
                  │                               │
                  ▼                               │
       servicios de inventario, acceso, conexiones, acciones y auditoría
                  │                       │
                  │                       ▼
                  │               registro de acciones
                  │                       │
                  │                       ▼
                  │              adaptador Linux/Windows
                  │                       │
                  │                       ▼
                  │              transporte AsyncSSH
                  │                       │
                  ▼                       ▼
        modelos SQLAlchemy ─► MariaDB    servidores SSH
```

- `configuracion.py` carga y valida variables de entorno. Las contraseñas se
  representan con `SecretStr` y la URL se construye con `SQLAlchemy.URL` para
  evitar concatenaciones y representaciones accidentales en texto claro.
- `base_datos.py` crea un motor asíncrono con comprobación previa de conexiones
  y cierre durante la finalización de FastAPI.
- `errores.py` convierte fallos conocidos y desconocidos en respuestas
  uniformes. Los detalles internos no se envían al cliente.
- `registro_logs.py` centraliza el formato y nivel de los registros.
- `rutas/salud.py` ejecuta `SELECT 1`; no informa un estado saludable basándose
  únicamente en que el proceso HTTP esté activo.
- `seguridad/autenticacion.py` identifica al usuario local, comprueba que esté
  activo y resuelve sus permisos persistentes antes de ejecutar un caso de uso.
- `servicios/gestor_inventario.py` administra servidores, grupos y asociaciones
  sin depender del canal que originó la solicitud.
- `servicios/gestor_acceso.py` administra usuarios y asignaciones de roles.
- `servicios/gestor_conexiones.py` selecciona el adaptador registrado, ejecuta
  únicamente su saludo fijo y normaliza el resultado.
- `acciones/registro.py` es la lista cerrada de operaciones, sus esquemas de
  parámetros, permisos y requisito de confirmación.
- `servicios/gestor_acciones.py` aplica la política en orden: catálogo,
  autorización, inventario, parámetros, confirmación, adaptador, SSH y auditoría.
- `conexiones/transporte_ssh.py` contiene la conexión AsyncSSH, la doble
  validación de host, los plazos y la recolección acotada de salida.
- `conexiones/credenciales.py` resuelve referencias de archivo confinadas o el
  socket del agente sin consultar secretos desde MariaDB.
- `adaptadores/linux.py` y `adaptadores/windows.py` encapsulan las diferencias
  de plataforma. PowerShell nunca aparece en las rutas ni en los futuros bots.
- `servicios/auditoria.py` registra el actor, la acción, el recurso y el
  resultado dentro de la misma base de datos.
- `modelos/` define inventario, control de acceso y auditoría. Las relaciones de
  muchos a muchos usan tablas explícitas y restricciones de integridad.
- `migraciones/` conserva la evolución reproducible del esquema y los datos
  mínimos de roles y permisos.
- `interfaces/` contiene contratos, no implementaciones, para impedir que los
  futuros canales de mensajería incorporen lógica de administración.

## Límites preparados para hitos posteriores

```text
Telegram ─┐
          ├──► backend común ─► autorización ─► operaciones controladas
Slack ────┘                                      │
                                                 ▼
                                      transporte remoto
                                                 │
                                     ┌───────────┴───────────┐
                                     ▼                       ▼
                              adaptador Linux         adaptador Windows
```

`CanalMensajeria` define la salida mínima de un canal. `TransporteRemoto`
normaliza disponibilidad, ejecución acotada y cierre; AsyncSSH ya implementa
ese puerto. Los bots futuros solo traducirán mensajes hacia casos de uso del
backend. La selección de comandos,
permisos, confirmaciones y auditoría no residirá en esos bots.

El contrato de transporte no asume Linux. Los adaptadores verifican la
plataforma y traducen cada acción común a su comando fijo. Los canales futuros
solo enviarán códigos y parámetros del catálogo, nunca texto para una shell.

## Decisiones de seguridad iniciales

- MariaDB escucha en `127.0.0.1:3378`, no en todas las interfaces.
- El contenedor tiene red y volumen propios, y activa `no-new-privileges`.
- La imagen está fijada a `mariadb:11.8.9` para reproducibilidad.
- Las credenciales reales solo pertenecen al `.env` local, ignorado por Git.
- La documentación contiene valores demostrativos, nunca credenciales reales.
- Las consultas usan las primitivas de SQLAlchemy; no se ejecuta una shell.
- Las respuestas inesperadas son genéricas y tienen un identificador de
  correlación.
- Las contraseñas de usuarios se almacenan como hashes Argon2; no pueden
  recuperarse desde la base de datos ni aparecen en las respuestas.
- Los servidores conservan una `referencia_credencial`, no contraseñas SSH ni
  claves privadas. El resolvedor confina archivos y exige permisos restrictivos.
- AsyncSSH no utiliza contraseña, interacción por teclado, claves por defecto ni
  configuración implícita de `~/.ssh/config`.
- Toda conexión exige una entrada previa en `known_hosts` y una huella SHA-256
  idéntica a la registrada. Nunca existe una modalidad de aceptación automática.
- La salida estándar y de error comparten un límite máximo; al agotarlo se
  interrumpe el proceso remoto. Conexión, autenticación y ejecución tienen
  plazos independientes.
- El código de acción se busca en un diccionario inmutable. Un código desconocido
  obtiene un error controlado y jamás se trata como comando.
- Cada acción usa un modelo Pydantic con campos adicionales prohibidos. El único
  parámetro actual es un identificador de proceso entero y acotado.
- `reiniciar_servidor` exige un permiso exclusivo y confirmación explícita. Se
  programa con un minuto de margen para evitar una desconexión instantánea.
- Cada ruta de inventario exige un permiso persistente. Los rechazos de
  autenticación y autorización también generan auditoría cuando existe un
  usuario identificable.
- Las eliminaciones requieren `confirmar=true` y respetan las restricciones de
  integridad de MariaDB.
- HTTP Basic es una adaptación local temporal y el servidor se limita a
  `127.0.0.1`; cualquier exposición de red futura exigirá TLS.
- Las dependencias directas están fijadas y se verifican mediante pruebas antes
  de actualizarse.

## Administración futura del Ubuntu anfitrión

Hermes no ejecuta órdenes directamente en su propio proceso. El Ubuntu del
laboratorio ya se comprobó mediante OpenSSH, autenticación por clave y
verificación estricta de la clave del host. Las acciones del hito 4 son
predefinidas, autorizadas y auditadas. En el hito 5 Telegram identificará
al usuario principalmente por su identificador numérico inmutable y delegará la
acción al backend. El número de teléfono no es un dato fiable ni siempre está
disponible para autorizar bots, por lo que no será el identificador principal.

Este flujo trata al anfitrión como otro servidor Linux del inventario. Así se
prueba el recorrido completo localmente sin crear una excepción insegura para
“ejecutar directamente” comandos recibidos por Telegram.
