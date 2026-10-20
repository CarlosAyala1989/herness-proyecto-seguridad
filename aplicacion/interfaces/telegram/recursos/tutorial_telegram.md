# Tutorial completo de Hermes para Telegram

Esta guía explica todos los comandos del bot de Hermes, con ejemplos para Linux
y Windows Server. Puedes volver a descargarla en cualquier momento mediante
`/tutorial`. Corresponde a los comandos incluidos en esta instalación; solicitar
el documento no cambia archivos, servicios ni cuentas de los equipos administrados.

## 1. Qué necesitas antes de empezar

Hermes y su base de datos se ejecutan en el servidor de quien lo instala.
Telegram transporta los mensajes; las operaciones administrativas se realizan
por SSH y las transferencias de archivos por SFTP.

Para utilizar el bot deben cumplirse estas condiciones:

1. El bot está iniciado y tiene conexión a Internet.
2. Tu ID numérico está fijado como propietario en la configuración local.
3. Ese ID está vinculado a un usuario Hermes activo y con los permisos necesarios.
4. Hablas con el bot en un chat privado. Los grupos de Telegram no están admitidos.
5. Para administrar un equipo, este debe estar registrado en el inventario,
   activo y accesible por SSH con una clave autorizada y su huella verificada.

Solo el propietario puede utilizar los comandos. El nombre visible, el
`@usuario` y conocer el enlace del bot no conceden permisos. Si aún no estás
autorizado, `/inicio` muestra una denegación y tu ID para registrarlo desde la
terminal del servidor. No envíes el token del bot ni contraseñas al chat.

Ser administrador de Hermes no convierte a la cuenta SSH en administrador del
sistema operativo. Leer recursos suele funcionar con una cuenta normal;
modificar servicios o usuarios puede requerir permisos adicionales preparados
en la máquina de destino. El bot no solicita la contraseña de `sudo`.

## 2. Cómo leer los ejemplos

- Escribe cada comando como un mensaje de Telegram independiente.
- Los textos entre `<...>` representan datos que debes reemplazar: no escribas
  los signos `<` y `>` en el mensaje real.
- Los valores entre `[...]` son opcionales; tampoco escribas los corchetes.
- Los IDs de servidor, grupo, aplicación y despliegue son diferentes. Los
  números `1` y `2` de esta guía son ejemplos, no valores de tu instalación.
- Usa `/servidores`, `/grupos` o `/aplicaciones` para consultar los IDs reales.
- `ubuntu-local` es un ejemplo de nombre de servidor. Puede llamarse de otra forma.
- Los nombres `hermes_prueba`, `operadores` y `hermes-prueba.service` son ejemplos
  de laboratorio: deben existir o prepararse cuando corresponda.

Hermes interpreta comandos de su catálogo. No es una terminal remota libre:
mensajes como `sudo apt update`, `/exec ...` o `/bash ...` no ejecutan una shell.

## 3. Primera sesión: consultar tu equipo

Envía estos mensajes, uno por uno:

```text
/inicio
/servidores
```

Pulsa el botón del servidor que quieras consultar, por ejemplo `ubuntu-local`.
Después envía:

```text
/seleccion
/diagnostico
/identidad
/proceso 1
```

Este recorrido es de lectura. Permite comprobar la selección, recursos,
usuario de conexión y un proceso existente sin reiniciar ni modificar el equipo.
Si el inventario está vacío, hay que registrar el destino desde la administración
local de Hermes. El bot no inventa una conexión ni registra máquinas por su cuenta.

## 4. Acceso, ayuda y tutorial

### /inicio

**Sintaxis:** `/inicio`

Comprueba tu autorización y muestra la bienvenida y el resumen de comandos.
No selecciona un servidor ni comprueba por sí solo el acceso SSH a los equipos.

```text
/inicio
```

Si aparece «Acceso denegado», utiliza el ID que muestra el bot para completar
la vinculación desde la terminal del servidor. Si ya estaba configurado,
comprueba que la cuenta Hermes esté activa y que el proceso haya cargado el
ID del propietario. Insistir con el `@usuario` no cambia esa autorización.

### /start

**Sintaxis:** `/start`

Es un alias de `/inicio`. Telegram puede enviarlo cuando pulsas **Iniciar** al
abrir el enlace del bot. Tiene los mismos requisitos de propietario y chat privado.

```text
/start
```

Puedes usar `/inicio` para mantener los comandos en español. El alias no
concede permisos nuevos ni abre un modo distinto del programa.

### /ayuda

**Sintaxis:** `/ayuda`

Muestra una referencia breve con los comandos disponibles y sus argumentos.
Resulta útil para recordar un nombre mientras trabajas. No requiere seleccionar
un equipo y no cambia la selección ni ejecuta operaciones SSH.

```text
/ayuda
```

Si necesitas el procedimiento completo de una operación, descarga esta guía
mediante `/tutorial`. Que un comando figure en la ayuda no significa que la
máquina de destino tenga preparados todos sus permisos o servicios.

### /tutorial

**Sintaxis:** `/tutorial`

Entrega este documento como un archivo adjunto llamado `tutorial_hermes.md`.
Puedes guardarlo y abrirlo con un editor de texto o un lector de Markdown.
No requiere un servidor seleccionado ni una raíz SFTP: el archivo forma parte
del propio programa y no se descarga desde los servidores del inventario.

```text
/tutorial
```

Solo se entrega después de comprobar el acceso del propietario. No recibe
argumentos ni permite elegir una ruta de archivo. Si la instalación se actualiza,
vuelve a solicitarlo para obtener la versión incluida con ese código.

## 5. Seleccionar qué equipos administras

La selección determina dónde actúan los comandos de diagnóstico, servicios,
procesos y usuarios. Puede ser un equipo, un grupo o todos los servidores activos.
Las transferencias de archivos necesitan exactamente un equipo. Los comandos
de aplicaciones utilizan el ID de la aplicación y su servidor asociado.

La selección conversacional se mantiene en memoria. Si el bot se reinicia,
vuelve a seleccionarla. `/inicio` y `/ayuda` no sustituyen `/servidores`.

### /servidores

**Sintaxis:** `/servidores`

Lista los servidores activos disponibles y presenta botones para elegir uno.
Cada botón muestra su ID y su nombre. Pulsarlo cambia la selección para las
operaciones siguientes; consultar la lista no ejecuta una modificación remota.

```text
/servidores
```

Pulsa, por ejemplo, el botón `1 · ubuntu-local` si ese es el ID real mostrado.
Después utiliza `/seleccion` para comprobar el destino. Si indica que no hay
servidores activos, el inventario debe prepararse desde la administración local.
El listado mostrado tiene un límite configurable; no equivale a un máximo fijo
de equipos que puedan registrarse en Hermes.

### /grupos

**Sintaxis:** `/grupos`

Lista grupos de inventario ya creados y ofrece botones para seleccionar uno.
Un grupo de inventario reúne servidores, por ejemplo los de laboratorio.
No es un grupo de Telegram ni un grupo de cuentas Linux o Windows.

```text
/grupos
```

Pulsa el grupo y comprueba `/seleccion` antes de actuar. Este comando no crea
grupos ni cambia sus miembros; esas tareas corresponden a la administración
del inventario. Si no hay grupos registrados, selecciona un servidor individual.

### /seleccionar

**Sintaxis:** `/seleccionar <id_servidor>`

Elige un servidor por su ID numérico, como alternativa al botón de `/servidores`.
Necesita exactamente un entero positivo de un equipo registrado, activo y
accesible para tu usuario Hermes. No recibe una dirección IP ni un nombre de equipo.

```text
/seleccionar 1
/seleccion
```

Reemplaza `1` por el ID mostrado en tu inventario. La nueva selección sustituye
la anterior y descarta las confirmaciones pendientes. Seleccionar un servidor
no comprueba todas sus operaciones: un diagnóstico posterior puede informar
de un fallo de conexión o permisos en el destino.

### /seleccionar_grupo

**Sintaxis:** `/seleccionar_grupo <id_grupo>`

Selecciona los servidores activos de un grupo de inventario existente. El ID
es el del grupo, no el de uno de sus miembros. Hermes comprueba los objetivos
y sus límites antes de aceptar la selección.

```text
/seleccionar_grupo 2
/seleccion
/diagnostico
```

Las lecturas vuelven a resolver los miembros del grupo. Antes de una operación
que exige confirmación, los destinos se fijan para que no se añadan otros mientras
decides. Un grupo vacío o sin objetivos válidos produce un error controlado.

### /seleccionar_todos

**Sintaxis:** `/seleccionar_todos`

Selecciona todos los servidores activos autorizados del inventario, dentro del
límite configurado por solicitud. No significa «todos los equipos de la red»:
Hermes solo conoce las máquinas registradas previamente.

```text
/seleccionar_todos
/seleccion
/diagnostico
```

Comprueba el alcance antes de enviar una orden que cambie servicios o cuentas.
La operación se ejecuta por servidor, con concurrencia acotada. Si uno está
apagado, puede aparecer como fallido sin impedir el resultado de los demás.

### /seleccion

**Sintaxis:** `/seleccion`

Muestra y vuelve a validar la selección vigente: servidor individual, grupo
o conjunto de todos los activos. Sirve para confirmar a qué equipos afectará
el próximo comando; no cambia el estado de las máquinas.

```text
/seleccion
```

Si responde «No hay servidores seleccionados», utiliza `/servidores` o
`/seleccionar <id>`. Una selección puede dejar de ser válida si el equipo se
desactiva o se retira del inventario. Revísala especialmente antes de cambios
en varios destinos.

## 6. Diagnóstico, identidad y procesos

Estos comandos necesitan una selección válida y los permisos de lectura
correspondientes. Pueden aplicarse a un servidor, un grupo o todos los activos.
La identidad de Telegram y el acceso SSH son controles independientes.

### /diagnostico

**Sintaxis:** `/diagnostico`

Consulta disponibilidad, uso de CPU, memoria y disco, tiempo de actividad,
sistema operativo, versión y nombre del equipo. Los valores reflejan el momento
de la lectura; no constituyen por sí solos un histórico ni una suscripción de alertas.

```text
/seleccionar 1
/diagnostico
```

Una métrica puede aparecer como «No disponible» sin invalidar las demás. En
selecciones múltiples se presenta un resultado por servidor y un resumen de
éxitos y fallos. Si el equipo no responde, revisa su red, OpenSSH, clave y huella.
El comando no aumenta permisos del sistema para obtener datos ocultos.

### /identidad

**Sintaxis:** `/identidad`

Informa el usuario de la sesión SSH y el nombre del equipo seleccionado.
Permite confirmar que Hermes está conectado al destino y con la cuenta
previstos. Ese usuario remoto no es necesariamente tu usuario de Telegram
ni el nombre del administrador local de Hermes.

```text
/identidad
```

Úsalo después de cambiar la selección o registrar una máquina. La operación
es de lectura. Si la cuenta remota es normal, las funciones que requieren
privilegios seguirán sujetas a los permisos de esa cuenta.

### /proceso

**Sintaxis:** `/proceso <pid>`

Consulta un proceso por su identificador numérico. Se admite un entero positivo
hasta `4194304`; no se aceptan nombres, comodines, signos ni expresiones de shell.
El proceso debe existir en el equipo al realizarse la lectura.

```text
/proceso 1
/proceso 2345
```

El segundo PID es solo un ejemplo. En un grupo, el mismo número puede referirse
a procesos distintos en cada máquina. Consultar un proceso no lo detiene, no
lo reinicia y no ofrece una función para matar procesos.

## 7. Consultar y administrar servicios

En Linux se utiliza el nombre de unidad de systemd, por ejemplo `ssh.service`.
En Windows se utiliza el nombre interno del servicio, como `sshd`, y no su
etiqueta traducida. Se aceptan nombres acotados con letras, números, puntos,
guiones, guiones bajos y `@`; no rutas, espacios ni comodines.

Leer un servicio y modificarlo son permisos distintos. En Linux una cuenta
no root necesita autorización `sudo -n` limitada para las modificaciones;
Hermes no abre un diálogo para pedir esa contraseña. En Windows se necesitan
los derechos correspondientes sobre el servicio.

Para practicar modificaciones, prepara una unidad prescindible de laboratorio.
Los ejemplos siguientes usan `hermes-prueba.service`. No detengas SSH, red,
MariaDB ni el propio bot para comprobar que funcionan los botones.

### /servicio

**Sintaxis:** `/servicio <nombre_servicio>`

Consulta estado e información de inicio automático sin modificar el servicio.
Puede devolver activo, inactivo, fallido, estados transitorios o datos no
disponibles según la plataforma y sus permisos.

```text
/servicio ssh.service
```

En Windows, sobre una selección de equipos Windows:

```text
/servicio sshd
```

Si el servicio no existe, verifica su nombre interno. Al seleccionar equipos
de distintos sistemas, el mismo nombre se envía a todos: utiliza grupos por
plataforma cuando sus nombres de servicio sean diferentes.

### /iniciar_servicio

**Sintaxis:** `/iniciar_servicio <nombre_servicio>`

Solicita iniciar el servicio seleccionado y presenta los botones **Confirmar**
y **Cancelar**. Enviar el mensaje no lo inicia todavía. Después de confirmar,
Hermes ejecuta la operación y vuelve a consultar el estado.

```text
/iniciar_servicio hermes-prueba.service
```

Comprueba el servicio y los destinos antes de pulsar **Confirmar**. Esta orden
no instala servicios inexistentes ni configura su inicio automático al arrancar
el sistema. Un rechazo de privilegios requiere preparar permisos en el destino.

### /detener_servicio

**Sintaxis:** `/detener_servicio <nombre_servicio>`

Solicita detener un servicio existente. Necesita confirmación y los permisos
de gestión de servicios de Hermes y del sistema remoto. Una selección múltiple
puede afectar a varios equipos.

```text
/detener_servicio hermes-prueba.service
```

Puede interrumpir una aplicación que dependa de ese servicio. En Windows no
se utiliza una detención forzada de dependencias. Si el servicio es crítico
para la conexión, puedes perder el acceso; utiliza una unidad de prueba.

### /reiniciar_servicio

**Sintaxis:** `/reiniciar_servicio <nombre_servicio>`

Solicita reiniciar un servicio y exige confirmación. Reiniciar un servicio
interrumpe su funcionamiento durante la operación; no equivale a consultar
su estado ni a recargar una configuración sin interrupciones.

```text
/reiniciar_servicio hermes-prueba.service
/servicio hermes-prueba.service
```

El segundo mensaje sirve para revisar el estado después del resultado. Si no
puede verificarse el cambio, consulta el mensaje por servidor y los registros
locales antes de repetir una operación sobre una aplicación importante.

## 8. Cuentas locales del sistema operativo

Las cuentas de esta sección pertenecen al servidor seleccionado. No son
usuarios de Telegram, identidades de Slack ni cuentas internas de Hermes.

Los nombres de cuenta admiten hasta 20 caracteres ASCII compatibles con Linux
y Windows: letras, números, punto, guion y guion bajo, con las restricciones
del validador. Usa nombres sencillos como `hermes_prueba`. Los grupos deben
existir antes de agregar o quitar miembros; pueden incluir espacios en Windows.

Las mutaciones exigen confirmación y permisos del sistema. Las cuentas del
sistema, los grupos privilegiados y la cuenta usada para SSH tienen protecciones.
El bot no permite activar la excepción administrativa para cuentas protegidas.
Practica con cuentas desechables; no con tu cuenta de acceso.

### /usuarios

**Sintaxis:** `/usuarios`

Lista cuentas locales, identificadores, estado, grupos e indicación de protección.
No devuelve contraseñas ni cambia las cuentas. El estado puede ser desconocido
cuando el sistema limita la información que puede leer la cuenta SSH.

```text
/usuarios
```

Comprueba este listado antes de una modificación. En varios destinos, una
cuenta del mismo nombre puede existir con estados y grupos diferentes.
La palabra «protegida» indica que las operaciones desde el bot estarán limitadas.

### /crear_usuario

**Sintaxis:** `/crear_usuario <cuenta> [nombre para mostrar]`

Crea una cuenta local inicialmente deshabilitada, después de confirmar.
No recibe una contraseña ni una clave SSH como argumentos. El nombre para
mostrar es opcional y puede contener varias palabras.

```text
/crear_usuario hermes_prueba Cuenta temporal de laboratorio
```

Antes de habilitarla hay que preparar una credencial segura fuera del bot.
En Linux se crea su directorio personal y se deja bloqueada y vencida; en
Windows se crea deshabilitada. Esta operación no concede privilegios de
administrador ni crea una identidad autorizada de Hermes.

### /agregar_grupo

**Sintaxis:** `/agregar_grupo <cuenta> <grupo>`

