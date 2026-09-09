# Arquitectura de Hermes

## Objetivo actual

La base separa configuración, transporte HTTP, autenticación, casos de uso,
persistencia y contratos externos. El hito 2 añade inventario y seguridad sin
trasladar lógica administrativa hacia Telegram o Slack.

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
      └──► rutas/{inventario,acceso,auditoria}.py │
                  │                               │
                  ▼                               │
       autenticación y permisos                   │
                  │                               │
                  ▼                               │
       servicios de inventario, acceso            │
       y consulta de auditoría                     │
                  │                               │
                  ▼                               ▼
        modelos SQLAlchemy ─────────────► MariaDB local
                                         (127.0.0.1:3378)
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
normaliza disponibilidad, ejecución acotada y cierre. Los bots futuros solo
traducirán mensajes hacia casos de uso del backend. La selección de comandos,
permisos, confirmaciones y auditoría no residirá en esos bots.

El contrato de transporte no asume Linux. Los adaptadores de sistema operativo
se incorporarán cuando sus operaciones tengan requisitos concretos, evitando
inventar ahora comandos o resultados que pertenecen a otros hitos.

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
  claves privadas. El resolvedor seguro pertenece al hito 3.
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

Hermes no ejecutará órdenes directamente en su propio proceso. El Ubuntu del
laboratorio ya puede registrarse como inventario, pero solo en el hito 3 se
conectará mediante OpenSSH usando una cuenta de mínimo privilegio, clave de
usuario y verificación estricta de la clave del host. En el hito 4 las acciones
serán predefinidas, autorizadas y auditadas. En el hito 5 Telegram identificará
al usuario principalmente por su identificador numérico inmutable y delegará la
acción al backend. El número de teléfono no es un dato fiable ni siempre está
disponible para autorizar bots, por lo que no será el identificador principal.

Este flujo trata al anfitrión como otro servidor Linux del inventario. Así se
prueba el recorrido completo localmente sin crear una excepción insegura para
“ejecutar directamente” comandos recibidos por Telegram.
