#!/bin/bash
# ===============================================
# Rueckgrat Linux Universal Installer
# Supports: Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE, etc.
# ===============================================

set -euo pipefail

trap 'echo "❌ Error: Error on line $LINENO"' ERR

PARAMETERS=$@

# print_header - Print centered bold header with top/bottom lines
# Usage: print_header "Title text"
# Args:
#   $1 - Header text
print_header() {
    local text="$1"
    local width=$(tput cols 2>/dev/null || echo 80)
    printf '\033[36m%*s\033[0m\n' "$width" '' | tr ' ' '_'
    echo ""
    printf '\033[1m%*s\033[0m\n' $(( (width + ${#text}) / 2 )) "$text"
    printf '\033[36m%*s\033[0m\n' "$width" '' | tr ' ' '_'
    echo ""
    print_info_block
}

# print_section - Print section separator line
# Usage: print_section
# No arguments
print_section() {
    local width=$(tput cols 2>/dev/null || echo 80)
    printf '\033[36m%*s\033[0m\n' "$width" '' | tr ' ' '_'
    echo ""
}

print_config_file_hint() {
    echo ""
    echo "💾 Saved config to $CONFIG_FILE"
    echo ""
    echo "💡 you can use this file for a quicker future install ie:"
    echo "   ./install -c my_config.json -y"
}

# read_tty - Read user input from tty, with default and YES-mode support
# Usage: read_tty <prompt> [default]
# Args:
#   $1 - Prompt text
#   $2 - Default value (optional)
#   $3 - yes mode. if true skip question and answer with default
# Returns: User input or default
read_tty() {
    local prompt="$1"
    local default="${2:-}"
    local yes_mode="${3:-false}"
    if [[ "$yes_mode" == true && -n "$default" ]]; then
        REPLY="$default"
        return
    fi
    local var
    read -p "$prompt" -r var </dev/tty
    REPLY="${var:-$default}"
}

# read_tty_s - like read_tty but with hidden output. used for passwords
# Usage: read_tty_s <prompt> [default]
# Args:
#   $1 - Prompt text
# Returns: User input or default
read_tty_s() {
    local prompt="$1"
    read -s -p "$prompt" -r REPLY </dev/tty
    echo ""
}

# version_ge - true if $1 >= $2 (dotted versions)
version_ge() {
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]
}

detect_gpu_backend() {
    local vendor=""
    local pci
    pci="$(lspci -nn 2>/dev/null || true)"

    GPU_INFO=$(lspci | grep -E 'VGA|3D|Display' | sed 's/.*: //' | xargs || echo 'None detected')
    NVIDIA_DRIVER=""
    NVIDIA_CUDA=""
    NVIDIA_COMPUTE_CAP=""
    TORCH_CUDA_INDEX=""
    TORCH_ROCM_INDEX=""

    if echo "$pci" | grep -qi '\[10de:' && { [ -e /dev/nvidia0 ] || command -v nvidia-smi >/dev/null; }; then
        vendor="nvidia"
    elif echo "$pci" | grep -qi '\[1002:' && [ -e /dev/kfd ]; then
        vendor="amd"
    elif echo "$pci" | grep -qiE '\[8086:.*(VGA|3D|Display)' && [ -e /dev/dri ]; then
        vendor="intel"
    elif echo "$pci" | grep -qi '\[10de:'; then
        vendor="nvidia"
    elif echo "$pci" | grep -qi '\[1002:'; then
        vendor="amd"
    elif echo "$pci" | grep -qiE '\[8086:.*(VGA|3D|Display)'; then
        vendor="intel"
    else
        vendor="cpu"
    fi

    case "$vendor" in
        nvidia) TORCH_BACKEND=cuda ;;
        amd)    TORCH_BACKEND=rocm ;;
        intel)  TORCH_BACKEND=xpu ;;
        *)      TORCH_BACKEND=cpu; vendor=cpu ;;
    esac

    if [ "$vendor" = "nvidia" ] && command -v nvidia-smi >/dev/null; then
        NVIDIA_DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1 | xargs)
        NVIDIA_CUDA=$(nvidia-smi | awk -F'CUDA Version: ' '/CUDA Version/ {print $2; exit}' | awk '{print $1}')
        NVIDIA_COMPUTE_CAP=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -n1 | xargs)
        case "$NVIDIA_CUDA" in
            12.8*|12.9*|13.*) TORCH_CUDA_INDEX=cu128 ;;
            12.6*|12.7*)      TORCH_CUDA_INDEX=cu126 ;;
            12.4*|12.5*)      TORCH_CUDA_INDEX=cu124 ;;
            12.[123]*)        TORCH_CUDA_INDEX=cu121 ;;
            11.*)             TORCH_CUDA_INDEX=cu118 ;;
            *)                TORCH_CUDA_INDEX=cu118 ;;
        esac
    fi

    if [ "$vendor" = "amd" ]; then
        local gfx=""
        # read the gfx target from the kernel driver (amdgpu/kfd), works without ROCm installed.
        # gfx_target_version is decimal major*10000 + minor*100 + stepping, e.g. 120000 = gfx1200, 100300 = gfx1030
        local v
        v=$(awk '/^gfx_target_version/ && $2 > 0 {print $2; exit}' /sys/class/kfd/kfd/topology/nodes/*/properties 2>/dev/null || true)
        if [ -n "$v" ]; then
            gfx=$(printf 'gfx%d%x%x' $((v / 10000)) $((v / 100 % 100)) $((v % 100)))
        elif command -v rocminfo >/dev/null; then
            gfx=$(rocminfo 2>/dev/null | awk '/Name: +gfx/{print $2; exit}')
        fi
        case "$gfx" in
            gfx120*) TORCH_ROCM_INDEX=rocm6.4 ;;
            gfx110*|gfx103*|gfx101*) TORCH_ROCM_INDEX=rocm6.3 ;;
            *) TORCH_ROCM_INDEX=rocm6.3 ;;
        esac
    fi

    GPU_VENDOR="$vendor"

    case "${GPU_VENDOR:-cpu}" in
        nvidia) LLAMA_SERVER_BACKEND=cuda ;;
        amd)    LLAMA_SERVER_BACKEND=rocm ;;
        intel)  LLAMA_SERVER_BACKEND=intel ;;
        *)      LLAMA_SERVER_BACKEND=cpu ;;
    esac
}

# check_llama_server_backend - fail if host cannot run official server-${backend} image
# Usage: check_llama_server_backend [backend]
check_llama_server_backend() {
    local backend="${1:-${LLAMA_SERVER_BACKEND:-cpu}}"
    local image="ghcr.io/ggml-org/llama.cpp:server-${backend}"

    case "$backend" in
        cuda)
            if ! command -v nvidia-smi >/dev/null; then
                echo "❌ Error: $image needs nvidia-smi (NVIDIA driver)"
                exit 1
            fi
            if [ ! -e /dev/nvidia0 ]; then
                echo "❌ Error: $image needs /dev/nvidia0"
                exit 1
            fi
            # official server-cuda is CUDA 12.8 → Linux driver >= 570
            if ! version_ge "${NVIDIA_DRIVER:-0}" "570"; then
                echo "❌ Error: $image needs NVIDIA driver >= 570 (host: ${NVIDIA_DRIVER:-unknown}, CUDA ${NVIDIA_CUDA:-unknown})"
                echo "   GeForce cannot use CUDA forward-compat. Upgrade the driver."
                exit 1
            fi
            if ! version_ge "${NVIDIA_CUDA:-0}" "12.8"; then
                echo "❌ Error: $image needs driver CUDA >= 12.8 (host nvidia-smi: ${NVIDIA_CUDA:-unknown})"
                exit 1
            fi
            if [ -n "${NVIDIA_COMPUTE_CAP:-}" ] && ! version_ge "$NVIDIA_COMPUTE_CAP" "7.5"; then
                echo "❌ Error: $image is not reliable on compute cap $NVIDIA_COMPUTE_CAP (need >= 7.5, Turing+)"
                exit 1
            fi
            ;;
        rocm)
            if [ ! -e /dev/kfd ]; then
                echo "❌ Error: $image needs AMD KFD (/dev/kfd)"
                exit 1
            fi
            ;;
        intel|sycl) # TODO intel was not tested
            if [ ! -e /dev/dri ]; then
                echo "❌ Error: $image needs /dev/dri"
                exit 1
            fi
            ;;
        cpu) ;;
        *)
            echo "❌ Error: unknown LLAMA_SERVER_BACKEND='$backend' (cuda|rocm|intel|cpu)"
            exit 1
            ;;
    esac
}

# get_info - collect some generall information
# Usage: get_info
# No arguments
get_info() {
    HOSTNAME=$(hostname)
    HOST_ADDR=$(hostname -I | awk '{print $1}')

    CPU_INFO=$(lscpu | grep 'Model name' | awk -F: '{print $2}' | xargs)
    

    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        DISTRO=${ID_LIKE:-$ID}
        
    else
        echo "❌ Error: failed to detect distro"
        exit 1
    fi

    RUECKGRAT_VERSION="unknown"
    if command -v git >/dev/null 2>&1; then    
        RUECKGRAT_VERSION=$(git describe --tags --abbrev=0 2>/dev/null) || true
    fi

    detect_gpu_backend
}

# print_info_block - printing info block
# Usage: print_info_block
# No arguments
print_info_block() {
    # remote runs (--local-config) have no git checkout, so no version to show
    if [[ -z "${LOCAL_CONFIG:-}" ]]; then
        echo "Rückgrat ver   ${RUECKGRAT_VERSION:----}"
        echo ""
    fi
    echo "Host           $HOSTNAME"
    echo "IP             $HOST_ADDR"
    echo "OS             $PRETTY_NAME"
    echo "CPU            $CPU_INFO"
    echo "GPU            $GPU_INFO"
    echo "GPU Vendor     $GPU_VENDOR"
    echo "Torch Backend  $TORCH_BACKEND"
    if [ "${GPU_VENDOR:-}" = "nvidia" ]; then
        echo "NVIDIA driver  ${NVIDIA_DRIVER:----}"
        echo "CUDA (driver)  ${NVIDIA_CUDA:----}"
        echo "Torch CUDA     ${TORCH_CUDA_INDEX:----}"
    fi

    if [ "${GPU_VENDOR:-}" = "amd" ]; then
        echo "Torch ROCM     ${TORCH_ROCM_INDEX:----}"
    fi

    echo ""
    echo "Current dir    $(pwd)"
    echo "Launched with  \"$(echo "$PARAMETERS" | sed -E 's/-p [^ ]+/-p ******/g')\""
}

# volume_cleanup - Check for and optionally remove existing Rueckgrat Docker resources
# Usage: volume_cleanup
# No arguments
volume_cleanup() {
    if command -v docker &> /dev/null; then
        ALL_CONTAINERS=$(docker ps -a -q --filter "name=rueckgrat" 2>/dev/null | wc -l) || {
            echo "❌ Error: Failed to query Docker (permission or daemon issue)" >&2
            exit 1
        }
        if [[ $ALL_CONTAINERS -gt 0 ]]; then
            CLEANUP=false
            if ! $YES; then
                print_section
                echo "Found existing Rueckgrat installation."
                echo ""
                echo "🐳 Container"
                echo "$(docker ps -a --filter "name=rueckgrat" --format "{{.Names}}" | sort | tr '\n' ' ')"
                echo ""
                echo "💾 Volumes"
                echo "$(docker volume ls --filter "name=rueckgrat" --format "{{.Name}}" | sort | tr '\n' ' ')"
                echo ""
                echo "📡 Networks"
                echo "$(docker network ls --filter "name=rueckgrat" --format "{{.Name}}" | sort | tr '\n' ' ')"
                echo ""

                read_tty "Keep previous installation (reuse volumes & containers)? (Y/n): " "Y" $YES
                if [[ "$REPLY" =~ ^[Nn]$ ]]; then
                    CLEANUP=true
                fi
            fi

            if $CLEAN_BUILD || $CLEANUP; then
                print_section
                echo "🗑️ Removing previous Rueckgrat installation..."
                docker stop $(docker ps -q --filter "name=rueckgrat") 2>/dev/null || true
                docker rm -f $(docker ps -a -q --filter "name=rueckgrat") 2>/dev/null || true
                docker volume rm $(docker volume ls -q --filter "name=rueckgrat") 2>/dev/null || true                
                echo "✅ Previous installation cleaned up."
            fi
        fi
    else
        install_docker
    fi
}

# package_available - Check if a package is available in distro-specific repos
# Usage: package_available <package>
# Args:
#   $1 - Package name to check
# Returns:
#   0 if available, 1 otherwise
package_available() {
    local package="$1"

    case "$DISTRO" in
        *debian*|*ubuntu*) apt-cache show "$package" >/dev/null 2>&1 ;;
        *fedora*|*rhel*|*centos*|*rocky*|*alma*) dnf list --available "$package" >/dev/null 2>&1 ;;
        *arch*) pacman -Si "$package" >/dev/null 2>&1 ;;
        *suse*|*opensuse*) zypper search --match-exact "$package" >/dev/null 2>&1 ;;
        *) echo "❌ Error: Unsupported distro $DISTRO"; exit 1 ;;
    esac
    return $?
}

# install_pkg - Install packages using distro-specific package manager
# Usage: install_pkg pkg1 [pkg2 ...]
# Args:
#   $@ - Package names to install
install_pkg() {
    case "$DISTRO" in
        *debian*|*ubuntu*) echo "$SUDO_PASSWORD" | sudo -S apt update -y && echo "$SUDO_PASSWORD" | sudo -S apt install -y "$@" ;;
        *fedora*|*rhel*|*centos*|*rocky*|*alma*) echo "$SUDO_PASSWORD" | sudo -S dnf install -y "$@" ;;
        *arch*) echo "$SUDO_PASSWORD" | sudo -S pacman -Syu --noconfirm "$@" ;;
        *suse*|*opensuse*) echo "$SUDO_PASSWORD" | sudo -S zypper install -y "$@" ;;
        *) echo "❌ Error: Unsupported distro. Install $@ manually."; exit 1 ;;
    esac
}

# Lookup table: package -> test command
declare -A pkg_check=(
    ["python3.13-venv"]="python3.13 -m venv --help &> /dev/null"
    ["build-essential"]="gcc --version &> /dev/null"
    ["python3.11-dev"]="python3.11-config --help &> /dev/null"    
)

