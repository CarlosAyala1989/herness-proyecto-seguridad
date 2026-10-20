#!/usr/bin/env bash
# Instalación interactiva para Ubuntu 24.04. Ejecutar como usuario con sudo.
set -Eeuo pipefail
umask 077

fallar() { printf 'Error: %s\n' "$*" >&2; exit 1; }
trap 'printf "La instalación se detuvo en la línea %s. Corrige el problema y vuelve a ejecutar bash instalar.sh; los datos se conservan.\n" "$LINENO" >&2' ERR

if [[ "${1:-}" == "--help" ]]; then
    cat <<'AYUDA'
Uso: bash instalar.sh
Instala Hermes en Ubuntu 24.04 con systemd, desde esta carpeta.
Ejecutar como usuario normal con sudo y una terminal interactiva.
Solicita la contraseña del administrador y, opcionalmente, tokens de mensajería.
Conserva .env, claves SSH y datos existentes al repetir la instalación.
AYUDA
    exit 0
fi
[[ $# == 0 ]] || fallar 'Argumento desconocido. Usa --help.'
[[ $EUID != 0 ]] || fallar 'Ejecuta bash instalar.sh como usuario normal con sudo, sin anteponer sudo al comando.'
[[ -t 0 && -t 1 ]] || fallar 'La instalación necesita una terminal interactiva.'
[[ -f /etc/os-release ]] || fallar 'No se pudo identificar el sistema operativo.'
# Archivo del sistema, no configuración del proyecto.
source /etc/os-release
[[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] || fallar 'El instalador admite Ubuntu 24.04.'
[[ -d /run/systemd/system ]] || fallar 'Se requiere systemd en ejecución.'
command -v sudo >/dev/null || fallar 'Instala sudo y autoriza tu usuario antes de continuar.'

HERMES_RUTA=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$HERMES_RUTA"
# Las rutas se incorporan a unidades systemd. Evitar interpretación de sus escapes.
[[ "$HERMES_RUTA" =~ ^/[a-zA-Z0-9_./-]+$ ]] || fallar 'Coloca el proyecto en una ruta sin espacios ni caracteres especiales.'
[[ -f pyproject.toml && -f .env.ejemplo ]] || fallar 'Faltan archivos del proyecto.'
HERMES_USUARIO=$(id -un)
HERMES_GRUPO=$(id -gn)
HERMES_UNIDADES=$(mktemp -d)
trap 'rm -rf -- "$HERMES_UNIDADES"' EXIT

# Detectar otra instalación antes de modificar paquetes, servicios o la base.
for servicio in api telegram slack monitoreo tareas base-datos; do
    unidad="/etc/systemd/system/hermes-${servicio}.service"
    if [[ -f "$unidad" ]] && ! grep -Fxq "WorkingDirectory=$HERMES_RUTA" "$unidad"; then
        fallar "Ya existe hermes-${servicio}.service para otra carpeta."
    fi
done

printf '\nInstalando Hermes en %s para el usuario %s.\n' "$HERMES_RUTA" "$HERMES_USUARIO"
sudo -v

# No sustituir una instalación existente de Docker CE por los paquetes de Ubuntu.
HERMES_PAQUETES=(python3.12 python3.12-venv ca-certificates curl)
if ! command -v docker >/dev/null; then
    HERMES_PAQUETES+=(docker.io docker-compose-v2)
elif ! docker compose version >/dev/null 2>&1; then
    if [[ "$(dpkg-query -W -f='${Status}' docker-ce-cli 2>/dev/null || true)" == 'install ok installed' ]]; then
        HERMES_PAQUETES+=(docker-compose-plugin)
    else
        HERMES_PAQUETES+=(docker-compose-v2)
    fi
fi
sudo apt-get update
sudo apt-get install -y "${HERMES_PAQUETES[@]}"
sudo systemctl enable --now docker.service
HERMES_DOCKER=(sudo docker)
if docker info >/dev/null 2>&1; then HERMES_DOCKER=(docker); fi
"${HERMES_DOCKER[@]}" compose version >/dev/null

/usr/bin/python3.12 -c 'import ctypes'
if [[ ! -d .venv ]]; then /usr/bin/python3.12 -m venv .venv; fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Se requiere un entorno virtual Python 3.12"'
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m aplicacion.comandos.configurar_instalacion --configuracion
HERMES_PUERTO_API=$(.venv/bin/python -m aplicacion.comandos.configurar_instalacion --puerto-api)

HERMES_COMPOSE=("${HERMES_DOCKER[@]}" compose --env-file .env -f infraestructura/compose.yaml)
"${HERMES_COMPOSE[@]}" up -d --wait --wait-timeout 180

# Detener solo las unidades de esta instalación antes de migrar el esquema.
for servicio in api telegram slack monitoreo tareas; do
    unidad="hermes-${servicio}.service"
    if [[ -f "/etc/systemd/system/$unidad" ]]; then
        if ! sudo grep -Fxq "WorkingDirectory=$HERMES_RUTA" "/etc/systemd/system/$unidad"; then
            fallar "Ya existe $unidad para otra carpeta; no se sobrescribió."
        fi
        sudo systemctl stop "$unidad"
    fi
done
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/python -m aplicacion.comandos.configurar_instalacion --administrador

crear_unidad() {
    local servicio=$1
    local ejecucion=$2
    local sin_nuevos_privilegios=true
    # Telegram puede ejecutar Codex y sudo según los permisos locales del usuario.
    if [[ "$servicio" == telegram ]]; then sin_nuevos_privilegios=false; fi
    cat > "$HERMES_UNIDADES/hermes-${servicio}.service" <<UNIDAD
[Unit]
Description=Hermes - $servicio
Wants=network-online.target
After=network-online.target docker.service hermes-base-datos.service
Requires=hermes-base-datos.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$HERMES_USUARIO
Group=$HERMES_GRUPO
WorkingDirectory=$HERMES_RUTA
ExecStart=$HERMES_RUTA/.venv/bin/$ejecucion
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=$sin_nuevos_privilegios
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIDAD
}

# El arranque espera a MariaDB, también después de reiniciar el servidor.
cat > "$HERMES_UNIDADES/hermes-base-datos.service" <<UNIDAD
[Unit]
Description=Hermes - MariaDB
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$HERMES_RUTA
ExecStart=/usr/bin/docker compose --env-file .env -f infraestructura/compose.yaml up -d --wait --wait-timeout 180
TimeoutStartSec=240

[Install]
WantedBy=multi-user.target
UNIDAD

crear_unidad api "uvicorn aplicacion.principal:aplicacion --host 127.0.0.1 --port $HERMES_PUERTO_API"
crear_unidad telegram 'python -m aplicacion.interfaces.telegram'
crear_unidad slack 'python -m aplicacion.interfaces.slack'
crear_unidad monitoreo 'python -m aplicacion.monitoreo'
crear_unidad tareas 'python -m aplicacion.tareas'
if [[ -f /etc/systemd/system/hermes-base-datos.service ]]; then
    sudo grep -Fxq "WorkingDirectory=$HERMES_RUTA" /etc/systemd/system/hermes-base-datos.service || fallar 'Ya existe una unidad de MariaDB para otra instalación.'
fi
for archivo in "$HERMES_UNIDADES/"*.service; do
    sudo install -m 644 "$archivo" /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-base-datos.service
HERMES_SERVICIOS=$(.venv/bin/python -m aplicacion.comandos.configurar_instalacion --servicios)
while read -r servicio habilitado; do
    if [[ "$habilitado" == true ]]; then
        sudo systemctl enable "hermes-${servicio}.service"
        sudo systemctl restart "hermes-${servicio}.service"
    else
        sudo systemctl disable --now "hermes-${servicio}.service"
    fi
done <<< "$HERMES_SERVICIOS"

HERMES_SALUDABLE=false
for ((intento=0; intento<30; intento++)); do
    if curl --fail --silent --max-time 3 "http://127.0.0.1:$HERMES_PUERTO_API/salud" >/dev/null; then
        HERMES_SALUDABLE=true
        break
    fi
    sleep 2
done
[[ "$HERMES_SALUDABLE" == true ]] || fallar 'La API no respondió correctamente. Revisa sudo journalctl -u hermes-api -n 50.'
while read -r servicio habilitado; do
    if [[ "$habilitado" == true ]]; then
        sudo systemctl is-active --quiet "hermes-${servicio}.service" || fallar "El servicio hermes-$servicio no está activo. Revisa sudo journalctl -u hermes-$servicio -n 50."
    fi
done <<< "$HERMES_SERVICIOS"
.venv/bin/python -m aplicacion.comandos.configurar_instalacion --vincular-canales
# El ID del propietario se fija al autorizarlo; recargar los procesos que lo usan.
while read -r servicio habilitado; do
    if [[ "$habilitado" == true && "$servicio" =~ ^(telegram|monitoreo|tareas)$ ]]; then
        sudo systemctl restart "hermes-${servicio}.service"
    fi
done <<< "$HERMES_SERVICIOS"
printf '\nHermes instalado. API local: http://127.0.0.1:%s/documentacion\n' "$HERMES_PUERTO_API"
printf 'Estado: sudo systemctl status hermes-api\nRegistros: sudo journalctl -u hermes-telegram -f\n'
printf 'Conserva esta carpeta: los servicios se ejecutan desde ella.\n'
printf 'Falta registrar tus servidores y preparar sus claves SSH y hosts conocidos; consulta documentacion/instalacion_automatica.md.\n'
