# Transferencia y administración de archivos

El hito 13 incorpora SFTP sobre la misma conexión AsyncSSH autenticada por clave,
verificada mediante `known_hosts` y huella SHA-256. No acepta rutas hasta que un
administrador registre una raíz concreta para el servidor.

## Preparar una raíz de laboratorio

En Linux crea un directorio dedicado y entrégalo a la cuenta SSH limitada. Este
ejemplo debe adaptarse al usuario real y ejecutarse conscientemente por un
administrador del laboratorio:

```bash
sudo install -d -o operador_hermes -g operador_hermes -m 0750 \
  /srv/hermes/intercambio
```

No autorices `/`, `/etc`, `/usr`, `/var` ni el directorio personal completo. En
Windows Server crea, por ejemplo, `C:\Hermes\Intercambio` y concede a la cuenta
OpenSSH solo los permisos NTFS necesarios. Hermes admite rutas de unidad local;
rechaza recursos UNC y la raíz completa de una unidad.

El subsistema SFTP de OpenSSH debe estar habilitado. Hermes no instala ni cambia
OpenSSH y no necesita `sudo` para transferir cuando la cuenta posee la raíz.

## Registrar la lista blanca

Con el backend local activo, registra una raíz de lectura y escritura. `curl`
solicita la contraseña HTTP sin guardarla en el comando:

```bash
curl --user administrador_local \
  --header 'Content-Type: application/json' \
  --data '{
    "ruta": "/srv/hermes/intercambio",
    "descripcion": "Intercambio del laboratorio",
    "permite_lectura": true,
    "permite_escritura": true,
    "activo": true
  }' \
  http://127.0.0.1:8000/api/v1/servidores/1/rutas-archivos-permitidas
```

Para Windows cambia la ruta por `C:\\Hermes\\Intercambio`. Se puede listar la
configuración con `GET` sobre la misma URL. Para eliminar una entrada se requiere
su identificador y `?confirmar=true`.

## Consultar, cargar y descargar por API

Consulta metadatos sin transferir contenido:

```bash
curl --get --user administrador_local \
  --data-urlencode 'ruta_remota=/srv/hermes/intercambio/evidencia.txt' \
  http://127.0.0.1:8000/api/v1/servidores/1/archivos/informacion
```

Carga un archivo local con cuerpo binario. La operación falla si el destino ya
existe:

```bash
curl --request PUT --user administrador_local \
  --header 'Content-Type: application/octet-stream' \
  --url-query 'ruta_remota=/srv/hermes/intercambio/evidencia.txt' \
  --data-binary @evidencia.txt \
  http://127.0.0.1:8000/api/v1/servidores/1/archivos/cargar
```

Para una sobrescritura deliberada añade simultáneamente
`sobrescribir=true&confirmar=true`. Hermes comprueba que el destino sea un archivo
regular y rechaza enlaces simbólicos, directorios y destinos fuera de la raíz.

Descarga con un nombre local explícito para evitar que `curl` elija una ruta:

```bash
curl --get --user administrador_local \
  --data-urlencode 'ruta_remota=/srv/hermes/intercambio/evidencia.txt' \
  --output evidencia_descargada.txt \
  http://127.0.0.1:8000/api/v1/servidores/1/archivos/descargar
```

## Mensajería

Telegram ofrece `/archivo_info`, `/descargar_archivo` y `/cargar_archivo`. Para
cargar, responde al documento de origen con el comando y una ruta completa. La
interfaz nunca solicita sobrescritura. Slack ofrece `archivo_info` y
`descargar_archivo`; la entrega necesita el alcance `files:write` del manifiesto.

Las rutas con espacios son válidas en Windows porque las interfaces reconstruyen
todos los argumentos posteriores al comando. Las transferencias exigen un único
servidor seleccionado; no se replica implícitamente un archivo a un grupo.

## Permisos y límites

- `consultar_archivos`: metadatos y lista de raíces; administrador, operador y auditor.
- `descargar_archivos`: contenido remoto; administrador y operador.
- `cargar_archivos`: creación o carga confirmada; administrador y operador.
- `gestionar_rutas_archivos`: alta y eliminación de raíces; solo administrador.

`HERMES_LIMITE_ARCHIVO_TRANSFERENCIA_BYTES` vale 8 MiB inicialmente y puede
configurarse entre 1 KiB y 50 MiB. `HERMES_TAMANO_BLOQUE_TRANSFERENCIA_BYTES`
controla la lectura y escritura por bloques. La operación usa además el tiempo
límite SSH configurado. En el laboratorio, el contenido se mantiene en memoria
solo durante la solicitud; no se escribe en disco local ni en MariaDB.

La auditoría registra usuario, canal, servidor, acción, resultado y cantidad de
bytes. No registra contenido ni incluye la ruta completa en el detalle.

## Comprobación

```bash
pytest -q pruebas/unitarias/test_rutas_remotas.py
pytest -o addopts='' -m integracion -q \
  pruebas/integracion/test_transporte_ssh.py \
  pruebas/integracion/test_archivos_api.py
```

La primera prueba levanta un servidor SSH/SFTP efímero real y verifica carga,
descarga, consulta, creación exclusiva y confinamiento. La segunda recorre API,
MariaDB, roles y auditoría con el transporte aislado. En este entorno no se ha
aportado una VM Windows Server ni credenciales de Telegram o Slack, por lo que
esas comprobaciones externas deben ejecutarse después siguiendo sus guías; no se
inventan resultados.

El hito 14 reutiliza estas mismas raíces y operaciones SFTP para instalar
artefactos con respaldo y verificación. Consulta `despliegues.md`; la carga o
descarga manual continúa aplicando todos los controles descritos aquí.
