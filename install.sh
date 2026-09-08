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
        if command -v rocminfo >/dev/null; then
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
    echo "Rückgrat ver   ${RUECKGRAT_VERSION:----}"
    echo ""
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
    echo "Launched with  $(echo "$PARAMETERS" | sed -E 's/-p [^ ]+/-p ******/g')"
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
            echo "$SUDO_PASSWORD" | sudo -S usermod -aG docker "$SUDO_USER && newgrp docker"
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

# install_caddy - Install Caddy if not present
# Usage: install_caddy
# No arguments
install_caddy() {
    command -v caddy &> /dev/null && return

    print_section
    echo "📦 detected missing caddy"

    read_tty "Install caddy? (Y/n): " "Y" $YES
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=amd64" -o /tmp/caddy
        echo "$SUDO_PASSWORD" | sudo -S install -m 755 /tmp/caddy /usr/local/bin/caddy
        rm -f /tmp/caddy

        echo "✅ Caddy installed."
     else
        echo "⚠️ Warning: Aborted by user"
        exit 0
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

# select_hosts_and_components - Interactively collect target hosts + per-host components
# Supports json config file loading/saving 
# Usage: select_hosts_and_components
select_hosts_and_components() {
    print_section

    if [[ -n "${CONFIG_FILE:-}" ]]; then
        if jq . "$CONFIG_FILE" >/dev/null 2>&1; then
            echo "📂 found valid config at $CONFIG_FILE"

            mkdir -p "$WORKING_DIR/rueckgrat/config"
            cp -f $CONFIG_FILE "$WORKING_DIR/rueckgrat/config/infrastructure.json"
            CONFIG_FILE="$WORKING_DIR/rueckgrat/config/infrastructure.json"

            echo "💾 Saved config to $CONFIG_FILE"
            echo ""
            echo "💡 you can use this file for a quicker future install ie:"
            echo "   ./install -c infrastructure.json -y"
        else
            echo "❌ Error: Failed to load config from $CONFIG_FILE"
        fi
        return
    fi 

    echo "Select hosts and their configuration"
    
    hosts=()
    while true; do
        echo ""
        read_tty "Target host (IP/hostname, empty=done): " ""
        host_addr=$REPLY
        [[ -z "$host_addr" ]] && break

        validate_ip $host_addr

        select_components

        node_json=""       
        hub_json=""
        chat_json=""

        if $INSTALL_NODE; then
            services=()
            modules=()

            if $INSTALL_LLAMA; then
                services+=("$(service_json "text_to_text" "llama_server" $LLAMA_SERVER_PORT "model" "$INSTALL_LLAMA_MODEL")")
            fi

            if $INSTALL_IMAGE_GEN; then
                services+=("$(module_json "text_to_image" "image_gen")")
            fi
            
            printf -v services_json '[%s]' "$(IFS=,; echo "${services[*]}")"

            node_json="\"node\":{\"port\":$NODE_PORT,\"services\":$services_json}"
        fi

        if $INSTALL_HUB; then
            hub_json="\"hub\":{\"port\":$HUB_PORT}"
        fi

        if $INSTALL_CHAT; then            
            chat_json="\"chat\":{}"
        fi

        if $INSTALL_CHAT_DOCKER; then
            chat_json="\"chat_docker\":{\"port\":$CHAT_DOCKER_PORT}"
        fi

        host_parts=("\"addr\":\"$host_addr\"")
        [ -n "$node_json" ] && host_parts+=("$node_json")
        [ -n "$hub_json" ] && host_parts+=("$hub_json")
        [ -n "$chat_json" ] && host_parts+=("$chat_json")
        host_json="{$(IFS=,; echo "${host_parts[*]}")}"
        hosts+=("$host_json")
    done

    CONFIG_FILE=$WORKING_DIR/rueckgrat/config/infrastructure.json
    printf -v hosts_json '[%s]' "$(IFS=,; echo "${hosts[*]}")"
    hosts_json="{\"hosts\":$hosts_json }"
    echo "$hosts_json" | jq . > "$CONFIG_FILE"
    echo "💾 Saved config to $CONFIG_FILE"
}

# select_components - Prompt user for which components to install
# Usage: select_components
# Sets: INSTALL_CHAT, INSTALL_CHAT_DOCKER, INSTALL_HUB, INSTALL_NODE, INSTALL_LLAMA
select_components() {
    INSTALL_CHAT=false; INSTALL_CHAT_DOCKER=false
    INSTALL_HUB=false; INSTALL_NODE=false
    INSTALL_LLAMA=false; INSTALL_LLAMA_MODEL=""
    INSTALL_IMAGE_GEN=false

    echo "Select components:"
    echo ""

    read_tty "Install native chat client? (Y/n): " "Y"
    [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_CHAT=true
    echo -e "\e[1A\e[K [$( [[ $INSTALL_CHAT == true ]] && echo '✅' || echo '⚫' )] Native Chat Client"

    read_tty "Install docker chat client? (y/N): " "N"
    [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_CHAT_DOCKER=true
    echo -e "\e[1A\e[K [$( [[ $INSTALL_CHAT_DOCKER == true ]] && echo '✅' || echo '⚫' )] Docker Chat Client"
    if [[ "$INSTALL_CHAT_DOCKER" == true ]]; then
        read_tty "Chat Docker port? [$CHAT_DOCKER_PORT_DEFAULT]: " "$CHAT_DOCKER_PORT_DEFAULT" $YES
        CHAT_DOCKER_PORT=$REPLY
        echo -e "\e[1A\e[K     Port: $CHAT_DOCKER_PORT"
    fi

    read_tty "Install Hub? (Y/n): " "Y"
    [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_HUB=true
    echo -e "\e[1A\e[K [$( [[ $INSTALL_HUB == true ]] && echo '✅' || echo '⚫' )] Hub"
    if [[ "$INSTALL_HUB" == true ]]; then
        read_tty "Hub port? [$HUB_PORT_DEFAULT]: " "$HUB_PORT_DEFAULT" $YES
        HUB_PORT=$REPLY
        echo -e "\e[1A\e[K     Port: $HUB_PORT"
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
            REGISTRY_JSON="$WORKING_DIR/rueckgrat/node/data/registry.json"
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
            echo -e "         Selected model: $INSTALL_LLAMA_MODEL"
        fi

        read_tty "Install image generation on Node? (Y/n): " "Y"
        [[ "$REPLY" =~ ^[Yy]$ ]] && INSTALL_IMAGE_GEN=true
        echo -e "\e[1A\e[K     [$( [[ $INSTALL_IMAGE_GEN == true ]] && echo '✅' || echo '⚫' )] ImageGen"
    fi
}

format_hosts() {
    if [[ -z "${CONFIG_FILE:-}" ]] || ! jq . "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "❌ Error: Invalid config" >&2
        return 1
    fi

  jq -r '
    .hosts[] as $h |
    "\nHost: \($h.addr)",
    "  "+(if $h.chat_docker then "[✅]" else "[⚫]" end)+" Docker Chat Client",
    "  "+(if $h.chat then "[✅]" else "[⚫]" end)+" Native Chat Client",
    "  "+(if $h.hub then "[✅]" else "[⚫]" end)+" Hub",
    "  "+(if $h.node then "[✅]" else "[⚫]" end)+" Node",
    "  "+($h.node.services[]? | "    [✅] \(.name)"),
    "  "+($h.node.modules[]? | "    [✅] \(.name)")
  ' "$CONFIG_FILE"
}

# confirm_install_configuration - Print full multi-host installation plan and ask for final confirmation
# Usage: confirm_install_configuration
# Exits if no components selected or user aborts
confirm_install_configuration() {
    print_section
    echo "Installation plan:"

    format_hosts

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
    pushd rueckgrat > /dev/null
    docker compose stop hub caddy 2>/dev/null || true
    docker compose --progress=$DOCKER_PROGRESS_MODE build ${NO_CACHE:-} hub caddy || { echo "❌ Error: Docker compose build of hub & cdaddy failed."; popd; exit 1; }
    docker compose up -d hub caddy || { echo "❌ Error: Docker compose up of hub & cdaddy failed."; popd; exit 1; }
    popd > /dev/null
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

    BUILD_ARGS=()
    COMPOSE_FILES=(-f compose.yml)

    if [ "$INSTALL_IMAGE_GEN" = true ]; then
        BUILD_ARGS+=(--build-arg INSTALL_IMAGE_GEN=true)
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

    echo "   vendor=${GPU_VENDOR:-cpu} backend=${TORCH_BACKEND:-cpu} cuda_index=${TORCH_CUDA_INDEX:-n/a}"
    echo "   compose=${COMPOSE_FILES[*]}"
    echo "   build_args=${BUILD_ARGS[*]:-none}"
    [ "${GPU_VENDOR:-}" = "amd" ] && echo "   amd_gids=video:$HOST_AMD_VIDEO render:$HOST_AMD_RENDER"

    pushd rueckgrat > /dev/null
    if [ "${GPU_VENDOR:-}" = "amd" ]; then
        set_env_value HOST_AMD_VIDEO "$HOST_AMD_VIDEO"
        set_env_value HOST_AMD_RENDER "$HOST_AMD_RENDER"
    fi

    docker compose "${COMPOSE_FILES[@]}" stop node 2>/dev/null || true
    docker compose --progress=$DOCKER_PROGRESS_MODE "${COMPOSE_FILES[@]}" \
        build ${NO_CACHE:-} "${BUILD_ARGS[@]}" node \
        || { echo "❌ Error: Docker compose build of node failed."; popd; exit 1; }
    docker compose "${COMPOSE_FILES[@]}" up -d node \
        || { echo "❌ Error: Docker compose up of node failed."; popd; exit 1; }
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

    pushd rueckgrat > /dev/null
    GGUF_FILE_PATH="$CONTAINER_MODELS_DIR/llm/$LLM_MODEL/$LLM_MODEL.gguf"
    set_env_value LLAMA_SERVER_MODEL "$GGUF_FILE_PATH"
    set_env_value LLAMA_SERVER_BACKEND "$LLAMA_SERVER_BACKEND"
    if [ "${GPU_VENDOR:-}" = "amd" ]; then
        set_env_value HOST_AMD_VIDEO "$HOST_AMD_VIDEO"
        set_env_value HOST_AMD_RENDER "$HOST_AMD_RENDER"
    fi    

    docker compose "${COMPOSE_FILES[@]}" stop llama-server 2>/dev/null || true
    docker compose --progress=$DOCKER_PROGRESS_MODE "${COMPOSE_FILES[@]}" build ${NO_CACHE:-} llama-server || { echo "❌ Error: Docker compose build of llama-server failed."; popd; exit 1; }
    docker compose "${COMPOSE_FILES[@]}" up -d llama-server || { echo "❌ Error: Docker compose up of llama-server failed."; popd; exit 1; }
    popd > /dev/null
}

# install_chat - Install Chat (Docker)
# Usage: deploy_chat_docker
# No arguments
deploy_chat_docker() {
    print_section
    echo "🐋 chat..."

    pushd rueckgrat > /dev/null
    if [[ -f $CADDY_CERT ]]; then
        cp "$CADDY_CERT" "$CHAT_DIR/app"
    else
        echo "❌ Error: Certificate not found at $CADDY_CERT"
        exit 1
    fi

    read_tty "Choose hub to connect this chat to (IP/hostname, empty=done): " ""
    HUB_ADDR=$REPLY
    if [ -n "$HUB_ADDR" ]; then
        validate_ip "$HUB_ADDR"
    fi
    
    set_env_value HUB_ADDR "$HUB_ADDR"

    docker compose --progress=$DOCKER_PROGRESS_MODE build ${NO_CACHE:-} chat || { echo "❌ Error: Docker compose build of chat failed."; popd; exit 1; }
    docker compose up -d chat || { echo "❌ Error: Docker compose up of chat failed."; popd; exit 1; }
    popd > /dev/null
}

# deploy_chat_native - Install Chat (Native)
# Usage: deploy_chat_native
# No arguments
deploy_chat_native() {
    install_dependencies python3 python3.13-venv alsa-utils

    print_section
    echo "📦 chat..."

    pushd rueckgrat/chat > /dev/null
    ./install.sh "$CADDY_CERT" || { echo "❌ Error: Chat native install failed!"; popd; exit 1; }
    popd > /dev/null
}

# prep_app_data_dir - creates models directory
# Usage: prep_app_data_dir
# No arguments
prep_app_data_dir() {
    echo "prep /var/lib/Rueckgrat ..."
    echo "$SUDO_PASSWORD" | sudo -S mkdir -p $APP_DATA_DIR
    echo "$SUDO_PASSWORD" | sudo -S mkdir -p $HOST_MODELS_DIR
    echo "$SUDO_PASSWORD" | sudo -S chown -R root:root $APP_DATA_DIR
    echo "$SUDO_PASSWORD" | sudo -S chmod -R 777 $APP_DATA_DIR
}

check_docker_group() {
    if ! groups | grep -q docker && [ "$(id -u)" -ne 0 ]; then
        echo "❌ Error: User not in docker group. Run: sudo usermod -aG docker $SUDO_USER && newgrp docker" >&2
        exit 1
    fi
}

# parse_host_config - set INSTALL_* flags from one host JSON object
# Usage: parse_host_config '<host json>'
parse_host_config() {
    local host_config="$1"    
    [[ -n "$host_config" ]] || { echo "❌ Error: host_config is empty" >&2; exit 1; }

    INSTALL_CHAT=false
    INSTALL_CHAT_DOCKER=false
    INSTALL_HUB=false
    INSTALL_NODE=false
    INSTALL_LLAMA=false
    INSTALL_IMAGE_GEN=false
    INSTALL_LLAMA_MODEL=""
    HUB_PORT=""
    NODE_PORT=""
    CHAT_DOCKER_PORT=""
    LLAMA_SERVER_PORT=""

    if echo "$host_config" | jq -e '.hub' >/dev/null; then
        INSTALL_HUB=true
        HUB_PORT=$(echo "$host_config" | jq -r '.hub.port // empty')
    fi

    if echo "$host_config" | jq -e '.chat' >/dev/null; then
        INSTALL_CHAT=true
    fi

    if echo "$host_config" | jq -e '.chat_docker' >/dev/null; then
        INSTALL_CHAT_DOCKER=true
        CHAT_DOCKER_PORT=$(echo "$host_config" | jq -r '.chat_docker.port // empty')
    fi

    if echo "$host_config" | jq -e '.node' >/dev/null; then
        INSTALL_NODE=true
        NODE_PORT=$(echo "$host_config" | jq -r '.node.port // empty')
        # todo use NODE_PORT

        local item type name
        for item in $(echo "$host_config" | jq -c '.node.services // [] | .[]'); do
            type=$(echo "$item" | jq -r '.type')
            name=$(echo "$item" | jq -r '.name')
            if [[ "$type" == "text_to_text" || "$name" == "llama_server" || "$name" == "llama-server" ]]; then
                INSTALL_LLAMA=true
                INSTALL_LLAMA_MODEL=$(echo "$item" | jq -r '.model // empty')
                LLAMA_SERVER_PORT=$(echo "$item" | jq -r '.port // empty')
            fi
            if [[ "$type" == "text_to_image" || "$name" == "image_gen" ]]; then
                INSTALL_IMAGE_GEN=true
            fi
        done
        for item in $(echo "$host_config" | jq -c '.node.modules // [] | .[]'); do
            type=$(echo "$item" | jq -r '.type')
            name=$(echo "$item" | jq -r '.name')
            if [[ "$type" == "text_to_image" || "$name" == "image_gen" ]]; then
                INSTALL_IMAGE_GEN=true
            fi
        done
    fi
}

write_default_env() {
    [ -f "$WORKING_DIR/rueckgrat/.env" ] && return

    # hub hostname
    set_env_value HUB_HOST "rueckgrat.hub"
    set_env_value HUB_ADDR "127.0.0.1"

    # models that work with Rückgrat (tested with 24GB vram)
    # cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L (autor's preffered option)
    # Huihui-Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-ggml-model-Q3_K
    # NousResearch_Hermes-4.3-36B-Q4_K_S
    # Huihui-Qwen3.6-27B-abliterated-ggml-model-Q5_K (had issues with json generation, maybe ran out of mem, unclear)
    # Huihui-Qwen3.6-27B-abliterated-ggml-model-Q4_K
    # dolphin-2.9.1-yi-1.5-34b-Q4_K_M (very fast 24GB a bit too tight)
    set_env_value LLAMA_SERVER_MODEL "$CONTAINER_MODELS_DIR/llm/cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L/cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L.gguf"

    # max context in tokens
    set_env_value LLAMA_SERVER_MAX_CONTEXT 4096

    # GPU layers
    set_env_value LLAMA_SERVER_GPU_LAYERS -1 # -1 means all layers run on GPU

    # llama-server port
    set_env_value LLAMA_SERVER_PORT 8080

    # llama-server backend ie. rocm, cuda, intel
    set_env_value LLAMA_SERVER_BACKEND rocm
}

# deploy_components - Local component installer
# Usage: deploy_components "hub,node,llama,chat:docker"
# Args:
#   $1 - host configuration string
deploy_components() {
    local host_config="$1"

    print_section
    echo "deploy components..."
    
    echo "reading config $host_config"
    parse_host_config "$host_config"

    # pretend to be in build dir
    CURRENT_DIR=$(pwd)
    WORKING_DIR=$CURRENT_DIR
    CHAT_DIR="$WORKING_DIR/rueckgrat/chat"
    CADDY_DIR="$WORKING_DIR/rueckgrat/caddy"
    CADDY_KEY="$CADDY_DIR/rueckgrat-caddy.key"
    CADDY_CERT="$CADDY_DIR/rueckgrat-caddy.cert"

    write_default_env

    check_docker_group
    volume_cleanup
    gen_caddy_cert
    prep_app_data_dir

    echo "deploy..."

    if $INSTALL_HUB || $INSTALL_NODE; then
        install_dependencies curl
        install_docker            
    fi

    if $INSTALL_HUB; then
        install_caddy
        deploy_hub
    fi

    if $INSTALL_NODE; then
        if [[ "$INSTALL_IMAGE_GEN" == true || "$INSTALL_LLAMA" == true ]]; then
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
    
    if $INSTALL_CHAT_DOCKER; then
        deploy_chat_docker
    fi
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

    install_dependencies rsync sshpass

    print_section
    echo "🌐 Deploying to $host_addr"

    local remote_dir="Rueckgrat-install"
    local SSH_CONTROL="/tmp/deploy-$SUDO_USER-$(echo "$host_addr" | tr '@:' '__')"
    local SSH_OPTS=( -o ControlMaster=auto -o ControlPersist=5m -o ControlPath="$SSH_CONTROL" )

    trap 'ssh -O exit "${SSH_OPTS[@]}" "$host_addr" >/dev/null 2>&1 || true' EXIT

    sshpass -p "$SUDO_PASSWORD" ssh "${SSH_OPTS[@]}" -o User="$SUDO_USER" -Nf "$host_addr" || { echo "❌ Error: failed to connect with $host_addr"; return 1; }

    if $CLEAN_BUILD; then
        echo "Clean destination..."
        echo "$SUDO_PASSWORD" | ssh -tt "${SSH_OPTS[@]}" "$host_addr" "sudo rm -rf $remote_dir/*"
    fi

    echo "Copying files..."
    rsync -az --checksum -e "ssh ${SSH_OPTS[*]}" --exclude='.git' --exclude='logs' ./ "$host_addr:$remote_dir/" || {
        echo "❌ Error: rsync failed for $host_addr"
        return 1
    }

    echo "Running installer..."
    ssh "${SSH_OPTS[@]}" -t -o StrictHostKeyChecking=no -o ConnectTimeout=15 "$host_addr" "
        set -euo pipefail
        cd $remote_dir
        chmod +x install.sh
        ./install.sh --local-config '$clean_config' ${CLEAN_BUILD:+-f} ${VERBOSE:+-v} ${YES:+-y} -p $SUDO_PASSWORD -u $SUDO_USER
    " || echo "❌ Error: Installation failed on $host_addr"
}

# deploy_on_hosts - Iterate host components and execute installs per host
# Usage: deploy_on_hosts
# No arguments
deploy_on_hosts() {
    host_configs=$(jq -c '.hosts[]' "$CONFIG_FILE")
    for host_config in $host_configs; do
        deploy_components_remote "$host_config"        
    done
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
    rsync -az --checksum -e "ssh ${SSH_OPTS[*]}" --exclude='.git' --exclude='logs' ./ "$host_addr:$remote_dir/" || {
        echo "❌ Error: rsync failed for $host_addr"
        return 1
    }
    echo "✅ Synced to $host_addr:$remote_dir/"
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
readonly NODE_PORT_DEFAULT=7346
readonly CHAT_DOCKER_PORT_DEFAULT=3001
readonly LLAMA_SERVER_PORT_DEFAULT=8080
readonly APP_DATA_DIR=/var/lib/Rueckgrat
readonly HOST_MODELS_DIR="$APP_DATA_DIR/models"

main() {   
    export DOCKER_BUILDKIT=1
    export COMPOSE_DOCKER_CLI_BUILD=1

    get_info
    
    CONFIG_FILE=""
    VERBOSE=false
    DOCKER_PROGRESS_MODE="quiet"
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
            --local-config|-lc) # don't use --local-config unless you know what you are doing
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
            -v|--verbose) VERBOSE=true; DOCKER_PROGRESS_MODE="auto"; shift ;;
            -f|--fresh) CLEAN_BUILD=true; NO_CACHE="--no-cache"; shift ;;
            -s|--sync) SYNC_ONLY=true; shift ;;
            -y|--yes) YES=true; shift ;;
            -h|--help) usage; exit 0 ;;
            -i|--info) info; exit 0 ;;
            *) echo "Unknown option: $1"; exit 1 ;;
        esac
    done

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

        select_hosts_and_components
        confirm_install_configuration

        deploy_on_hosts

        echo "All done! Enjoy Rueckgrat ✨"
        print_section
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi