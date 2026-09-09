# Arquitectura de Hermes

## Objetivo actual

La base separa configuración, transporte HTTP, autenticación, casos de uso,
persistencia y contratos externos. Telegram y Slack usan los mismos servicios
de diagnóstico, inventario, autorización, SSH y auditoría. El orquestador
múltiple y el monitor añaden concurrencia acotada sin cambiar esos límites.

## Componentes actuales

```text
HTTP local ──► rutas FastAPI ─────────────────────┐
Telegram ──► interfaz/telegram ──┐                │
                                 ├──► gestor_mensajeria
Slack ─────► interfaz/slack ─────┘                │
                                                  ▼
                    autenticación, permisos y registro de acciones
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
          inventario y usuarios   auditoría SQLAlchemy   adaptador por sistema
                 │                       │                       │
                 └──────────────► MariaDB                       ▼
                                                        transporte AsyncSSH
                                                                │
                                                                ▼
                                                        servidores SSH
```

El proceso `aplicacion.monitoreo` entra directamente por servicios internos,
sin simular un usuario de Telegram, Slack o HTTP. Ejecuta únicamente acciones
de lectura del catálogo y registra las transiciones con canal `sistema`.

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
- `servicios/gestor_acciones_multiples.py` resuelve IDs, grupos o todos los
  servidores activos; crea una tarea y una sesión de base de datos por destino,
  limita la concurrencia y consolida resultados sin propagar fallos.
- `modelos/identidad_mensajeria.py` vincula un identificador externo inmutable
  con un usuario Hermes sin almacenar tokens ni números telefónicos.
- `servicios/gestor_mensajeria.py` es la fachada común: abre sesiones aisladas
  y delega en los mismos casos de uso que FastAPI. `gestor_telegram.py` y
  `gestor_slack.py` solo fijan identidad, límites y canal de auditoría.
- `interfaces/telegram/` solo interpreta comandos, botones y respuestas. Se
  ejecuta por sondeo saliente y no publica un webhook ni puertos nuevos.
- `interfaces/slack/` traduce `/hermes` y botones mediante Bolt asíncrono. Usa
  Socket Mode saliente y tampoco publica puertos.
- `monitoreo/sondeador.py` obtiene diagnóstico y servicios críticos mediante
  una conexión reutilizada por servidor y un plazo total.
- `monitoreo/evaluador.py` convierte lecturas en episodios deduplicados y
  recuperaciones auditadas.
- `monitoreo/notificaciones.py` materializa una entrega por suscripción,
  reintenta fallos y adapta Telegram o Slack sin conocer SSH.
- `monitoreo/motor.py` limita la concurrencia y aísla el fallo de cada destino.
- `conexiones/transporte_ssh.py` contiene la conexión AsyncSSH, la doble
  validación de host, los plazos y la recolección acotada de salida.
- `conexiones/credenciales.py` resuelve referencias de archivo confinadas o el
  socket del agente sin consultar secretos desde MariaDB.
- `adaptadores/linux.py` y `adaptadores/windows.py` encapsulan las diferencias
  de plataforma. PowerShell nunca aparece en las rutas ni en las interfaces de
  mensajería.
- `adaptadores/diagnostico.py` valida y normaliza el contrato común de métricas;
  los valores ausentes se representan con `None` dentro del backend.
- `adaptadores/servicios.py` valida nombres, estados, marcadores y errores de
  servicios con un contrato común para Linux y Windows Server.
- `servicios/auditoria.py` registra el actor, la acción, el recurso y el
  resultado dentro de la misma base de datos.
- `modelos/` define inventario, control de acceso y auditoría. Las relaciones de
  muchos a muchos usan tablas explícitas y restricciones de integridad.
- `migraciones/` conserva la evolución reproducible del esquema y los datos
  mínimos de roles y permisos.
- `interfaces/` contiene los contratos y las adaptaciones de mensajería; no
  contiene comandos del sistema ni reglas de permisos.

## Canales sobre el backend común

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
normaliza disponibilidad, ejecución acotada y cierre; AsyncSSH implementa ese
puerto. Telegram y Slack traducen mensajes hacia la misma fachada. La selección
de órdenes remotas, los permisos y la auditoría no residen en los bots; cada
interfaz solo mantiene la selección conversacional y el desafío efímero de
confirmación.

El contrato de transporte no asume Linux. Los adaptadores verifican la
plataforma y traducen cada acción común a su comando fijo. Los canales
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
- El diagnóstico usa un guion interno fijo por plataforma. Linux consulta
  `/proc` y `df`; Windows consulta clases CIM mediante PowerShell. Ninguno acepta
  texto, rutas o comandos aportados por el usuario.
- La salida diagnóstica exige exactamente el marcador y los campos esperados;
  rechaza duplicados, porcentajes fuera de `0..100`, valores no finitos y tiempos
  de actividad no enteros.
- Cada acción usa un modelo Pydantic con campos adicionales prohibidos. El único
  parámetro actual es un identificador de proceso entero y acotado.
- `reiniciar_servidor` exige un permiso exclusivo y confirmación explícita. Se
  programa con un minuto de margen para evitar una desconexión instantánea.
- Telegram solo acepta conversaciones privadas y resuelve cada interacción por
  el identificador numérico almacenado en `identidades_mensajeria`. El nombre
  visible y el teléfono no conceden acceso.
- Las confirmaciones Telegram usan un valor aleatorio, caducan, pertenecen al
  estado de un único usuario y solo pueden consumirse una vez.
- Inicio, detención y reinicio de servicios comparten la confirmación genérica;
  el desafío queda ligado en memoria a la acción, parámetros y selección que ya
  fueron autorizados. Una selección dinámica se fija en IDs antes de confirmar
  y todo vuelve a validarse al consumirla.
- Las acciones múltiples prohíben selectores ambiguos y IDs duplicados. El
  inventario no tiene un máximo fijo, pero cada solicitud está acotada para
  proteger conexiones, memoria y tamaño de respuesta.
- Cada destino concurrente abre su propia sesión de SQLAlchemy. Un semáforo y
  un plazo total individual aíslan servidores lentos o desconectados, y cada
  resultado conserva auditoría por servidor.
- `consultar_servicios` está separado de `gestionar_servicios`. El operador de
  inventario solo recibe lectura y el administrador recibe las mutaciones.
- La interfaz limita a 30 solicitudes por identidad y minuto y acota a 5 000 las
  identidades conservadas temporalmente por su limitador.
- El token Telegram es `SecretStr`, se exige solo al habilitar el canal y nunca
  se incorpora a mensajes, auditoría ni registros.
- Slack combina `team_id` y `user_id`, exige mensajes directos y vuelve a
  comprobar el vínculo persistente en cada interacción. El nombre, correo y
  teléfono no conceden acceso.
- Bolt confirma comandos y botones antes de cualquier consulta o conexión
  remota. Socket Mode valida el sobre autenticado sin exponer un endpoint HTTP.
- Los tokens `xoxb-` y `xapp-` son `SecretStr`; el manifiesto solicita solo
  `commands`, `chat:write` y `connections:write` en el token correspondiente.
- Las confirmaciones Slack son aleatorias, caducables, de un solo uso y quedan
  ligadas a la identidad y a destinos fijados antes de mostrar los botones.
- Cada ruta de inventario exige un permiso persistente. Los rechazos de
  autenticación y autorización también generan auditoría cuando existe un
  usuario identificable.
- Las eliminaciones requieren `confirmar=true` y respetan las restricciones de
  integridad de MariaDB.
- HTTP Basic es una adaptación local temporal y el servidor se limita a
  `127.0.0.1`; cualquier exposición de red futura exigirá TLS.
- Las dependencias directas están fijadas y se verifican mediante pruebas antes
  de actualizarse.
- Cada condición de monitoreo dispone de una clave activa única; los ciclos
  repetidos actualizan el episodio en lugar de crear alertas duplicadas.
- Las recuperaciones solo se notifican a destinos que recibieron la apertura.
  Cada intento queda persistido y se detiene al alcanzar el máximo configurado.
- Los destinos de alerta deben ser identidades activas, pertenecer a usuarios
  activos y contar con una suscripción explícita habilitada por un administrador.

## Administración futura del Ubuntu anfitrión

Hermes no ejecuta órdenes directamente en su propio proceso. El Ubuntu del
laboratorio ya se comprobó mediante OpenSSH, autenticación por clave y
verificación estricta de la clave del host. Las acciones son predefinidas,
autorizadas y auditadas. Telegram usa el identificador numérico; Slack combina
el espacio y usuario inmutables. Ambos delegan al backend y ninguno autoriza
por número telefónico.

Este flujo trata al anfitrión como otro servidor Linux del inventario. Así se
prueba el recorrido completo localmente sin crear una excepción insegura para
“ejecutar directamente” comandos recibidos por Telegram.
