#!/bin/bash
# ===============================================
# Rueckgrat Linux Universal Installer
# Supports: Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE, etc.
# ===============================================

set -euo pipefail

echo "🚀 Rueckgrat Linux Installer"
echo "============================="

# Parse arguments
CHAT_ONLY=false
YES=false

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

# Package manager helpers
install_pkg() {
    echo "📦 installing $@ ..."
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

# ==================== BASIC DEPENDENCIES ==================
install_dependencies() {
    if ! command -v git &> /dev/null; then
        install_pkg git
    else    
        echo "✅ git already installed."
    fi

    if ! command -v python3 &> /dev/null; then
        install_pkg python3
    else    
        echo "✅ python3 already installed."
    fi
}

install_dependencies

# ==================== REPOSITORY SETUP ====================
echo "🔍 Checking repository..."

IN_WORKSPACE_INSTALL=true

if [[ -d ".git" ]]; then
    echo "✅ Already inside the Rueckgrat repository. Using branch '$(git branch --show-current)'."
elif [[ -d "Rueckgrat-install" ]]; then
    cd Rueckgrat-install
    echo "✅ Found repo in 'Rueckgrat-install' directory. Using branch: '$(git branch --show-current)'."
    IN_WORKSPACE_INSTALL=false
else
    echo "📥 Cloning fresh copy..."
    
    # Clone as current user (important!)
    sudo -u $(whoami) git clone https://github.com/tanzfisch/Rueckgrat.git Rueckgrat-install
    
    cd Rueckgrat-install
    echo "✅ Repository cloned successfully."
    IN_WORKSPACE_INSTALL=false
fi

# ==================== COMPONENT SELECTION ====================
echo ""
echo "Component Selection:"

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
        read -p "Install Hub? (Y/n): " -r install_hub < /dev/stdin
        install_hub=${install_hub:-Y}
        read -p "Install Node? (Y/n): " -r install_node < /dev/stdin
        install_node=${install_node:-Y}

        [[ "${install_hub:-}"  =~ ^[Yy]$ ]] && INSTALL_HUB=true
        [[ "${install_node:-}" =~ ^[Yy]$ ]] && INSTALL_NODE=true
        [[ "${install_chat:-}" =~ ^[Yy]$ ]] && INSTALL_CHAT=true

        if $INSTALL_NODE; then
          read -p "Install llama-server (recommended)? (Y/n): " -r install_llama < /dev/stdin
          install_llama=${install_llama:-Y}
          [[ -z "${install_llama:-}" || "${install_llama:-}" =~ ^[Yy]$ ]] && INSTALL_LLAMA=true
        fi
    fi
fi

if ! $INSTALL_HUB && ! $INSTALL_NODE && ! $INSTALL_CHAT; then
  echo "❌ Nothing selected. Exiting."
  exit 0
fi

# ==================== DOCKER (only if needed) ====================
install_docker() {
    if ! command -v docker &> /dev/null; then
        echo "🐳 Installing Docker via official script..."
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        rm -f get-docker.sh

        sudo usermod -aG docker "$USER"
        echo "✅ Docker installed. Log out/in for group changes."
    else
        echo "✅ Docker already installed."
    fi
}

if ! $CHAT_ONLY; then
    install_docker
fi

# ==================== CADDY ====================
install_caddy() {
    if command -v caddy &> /dev/null; then
        echo "✅ Caddy already installed."
        return
    fi

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

# ==================== VOLUME CLEANUP ====================
if $INSTALL_HUB || $INSTALL_NODE; then
    echo "🔍 Checking existing Rueckgrat containers..."
    RUNNING_CONTAINERS=$(docker ps -q --filter "name=rueckgrat" 2>/dev/null | wc -l)

    if [[ $RUNNING_CONTAINERS -gt 0 ]]; then
        echo "⚠️  Found running Rueckgrat containers."
        if $YES; then
            keep_previous="N"
        else
            read -p "Keep previous installation (reuse volumes & containers)? (y/N): " -r keep_previous < /dev/stdin
            keep_previous=${keep_previous:-N}
        fi
        
        if [[ "${keep_previous:-}" =~ ^[Nn]$ ]]; then
            echo "🛑 Stopping and removing previous Rueckgrat installation..."
            
            docker ps -q --filter "name=rueckgrat" | xargs -r docker stop 2>/dev/null || true
            docker ps -a -q --filter "name=rueckgrat" | xargs -r docker rm -f 2>/dev/null || true
            
            echo "🗑️  Removing old volumes..."
            for vol in rueckgrat_caddy_data rueckgrat_caddy_config rueckgrat_node_images rueckgrat_hub_db rueckgrat_hub_images; do
                docker volume rm "$vol" 2>/dev/null || true
            done
            echo "✅ Previous installation cleaned up."
        else
            echo "✅ Keeping previous installation (reusing volumes and containers)."
        fi
    fi
fi

# ==================== HUB ====================
if $INSTALL_HUB; then
    install_caddy

    pushd rueckgrat > /dev/null
    if [[ -f .env.example ]]; then
        cp -n .env.example .env 2>/dev/null || true
        echo "✅ .env created from template."
    fi

    echo "🐋 compose up hub & daddy..."
    docker compose up --build -d hub caddy || echo "❌ Docker compose failed."
    popd > /dev/null
fi

# ==================== NODE ====================
if $INSTALL_NODE; then
    if ! $INSTALL_HUB; then
        if $YES; then
            HUB_ADDR="localhost"
        else
            read -p "Hub IP/hostname (default: localhost): " -r HUB_ADDR < /dev/stdin
            HUB_ADDR=${HUB_ADDR:-localhost}
        fi

        pushd rueckgrat > /dev/null
        if [[ -f .env.example && ! -f .env ]]; then
            cp .env.example .env
        fi
        echo "⚙️ update .env"
        sed -i "s|^#HUB_IP=.*|HUB_IP=${HUB_ADDR}|" .env 2>/dev/null || true
        popd > /dev/null
    fi

    pushd rueckgrat > /dev/null
    echo "🐋 compose up node..."
    docker compose up --build -d node || { echo "❌ Node failed."; popd; exit 1; }
    popd > /dev/null

    if $INSTALL_LLAMA; then
        pushd rueckgrat > /dev/null
        docker compose up --build -d llama-server || { echo "❌ llama-server failed."; popd; exit 1; }
        popd > /dev/null
    fi
fi

# ==================== CHAT CLIENT ====================
if $INSTALL_CHAT; then
    echo "📦 Installing Chat Client..."
    pushd chat > /dev/null
    ./install.sh || { echo "❌ Chat install failed!"; popd; exit 1; }
    popd > /dev/null
fi

echo ""
echo "🎉 Installation finished!"

BASE_DIR=$([ "$IN_WORKSPACE_INSTALL" = true ] && echo "" || echo "Rueckgrat-install/")

if $INSTALL_HUB || $INSTALL_NODE; then
    echo ""
    echo "→ Services:  cd ${BASE_DIR}rueckgrat && docker compose ps"
    echo "→ Logs:      cd ${BASE_DIR}rueckgrat && docker compose logs -f"
fi

if $INSTALL_CHAT; then
    echo ""
    echo "In oder to use the chat. Get the certificate from your caddy installation"
    echo "For example like this:"
    echo "curl -k https://localhost/health"
    echo "docker cp rueckgrat-caddy-1:/data/caddy/pki/authorities/local/root.crt ~/.ssh/caddy-root.crt"
    echo ""
    echo "At first start, chat should ask you for the network settings. If not check ~/.config/Rueckgrat/rueckgrat.conf"
    echo "The hub (via caddy) is configured to listen to rueckgrat.hub and localhost" # TODO
    echo ""
    echo "→ Chat:      cd ${BASE_DIR}chat && ./run.sh"
fi

echo ""
echo "All done! Enjoy Rueckgrat ✨"
