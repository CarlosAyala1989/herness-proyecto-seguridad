#!/usr/bin/env bash
# El bloque completo se lee antes de ejecutar nada, también con curl | bash.
{
set -Eeuo pipefail
umask 077

hermes_error() { printf 'Error: %s\n' "$*" >&2; exit 1; }

hermes_instalar() {
    if [[ "${1:-}" == --help ]]; then
        cat <<'AYUDA'
Instalar Hermes desde Internet:
  curl -fsSL https://raw.githubusercontent.com/CarlosAyala1989/herness-proyecto-seguridad/main/instalar.sh | bash

Ubuntu 24.04 con systemd, usuario normal con sudo y terminal interactiva.
Descarga el programa en ~/.local/share/hermes y abre el asistente.
Opcionales: HERMES_DIRECTORIO_INSTALACION (ruta absoluta), HERMES_VERSION (rama, etiqueta o commit).
Desde un repositorio ya descargado: bash instalar.sh
AYUDA
        return 0
    fi
    [[ $# == 0 ]] || hermes_error 'Argumento desconocido. Usa --help.'
    [[ $EUID != 0 ]] || hermes_error 'Ejecuta el comando como usuario normal con sudo, sin anteponer sudo a bash.'
    [[ -t 1 ]] || hermes_error 'La instalación necesita una terminal interactiva.'
    # La entrada estándar contiene el script cuando se usa curl | bash.
    # Leer las respuestas desde la terminal, nunca desde el código descargado.
    if [[ ! -t 0 ]]; then
        if ! { exec </dev/tty; } 2>/dev/null; then
            hermes_error 'No hay terminal disponible para introducir las credenciales.'
        fi
    fi

    local archivo=${BASH_SOURCE[0]:-}
    local ruta_local
    if [[ -n "$archivo" && -f "$archivo" ]]; then
        ruta_local=$(cd -- "$(dirname -- "$archivo")" && pwd -P)
        if [[ -f "$ruta_local/pyproject.toml" && -f "$ruta_local/infraestructura/instalar_local.sh" ]]; then
            bash "$ruta_local/infraestructura/instalar_local.sh"
            return
        fi
    fi

    [[ -f /etc/os-release ]] || hermes_error 'No se pudo identificar el sistema operativo.'
    source /etc/os-release
    [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] || hermes_error 'El instalador admite Ubuntu 24.04.'
    [[ -d /run/systemd/system ]] || hermes_error 'Se requiere systemd en ejecución.'
    command -v sudo >/dev/null || hermes_error 'Se requiere un usuario autorizado para usar sudo.'

    local repositorio=https://github.com/CarlosAyala1989/herness-proyecto-seguridad.git
    local version=${HERMES_VERSION:-main}
    local destino=${HERMES_DIRECTORIO_INSTALACION:-$HOME/.local/share/hermes}
    [[ "$version" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]*$ && "$version" != *..* ]] || hermes_error 'La versión solicitada no es válida.'
    [[ "$destino" =~ ^/[a-zA-Z0-9_./-]+$ && "$destino" != / ]] || hermes_error 'Usa una ruta absoluta sin espacios ni caracteres especiales.'
    [[ ! -L "$destino" ]] || hermes_error 'La carpeta de instalación no puede ser un enlace simbólico.'
    mkdir -p -- "$(dirname -- "$destino")"
    destino="$(cd -- "$(dirname -- "$destino")" && pwd -P)/$(basename -- "$destino")"

    if ! command -v git >/dev/null; then
        sudo apt-get update
        sudo apt-get install -y git ca-certificates
    fi

    local descarga
    if [[ -e "$destino" ]]; then
        [[ -d "$destino/.git" ]] || hermes_error "La carpeta $destino ya existe y no es una instalación Git de Hermes."
        [[ "$(git -C "$destino" config --get remote.origin.url)" == "$repositorio" ]] || hermes_error 'La carpeta existente pertenece a otro repositorio.'
        [[ -z "$(git -C "$destino" status --porcelain --untracked-files=normal)" ]] || hermes_error 'Hay cambios locales en la instalación; consérvalos antes de actualizar.'
        descarga=$destino
    else
        HERMES_TEMPORAL=$(mktemp -d "$(dirname -- "$destino")/.hermes-descarga.XXXXXX")
        descarga=$HERMES_TEMPORAL
        git init --quiet "$descarga"
        git -C "$descarga" remote add origin "$repositorio"
    fi

    printf '\nDescargando Hermes (%s) desde GitHub…\n' "$version"
    GIT_TERMINAL_PROMPT=0 git -C "$descarga" fetch --depth=1 origin "$version"
    for requerido in infraestructura/instalar_local.sh pyproject.toml .env.ejemplo; do
        git -C "$descarga" cat-file -e "FETCH_HEAD:$requerido" || hermes_error 'La versión descargada no incluye el instalador completo de Hermes.'
    done

    # Las configuraciones son locales: una versión no debe convertirlas en código versionado.
    local reservada
    for reservada in .env .venv .secretos; do
        if git -C "$descarga" cat-file -e "FETCH_HEAD:$reservada" 2>/dev/null; then
            hermes_error "La versión descargada incluye la ruta local reservada $reservada."
        fi
    done

    local servicio unidad
    # Detener los procesos de esta carpeta antes de sustituir su código.
    for servicio in api telegram slack monitoreo tareas base-datos; do
        unidad="/etc/systemd/system/hermes-${servicio}.service"
        if [[ -f "$unidad" ]] && ! grep -Fxq "WorkingDirectory=$destino" "$unidad"; then
            hermes_error "Ya existe hermes-$servicio para otra carpeta."
        fi
    done
    for servicio in api telegram slack monitoreo tareas; do
        if [[ -f "/etc/systemd/system/hermes-${servicio}.service" ]]; then
            sudo systemctl stop "hermes-${servicio}.service"
        fi
    done
    git -C "$descarga" checkout --quiet --detach FETCH_HEAD
    if [[ "$descarga" != "$destino" ]]; then
        mv -T -- "$descarga" "$destino"
        HERMES_TEMPORAL=
    fi
    printf 'Código preparado en %s (commit %s).\n' "$destino" "$(git -C "$destino" rev-parse --short HEAD)"
    bash "$destino/infraestructura/instalar_local.sh"
}

HERMES_TEMPORAL=
trap 'if [[ -n "$HERMES_TEMPORAL" ]]; then rm -rf -- "$HERMES_TEMPORAL"; fi' EXIT
trap 'printf "La instalación se detuvo. Puedes repetir el mismo comando después de corregir el problema.\n" >&2' ERR
hermes_instalar "$@"
exit 0
}