Agrega una cuenta local a un grupo existente, con confirmación. No crea ese
grupo ni modifica los grupos de inventario de servidores.

```text
/agregar_grupo hermes_prueba operadores
```

En un Windows de laboratorio, si el grupo está permitido:

```text
/agregar_grupo hermes_prueba Usuarios de laboratorio
```

Los grupos privilegiados están protegidos. No uses `sudo`, `docker`, `root`
o equivalentes como ejemplos de práctica: pueden conceder acceso administrativo
y el bot mantiene desactivada la excepción que permitiría esos cambios.

### /quitar_grupo

**Sintaxis:** `/quitar_grupo <cuenta> <grupo>`

Retira una cuenta de un grupo existente después de confirmar. No elimina ni
la cuenta ni el grupo. Puede quitar acceso a archivos o funciones que dependan
de la pertenencia a ese grupo.

```text
/quitar_grupo hermes_prueba operadores
```

Comprueba primero `/usuarios` y el efecto esperado en cada destino. Las mismas
protecciones de cuentas y grupos se aplican a esta operación; no sirve para
alterar desde Telegram una cuenta protegida o la sesión SSH operadora.

### /bloquear_usuario

**Sintaxis:** `/bloquear_usuario <cuenta>`

Solicita bloquear o deshabilitar una cuenta local, según el sistema operativo.
Necesita confirmación y permisos específicos. No elimina sus datos y no
equivale a cerrar inmediatamente todas sus sesiones o procesos existentes.

```text
/bloquear_usuario hermes_prueba
```

La cuenta SSH operadora y las cuentas protegidas se rechazan. No asumas que
el estado de una cuenta reemplaza una política completa de acceso por claves,
servicios y sesiones del sistema: consulta después `/usuarios`.

### /desbloquear_usuario

**Sintaxis:** `/desbloquear_usuario <cuenta>`

Solicita desbloquear o habilitar una cuenta local existente. Requiere
confirmación. No crea una contraseña ni aprovisiona una clave de acceso.

```text
/desbloquear_usuario hermes_prueba
```

Antes de confirmar, asegúrate de que un administrador haya preparado sus
credenciales y permisos fuera de Hermes. Habilitar una cuenta no garantiza
que OpenSSH u otros servicios permitan iniciar sesión con ella.

### /eliminar_usuario

**Sintaxis:** `/eliminar_usuario <cuenta>`

Elimina una cuenta local tras confirmación. Exige permisos de gestión y de
eliminación, además de los del sistema. En Linux también elimina su directorio
personal; puede destruir datos de esa cuenta.

```text
/eliminar_usuario hermes_prueba
```

Utiliza solo una cuenta de prueba que puedas perder. No hay un comando del
bot para deshacer esta eliminación. Las cuentas protegidas y la cuenta que
sostiene SSH no se pueden eliminar desde Telegram.

## 9. Archivos: consultar, descargar y cargar

Selecciona exactamente un servidor mediante su botón o `/seleccionar <id>`.
Una selección de grupo o de «todos» no se transforma automáticamente en una
transferencia individual, aunque en ese momento contenga un solo equipo.

El administrador debe registrar primero raíces permitidas de lectura o escritura
y preparar los permisos de sus directorios. Estar autorizado como propietario
no permite acceder a cualquier ruta. Los ejemplos `/srv/hermes/intercambio`
y `C:/Hermes/Intercambio` solo funcionan si esas raíces están preparadas.

Usa rutas absolutas completas. No utilices `~`, rutas relativas, `..`, recursos
UNC ni la raíz completa de un disco. Las rutas que escapan de una raíz permitida
por enlaces o por su resolución canónica se rechazan. Las rutas con espacios
se reconstruyen a partir de los argumentos; no agregues comillas de shell.

El límite predeterminado de transferencias es 8 MiB (8 388 608 bytes), configurable
por el administrador. Los contenidos no se guardan en MariaDB; las transferencias
sí quedan auditadas. Al enviar o recibir un documento por el chat, su contenido
también pasa por Telegram.

### /archivo_info

**Sintaxis:** `/archivo_info <ruta_absoluta>`

Consulta tipo, tamaño y fecha de modificación de una ruta permitida sin
descargar su contenido. Necesita permisos de consulta y un único servidor
seleccionado.

```text
/archivo_info /srv/hermes/intercambio/evidencia.txt
```

En Windows:

```text
/archivo_info C:/Hermes/Intercambio/evidencia.txt
```

El tamaño puede figurar como no disponible según el tipo y los metadatos del
destino. Esta consulta no lista automáticamente todo un árbol de carpetas ni
modifica el archivo.

### /descargar_archivo

**Sintaxis:** `/descargar_archivo <ruta_absoluta>`

Lee un archivo regular dentro de una raíz de lectura permitida y lo entrega
como documento adjunto en Telegram. Se comprueban la ruta, permisos, tamaño
y límites de tiempo antes de completar la operación.

```text
/descargar_archivo /srv/hermes/intercambio/evidencia.txt
```

Guarda el adjunto desde Telegram si deseas conservar una copia local. El
comando no descarga directorios, no crea un ZIP y no envía implícitamente el
mismo archivo desde todos los miembros de un grupo.

### /cargar_archivo

**Sintaxis:** responder a un documento con `/cargar_archivo <ruta_destino_absoluta>`

El procedimiento tiene tres pasos:

1. Selecciona un único servidor.
2. Envía al chat el archivo como **documento**. Por ejemplo, un archivo de texto
   llamado `evidencia.txt`.
3. Usa **Responder** sobre ese mensaje y escribe la ruta completa de destino:

```text
/cargar_archivo /srv/hermes/intercambio/evidencia-nueva.txt
```

La raíz debe permitir escritura y la cuenta SSH debe poder crear el archivo.
Telegram debe informar su tamaño dentro del límite. Enviar el comando como
un mensaje independiente, sin responder al documento, no carga el archivo.

Esta carga no pide confirmación y **nunca sobrescribe un archivo existente**.
Si el destino ya existe, usa otro nombre. No añadas parámetros como `--force`
o `sobrescribir=true`: no forman parte de este comando de Telegram.

## 10. Aplicaciones y despliegues

Una aplicación administrada relaciona un servidor registrado con una plantilla
de despliegue previamente aprobada. La plantilla fija la plataforma, un archivo
de destino y, opcionalmente, un servicio que se reiniciará. El catálogo actual
instala un archivo; no interpreta un script arbitrario, un repositorio o un
proyecto completo recibido por el chat.

Las aplicaciones, plantillas, raíces y permisos se preparan desde la administración
local de Hermes. Para desplegar debes cargar antes el artefacto en el mismo
servidor. Las consultas y cambios de esta sección usan el ID de aplicación;
no dependen de qué servidor o grupo esté seleccionado en el chat.

### /aplicaciones

**Sintaxis:** `/aplicaciones`

Lista las aplicaciones registradas, su ID, el ID de su servidor y la versión
vigente cuando existe. Sirve para obtener el identificador que necesitan los
otros comandos de despliegue.

```text
/aplicaciones
```

Si responde que no hay aplicaciones administradas, primero hay que crear
sus plantillas y asociaciones. No es una lista de todos los paquetes o
programas instalados en el sistema operativo.

### /estado_aplicacion

**Sintaxis:** `/estado_aplicacion <id_aplicacion>`

Consulta la versión vigente, estado operativo, integridad del archivo y el
estado del servicio asociado, cuando la plantilla lo define. No instala
versiones ni reinicia servicios.

```text
/estado_aplicacion 1
```

Una integridad «sin referencia» indica que no hay una huella vigente con la
que comparar; no significa que se haya verificado el contenido. Si el archivo
se alteró fuera de Hermes, revisa la diferencia antes de intentar un despliegue.

### /desplegar

**Sintaxis:** `/desplegar <id_aplicacion> <version> <ruta_artefacto>`

Solicita instalar el archivo de un artefacto que ya existe en el servidor de
esa aplicación. La versión es una etiqueta sin espacios, por ejemplo `1.0.0`.
La ruta debe ser absoluta y estar autorizada; no es una URL de descarga.

```text
/desplegar 1 1.0.0 /srv/hermes/artefactos/api-1.0.0.bin
```

Revisa los datos y pulsa **Confirmar** para ejecutar. Hermes respalda el destino
anterior si existe, instala por SFTP, verifica SHA-256 y reinicia el servicio
opcional de la plantilla. Un fallo capturado provoca un intento de restauración
automática y deja constancia del resultado.

Es una modificación real de archivos y puede interrumpir un servicio. Si el
proceso cae bruscamente durante la escritura, puede quedar un archivo parcial;
revisa el estado y el respaldo antes de repetir. No es un despliegue atómico
de paquetes ni ejecuta migraciones de base de datos de la aplicación.

### /revertir_despliegue

**Sintaxis:** `/revertir_despliegue <id_aplicacion> <id_despliegue>`

Solicita deshacer el despliegue completado que representa la versión vigente.
Requiere confirmación y acceso al respaldo verificado. El ID de despliegue
se obtiene del historial de la aplicación en la API local; no es la etiqueta
de versión ni el ID del servidor.

```text
/revertir_despliegue 1 5
```

Si había un destino anterior, se restaura su copia. Si la primera instalación
creó el archivo sobre un destino vacío, la reversión lo elimina. El servicio
opcional se vuelve a comprobar. No se admite elegir cualquier versión antigua
del historial como si fuera un selector general de versiones.

## 11. Reinicio del equipo y confirmaciones

Las operaciones sensibles muestran botones **Confirmar** y **Cancelar**.
La confirmación pertenece al propietario, está ligada a la operación y a sus
destinos, se consume una sola vez y caduca: el valor predeterminado es 60 segundos,
configurable entre 30 y 300. No escribas «sí» o «confirmar» como texto: pulsa el botón.

Una nueva selección invalida las confirmaciones anteriores. Preparar otra
operación sensible reemplaza la pendiente correspondiente; mantén un solo
cambio pendiente y revisa siempre el mensaje que vas a confirmar. Reiniciar
el bot también pierde su estado conversacional y sus desafíos pendientes.

### /reiniciar

**Sintaxis:** `/reiniciar`

Solicita reiniciar el sistema operativo de la selección actual. No reinicia
solo Hermes ni un servicio concreto. Necesita un permiso exclusivo y una
confirmación antes de enviar la orden al sistema remoto.

```text
/seleccion
/reiniciar
```

El primer mensaje te permite revisar los equipos. No pulses **Confirmar** para
una demostración ordinaria: esta operación es real. El reinicio se programa
con aproximadamente un minuto de margen, y la respuesta informa de la
programación, no de que el equipo ya haya completado su arranque.

Si reinicias el servidor que aloja Hermes, el bot quedará desconectado durante
el proceso. Su recuperación depende del arranque automático de sus servicios,
de MariaDB y de la red. Un destino que no reciba la orden puede fallar aunque
otros equipos de una selección múltiple sí se reinicien.

### /cancelar

**Sintaxis:** `/cancelar`

Descarta una confirmación pendiente de servicios, cuentas, reinicios o despliegues.
Si no existe ninguna, informa que no hay confirmaciones pendientes. No elimina
la selección del chat ni revoca operaciones que ya fueron ejecutadas.

```text
/cancelar
```

También puedes pulsar **Cancelar** en el mensaje de confirmación. Si ya
confirmaste un reinicio o una modificación, `/cancelar` no la deshace ni cancela
su programación en el sistema operativo. La reversión de un despliegue utiliza
su propio comando y condiciones; los demás cambios pueden requerir recuperación
manual.

## 12. Recorridos completos de ejemplo

### Revisar el estado de un equipo

```text
/inicio
/servidores
```

Pulsa el equipo, verifica la selección y consulta:

```text
/seleccion
/diagnostico
/identidad
/servicio ssh.service
/proceso 1
/usuarios
```

`ssh.service` es el ejemplo Linux. Para Windows consulta `sshd`. Ninguno de
estos mensajes cambia el estado del equipo.

### Consultar varios servidores

```text
/grupos
/seleccionar_grupo 2
/seleccion
/diagnostico
```

Reemplaza el ID por el grupo real. Examina los resultados de cada máquina;
un resumen con errores no implica que todas hayan fallado. Regresa a una
selección individual con `/servidores` antes de transferir archivos.

### Practicar una confirmación sin ejecutar el cambio

Sobre una VM de laboratorio y una unidad de prueba ya preparada:

```text
/seleccionar 1
/reiniciar_servicio hermes-prueba.service
/cancelar
```

No pulses **Confirmar** entre los dos últimos mensajes. El ejemplo permite
ver el desafío y cancelarlo, pero puede fallar antes si no tienes el permiso,
servicio o selección requeridos.

### Transferir un documento preparado para intercambio

1. Selecciona el equipo y comprueba que tenga una raíz de lectura y escritura.
2. Envía un documento y responde a él con el comando de carga.
3. Consulta y descarga la nueva copia:

```text
/cargar_archivo /srv/hermes/intercambio/ejemplo-nuevo.txt
/archivo_info /srv/hermes/intercambio/ejemplo-nuevo.txt
/descargar_archivo /srv/hermes/intercambio/ejemplo-nuevo.txt
```

El primer comando debe ir como **respuesta al documento**, no pegado como parte
de un único bloque con los otros dos.

## 13. Errores frecuentes y cómo actuar

| Mensaje o situación | Qué revisar |
| --- | --- |
| Acceso denegado | ID del propietario en `.env`, vínculo activo, usuario Hermes activo y reinicio del proceso tras configurar el ID. |
| Solo atiende conversaciones privadas | Abre el chat directo con tu bot; no uses un grupo de Telegram. |
| No hay servidores activos | Registra y activa equipos en el inventario desde la administración local. |
| No hay selección | Selecciona un servidor, grupo o todos; vuelve a hacerlo si reiniciaste el bot. |
| Uso correcto… | Respeta el número de argumentos, reemplaza los marcadores y envía un comando por mensaje. |
| No tiene permiso | Revisa el rol Hermes y los permisos del sistema remoto; son controles separados. |
| Fallo de autenticación SSH | Revisa la clave autorizada, su referencia, propietario y permisos locales. Un servicio no hereda automáticamente tu `ssh-agent` de la terminal. |
| Identidad del servidor no verificada | Comprueba su clave de host por un canal confiable; no desactives la verificación ni aceptes cambios de huella a ciegas. |
| Servicio no encontrado | Usa el nombre exacto de unidad Linux o el nombre interno Windows. |
| Confirmación caducada o no válida | Solicita de nuevo la operación y utiliza su botón más reciente antes de que venza. |
| Ruta no permitida | Prepara la raíz de lectura/escritura, permisos y resolución canónica; no uses rutas relativas ni escapes. |
| Archivo ya existente | Elige otro destino: la carga desde Telegram no sobrescribe. |
| Debes responder a un documento | Usa la función **Responder** de Telegram sobre el archivo original. |
| No hay aplicaciones administradas | Crea antes la plantilla y la asociación con el servidor en la API local. |
| Límite temporal de solicitudes | Espera a que pase la ventana; se admiten hasta 30 solicitudes por identidad y minuto. |
| El bot no responde después de reiniciar | Comprueba conexión, MariaDB y el servicio de Hermes; vuelve a seleccionar el equipo cuando esté disponible. |

No repitas muchas veces una modificación si el resultado fue ambiguo.
Comprueba primero el estado real del destino. En operaciones múltiples puede
haber cambios completados en unos equipos y errores en otros; no existe una
reversión automática global de todos los cambios de servicios o usuarios.

## 14. Qué se configura fuera del chat

Los siguientes elementos necesitan preparación local o la API administrativa;
este bot no ofrece comandos para crearlos automáticamente:

- Inventario de servidores, grupos y sus asociaciones.
- Claves SSH, huellas de host y permisos del sistema operativo.
- Raíces de archivos autorizadas y sus permisos de lectura/escritura.
- Plantillas, aplicaciones administradas e historial de despliegues.
- Umbrales de monitoreo, servicios críticos y suscripciones a alertas.
- Definiciones y consulta administrativa de tareas programadas.

Hermes puede entregar alertas y resultados de tareas al propietario cuando esas
funciones están preparadas. `/diagnostico` no crea una alerta y `/cancelar` no
cancela una tarea programada persistente.

No existen comandos de Telegram para instalar paquetes, ejecutar shell libre,
cambiar contraseñas, crear grupos del sistema, forzar sobrescrituras o consultar
el historial completo de auditoría. La API local y la documentación del proyecto
describen las funciones administrativas adicionales.

Para empezar con una máquina ya preparada basta con `/inicio`, elegirla en
`/servidores` y consultar `/diagnostico`. Conserva esta guía y vuelve a pedir
`/tutorial` después de actualizar Hermes.
