# Despliegue controlado de aplicaciones

El hito 14 incorpora plantillas cerradas de despliegue, aplicaciones asociadas
a un servidor, historial de versiones, verificación posterior y reversión. La
primera estrategia admitida es `archivo_unico`: Hermes instala un artefacto ya
cargado en el servidor mediante SFTP y, opcionalmente, reinicia y consulta un
servicio conocido.

No se reciben guiones, órdenes de consola ni fragmentos de PowerShell. La
plantilla solo conserva datos estructurados: sistema operativo, ruta exacta de
destino y nombre opcional del servicio. Linux usa el adaptador `systemctl` y
Windows Server usa su adaptador PowerShell existente.

## Flujo y persistencia

```text
artefacto en raíz de lectura
          │
          ▼
validar usuario, permiso, aplicación, plataforma y rutas
          │
          ▼
crear historial en_progreso y respaldar el destino existente
          │
          ▼
instalar por SFTP ─► verificar SHA-256 ─► reiniciar servicio opcional
          │                                      │
          ├── éxito: versión actual y auditoría  │
          └── fallo: restauración automática ◄───┘
```

MariaDB almacena:

- `plantillas_despliegue`: procedimiento autorizado por plataforma;
- `aplicaciones_administradas`: vínculo entre plantilla y servidor, con la
  versión vigente;
- `despliegues_aplicaciones`: versión solicitada, versión anterior, hash,
  respaldo y su hash, estado, actor, tiempos y resultado.

La migración `0011` crea estas tablas y los permisos
`consultar_aplicaciones`, `gestionar_aplicaciones`,
`desplegar_aplicaciones` y `revertir_despliegues`. El administrador recibe los
cuatro; el operador puede consultar y desplegar; el auditor solo puede
consultar.

## Preparar un servidor Linux

El artefacto y el destino deben estar dentro de raíces activas de lectura. El
destino también necesita escritura. Para el laboratorio puede registrarse una
raíz dedicada, nunca `/`:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "ruta": "/srv/hermes",
    "descripcion": "Artefactos y aplicaciones del laboratorio",
    "permite_lectura": true,
    "permite_escritura": true
  }' \
  http://127.0.0.1:8000/api/v1/servidores/1/rutas-archivos-permitidas
```

Prepara los directorios y permisos en la VM autorizada. La cuenta SSH debe
poder escribir únicamente en ese árbol y, si se configura un servicio, tener
solo la autorización necesaria para reiniciarlo y consultarlo.

Carga un artefacto sin sobrescribir otro existente:

```bash
curl --user administrador_local \
  --request PUT \
  --header 'Content-Type: application/octet-stream' \
  --data-binary @artefactos/api-1.0.0.bin \
  'http://127.0.0.1:8000/api/v1/servidores/1/archivos/cargar?ruta_remota=/srv/hermes/artefactos/api-1.0.0.bin'
```

Registra una plantilla. Omite `nombre_servicio` si el archivo no controla un
servicio:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "nombre": "api_linux_archivo",
    "descripcion": "Binario único de la API de laboratorio",
    "sistema_operativo": "linux",
    "tipo": "archivo_unico",
    "ruta_destino": "/srv/hermes/aplicaciones/api.bin",
    "nombre_servicio": "api-hermes.service"
  }' \
  http://127.0.0.1:8000/api/v1/plantillas-despliegue
```

Asocia la plantilla con un servidor compatible:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "nombre": "api_laboratorio",
    "descripcion": "API instalada en Ubuntu",
    "id_servidor": 1,
    "id_plantilla_despliegue": 1
  }' \
  http://127.0.0.1:8000/api/v1/aplicaciones-administradas
```

## Instalar, verificar y revertir

Toda instalación exige `confirmar: true`. Hermes crea primero el historial,
descarga el artefacto con el límite global, respalda el destino si existe,
instala, vuelve a descargar el resultado y compara su SHA-256. Si hay un
servicio asociado, lo reinicia mediante el adaptador de la plataforma y exige
que termine `activo`.

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "version": "1.0.0",
    "ruta_artefacto": "/srv/hermes/artefactos/api-1.0.0.bin",
    "confirmar": true
  }' \
  http://127.0.0.1:8000/api/v1/aplicaciones-administradas/1/despliegues
```

Consulta el estado operativo y el historial:

```bash
curl --user administrador_local \
  http://127.0.0.1:8000/api/v1/aplicaciones-administradas/1/estado

curl --user administrador_local \
  http://127.0.0.1:8000/api/v1/aplicaciones-administradas/1/despliegues
```

Solo puede revertirse el despliegue completado que representa la versión
vigente. Si el destino existía, se restaura su copia; si fue la primera
instalación sobre un destino vacío, se elimina el archivo instalado. Después se
reinicia el servicio opcional. Antes de escribir, el respaldo debe coincidir con
el SHA-256 conservado por el despliegue; un archivo alterado se rechaza.

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{"confirmar": true}' \
  http://127.0.0.1:8000/api/v1/aplicaciones-administradas/1/despliegues/1/revertir
```

Ante un fallo de instalación o verificación, Hermes intenta la misma
restauración automáticamente, conserva el historial como `fallido` y registra
el resultado. Si la recuperación no puede confirmarse, el mensaje lo indica y
se requiere inspección manual del servidor.

## Windows Server

El flujo es idéntico, pero la plantilla debe declarar `windows_server`, usar
una ruta absoluta de unidad y un nombre de servicio válido:

```json
{
  "nombre": "api_windows_archivo",
  "sistema_operativo": "windows_server",
  "tipo": "archivo_unico",
  "ruta_destino": "C:/Hermes/aplicaciones/api.exe",
  "nombre_servicio": "ServicioHermes"
}
```

La raíz permitida podría ser `C:/Hermes`. Una plantilla Windows no puede
asociarse con un servidor Linux, ni a la inversa. SFTP y el reinicio del
servicio continúan viajando por OpenSSH; el canal de mensajería nunca conoce
los comandos nativos.

## Telegram y Slack

Con una identidad ya vinculada y los permisos correspondientes, Telegram
ofrece:

```text
/aplicaciones
/estado_aplicacion 1
/desplegar 1 1.0.0 /srv/hermes/artefactos/api-1.0.0.bin
/revertir_despliegue 1 1
```

Slack ofrece los equivalentes:

```text
/hermes aplicaciones
/hermes estado_aplicacion 1
/hermes desplegar 1 1.0.0 /srv/hermes/artefactos/api-1.0.0.bin
/hermes revertir_despliegue 1 1
```

Desplegar y revertir muestran botones con un desafío aleatorio, caducable y de
un solo uso. Al pulsarlo se vuelven a comprobar identidad, permiso y estado
persistente. El registro de auditoría identifica `api`, `telegram` o `slack`.

## Límites actuales

- Solo está disponible la estrategia reproducible de archivo único. Paquetes,
  contenedores, migraciones de una aplicación y secuencias de varios pasos no se
  interpretan como comandos libres.
- El artefacto debe haberse cargado previamente en el mismo servidor mediante
  las funciones SFTP del hito 13.
- Los respaldos quedan en la raíz autorizada con un sufijo interno. Su política
  de retención deberá definirse antes de producción.
- Si la versión vigente tenía una huella registrada, Hermes exige que el
  contenido remoto coincida antes de respaldarlo; un cambio externo se
  rechaza. Los errores de escritura parcial detectados disparan restauración
  y verificación de contenido y servicio. La reversión manual también intenta
  conservar la versión vigente cuando falla.
- Una caída brusca del proceso durante la escritura SFTP directa puede dejar
  un archivo parcial. Verifica el destino y utiliza el respaldo antes de un
  nuevo intento. Una instalación atómica con recuperación tras reinicio queda
  fuera de la estrategia actual de archivo único.
- No se admite una segunda instalación concurrente de la misma aplicación; la
  fila se bloquea durante la operación remota acotada.
- La demostración automatizada usa un servidor AsyncSSH Linux efímero y un
  transporte simulado para los recorridos de API y canales. Una VM Windows real
  requiere OpenSSH y credenciales del laboratorio, por lo que no se inventa un
  resultado externo.