# install_dependencies - Check and install missing packages
# Usage: install_dependencies pkg1 [pkg2 ...]
# Args:
#   $@ - List of package names to check/install
install_dependencies() {
    local deps=("$@")
    local missing_deps=()
    for pkg in "${deps[@]}"; do
        check="${pkg_check[$pkg]:-command -v $pkg &> /dev/null}"
        if ! eval "$check"; then
            missing_deps+=("$pkg")
        fi
    done

    if [ ${#missing_deps[@]} -gt 0 ]; then
        print_section
        echo "📦 detected missing dependencies: ${missing_deps[*]}"

        read_tty "Install dependencies? (Y/n): " "Y" $YES
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            install_pkg "${missing_deps[@]}"
            echo "✅ Dependencies installed."
        fi
    fi
}

# install_docker - Install Docker
# Usage: install_docker
# No arguments
install_docker() {
    if ! command -v docker &> /dev/null; then
        print_section
        echo "📦 detected missing docker"

        read_tty "Install docker? (Y/n): " "Y" $YES
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            curl -fsSL https://get.docker.com -o get-docker.sh
            echo "$SUDO_PASSWORD" | sudo -S sh get-docker.sh
            rm -f get-docker.sh
            echo "$SUDO_PASSWORD" | sudo -S usermod -aG docker "$SUDO_USER"
            echo "✅ Docker installed."
        else
            echo "⚠️ Warning: Aborted by user"
            exit 0
        fi
    fi

    if ! docker buildx version >/dev/null 2>&1; then
        echo "❌ Error: docker buildx not found"
        exit 1
    fi
}

# install_nvidia_toolkit - Host NVIDIA Container Toolkit for Docker
# Usage: install_nvidia_toolkit
# Expects GPU_VENDOR from detect_gpu_backend. No-op unless nvidia.
install_nvidia_toolkit() {
    [ "${GPU_VENDOR:-}" = "nvidia" ] || return 0

    if command -v nvidia-ctk >/dev/null \
        && command -v nvidia-container-cli >/dev/null \
        && nvidia-container-cli info >/dev/null 2>&1 \
        && docker run --rm --gpus all alpine ls /dev/nvidia0 >/dev/null 2>&1; then
            echo "✅ NVIDIA container toolkit already configured"
            return 0
    fi

    if ! command -v nvidia-smi >/dev/null 2>&1; then
        echo "❌ Error: NVIDIA GPU detected but nvidia-smi missing (install the driver first)"
        exit 1
    fi

    print_section
    echo "📦 NVIDIA GPU needs the container toolkit for Docker"

    read_tty "Install nvidia-container-toolkit? (Y/n): " "Y" $YES
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "⚠️ Warning: Aborted by user"
        exit 0
    fi

    local keyring=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    local list=/etc/apt/sources.list.d/nvidia-container-toolkit.list
    local tmp
    tmp="$(mktemp -d)"

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o "$tmp/key.asc"
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list -o "$tmp/list"

    gpg --batch --yes --dearmor -o "$tmp/keyring.gpg" "$tmp/key.asc"
    sed "s#deb https://#deb [signed-by=$keyring] https://#g" "$tmp/list" > "$tmp/list.signed"

    echo "$SUDO_PASSWORD" | sudo -S mkdir -p /usr/share/keyrings
    echo "$SUDO_PASSWORD" | sudo -S cp "$tmp/keyring.gpg" "$keyring"
    echo "$SUDO_PASSWORD" | sudo -S cp "$tmp/list.signed" "$list"
    echo "$SUDO_PASSWORD" | sudo -S chmod 644 "$keyring" "$list"
    rm -rf "$tmp"

    echo "$SUDO_PASSWORD" | sudo -S apt-get update
    install_dependencies nvidia-container-toolkit
    echo "$SUDO_PASSWORD" | sudo -S nvidia-ctk runtime configure --runtime=docker
    echo "$SUDO_PASSWORD" | sudo -S systemctl restart docker

    if docker info 2>/dev/null | grep -qiE 'Runtimes:.*nvidia'; then
        echo "✅ NVIDIA container toolkit installed"
    else
        echo "❌ Error: toolkit installed but Docker has no nvidia runtime"
        exit 1
    fi
}

# safe_rm_rf - Safely remove file/dir, using sudo only if needed
# Usage: safe_rm_rf <path>
# Args:
#   $1 - Path to remove
safe_rm_rf() {
    [[ -z "$1" || ! -e "$1" ]] && return
    echo "🗑️ $1"
    if [[ -w "$1" ]] || [[ -w "$(dirname "$1")" ]]; then
        rm -rf "$1"
    else
        echo "$SUDO_PASSWORD" | sudo -S rm -rf "$1"
    fi
}

# setup_repository - Setup or update Rueckgrat git repository
# Usage: setup_repository
# No arguments
setup_repository() {
    install_dependencies git

    print_section

    if [[ -d ".git" ]]; then
        echo "✅ Using existing repo on branch '$(git branch --show-current)'."
        git pull &> /dev/null || true
    elif [[ -d "Rueckgrat-install" ]]; then
        cd Rueckgrat-install
        echo "✅ Using existing repo on branch '$(git branch --show-current)'."
        git pull &> /dev/null || true
    else
        echo "📥 Cloning fresh copy..."
        git clone https://github.com/tanzfisch/Rueckgrat.git Rueckgrat-install
        cd Rueckgrat-install
    fi

    WORKING_DIR=$(pwd)

    write_default_env
}

service_json() {
  local type="$1" name="$2" port="$3"
  shift 3
  local extra=""
  while [ $# -gt 0 ]; do
    extra="${extra},\"$1\":\"$2\""
    shift 2
  done
  echo "{\"type\":\"$type\",\"name\":\"$name\",\"port\":$port$extra}"
}

module_json() {
  local type="$1" name="$2"
  shift 2
  local extra=""
  while [ $# -gt 0 ]; do
    extra="${extra},\"$1\":\"$2\""
    shift 2
  done
  echo "{\"type\":\"$type\",\"name\":\"$name\"$extra}"
}

# validate_ip - validates ip
# Usage: validate_ip 1.1.1.1
validate_ip() {
    local ip="$1"
    if [[ ! $ip =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        echo "❌ Error: invalid IP"
        exit 1
    fi
}

# setup - Interactively collect target hosts + per-host components, then the
# optional Cloudflare node (asked once, after all hosts)
# Supports json config file loading/saving 
# Usage: setup
setup() {
    print_section

    if [[ -n "${CONFIG_FILE:-}" ]]; then
        if jq . "$CONFIG_FILE" >/dev/null 2>&1; then
            echo "📂 found valid config at $CONFIG_FILE"

            mkdir -p "$WORKING_DIR/rueckgrat/config"
            cp -f "$CONFIG_FILE" "$WORKING_DIR/rueckgrat/config/infrastructure.json"
            CONFIG_FILE="$WORKING_DIR/rueckgrat/config/infrastructure.json"

            print_config_file_hint
        else
            echo "❌ Error: Failed to load config from $CONFIG_FILE"
            exit 1
        fi
        return
    fi

    echo "Select hosts and their configuration"

    local hosts_json='[]'
    local host_addr host_json services_json

    while true; do
        echo ""
        read_tty "Target host (IP/hostname, empty=done): " ""
        host_addr=$REPLY
        [[ -z "$host_addr" ]] && break

        validate_ip "$host_addr"

        select_components

        host_json=$(jq -n \
            --arg addr "$host_addr" \
            --arg models_dir "$HOST_MODELS_DIR" \
            '{addr: $addr, models_dir: $models_dir}')

        if $INSTALL_NODE; then
            services_json='[]'

            if $INSTALL_LLAMA; then
                services_json=$(jq \
                    --arg port       "$LLAMA_SERVER_PORT" \
                    --arg model      "$INSTALL_LLAMA_MODEL" \
                    --arg ctx        "$LLAMA_SERVER_MAX_CONTEXT" \
                    --arg gpu_layers "$LLAMA_SERVER_GPU_LAYERS" \
                    --arg flash_attn "$LLAMA_SERVER_FLASH_ATTN" \
                    --arg temp       "$LLAMA_SERVER_TEMP" \
                    --arg n_parallel "$LLAMA_SERVER_N_PARALLEL" \
                    --arg extra_args "$LLAMA_SERVER_EXTRA_ARGS" \
                    '. + [{
                        type: "text_to_text",
                        name: "llama_server",
                        port:        ($port       | tonumber),
                        model:       $model,
                        max_context: ($ctx        | tonumber),
                        gpu_layers:  ($gpu_layers | tonumber),
                        flash_attn:  $flash_attn,
                        temp:        ($temp       | tonumber),
                        n_parallel:  ($n_parallel | tonumber),
                        extra_args:  $extra_args
                    }]' <<< "$services_json")
            fi

            if $INSTALL_IMAGE_GEN; then
                services_json=$(jq '. + [{type: "text_to_image", name: "image_gen"}]' <<< "$services_json")
            fi

            if $INSTALL_TTS; then
                services_json=$(jq --arg model "$TTS_MODEL" \
                    '. + [{type: "text_to_speech", name: "tts", model: $model}]' <<< "$services_json")
            fi

            if $INSTALL_STT; then
                services_json=$(jq '. + [{type: "speech_to_text", name: "stt"}]' <<< "$services_json")
            fi

            if $INSTALL_EMBEDDING; then
                services_json=$(jq '. + [{type: "text_to_embedding", name: "embedding"}]' <<< "$services_json")
            fi

            if $INSTALL_DECISION; then
                services_json=$(jq '. + [{type: "text_to_decision", name: "decision"}]' <<< "$services_json")
            fi

            host_json=$(jq \
                --arg port "$NODE_PORT" \
                --argjson services "$services_json" \
                '. + {node: {port: ($port | tonumber), services: $services}}' <<< "$host_json")
        fi

        if $INSTALL_HUB; then
            host_json=$(jq --arg port "$HUB_PORT" --arg signup_mode "$SIGNUP_MODE" \
                '. + {hub: {port: ($port | tonumber), signup_mode: $signup_mode}}' <<< "$host_json")
        fi

        if $INSTALL_CHAT; then
            host_json=$(jq '. + {chat: {}}' <<< "$host_json")
        fi

        hosts_json=$(jq --argjson host "$host_json" '. + [$host]' <<< "$hosts_json")
    done

    local cloudflare_json users_json
    select_cloudflare "$hosts_json"
    cloudflare_json="$CLOUDFLARE_JSON"

    select_default_users
    users_json="$USERS_JSON"

    select_chat_apk

    CONFIG_FILE="$WORKING_DIR/rueckgrat/config/infrastructure.json"
    jq --argjson cloudflare "$cloudflare_json" --argjson users "$users_json" --argjson chat_apk "$CHAT_APK" \
        '{hosts: ., cloudflare: $cloudflare, users: $users, chat_apk: $chat_apk}' <<< "$hosts_json" > "$CONFIG_FILE"
    print_config_file_hint
}

# select_default_users - Ask once whether default users should be created on the hub.
# They're saved in the config, so a reinstall from it recreates them without asking.
# Usage: select_default_users
# Sets: USERS_JSON (the "users" list for the config file), e.g. [{"name":"martin","email":null}]
select_default_users() {
    local name email
    USERS_JSON='[]'

    echo ""
    read_tty "Would you like some default users? (y/N): " "n"
    if ! [[ "$REPLY" =~ ^[Yy]$ ]]; then
        return
    fi

    while true; do
        read_tty "     User name (empty=done): " ""
        name="$REPLY"
        [[ -z "$name" ]] && break
        read_tty "     Email for $name (optional): " ""
        email="$REPLY"
        # empty email -> null in the JSON
        USERS_JSON=$(jq -c --arg name "$name" --arg email "$email" \
            '. + [{name: $name, email: (if $email == "" then null else $email end)}]' <<< "$USERS_JSON")
    done
}

# select_chat_apk - Ask once whether an Android APK of the chat client should be built.
# Saved in the config as "chat_apk", so a reinstall from it (-c) builds it again without asking.
# Usage: select_chat_apk
# Sets: CHAT_APK (true or false)
select_chat_apk() {
    CHAT_APK=false

    echo ""
    read_tty "Would you like to build an Android APK for the chat client? (y/N): " "n"
    [[ "$REPLY" =~ ^[Yy]$ ]] && CHAT_APK=true
    echo -e "\e[1A\e[K [$( [[ $CHAT_APK == true ]] && echo '✅' || echo '⚫' )] Android APK (chat client)"
}

# select_cloudflare - Ask once whether a Cloudflare node (cloudflared) is wanted,
# where it goes and which tunnel token it uses
# Token: asked here and saved in the config (never read from rueckgrat/.env)
# Usage: select_cloudflare '<hosts json>'
# Sets: CLOUDFLARE_JSON (the "cloudflare" block for the config file)
select_cloudflare() {
    local hosts_json="$1"
    local hub_addr hub_port cf_addr token
    CLOUDFLARE_JSON='{"enabled": false}'

    hub_addr=$(jq -r '[.[] | select(.hub)][0].addr // empty' <<< "$hosts_json")
    hub_port=$(jq -r '[.[] | select(.hub)][0].hub.port // empty' <<< "$hosts_json")
    hub_port="${hub_port:-$HUB_PORT_DEFAULT}"

    echo ""
    read_tty "Would you also like a Cloudflare node (tunnel to the hub)? (y/N): " "n"
    if ! [[ "$REPLY" =~ ^[Yy]$ ]]; then
        echo -e "\e[1A\e[K [⚫] Cloudflare"
        return
    fi
    if [[ -z "$hub_addr" ]]; then
        echo "⚠️ Warning: no hub selected, Cloudflare node skipped"
        return
    fi
    echo -e "\e[1A\e[K [✅] Cloudflare"

    # no default: cloudflared is meant for its own machine, not the hub
    while true; do
        read_tty "Cloudflare node IP: " ""
        [[ -n "$REPLY" ]] && break
        echo -e "\e[1A\e[K     ⚠️ please enter the IP of the Cloudflare node"
    done
    cf_addr="$REPLY"
    validate_ip "$cf_addr"
    echo -e "\e[1A\e[K     IP: $cf_addr"

    read_tty_s "     Cloudflare tunnel token (empty = no tunnel): "
    token="$REPLY"
    if [[ -z "$token" ]]; then
        echo "     no token, no tunnel"
        return
    fi
    # the input is hidden, so confirm that something arrived without showing it
    echo -e "\e[1A\e[K     Cloudflare tunnel token: ******** (${#token} characters)"

    CLOUDFLARE_JSON=$(jq -nc --arg addr "$cf_addr" --arg hub_addr "$hub_addr" --arg hub_port "$hub_port" --arg token "$token" \
        '{enabled: true, addr: $addr, hub_addr: $hub_addr, hub_port: ($hub_port | tonumber), token: $token}')
}

# select_tts_model - Ask which Chatterbox model the TTS node of this host uses.
# Saved in the host's tts service as "model", so a reinstall from the config (-c) uses it again.
# Configs from before this option have no "model" there -> chatterbox (English)
# Usage: select_tts_model
# Sets: TTS_MODEL (registry name: chatterbox or chatterbox_multilingual)
select_tts_model() {
    TTS_MODEL="chatterbox_multilingual"

    # same index style as the llm selection, 1 (english) is the default
    echo "         1) chatterbox (English only)"
    echo "         2) ⭐ chatterbox_multilingual (23 languages)"
    while true; do
        read_tty "         📋 Select tts model by index [2]: " "2" $YES
        [[ "$REPLY" == "1" || "$REPLY" == "2" ]] && break
        echo -e "\e[1A\e[K         ⚠️ please answer 1 or 2"
    done
    [[ "$REPLY" == "2" ]] && TTS_MODEL="chatterbox_multilingual"
    echo -e "\e[1A\e[K         Model: $TTS_MODEL"
}

# select_components - Prompt user for which components to install
# Usage: select_components
# Sets: INSTALL_CHAT, INSTALL_HUB, INSTALL_NODE, INSTALL_LLAMA
select_components() {
    INSTALL_CHAT=false;
    INSTALL_HUB=false;
    INSTALL_NODE=false
    INSTALL_LLAMA=false; 
    INSTALL_LLAMA_MODEL=""
    INSTALL_IMAGE_GEN=false
    INSTALL_TTS=false
    TTS_MODEL="chatterbox_multilingual"
    INSTALL_STT=false
    INSTALL_EMBEDDING=false
    INSTALL_DECISION=false
    REGISTRY_JSON="${REGISTRY_JSON:-$WORKING_DIR/rueckgrat/node/data/registry.json}"

    echo "Select components:"
    echo ""

    read_tty "Install native chat client? (Y/n): " "Y"
    [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_CHAT=true
    echo -e "\e[1A\e[K [$( [[ $INSTALL_CHAT == true ]] && echo '✅' || echo '⚫' )] Native Chat Client"

    read_tty "Install Hub? (Y/n): " "Y"
    [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_HUB=true
    echo -e "\e[1A\e[K [$( [[ $INSTALL_HUB == true ]] && echo '✅' || echo '⚫' )] Hub"
    if [[ "$INSTALL_HUB" == true ]]; then
        read_tty "Hub port? [$HUB_PORT_DEFAULT]: " "$HUB_PORT_DEFAULT" $YES
        HUB_PORT=$REPLY
        echo -e "\e[1A\e[K     Port: $HUB_PORT"
        while true; do
            read_tty "Signup mode, open or invite? [$SIGNUP_MODE_DEFAULT]: " "$SIGNUP_MODE_DEFAULT" $YES
            [[ "$REPLY" == "open" || "$REPLY" == "invite" ]] && break
            echo -e "\e[1A\e[K     ⚠️ please answer open or invite"
        done
        SIGNUP_MODE=$REPLY
        echo -e "\e[1A\e[K     Signup: $SIGNUP_MODE"
    fi

    read_tty "Install Node? (Y/n): " "Y"
    [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_NODE=true
    echo -e "\e[1A\e[K [$( [[ $INSTALL_NODE == true ]] && echo '✅' || echo '⚫' )] Node"
    if $INSTALL_NODE; then
        read_tty "Node port? [$NODE_PORT_DEFAULT]: " "$NODE_PORT_DEFAULT" $YES
        NODE_PORT=$REPLY
        echo -e "\e[1A\e[K     Port: $NODE_PORT"

        read_tty "Install llama-server on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_LLAMA=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_LLAMA == true ]] && echo '✅' || echo '⚫' )] llama-server"
        if $INSTALL_LLAMA; then
            read_tty "llama-server port? [$LLAMA_SERVER_PORT_DEFAULT]: " "$LLAMA_SERVER_PORT_DEFAULT" $YES
            LLAMA_SERVER_PORT=$REPLY
            echo -e "\e[1A\e[K         Port: $LLAMA_SERVER_PORT"
            # your model selection code here (multi-line, no overwrite)
            DEFAULT_LLM="cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L"            
            TYPE="llm"
            mapfile -t models < <(jq -r --arg t "$TYPE" 'to_entries[] | select(.value.type == $t) | .key' "$REGISTRY_JSON")
            DEFAULT_IDX=0
            for i in "${!models[@]}"; do
                if [[ "${models[i]}" == "$DEFAULT_LLM" ]]; then DEFAULT_IDX=$((i+1)); break; fi
            done
            for i in "${!models[@]}"; do
                if [ "$i" -eq "$((DEFAULT_IDX - 1))" ]; then echo "         $((i+1))) ⭐ ${models[i]}"; else echo "         $((i+1))) ${models[i]}"; fi
            done
            read_tty "         📋 Select model by index [$DEFAULT_IDX]: " "$DEFAULT_IDX"
            idx=$REPLY
            INSTALL_LLAMA_MODEL="${models[idx-1]}"

            eval "$(jq -r --arg k "$INSTALL_LLAMA_MODEL" --arg np "$LLAMA_SERVER_N_PARALLEL_DEFAULT" --arg mc "$LLAMA_SERVER_MAX_CONTEXT_DEFAULT" --arg gl "$LLAMA_SERVER_GPU_LAYERS_DEFAULT" --arg fa "$LLAMA_SERVER_FLASH_ATTN_DEFAULT" --arg tp "$LLAMA_SERVER_TEMP_DEFAULT" '
            .[$k].llama // {} | [
                "LLAMA_SERVER_MAX_CONTEXT=\(.max_context // $mc | @sh)",
                "LLAMA_SERVER_GPU_LAYERS=\(.gpu_layers // $gl | @sh)",
                "LLAMA_SERVER_FLASH_ATTN=\(.flash_attn // $fa | @sh)",
                "LLAMA_SERVER_TEMP=\(.temp // $tp | @sh)",
                "LLAMA_SERVER_N_PARALLEL=\(.n_parallel // $np | @sh)",
                "LLAMA_SERVER_EXTRA_ARGS=\(.extra_args // "" | @sh)"
            ] | join("\n")
            ' "$REGISTRY_JSON")"

            echo -e "         Selected model: $INSTALL_LLAMA_MODEL"
        fi

        read_tty "Install image generation on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_IMAGE_GEN=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_IMAGE_GEN == true ]] && echo '✅' || echo '⚫' )] ImageGen"

        read_tty "Install text to speech (Chatterbox) on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_TTS=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_TTS == true ]] && echo '✅' || echo '⚫' )] TTS"
        if $INSTALL_TTS; then
            select_tts_model
        fi

        read_tty "Install speech to text (faster-whisper) on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_STT=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_STT == true ]] && echo '✅' || echo '⚫' )] STT"

        read_tty "Install text embeddings (memory search) on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_EMBEDDING=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_EMBEDDING == true ]] && echo '✅' || echo '⚫' )] Embedding"

        read_tty "Install decision model (Laya, experimental, needs torch) on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_DECISION=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_DECISION == true ]] && echo '✅' || echo '⚫' )] Decision"
    fi

    read_tty "Models folder? [$HOST_MODELS_DIR_DEFAULT]: " "$HOST_MODELS_DIR_DEFAULT" $YES
    HOST_MODELS_DIR="$REPLY"
    echo -e "\e[1A\e[K     Models: $HOST_MODELS_DIR"
}

_format_host_jq='
  "\nHost: \($h.addr)",
  "  "+(if $h.chat then "[✅]" else "[⚫]" end)+" Native Chat Client",
  "  "+(if $h.hub then "[✅]" else "[⚫]" end)+" Hub"+(if $h.hub.signup_mode then " (signup: \($h.hub.signup_mode))" else "" end),
  "  "+(if $h.node then "[✅]" else "[⚫]" end)+" Node",
  "  "+($h.node.services[]? | "    [✅] \(.name)" + (if .name == "tts" then " (\(.model // "chatterbox"))" else "" end)),
  "  "+($h.node.modules[]? | "    [✅] \(.name)")
'

format_hosts() {
    if [[ -z "${CONFIG_FILE:-}" ]] || ! jq . "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "❌ Error: Invalid config" >&2
        return 1
    fi

    jq -r ".hosts[] as \$h | $_format_host_jq" "$CONFIG_FILE"
}

format_host() {
    local host="${1:-}"
    if [[ -z "${CONFIG_FILE:-}" ]] || ! jq . "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "❌ Error: Invalid config" >&2
        return 1
    fi

    if [[ -z "$host" ]]; then
        echo "❌ Error: No host specified" >&2
        return 1
    fi

    jq -r --arg host "$host" ".hosts[] | select(.addr == \$host) as \$h | $_format_host_jq" "$CONFIG_FILE"
}

# confirm_install_configuration - Print full multi-host installation plan and ask for final confirmation
# Usage: confirm_install_configuration
# Exits if no components selected or user aborts
confirm_install_configuration() {
    print_section
    echo "Installation plan:"

    format_hosts
    jq -r 'if .cloudflare.enabled == true
           then "\nCloudflare: [✅] cloudflared on \(.cloudflare.addr) -> hub \(.cloudflare.hub_addr):\(.cloudflare.hub_port)"
           else "\nCloudflare: [⚫]" end' "$CONFIG_FILE"
    # configs from before this option have no "chat_apk" key -> false
    jq -r 'if (.chat_apk // false) == true
           then "Android APK: [✅] chat client, built on this machine"
           else "Android APK: [⚫]" end' "$CONFIG_FILE"

    echo ""
    read_tty "Execute this plan? (Y/n): " "Y" $YES
    if ! [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "⚠️ Warning: Aborted by user"
        exit 0
    fi
}

# deploy_hub - Build and start Hub + Caddy containers
# Usage: deploy_hub
# No arguments
deploy_hub() {
    print_section
    echo "🐋 hub & caddy..."

    set_env_value HOST_MODELS_DIR "$HOST_MODELS_DIR"
    set_env_value SIGNUP_MODE "${SIGNUP_MODE:-$SIGNUP_MODE_DEFAULT}"
    set_env_value HUB_PORT "${HUB_PORT:-$HUB_PORT_DEFAULT}"

    echo "   signup mode  ${SIGNUP_MODE:-$SIGNUP_MODE_DEFAULT}"
    echo "   port         ${HUB_PORT:-$HUB_PORT_DEFAULT}"

    pushd rueckgrat > /dev/null
    docker compose stop hub caddy 2>/dev/null || true
    docker compose build ${DOCKER_QUIET_BUILD:-} ${NO_CACHE:-} hub caddy || { echo "❌ Error: Docker compose build of hub & cdaddy failed."; popd; exit 1; }
    docker compose up -d hub caddy || { echo "❌ Error: Docker compose up of hub & cdaddy failed."; popd; exit 1; }
    popd > /dev/null

    seed_default_users
}

# seed_default_users - After a fresh (-f) hub deploy the database is empty, so create
# the "users" from the config one by one with hub_management.
# Usage: seed_default_users
seed_default_users() {
    $CLEAN_BUILD || return 0

    # CONFIG_FILE is set by setup and dev.sh; a remote install (--local-config) only has
    # the rsynced copy in the working dir
    local config="${CONFIG_FILE:-$WORKING_DIR/rueckgrat/config/infrastructure.json}"
    [[ -f "$config" ]] || return 0

    local names name i
    mapfile -t names < <(jq -r '.users // [] | .[].name // empty' "$config")
    [[ ${#names[@]} -gt 0 ]] || return 0

    print_section
    echo "👤 default users..."

    # give the freshly started container a moment before docker exec
    for i in $(seq 1 30); do
        docker exec rueckgrat_hub true 2>/dev/null && break
        sleep 1
    done

    for name in "${names[@]}"; do
        docker exec rueckgrat_hub python -m app.hub_management user create "$name" \
            || echo "⚠️ Warning: could not create user $name"
    done
}

# gen_caddy_cert - generate caddy certificate
# Usage: gen_caddy_cert
# No arguments
gen_caddy_cert() {
    print_section
    echo "🔑 handling caddy certificate..."
    echo ""
    CADDY_DIR="$WORKING_DIR/rueckgrat/caddy"
    mkdir -p "$CADDY_DIR"

    CADDY_KEY="$CADDY_DIR/rueckgrat-caddy.key"
    CADDY_CERT="$CADDY_DIR/rueckgrat-caddy.cert"

    if [ -n "$KEY_FILE" ] && [ -n "$CERT_FILE" ]; then
        cp $KEY_FILE $CADDY_KEY
        cp $CERT_FILE $CADDY_CERT
        echo "using provided key/cert pair"
    else
        if [ ! -f "$CADDY_KEY" ] || [ ! -f "$CADDY_CERT" ]; then
            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$CADDY_KEY" -out "$CADDY_CERT" -subj "/CN=rueckgrat.hub" \
            -addext "subjectAltName = DNS:rueckgrat.hub,DNS:localhost,IP:192.168.2.39"
            echo "generated new key/cert pair"
        else
            echo "use existing key/cert pair"
        fi
    fi
    echo "key: $CADDY_KEY"
    echo "crt: $CADDY_CERT"
}

# deploy_node - Build and start Node container
# Usage: deploy_node
# No arguments
deploy_node() {
    print_section
    echo "🐋 node..."

    set_env_value HOST_MODELS_DIR "$HOST_MODELS_DIR"
    set_env_value NODE_PORT "${NODE_PORT:-$NODE_PORT_DEFAULT}"
    set_env_value TTS_MODEL "${TTS_MODEL:-chatterbox}"

    BUILD_ARGS=()
    COMPOSE_FILES=(-f compose.yml)

    if [ "$INSTALL_IMAGE_GEN" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_IMAGE_GEN=true)
    fi

    if [ "$INSTALL_TTS" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_TTS=true)
    fi

    if [ "$INSTALL_STT" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_STT=true)
    fi

    if [ "$INSTALL_EMBEDDING" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_EMBEDDING=true)
    fi

    if [ "$INSTALL_DECISION" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_DECISION=true)
    fi

    if [[ "$INSTALL_IMAGE_GEN" == true || "$INSTALL_TTS" == true || "$INSTALL_DECISION" == true ]]; then
        BUILD_ARGS+=(--build-arg "TORCH_BACKEND=${TORCH_BACKEND:-cpu}")
        BUILD_ARGS+=(--build-arg "TORCH_CUDA_INDEX=${TORCH_CUDA_INDEX:-cu128}")
        BUILD_ARGS+=(--build-arg "TORCH_ROCM_INDEX=${TORCH_ROCM_INDEX:-rocm6.3}")
    fi

    if [ "$INSTALL_LLAMA" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_LLAMA=true)
    fi

    case "${GPU_VENDOR:-cpu}" in
        amd)
            COMPOSE_FILES+=(-f compose.amd.yml)
            HOST_AMD_VIDEO=$(getent group video | cut -d: -f3)
            HOST_AMD_RENDER=$(getent group render | cut -d: -f3)
            [ -n "$HOST_AMD_VIDEO" ] && [ -n "$HOST_AMD_RENDER" ] \
              || { echo "❌ Error: host video/render GIDs not found"; exit 1; }
            export HOST_AMD_VIDEO HOST_AMD_RENDER
            ;;
        nvidia) COMPOSE_FILES+=(-f compose.nvidia.yml) ;;
    esac

    echo "   port        ${NODE_PORT:-$NODE_PORT_DEFAULT}"
    [ "$INSTALL_TTS" = true ] && echo "   tts_model   ${TTS_MODEL:-chatterbox}"
    echo "   vendor      ${GPU_VENDOR:-cpu}"
    echo "   backend     ${TORCH_BACKEND:-cpu}"
    echo "   cuda_index  ${TORCH_CUDA_INDEX:-n/a}"
    echo "   compose     ${COMPOSE_FILES[*]}"
    echo "   build_args  ${BUILD_ARGS[*]:-none}"
    [ "${GPU_VENDOR:-}" = "amd" ] && echo "   amd_gids=video:$HOST_AMD_VIDEO render:$HOST_AMD_RENDER"

    pushd rueckgrat > /dev/null
    if [ "${GPU_VENDOR:-}" = "amd" ]; then
        set_env_value HOST_AMD_VIDEO "$HOST_AMD_VIDEO"
        set_env_value HOST_AMD_RENDER "$HOST_AMD_RENDER"
    fi

    docker compose "${COMPOSE_FILES[@]}" stop node 2>/dev/null || true
    docker compose "${COMPOSE_FILES[@]}" \
        build ${DOCKER_QUIET_BUILD:-} ${NO_CACHE:-} "${BUILD_ARGS[@]}" node \
        || { echo "❌ Error: Docker compose build of node failed."; popd; exit 1; }
    docker compose "${COMPOSE_FILES[@]}" up -d node \
        || { echo "❌ Error: Docker compose up of node failed."; popd; exit 1; }
    popd > /dev/null
}

# deploy_cloudflared - Start the Cloudflare tunnel container (cloudflared) on this host
# Forwards to the hub under the hub's default hostname (HUB_HOST, rueckgrat.hub) and port
# Usage: deploy_cloudflared
# Uses: CLOUDFLARE_TUNNEL_TOKEN (from the host config), CLOUDFLARE_HUB_ADDR, CLOUDFLARE_HUB_PORT
deploy_cloudflared() {
    print_section
    echo "🐋 cloudflared..."

    local token="${CLOUDFLARE_TUNNEL_TOKEN:-}"
    [[ -n "$token" ]] || { echo "❌ Error: no Cloudflare tunnel token in the host config"; exit 1; }

    # inside the container 127.0.0.1 is the container itself, so a hub on this
    # same machine is reached through the docker host gateway instead
    local hub_addr="${CLOUDFLARE_HUB_ADDR:-}"
    if [[ -z "$hub_addr" ]] || is_local_host "$hub_addr"; then
        hub_addr="host-gateway"
    fi

    set_env_value CLOUDFLARE_TUNNEL_TOKEN "$token"
    set_env_value CLOUDFLARE_HUB_ADDR "$hub_addr"

    echo "   hub          rueckgrat.hub -> $hub_addr"
    echo "   port         ${CLOUDFLARE_HUB_PORT:-$HUB_PORT_DEFAULT}"

    pushd rueckgrat > /dev/null
    # --no-deps: don't pull caddy/hub onto this machine just because of depends_on
    docker compose --profile cloudflare up -d --no-deps cloudflared \
        || { echo "❌ Error: Docker compose up of cloudflared failed."; popd; exit 1; }
    popd > /dev/null
}

# set_env_value - Set or replace KEY=VALUE in a .env file
# Usage: set_env_value <key> <value> [file]
# Args:
#   $1 - Key
#   $2 - Value
#   $3 - File (default: .env)
set_env_value() {
    local key="$1"
    local value="$2"
    local file="${3:-$WORKING_DIR/rueckgrat/.env}"
    mkdir -p "$(dirname "$file")"
    touch "$file"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        # make sure the last line is terminated before appending
        if [ -s "$file" ] && [ -n "$(tail -c1 "$file")" ]; then
            echo >> "$file"
        fi
        echo "${key}=${value}" >> "$file"
    fi
}

# deploy_llama - Download/select LLM model and start llama-server
# Usage: deploy_llama "model name"
# Args:
#   $1 - model name
deploy_llama() {
    local LLM_MODEL="$1"

    print_section
    echo "🐋 llama-server..."
    echo "running $LLM_MODEL on $LLAMA_SERVER_BACKEND"

    set_env_value HOST_MODELS_DIR "$HOST_MODELS_DIR"

    check_llama_server_backend "$LLAMA_SERVER_BACKEND"

    COMPOSE_FILES=(-f compose.yml)
    case "${GPU_VENDOR:-cpu}" in
        amd)
            COMPOSE_FILES+=(-f compose.amd.yml)
            HOST_AMD_VIDEO=$(getent group video | cut -d: -f3)
            HOST_AMD_RENDER=$(getent group render | cut -d: -f3)
            [ -n "$HOST_AMD_VIDEO" ] && [ -n "$HOST_AMD_RENDER" ] \
              || { echo "❌ Error: host video/render GIDs not found"; exit 1; }
            export HOST_AMD_VIDEO HOST_AMD_RENDER
            ;;
        nvidia) COMPOSE_FILES+=(-f compose.nvidia.yml) ;;
    esac

    echo "   vendor=${GPU_VENDOR:-cpu} backend=$LLAMA_SERVER_BACKEND"
    echo "   compose=${COMPOSE_FILES[*]}"
    [ "${GPU_VENDOR:-}" = "amd" ] && echo "   amd_gids=video:$HOST_AMD_VIDEO render:$HOST_AMD_RENDER"

    set_env_value LLAMA_SERVER_MAX_CONTEXT "${LLAMA_SERVER_MAX_CONTEXT}"
    set_env_value LLAMA_SERVER_GPU_LAYERS "${LLAMA_SERVER_GPU_LAYERS}"
    set_env_value LLAMA_SERVER_FLASH_ATTN "${LLAMA_SERVER_FLASH_ATTN}"
    set_env_value LLAMA_SERVER_TEMP "${LLAMA_SERVER_TEMP}"
    set_env_value LLAMA_SERVER_N_PARALLEL "${LLAMA_SERVER_N_PARALLEL}"
    set_env_value LLAMA_SERVER_EXTRA_ARGS "${LLAMA_SERVER_EXTRA_ARGS}"

    pushd rueckgrat > /dev/null
    set_env_value LLAMA_SERVER_MODEL "$LLAMA_SERVER_MODEL"
    
    set_env_value LLAMA_SERVER_BACKEND "$LLAMA_SERVER_BACKEND"
    if [ "${GPU_VENDOR:-}" = "amd" ]; then
        set_env_value HOST_AMD_VIDEO "$HOST_AMD_VIDEO"
        set_env_value HOST_AMD_RENDER "$HOST_AMD_RENDER"
    fi    

    docker compose "${COMPOSE_FILES[@]}" stop llama-server 2>/dev/null || true
    docker compose "${COMPOSE_FILES[@]}" build ${DOCKER_QUIET_BUILD:-} ${NO_CACHE:-} llama-server || { echo "❌ Error: Docker compose build of llama-server failed."; popd; exit 1; }
    docker compose "${COMPOSE_FILES[@]}" up -d llama-server || { echo "❌ Error: Docker compose up of llama-server failed."; popd; exit 1; }
    popd > /dev/null
}

# deploy_chat_native - Install Chat (Native)
# Usage: deploy_chat_native
# No arguments
deploy_chat_native() {
    install_dependencies python3 python3.13-venv alsa-utils libportaudio2 portaudio19-dev

    print_section
    echo "📦 chat..."

    pushd rueckgrat/chat > /dev/null

    CERT_NAME="rueckgrat-caddy.cert"
    CERT_DEST_SSH="$HOME/.ssh/$CERT_NAME"
    CERT_DEST_ASSETS="$PWD/assets/$CERT_NAME"

    mkdir -p "$HOME/.ssh" assets

    if [[ -n "${CADDY_CERT:-}" ]]; then
        echo "🔑 Installing certificate from: $CADDY_CERT"
        cp -f "$CADDY_CERT" "$CERT_DEST_SSH"
        cp -f "$CADDY_CERT" "$CERT_DEST_ASSETS"
        chmod 644 "$CERT_DEST_SSH" "$CERT_DEST_ASSETS"
        echo "✅ Certificate installed to $CERT_DEST_SSH and $CERT_DEST_ASSETS"
    elif [[ -f "$CERT_DEST_SSH" ]]; then
        echo "⚠️ Warning: Using existing certificate: $CERT_DEST_SSH"
        cp -f "$CERT_DEST_SSH" "$CERT_DEST_ASSETS"
        chmod 644 "$CERT_DEST_ASSETS"
    elif [[ -f "$CERT_DEST_ASSETS" ]]; then
        echo "⚠️ Warning: Using existing certificate: $CERT_DEST_ASSETS"
        cp -f "$CERT_DEST_ASSETS" "$CERT_DEST_SSH"
        chmod 644 "$CERT_DEST_SSH"
    else
        echo "❌ Error: No certificate path provided and neither $CERT_DEST_SSH nor $CERT_DEST_ASSETS found."
        popd > /dev/null
        exit 1
    fi

    [ -x .venv/bin/python ] || { rm -rf .venv; python3 -m venv .venv; }
    source .venv/bin/activate
    .venv/bin/python -m pip install -r requirements_desktop.txt

    popd > /dev/null
}

# build_chat_apk - Build the Android APK of the chat client on this machine, if the
# config says so ("chat_apk": true). Old configs without the key count as false.
# flet build downloads Flutter, a JDK and the Android SDK itself the first time (several GB).
# Usage: build_chat_apk [force]
# Args:
#   $1 - force: "true" builds without looking at the config at all (used by --apk)
# Returns: 1 if the build failed (the normal install flow ignores that, the hosts are deployed already)
# Output: $WORKING_DIR/dist/rueckgrat-chat-<tag>.apk when HEAD is exactly on the latest tag,
#         otherwise rueckgrat-chat-<tag>-<hash>.apk (without a tag just -<hash>,
#         outside a git checkout plain rueckgrat-chat.apk)
build_chat_apk() {
    local force="${1:-false}"
    if [[ "$force" != true ]]; then
        [[ "$(jq -r '.chat_apk // false' "$CONFIG_FILE")" == "true" ]] || return 0
    fi

    # only ask for the sudo password if something has to be installed
    if ! command -v python3 &> /dev/null || ! eval "${pkg_check[python3.13-venv]}"; then
        get_user_passwd
    fi
    install_dependencies python3 python3.13-venv

    print_section
    echo "📱 chat apk..."

    local chat_dir="$WORKING_DIR/rueckgrat/chat"
    local apk_src="$chat_dir/build/apk/chat.apk"
    local apk_version=""
    if git -C "$WORKING_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null | grep -qx master && \
    git -C "$WORKING_DIR" describe --tags --exact-match HEAD &>/dev/null; then
        local git_tag
        git_tag="$(git -C "$WORKING_DIR" describe --tags --abbrev=0 2>/dev/null || true)"
        [[ -n "$git_tag" ]] && apk_version+="-$git_tag"
    else
        local git_hash
        git_hash="$(git -C "$WORKING_DIR" rev-parse --short HEAD 2>/dev/null || true)"
        [[ -n "$git_hash" ]] && apk_version+="-$git_hash"
    fi
    local apk_dest="$WORKING_DIR/dist/rueckgrat-chat${apk_version}.apk"
    local cert="$WORKING_DIR/rueckgrat/caddy/rueckgrat-caddy.cert"

    pushd "$chat_dir" > /dev/null

    # the app trusts the hub through the caddy cert bundled in assets/
    mkdir -p assets
    if [[ -f "$cert" ]]; then
        cp -f "$cert" assets/rueckgrat-caddy.cert
    elif [[ -f assets/rueckgrat-caddy.cert ]]; then
        echo "⚠️ Warning: $cert not found, using the older copy in assets/ (it may not match the hub)"
    else
        echo "⚠️ Warning: no caddy certificate yet ($cert is missing)."
        echo "   The normal install generates it. Without it the APK will not trust the hub."
    fi

    # same venv as the native chat client; requirements_desktop.txt brings the flet CLI
    [ -x .venv/bin/python ] || { rm -rf .venv; python3 -m venv .venv; }
    if ! .venv/bin/python -m pip install -r requirements_desktop.txt; then
        echo "❌ Error: could not install the flet build tools for the APK"
        popd > /dev/null
        return 1
    fi

    # -y: let flet install Flutter/JDK/Android SDK without asking, otherwise flet asks itself
    local flet_args=(build apk)
    if $YES; then flet_args+=(--yes); fi

    if ! { .venv/bin/flet clean && .venv/bin/flet "${flet_args[@]}"; }; then
        echo "❌ Error: flet build apk failed (see output above)"
        popd > /dev/null
        return 1
    fi
    popd > /dev/null

    if [[ ! -f "$apk_src" ]]; then
        echo "❌ Error: build finished but $apk_src is missing"
        return 1
    fi

    mkdir -p "$(dirname "$apk_dest")"
    cp -f "$apk_src" "$apk_dest"
    echo "✅ APK: $apk_dest"
    echo "💡 install it on a phone with USB debugging: adb install -r $apk_dest"
}

# prep_data_dirs - creates essential directories
# Usage: prep_data_dirs
# No arguments
prep_data_dirs() {
    if [[ -d "$HOST_MODELS_DIR" ]]; then
        return
    fi    
    echo "prep $HOST_MODELS_DIR ..."
    echo "$SUDO_PASSWORD" | sudo -S mkdir -p "$HOST_MODELS_DIR"
    echo "$SUDO_PASSWORD" | sudo -S chown -R root:root "$HOST_MODELS_DIR"
    echo "$SUDO_PASSWORD" | sudo -S chmod -R 777 "$HOST_MODELS_DIR"
}

check_docker_group() {
    [ "$(id -u)" -eq 0 ] && return 0                     # root needs no group
    groups | grep -qw docker && return 0                 # current login already has it

    if id -nG "$SUDO_USER" | grep -qw docker; then
        # member in /etc/group (e.g. docker was just installed), but this login
        # predates that. Run every docker call through sg so it works right now.
        docker() { sg docker -c "$(printf '%q ' docker "$@")"; }
        echo "ℹ️ docker group not active in this login yet, using sg docker for this run"
        return 0
    fi

    echo "❌ Error: User not in docker group. Run: sudo usermod -aG docker $SUDO_USER, then log out and back in" >&2
    exit 1
}

# resolve_model_file - print container path of the GGUF llama-server should load
# Usage: resolve_model_file <model name>
# Uses llama.model_file from the registry, else the first .gguf in files
resolve_model_file() {
    local model="$1" rel
    rel=$(jq -r --arg k "$model" '
        .[$k] as $m
        | ($m.llama.model_file
            // ($m.files // [] | map(select(.source | endswith(".gguf"))) | first // empty
                | (if .path == "" then "" else .path + "/" end) + (.source | split("/") | last)))
        | $m.install_path + "/" + .
    ' "$REGISTRY_JSON")
    [[ -n "$rel" && "$rel" != "null" ]] || return 1
    echo "$CONTAINER_MODELS_DIR/$rel"
}

# parse_host_config - set INSTALL_* flags from one host JSON object
# Usage: parse_host_config '<host json>'
parse_host_config() {
    local host_config="$1"
    [[ -n "$host_config" ]] || { echo "❌ Error: host_config is empty" >&2; exit 1; }
    [[ -f "${REGISTRY_JSON:-}" ]] || { echo "❌ Error: REGISTRY_JSON not set or missing" >&2; exit 1; }

    INSTALL_CHAT=false
    INSTALL_HUB=false
    INSTALL_NODE=false
    INSTALL_LLAMA=false
    INSTALL_IMAGE_GEN=false
    INSTALL_TTS=false
    TTS_MODEL="chatterbox_multilingual"
    INSTALL_STT=false
    INSTALL_EMBEDDING=false
    INSTALL_DECISION=false
    INSTALL_CLOUDFLARED=false
    CLOUDFLARE_TUNNEL_TOKEN=""
    CLOUDFLARE_HUB_ADDR=""
    CLOUDFLARE_HUB_PORT=""
    INSTALL_LLAMA_MODEL=""
    HUB_PORT=""
    SIGNUP_MODE=""
    NODE_PORT=""
    LLAMA_SERVER_PORT=""
    LLAMA_SERVER_MODEL=""
    LLAMA_SERVER_MAX_CONTEXT="${LLAMA_SERVER_MAX_CONTEXT_DEFAULT}"
    LLAMA_SERVER_GPU_LAYERS="${LLAMA_SERVER_GPU_LAYERS_DEFAULT}"
    LLAMA_SERVER_FLASH_ATTN="${LLAMA_SERVER_FLASH_ATTN_DEFAULT}"
    LLAMA_SERVER_TEMP="${LLAMA_SERVER_TEMP_DEFAULT}"
    LLAMA_SERVER_N_PARALLEL="${LLAMA_SERVER_N_PARALLEL_DEFAULT}"
    LLAMA_SERVER_EXTRA_ARGS=""

    if echo "$host_config" | jq -e '.hub' >/dev/null; then
        INSTALL_HUB=true
        HUB_PORT=$(echo "$host_config" | jq -r '.hub.port // empty')
        SIGNUP_MODE=$(echo "$host_config" | jq -r '.hub.signup_mode // empty')
    fi

    if echo "$host_config" | jq -e '.chat' >/dev/null; then
        INSTALL_CHAT=true
    fi

    if echo "$host_config" | jq -e '.cloudflared' >/dev/null; then
        INSTALL_CLOUDFLARED=true
        CLOUDFLARE_HUB_ADDR=$(echo "$host_config" | jq -r '.cloudflared.hub_addr // empty')
        CLOUDFLARE_HUB_PORT=$(echo "$host_config" | jq -r '.cloudflared.hub_port // empty')
        CLOUDFLARE_TUNNEL_TOKEN=$(echo "$host_config" | jq -r '.cloudflared.token // empty')
    fi

    if echo "$host_config" | jq -e '.node' >/dev/null; then
        INSTALL_NODE=true
        NODE_PORT=$(echo "$host_config" | jq -r '.node.port // empty')

        local item type name reg
        while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            type=$(echo "$item" | jq -r '.type')
            name=$(echo "$item" | jq -r '.name')
            if [[ "$type" == "text_to_text" || "$name" == "llama_server" || "$name" == "llama-server" ]]; then
                INSTALL_LLAMA=true
                INSTALL_LLAMA_MODEL=$(echo "$item" | jq -r '.model // empty')
                LLAMA_SERVER_PORT=$(echo "$item" | jq -r '.port // empty')

                # precedence: host config > registry llama block > install.sh default
                reg=$(jq -c --arg k "$INSTALL_LLAMA_MODEL" '.[$k].llama // {}' "$REGISTRY_JSON")
                eval "$(jq -r --argjson r "$reg" '
                    def pick(k): (.[k] // $r[k] // empty) | tostring | @sh;
                    "LLAMA_SERVER_MAX_CONTEXT_CFG=\(pick("max_context"))",
                    "LLAMA_SERVER_GPU_LAYERS_CFG=\(pick("gpu_layers"))",
                    "LLAMA_SERVER_FLASH_ATTN_CFG=\(pick("flash_attn"))",
                    "LLAMA_SERVER_TEMP_CFG=\(pick("temp"))",
                    "LLAMA_SERVER_N_PARALLEL_CFG=\(pick("n_parallel"))",
                    "LLAMA_SERVER_EXTRA_ARGS_CFG=\(pick("extra_args"))"
                ' <<< "$item")"

                LLAMA_SERVER_MAX_CONTEXT="${LLAMA_SERVER_MAX_CONTEXT_CFG:-$LLAMA_SERVER_MAX_CONTEXT_DEFAULT}"
                LLAMA_SERVER_GPU_LAYERS="${LLAMA_SERVER_GPU_LAYERS_CFG:-$LLAMA_SERVER_GPU_LAYERS_DEFAULT}"
                LLAMA_SERVER_FLASH_ATTN="${LLAMA_SERVER_FLASH_ATTN_CFG:-$LLAMA_SERVER_FLASH_ATTN_DEFAULT}"
                LLAMA_SERVER_TEMP="${LLAMA_SERVER_TEMP_CFG:-$LLAMA_SERVER_TEMP_DEFAULT}"
                LLAMA_SERVER_N_PARALLEL="${LLAMA_SERVER_N_PARALLEL_CFG:-$LLAMA_SERVER_N_PARALLEL_DEFAULT}"
                LLAMA_SERVER_EXTRA_ARGS="${LLAMA_SERVER_EXTRA_ARGS_CFG:-}"

                LLAMA_SERVER_MODEL=$(resolve_model_file "$INSTALL_LLAMA_MODEL") \
                    || { echo "❌ Error: no GGUF found for $INSTALL_LLAMA_MODEL in $REGISTRY_JSON" >&2; exit 1; }
            fi
            if [[ "$type" == "text_to_image" || "$name" == "image_gen" ]]; then
                INSTALL_IMAGE_GEN=true
            fi
            if [[ "$type" == "text_to_speech" || "$name" == "tts" ]]; then
                INSTALL_TTS=true
                # configs from before this option have no "model" -> chatterbox (English)
                TTS_MODEL=$(echo "$item" | jq -r '.model // "chatterbox"')
                if [[ "$TTS_MODEL" != "chatterbox" && "$TTS_MODEL" != "chatterbox_multilingual" ]]; then
                    echo "⚠️ Warning: unknown tts model $TTS_MODEL, using chatterbox" >&2
                    TTS_MODEL="chatterbox_multilingual"
                fi
            fi
            if [[ "$type" == "speech_to_text" || "$name" == "stt" ]]; then
                INSTALL_STT=true
            fi
            if [[ "$type" == "text_to_embedding" ]]; then
                INSTALL_EMBEDDING=true
            fi
            if [[ "$type" == "text_to_decision" ]]; then
                INSTALL_DECISION=true
            fi
        done < <(echo "$host_config" | jq -c '.node.services // [] | .[]')

        while IFS= read -r item; do
            [[ -z "$item" ]] && continue
            type=$(echo "$item" | jq -r '.type')
            name=$(echo "$item" | jq -r '.name')
            if [[ "$type" == "text_to_image" || "$name" == "image_gen" ]]; then
                INSTALL_IMAGE_GEN=true
            fi
            if [[ "$type" == "text_to_speech" || "$name" == "tts" ]]; then
                INSTALL_TTS=true
            fi
            if [[ "$type" == "speech_to_text" || "$name" == "stt" ]]; then
                INSTALL_STT=true
            fi
            if [[ "$type" == "text_to_embedding" ]]; then
                INSTALL_EMBEDDING=true
            fi
            if [[ "$type" == "text_to_decision" ]]; then
                INSTALL_DECISION=true
            fi
        done < <(echo "$host_config" | jq -c '.node.modules // [] | .[]')
    fi

    HOST_MODELS_DIR=$(echo "$host_config" | jq -r '.models_dir // empty')
    HOST_MODELS_DIR="${HOST_MODELS_DIR:-$HOST_MODELS_DIR_DEFAULT}"
}

write_default_env() {
    set_env_value HUB_HOST "rueckgrat.hub"
    set_env_value HUB_ADDR "127.0.0.1"

    set_env_value HOST_MODELS_DIR "$HOST_MODELS_DIR_DEFAULT"

    set_env_value LLAMA_SERVER_PORT "$LLAMA_SERVER_PORT_DEFAULT"
    set_env_value LLAMA_SERVER_BACKEND "$LLAMA_SERVER_BACKEND_DEFAULT"

    set_env_value HUB_PORT "$HUB_PORT_DEFAULT"
    set_env_value NODE_PORT "$NODE_PORT_DEFAULT"
}

# deploy_components - Local component installer
# Usage: deploy_components "hub,node,llama"
# Args:
#   $1 - host configuration string
deploy_components() {
    local host_config="$1"

    print_section
    echo "deploy components..."
    
    echo "reading config $(echo "$host_config" | jq -c 'if .cloudflared.token then .cloudflared.token = "******" else . end')"
    REGISTRY_JSON="$(pwd)/rueckgrat/node/data/registry.json"
    [[ -f "$REGISTRY_JSON" ]] || { echo "❌ Error: registry file missing at $REGISTRY_JSON"; exit 1; }

    parse_host_config "$host_config"

    # pretend to be in build dir
    CURRENT_DIR=$(pwd)
    WORKING_DIR=$CURRENT_DIR
    CHAT_DIR="$WORKING_DIR/rueckgrat/chat"
    CADDY_DIR="$WORKING_DIR/rueckgrat/caddy"
    CADDY_KEY="$CADDY_DIR/rueckgrat-caddy.key"
    CADDY_CERT="$CADDY_DIR/rueckgrat-caddy.cert"

    if $INSTALL_CLOUDFLARED; then
        install_dependencies curl
        install_docker
        check_docker_group
        deploy_cloudflared
        return
    fi

    write_default_env    

    if $INSTALL_HUB || $INSTALL_NODE; then
        install_dependencies curl
        install_docker
    fi

    check_docker_group
    volume_cleanup
    gen_caddy_cert
    prep_data_dirs

    echo "deploy..."

    if $INSTALL_HUB; then
        deploy_hub
    fi

    if $INSTALL_NODE; then
        if [[ "$INSTALL_IMAGE_GEN" == true || "$INSTALL_TTS" == true || "$INSTALL_STT" == true || "$INSTALL_DECISION" == true || "$INSTALL_LLAMA" == true ]]; then
            install_nvidia_toolkit
        fi

        deploy_node

        if $INSTALL_LLAMA; then
            deploy_llama $INSTALL_LLAMA_MODEL
        fi
    fi

    if $INSTALL_CHAT; then
        deploy_chat_native
    fi
}

# is_local_host - true if the address points at this machine
# Usage: is_local_host <addr>
is_local_host() {
    local addr="${1#*@}"   # strip user@
    [[ "$addr" == "localhost" || "$addr" == 127.* || "$addr" == "::1" ]] && return 0
    [[ "$addr" == "$(hostname)" || "$addr" == "$(hostname -f 2>/dev/null)" ]] && return 0
    local ip
    for ip in $(hostname -I 2>/dev/null); do
        [[ "$addr" == "$ip" ]] && return 0
    done
    return 1
}

remove_line_breaks() {
    echo -n "${1//$'\n'$'\r'/}"
}

# deploy_components_remote - Copy workspace + run installer with --host-config on target host
# Usage: deploy_components_remote <host> <comps>
# Args:
#   $1 - host config string
deploy_components_remote() {
    local host_config="$1"
    host_addr=$(echo "$host_config" | jq -r '.addr')
    clean_config=$(remove_line_breaks "$host_config")

    # --in-place: same host -> install right here in the working dir, no copy, no ssh
    if $IN_PLACE && is_local_host "$host_addr"; then
        print_section
        echo "🏠 Installing $host_addr in place ($(pwd))"
        ./install.sh --local-config "$clean_config" $([[ $CLEAN_BUILD == true ]] && echo -f) $([[ $VERBOSE == true ]] && echo -v) $([[ $YES == true ]] && echo -y) -p "$SUDO_PASSWORD" -u "$SUDO_USER" \
            || echo "❌ Error: Installation failed on $host_addr"
        return
    fi

    install_dependencies rsync sshpass

    print_section
    echo "🌐 Deploying to $host_addr"

    local remote_dir="Rueckgrat-install"
    local SSH_CONTROL="/tmp/deploy-$SUDO_USER-$(echo "$host_addr" | tr '@:' '__')"
    local SSH_OPTS=( -o ControlMaster=auto -o ControlPersist=5m -o ControlPath="$SSH_CONTROL" )

    trap 'ssh -O exit "${SSH_OPTS[@]}" "$host_addr" >/dev/null 2>&1 || true' EXIT

    sshpass -p "$SUDO_PASSWORD" ssh "${SSH_OPTS[@]}" -o User="$SUDO_USER" -Nf "$host_addr" || { echo "❌ Error: failed to connect with $host_addr"; return 1; }

    # rsync must exist on both ends of the copy, so check the target before using it
    # (jq is installed by the target's own installer at the start of main)
    if ! ssh "${SSH_OPTS[@]}" "$host_addr" 'command -v rsync >/dev/null'; then
        echo "❌ Error: rsync missing on $host_addr - install it there first (e.g. sudo apt install rsync)"
        return 1
    fi

    if $CLEAN_BUILD; then
        echo "Clean destination..."
        echo "$SUDO_PASSWORD" | ssh -tt "${SSH_OPTS[@]}" "$host_addr" "sudo rm -rf $remote_dir/*"
    fi

    echo "Copying files..."
    rsync -az --checksum -e "ssh ${SSH_OPTS[*]}" --exclude='.git' --exclude='logs' --exclude='.venv' ./ "$host_addr:$remote_dir/" || {
        echo "❌ Error: rsync failed for $host_addr"
        return 1
    }

    echo "Running installer..."
    ssh "${SSH_OPTS[@]}" -t -o StrictHostKeyChecking=no -o ConnectTimeout=15 "$host_addr" "
        set -euo pipefail
        cd $remote_dir
        chmod +x install.sh
        ./install.sh --local-config '$clean_config' $([[ $CLEAN_BUILD == true ]] && echo -f) $([[ $VERBOSE == true ]] && echo -v) $([[ $YES == true ]] && echo -y) -p $SUDO_PASSWORD -u $SUDO_USER
    " || echo "❌ Error: Installation failed on $host_addr"
}

# deploy_on_hosts - Iterate host components and execute installs per host
# Usage: deploy_on_hosts
# No arguments
deploy_on_hosts() {
    while IFS= read -r -u3 host_config; do
        [[ -z "$host_config" ]] && continue
        deploy_components_remote "$host_config"
    done 3< <(jq -c '.hosts[]' "$CONFIG_FILE")
}

# deploy_cloudflare_node - Deploy the Cloudflare node saved in the config by setup
# (no questions here). Token comes only from the config
# Usage: deploy_cloudflare_node
deploy_cloudflare_node() {
    jq -e '.cloudflare.enabled == true' "$CONFIG_FILE" >/dev/null 2>&1 || return 0

    local cf_addr hub_addr hub_port token cf_config
    cf_addr=$(jq -r '.cloudflare.addr // empty' "$CONFIG_FILE")
    hub_addr=$(jq -r '.cloudflare.hub_addr // empty' "$CONFIG_FILE")
    hub_port=$(jq -r '.cloudflare.hub_port // empty' "$CONFIG_FILE")
    hub_port="${hub_port:-$HUB_PORT_DEFAULT}"

    token=$(jq -r '.cloudflare.token // empty' "$CONFIG_FILE")

    print_section
    if [[ -z "$cf_addr" || -z "$token" ]]; then
        echo "⚠️ Warning: Cloudflare node in config but no IP or token, no tunnel"
        return 0
    fi
    echo "   cloudflare   $cf_addr -> hub $hub_addr:$hub_port"

    # the token travels inside this one-host config, like ports do for nodes
    cf_config=$(jq -nc --arg addr "$cf_addr" --arg hub_addr "$hub_addr" --arg hub_port "$hub_port" --arg token "$token" \
        '{addr: $addr, cloudflared: {hub_addr: $hub_addr, hub_port: ($hub_port | tonumber), token: $token}}')

    # never wipe here: the Cloudflare node may be a machine that also runs the hub or a node
    CLEAN_BUILD=false deploy_components_remote "$cf_config"

    echo ""
    echo "💡 In Cloudflare Zero Trust, set the tunnel's public hostname service to:"
    echo "   http://rueckgrat.hub:$hub_port"
}

# usage - Display help message and exit
# Prints command-line options and usage for the installer script.
# Usage: usage
# No arguments
usage() {
    echo "Rückgrat ver $RUECKGRAT_VERSION"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  --config | -c          FILE         Load hosts & components from config file"
    echo "  --key                  FILE         Path to caddy private key file"
    echo "  --cert                 FILE         Path to caddy certificate file"
    echo "  --fresh | -f                        Perform clean build/install (remove previous)"
    echo "  --verbose | -v                      Enable verbose output"
    echo "  --yes | -y                          Non interactive where possible"
    echo "  --host-config | -hc    STRING       partial config for just one host"    
    echo "  --sync | -s                         Dev mode: rsync local tree to remote hosts only"
    echo "  --in-place                          Install in the current directory when the target is this host"
    echo "  --apk | -a                          Only build the Android APK of the chat client, then exit"
    echo "  --user | -u            USER         Sudo username"
    echo "  --password | -p        PASSWORD     Sudo password"
    echo "  --info | -i                         Print system info"
    echo "  --help | -h                         Show this help"
    echo ""
    echo "Expert:"
    echo "  --local-config | -lc   STRING       works like host-config but it assumes that the script"
    echo "                                      was executed already on the correct machine"
    echo ""    
}

info() {
    print_header "System Info"
    print_section
}

# get_user_passwd - makes sure we have user and password ready
# Usage: get_user_passwd
# No arguments
get_user_passwd() {
    if [[ -z "$SUDO_USER" ]]; then
        read_tty "Enter sudo username ($(whoami)): " "$(whoami)" $YES
        SUDO_USER="$REPLY"
    fi

    if [[ -z "$SUDO_PASSWORD" ]]; then
        read_tty_s "Enter password for $SUDO_USER: "
        SUDO_PASSWORD="$REPLY"
    fi    
}

# resolve_config_file checks if config file already exists
resolve_config_file() {
    CONFIG_FILE=$WORKING_DIR/rueckgrat/config/infrastructure.json
    [[ -f "$CONFIG_FILE" ]] || { echo "❌ Error: config file not found: $CONFIG_FILE. Try run install regularily first before using sync."; exit 1; }
}

# rsync_to_host - Copy current workspace to a remote host (no install)
rsync_to_host() {
    local host_addr="$1"
    local remote_dir="Rueckgrat-install"
    local SSH_CONTROL="/tmp/deploy-$SUDO_USER-$(echo "$host_addr" | tr '@:' '__')"
    local SSH_OPTS=( -o ControlMaster=auto -o ControlPersist=5m -o ControlPath="$SSH_CONTROL" )

    trap 'ssh -O exit "${SSH_OPTS[@]}" "$host_addr" >/dev/null 2>&1 || true' EXIT

    sshpass -p "$SUDO_PASSWORD" ssh "${SSH_OPTS[@]}" -o User="$SUDO_USER" -Nf "$host_addr" || { echo "❌ Error: failed to connect with $host_addr"; return 1; }

    echo "Copying files to $host_addr..."
    rsync -az --checksum -e "ssh ${SSH_OPTS[*]}" \
        --exclude='.git' --exclude='logs' --exclude='build/' \
        ./ "$host_addr:$remote_dir/" || {
        echo "❌ Error: rsync failed for $host_addr"
        return 1
    }
    echo "✅ Synced to $host_addr:~/$remote_dir/"
}

sync_on_hosts() {
    install_dependencies rsync sshpass jq

    while IFS= read -r host_config; do
        host_addr=$(echo "$host_config" | jq -r '.addr')
        print_section
        echo "🔄 Syncing to $host_addr"
        rsync_to_host "$host_addr"
    done < <(jq -c '.hosts[]' "$CONFIG_FILE")
}

readonly CONTAINER_MODELS_DIR="/models"
readonly HUB_PORT_DEFAULT=14223
readonly SIGNUP_MODE_DEFAULT="invite"                # open: anyone can sign up, invite: signup needs an invite token
readonly NODE_PORT_DEFAULT=7346
readonly HOST_MODELS_DIR_DEFAULT="/var/lib/Rueckgrat/models"

readonly LLAMA_SERVER_MAX_CONTEXT_DEFAULT=4096
readonly LLAMA_SERVER_GPU_LAYERS_DEFAULT=-1       # -1 means all layers run on GPU
readonly LLAMA_SERVER_PORT_DEFAULT=8080
readonly LLAMA_SERVER_FLASH_ATTN_DEFAULT="on"
readonly LLAMA_SERVER_TEMP_DEFAULT=0.7
readonly LLAMA_SERVER_N_PARALLEL_DEFAULT=2
readonly LLAMA_SERVER_BACKEND_DEFAULT=rocm        # llama-server backend ie. rocm, cuda, intel

main() {   
    export DOCKER_BUILDKIT=1
    export COMPOSE_DOCKER_CLI_BUILD=1

    get_info
    
    CONFIG_FILE=""
    VERBOSE=false
    DOCKER_QUIET_BUILD="--quiet"
    CLEAN_BUILD=false
    HOST_CONFIG=""
    LOCAL_CONFIG=""
    KEY_FILE=""
    CERT_FILE=""
    YES=false
    SUDO_USER="$(whoami)"
    SUDO_PASSWORD=""
    NO_CACHE=""
    SYNC_ONLY=false
    IN_PLACE=false
    APK_ONLY=false
    HOST_MODELS_DIR=HOST_MODELS_DIR_DEFAULT
    NODE_PORT=NODE_PORT_DEFAULT
    HUB_PORT=HUB_PORT_DEFAULT
    LLAMA_SERVER_PORT=LLAMA_SERVER_PORT_DEFAULT

    while [[ $# -gt 0 ]]; do
        case $1 in
            --config|-c)
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --config requires a filename"
                    exit 1
                fi
                CONFIG_FILE="$2"
                shift 2
                ;;
            --host-config|-hc)
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --host-config requires config string for one host"
                    exit 1
                fi
                HOST_CONFIG="$2"
                YES=true
                shift 2
                ;;
            --local-config|-lc) # don't use --local-config manually unless you know what you are doing
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --local-config requires config string for one host"
                    exit 1
                fi
                LOCAL_CONFIG="$2"
                YES=true
                shift 2
                ;;                
            --key)
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --key requires a filename"
                    exit 1
                fi
                KEY_FILE="$2"
                shift 2
                ;;
            --cert)
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --cert requires a filename"
                    exit 1
                fi
                CERT_FILE="$2"
                shift 2
                ;;        
            -u|--user)
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --user requires a username"
                    exit 1
                fi
                SUDO_USER="$2"
                shift 2
                ;;
            -p|--password)
                if [[ -z "${2:-}" ]]; then
                    echo "❌ Error: --password requires a password"
                    exit 1
                fi
                SUDO_PASSWORD="$2"
                shift 2
                ;;
            -v|--verbose) VERBOSE=true; DOCKER_QUIET_BUILD=""; shift ;;
            -f|--fresh) CLEAN_BUILD=true; NO_CACHE="--no-cache"; shift ;;
            -s|--sync) SYNC_ONLY=true; shift ;;
            --in-place) IN_PLACE=true; shift ;;
            -a|--apk) APK_ONLY=true; shift ;;
            -y|--yes) YES=true; shift ;;
            -h|--help) usage; exit 0 ;;
            -i|--info) info; exit 0 ;;
            *) echo "Unknown option: $1"; exit 1 ;;
        esac
    done

    # APK only: needs no config and no jq, so it runs before the jq install
    if $APK_ONLY; then
        print_header "📱 Rückgrat Chat APK"
        WORKING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        [[ -d "$WORKING_DIR/rueckgrat/chat" ]] || { echo "❌ Error: no rueckgrat/chat in $WORKING_DIR"; exit 1; }
        build_chat_apk true || exit 1
        print_section
        exit 0
    fi

    if ! command -v jq &> /dev/null; then
        get_user_passwd
        install_dependencies jq
    fi

    if $SYNC_ONLY; then
        print_header "🔄 Rückgrat Sync"
    
        get_user_passwd

        setup_repository

        resolve_config_file
        
        sync_on_hosts
        echo "Sync done."
        print_section
        return
    fi        
  
    if [[ -n "$LOCAL_CONFIG" ]]; then
        print_header "🌐 Rückgrat Installer ($HOSTNAME - $HOST_ADDR)"
        get_user_passwd
        deploy_components "$LOCAL_CONFIG"
    elif [[ -n "$HOST_CONFIG" ]]; then
        REMOTE_ADDR=$(echo "$HOST_CONFIG" | jq -r '.addr')
        echo "$HOST_ADDR $REMOTE_ADDR"
        if [ $HOST_ADDR == $REMOTE_ADDR ]; then
            print_header "🏠 Rückgrat Installer ($HOSTNAME - $HOST_ADDR)"
            get_user_passwd
            deploy_components "$HOST_CONFIG"
        else
            print_header "🚀 Rückgrat Installer"
            get_user_passwd
            deploy_components_remote "$HOST_CONFIG"
        fi
    else
        print_header "🚀 Rückgrat Installer"

        get_user_passwd

        setup_repository

        gen_caddy_cert

        setup
        confirm_install_configuration

        deploy_on_hosts

        deploy_cloudflare_node

        build_chat_apk || true

        echo "All done! Enjoy Rueckgrat ✨"
        echo "follow live logs of all services in this compose project: cd rueckgrat && docker compose logs -f"
        print_section
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi