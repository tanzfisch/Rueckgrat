#!/bin/bash
# ===============================================
# Rueckgrat Linux Universal Installer
# Supports: Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE, etc.
# ===============================================

set -euo pipefail

print_header() {
    local text="$1"
    local width=$(tput cols)
    printf '\033[36m%*s\033[0m\n' "$width" '' | tr ' ' '_'
    echo ""
    printf '\033[1m%*s\033[0m\n' $(( (width + ${#text}) / 2 )) "$text"
    printf '\033[36m%*s\033[0m\n' "$width" '' | tr ' ' '_'
    echo ""
}

print_section() {
    local width=$(tput cols)
    printf '\033[36m%*s\033[0m\n' "$width" '' | tr ' ' '_'
    echo ""
}

print_header "🚀 Rückgrat Installer"

# ==================== GLOBALS ==============================
HUB_HOSTNAME="rueckgrat.hub"

# ==================== HANDLE PARAMETERS ====================
CHAT_ONLY=false
YES=false
VERBOSE=false
DOCKER_PROGRESS_MODE="quiet"
CLEAN_BUILD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --chat_only)
            CHAT_ONLY=true
            shift
            ;;
        -y|--yes)
            YES=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            DOCKER_PROGRESS_MODE="auto"
            shift
            ;;
        -c|--clean)
            NO_CACHE=--no-cache
            CLEAN_BUILD=true
            shift
            ;;
        --hub-ip)
            HUB_ADDR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ==================== DISTRO DETECTION ====================
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        DISTRO=${ID_LIKE:-$ID}
        VERSION=${VERSION_ID:-}
    else
        DISTRO="unknown"
    fi

    echo "Detected: $PRETTY_NAME ($DISTRO $VERSION)"
}

detect_distro

# ==================== VOLUME CLEANUP ====================
ALL_CONTAINERS=$(docker ps -a -q --filter "name=rueckgrat" 2>/dev/null | wc -l)

if [[ $ALL_CONTAINERS -gt 0 ]]; then
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

    if $YES; then
        keep_previous="Y"
    else
        read -p "Keep previous installation (reuse volumes & containers)? (Y/n): " -r keep_previous < /dev/stdin
        keep_previous=${keep_previous:-Y}
    fi
    
    if [[ "${keep_previous:-}" =~ ^[Nn]$ ]]; then
        echo "🗑️ Removing previous Rueckgrat installation..."
        docker ps -q --filter "name=rueckgrat" | xargs -r docker stop 2>/dev/null || true
        docker ps -a -q --filter "name=rueckgrat" | xargs -r docker rm -f 2>/dev/null || true
        
        for vol in rueckgrat_caddy_data rueckgrat_caddy_config rueckgrat_node_images rueckgrat_hub_db rueckgrat_hub_images; do
            docker volume rm "$vol" 2>/dev/null || true
        done
        
        docker network rm rueckgrat-net-local 2>/dev/null || true
        
        echo "✅ Previous installation cleaned up."
    fi
fi

# ==================== PACKAGE MANAGER HELPER ==============
install_pkg() {
    case "$DISTRO" in
        *debian*|*ubuntu*)
            sudo apt update -y && sudo apt install -y "$@"
            ;;
        *fedora*|*rhel*|*centos*|*rocky*|*alma*)
            sudo dnf install -y "$@"
            ;;
        *arch*)
            sudo pacman -Syu --noconfirm "$@"
            ;;
        *suse*|*opensuse*)
            sudo zypper install -y "$@"
            ;;
        *)
            echo "❌ Unsupported distro. Please install $@ manually."
            exit 1
            ;;
    esac
}

# ==================== DEPENDENCIES ========================
deps=(git python3)
missing_deps=()
for pkg in "${deps[@]}"; do
    if ! command -v "$pkg" &> /dev/null; then
        missing_deps+=("$pkg")
    fi
done

if [ ${#missing_deps[@]} -gt 0 ]; then
    print_section
    echo "📦 installing missing dependencies..."
    echo "${missing_deps[*]}"
    echo ""

    install_pkg "${missing_deps[@]}"
    echo "✅ finished installing dependencies"
fi

# ==================== REPOSITORY SETUP ====================
print_section
IN_WORKSPACE_INSTALL=true

if [[ -d ".git" ]]; then
    echo "✅ Using branch '$(git branch --show-current)'."
    git pull
elif [[ -d "Rueckgrat-install" ]]; then
    cd Rueckgrat-install
    echo "✅ Using branch: '$(git branch --show-current)'."
    git pull
    IN_WORKSPACE_INSTALL=false
else
    echo "📥 Cloning fresh copy..."
    sudo -u $(whoami) git clone https://github.com/tanzfisch/Rueckgrat.git Rueckgrat-install
    
    cd Rueckgrat-install
    echo "✅ Using branch: '$(git branch --show-current)'."
    IN_WORKSPACE_INSTALL=false
fi

# current dir depends on workspace
CURRENT_DIR=$(pwd)
BUILD_DIR="$CURRENT_DIR/build"
CERT_DIR="$BUILD_DIR/certs"
CADDY_CERT=$CERT_DIR/rueckgrat-caddy.crt
LOGS_DIR="$CURRENT_DIR/logs"

safe_rm_rf() {
    local dir="$1"
    if [[ -z "$dir" || ! -e "$dir" ]]; then
        return 0
    fi
    
    echo "🗑️ $dir"
    if [[ -w "$dir" ]] || [[ -w "$(dirname "$dir")" ]]; then
        rm -rf "$dir"
    else
        sudo rm -rf "$dir"
    fi
}

if $CLEAN_BUILD; then
    print_section
    echo "🧹 clean up build..."
    safe_rm_rf "$BUILD_DIR"
    safe_rm_rf "$LOGS_DIR"
fi

mkdir -p $BUILD_DIR && chmod 777 $BUILD_DIR
mkdir -p $CERT_DIR && chmod 777 $CERT_DIR
mkdir -p $LOGS_DIR && chmod 777 $LOGS_DIR

# ==================== COMPONENT SELECTION ====================
if ! $YES; then
    print_section
    echo "Component Selection"
    echo ""
fi

INSTALL_CHAT_DOCKER=false

if $CHAT_ONLY; then
    INSTALL_CHAT=true
    INSTALL_HUB=false
    INSTALL_NODE=false
    INSTALL_LLAMA=false
else
    INSTALL_HUB=false
    INSTALL_NODE=false
    INSTALL_CHAT=false
    INSTALL_LLAMA=false

    if $YES; then
        INSTALL_CHAT=true
        INSTALL_HUB=true
        INSTALL_NODE=true
        INSTALL_LLAMA=true
    else
        read -p "Install Chat Client? (Y/n): " -r install_chat < /dev/stdin
        install_chat=${install_chat:-Y}
        [[ "${install_chat:-}" =~ ^[Yy]$ ]] && INSTALL_CHAT=true
        
        if $INSTALL_CHAT; then
            if $YES; then
                INSTALL_CHAT_DOCKER=false
            else
                read -p "Install Chat via Docker (instead of native)? (y/N): " -r chat_docker < /dev/stdin
                chat_docker=${chat_docker:-N}
                [[ -n "${chat_docker}" && "${chat_docker}" =~ ^[Yy]$ ]] && INSTALL_CHAT_DOCKER=true || INSTALL_CHAT_DOCKER=false
            fi
        fi

        read -p "Install Hub? (Y/n): " -r install_hub < /dev/stdin
        install_hub=${install_hub:-Y}
        [[ "${install_hub:-}"  =~ ^[Yy]$ ]] && INSTALL_HUB=true

        read -p "Install Node? (Y/n): " -r install_node < /dev/stdin
        install_node=${install_node:-Y}
        [[ "${install_node:-}" =~ ^[Yy]$ ]] && INSTALL_NODE=true

        if $INSTALL_NODE; then
          read -p "Install llama-server on Node? (Y/n): " -r install_llama < /dev/stdin
          install_llama=${install_llama:-Y}
          [[ -z "${install_llama:-}" || "${install_llama:-}" =~ ^[Yy]$ ]] && INSTALL_LLAMA=true
        fi
    fi
fi

if ! $INSTALL_HUB && ! $INSTALL_NODE && ! $INSTALL_CHAT; then
  echo "❌ Nothing selected. Exiting."
  exit 0
fi

if [[ -z "$HUB_ADDR" ]]; then
    print_section
    read -p "Hub IP: " -r HUB_ADDR < /dev/stdin
fi

if [[ ! $HUB_ADDR =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ Invalid IP address"
    exit 1
fi

if ! grep -q "\b$HUB_HOSTNAME\b" /etc/hosts; then
    if $YES; then
        confirm="Y"
    else
        print_section
        read -p "Add $HUB_ADDR $HUB_HOSTNAME to /etc/hosts? (Y/n) " -r confirm
    fi

    if [[ -z $confirm || $confirm =~ ^[Yy]$ ]]; then
        echo "$HUB_ADDR $HUB_HOSTNAME" | sudo tee -a /etc/hosts >/dev/null
        if ! $YES; then
            echo "✅ Added to /etc/hosts"
        fi
    fi
fi

# ==================== DOCKER (only if needed) ====================
install_docker() {
    if command -v docker &> /dev/null; then
        return
    fi

    print_section
    echo "🐳 Installing Docker via official script..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm -f get-docker.sh

    sudo usermod -aG docker "$USER"
    echo "✅ Docker installed. Log out/in for group changes."
}

if ! $CHAT_ONLY || $INSTALL_CHAT_DOCKER; then
    install_docker
fi

# ==================== CADDY ====================
install_caddy() {
    if command -v caddy &> /dev/null; then
        return
    fi

    print_section
    echo "📦 Installing Caddy (static binary preferred)..."

    # Try static binary first (most universal)
    if command -v curl &> /dev/null; then
        curl -fsSL https://caddyserver.com/api/download?os=linux&arch=amd64 -o /tmp/caddy
        sudo install -m 755 /tmp/caddy /usr/local/bin/caddy
        rm -f /tmp/caddy
        echo "✅ Caddy installed via static binary."
        return
    fi

    # fallback to package manager
    install_pkg caddy
}

if $INSTALL_HUB; then
    install_caddy
fi

# ==================== HUB ====================
if $INSTALL_HUB; then
    print_section
    echo "⬇️ installing hub & caddy..."

    pushd rueckgrat > /dev/null
    if [[ -f .env.example ]]; then
        cp -n .env.example .env 2>/dev/null || true
        echo "✅ .env created from template."
    fi

    echo "🐋 hub & caddy..."
    docker compose --progress=$DOCKER_PROGRESS_MODE build ${NO_CACHE:-} hub caddy || { echo "❌ Docker compose build of hub & daddy failed."; popd; exit 1; }
    docker compose up -d hub caddy || { echo "❌ Docker compose up of hub & daddy failed."; popd; exit 1; }
    popd > /dev/null

    sleep 5
fi

# ==================== RETRIEVE CADDY CERTIFICATE ====================
print_section
echo "🔑 Retrieving Caddy root certificate..."
RESPONSE=$(curl -k -s https://rueckgrat.hub/health 2> /dev/null)
if [ ! "$RESPONSE" = '{"status":"ok"}' ]; then
    echo "❌ Could not connect to caddy."
    exit 1
fi

if docker cp rueckgrat-caddy-1:/data/caddy/pki/authorities/local/root.crt $CADDY_CERT 2>/dev/null; then
    echo "✅ Certificate stored in $CADDY_CERT"
else
    echo "❌ Could not copy caddy certificate."
    exit 1
fi

# ==================== NODE ====================
if $INSTALL_NODE; then
    print_section
    echo "⬇️ installing node..."

    if ! $INSTALL_HUB; then
        pushd rueckgrat > /dev/null
        if [[ -f .env.example && ! -f .env ]]; then
            cp .env.example .env
        fi
        echo "⚙️ update .env"
        sed -i "s|^#HUB_HOST=.*|HUB_HOST=${HUB_HOSTNAME}|" .env 2>/dev/null || true
        popd > /dev/null
    fi

    pushd rueckgrat > /dev/null
    echo "🐋 node..."
    docker compose --progress=$DOCKER_PROGRESS_MODE build ${NO_CACHE:-} node || { echo "❌ Docker compose build of node failed."; popd; exit 1; }
    docker compose up -d node || { echo "❌ Docker compose up of node failed."; popd; exit 1; }
    popd > /dev/null
fi

if $INSTALL_LLAMA; then
    print_section
    echo "⬇️ installing llama-server..."

    source scripts/registry_functions.sh

    DEFAULT_LLM="cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L"
    DEFAULT_HOST="localhost:7346"
    declare -a MODEL_NAMES
    declare -i DEFAULT_IDX=-1
    VERBOSE=$([[ $YES == false ]] && echo true || echo false)
    fetch_llm_models $DEFAULT_LLM $DEFAULT_HOST MODEL_NAMES DEFAULT_IDX $VERBOSE || { exit 1; }

    if $YES; then
        idx=$DEFAULT_IDX
    else
        read -p "📋 Select model [$DEFAULT_LLM]: " idx
        idx=${idx:-$DEFAULT_IDX}
    fi
    LLM_MODEL="${MODEL_NAMES[$((idx-1))]}"

    install_llm "$LLM_MODEL" || { exit 1; }

    pushd rueckgrat > /dev/null
    GGUF_FILE_PATH="/models/llm/$LLM_MODEL/$LLM_MODEL.gguf"
    sed -i "s|^LLAMA_CPP_MODEL=.*|LLAMA_CPP_MODEL=$GGUF_FILE_PATH|" .env

    echo "🐋 llama-server..."
    docker compose --progress=$DOCKER_PROGRESS_MODE build ${NO_CACHE:-} llama-server || { echo "❌ Docker compose build of llama-server failed."; popd; exit 1; }
    docker compose up -d llama-server || { echo "❌ Docker compose up of llama-server failed."; popd; exit 1; }
    popd > /dev/null
fi

# ==================== CHAT CLIENT ====================
if $INSTALL_CHAT; then   
    print_section
    echo "⬇️ installing chat..."

    if $INSTALL_CHAT_DOCKER; then
        pushd rueckgrat > /dev/null

        mkdir -p chat/build
        if [[ -f $CADDY_CERT ]]; then
            cp $CADDY_CERT chat/build/
        else
            echo "❌ Certificate not found at $CADDY_CERT"
            exit 1
        fi

        echo "🐋 chat..."
        docker compose --progress=$DOCKER_PROGRESS_MODE build ${NO_CACHE:-} chat || { echo "❌ Docker compose build of chat failed."; popd; exit 1; }
        docker compose up -d chat || { echo "❌ Docker compose up of chat failed."; popd; exit 1; }
        popd > /dev/null
    else
        echo "📦 install chat..."
        pushd rueckgrat/chat > /dev/null
        ./install.sh "$CADDY_CERT" || { echo "❌ Chat native install failed!"; popd; exit 1; }
        popd > /dev/null
    fi
fi

print_header "🎉 Installation finished!"

BASE_DIR=$([ "$IN_WORKSPACE_INSTALL" = true ] && echo "" || echo "Rueckgrat-install/")

if $INSTALL_HUB || $INSTALL_NODE || $INSTALL_CHAT_DOCKER; then
    echo ""
    echo "→ Services:  cd ${BASE_DIR}rueckgrat && docker compose ps"
    echo "→ Logs:      cd ${BASE_DIR}rueckgrat && docker compose logs -f"
fi

if $INSTALL_CHAT && ! $INSTALL_CHAT_DOCKER; then
    echo ""
    echo "In oder to use the chat. Get the certificate from your caddy installation"
    echo "For example like this:"
    echo "curl -k https://localhost/health"
    echo "docker cp rueckgrat-caddy-1:/data/caddy/pki/authorities/local/root.crt ~/.ssh/caddy-root.crt"
    echo ""
    echo "At first start, chat should ask you for the network settings. If not check ~/.config/Rueckgrat/rueckgrat.conf"
    echo "The hub (via caddy) is configured to listen to rueckgrat.hub and localhost" # TODO
    echo ""
    echo "→ Chat:      cd ${BASE_DIR}rueckgrat/chat && ./run.sh"
fi

echo ""
echo "All done! Enjoy Rueckgrat ✨"
print_section