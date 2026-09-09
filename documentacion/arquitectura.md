# Arquitectura base de Hermes

## Objetivo del hito 1

La primera base separa configuración, transporte HTTP, persistencia y contratos
externos. Esta separación permite agregar inventario, autenticación, SSH y bots
sin trasladar lógica administrativa hacia Telegram o Slack.

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
      ▼
aplicacion/rutas/salud.py
      │
      ▼
aplicacion/base_datos.py ─────► MariaDB local (127.0.0.1:3378)
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
- Las dependencias directas están fijadas y se verifican mediante pruebas antes
  de actualizarse.

## Administración futura del Ubuntu anfitrión

Hermes no ejecutará órdenes directamente en su propio proceso. En los hitos 2 y
3, el Ubuntu del laboratorio podrá registrarse con una dirección accesible y se
conectará mediante OpenSSH usando una cuenta de mínimo privilegio, clave de
usuario y verificación estricta de la clave del host. En el hito 4 las acciones
serán predefinidas, autorizadas y auditadas. En el hito 5 Telegram identificará
al usuario principalmente por su identificador numérico inmutable y delegará la
acción al backend.

Este flujo trata al anfitrión como otro servidor Linux del inventario. Así se
prueba el recorrido completo localmente sin crear una excepción insegura para
“ejecutar directamente” comandos recibidos por Telegram.

