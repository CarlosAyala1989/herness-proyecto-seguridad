# Arquitectura de Hermes

## Objetivo actual

La base separa configuración, transporte HTTP, autenticación, casos de uso,
persistencia y contratos externos. Telegram, diagnóstico y servicios usan
esos mismos servicios sin duplicar inventario, autorización, SSH ni auditoría.
El orquestador múltiple añade concurrencia acotada sin cambiar esos límites.

## Componentes actuales

```text
HTTP local ──► rutas FastAPI ────────────┐
                                         │
Telegram ──► interfaz/telegram ──► gestor_telegram
                                         │
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
- `servicios/gestor_telegram.py` es la fachada del backend para el canal: abre
  sesiones aisladas y delega en los mismos casos de uso que FastAPI.
- `interfaces/telegram/` solo interpreta comandos, botones y respuestas. Se
  ejecuta por sondeo saliente y no publica un webhook ni puertos nuevos.
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

## Límites preparados para hitos posteriores

```text
Telegram ─┐
          ├──► backend común ─► autorización ─► operaciones controladas
Slack ────┘       (hito 9)                       │
                                                 ▼
                                      transporte remoto
                                                 │
                                     ┌───────────┴───────────┐
                                     ▼                       ▼
                              adaptador Linux         adaptador Windows
```

`CanalMensajeria` define la salida mínima de un canal. `TransporteRemoto`
normaliza disponibilidad, ejecución acotada y cierre; AsyncSSH ya implementa
ese puerto. Telegram ya traduce mensajes hacia casos de uso del backend. La
selección de órdenes remotas, los permisos y la auditoría no residen en el bot;
su interfaz solo mantiene la selección conversacional y el desafío efímero de
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
verificación estricta de la clave del host. Las acciones son predefinidas,
autorizadas y auditadas. Telegram identifica al usuario por su identificador
numérico inmutable y delega la acción al backend. El número de teléfono no es
un dato fiable ni siempre está disponible para bots, por lo que no se usa para
autorizar.

Este flujo trata al anfitrión como otro servidor Linux del inventario. Así se
prueba el recorrido completo localmente sin crear una excepción insegura para
“ejecutar directamente” comandos recibidos por Telegram.
