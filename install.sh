#!/bin/bash
# ===============================================
# Rueckgrat Linux Universal Installer
# Supports: Debian/Ubuntu, Fedora/RHEL, Arch, openSUSE, etc.
# ===============================================

set -euo pipefail

echo "🚀 Rueckgrat Linux Installer"
echo "============================="

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
            echo "❌ Unsupported distro. Please install dependencies manually."
            exit 1
            ;;
    esac
}

# ==================== REPOSITORY SETUP ====================
echo "📥 Checking repository..."

if [[ -d ".git" ]]; then
    echo "✅ Already inside Rueckgrat repository."
elif [[ -d "Rueckgrat-temp" ]]; then
    echo "✅ Found 'Rueckgrat-temp', entering..."
    cd Rueckgrat-temp
else
    echo "📥 Cloning fresh copy..."
    git clone https://github.com/tanzfisch/Rueckgrat.git Rueckgrat-temp
    cd Rueckgrat-temp
    echo "✅ Cloned successfully."
fi

# ==================== COMPONENT SELECTION ====================
echo ""
echo "Component Selection:"

# Force reading from terminal (important for curl | bash)
INSTALL_HUB=false
INSTALL_NODE=false
INSTALL_LLAMA=false
INSTALL_CHAT=false

read -p "Install Chat Client? (y/N): " -r install_chat </dev/tty
read -p "Install Hub? (y/N): " -r install_hub </dev/tty
read -p "Install Node? (y/N): " -r install_node </dev/tty

[[ "${install_hub:-}"  =~ ^[Yy]$ ]] && INSTALL_HUB=true
[[ "${install_node:-}" =~ ^[Yy]$ ]] && INSTALL_NODE=true
[[ "${install_chat:-}" =~ ^[Yy]$ ]] && INSTALL_CHAT=true

if $INSTALL_NODE; then
  read -p "Install llama-server (recommended)? (Y/n): " -r install_llama </dev/tty
  [[ -z "${install_llama:-}" || "${install_llama:-}" =~ ^[Yy]$ ]] && INSTALL_LLAMA=true
fi

if ! $INSTALL_HUB && ! $INSTALL_NODE && ! $INSTALL_CHAT; then
  echo "❌ Nothing selected. Exiting."
  exit 0
fi

# ==================== DOCKER (only if needed) ====================
if $INSTALL_HUB || $INSTALL_NODE; then
    echo "📦 Checking Docker..."

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

    # Fallback to package manager
    case "$DISTRO" in
        *debian*|*ubuntu*) install_pkg caddy ;;
        *fedora*|*rhel*)   sudo dnf install -y caddy ;;
        *arch*)            sudo pacman -S --noconfirm caddy ;;
        *suse*)            sudo zypper install -y caddy ;;
    esac
}

# ==================== VOLUME CLEANUP ====================
if $INSTALL_HUB || $INSTALL_NODE; then
    echo "🔍 Checking existing Rueckgrat containers..."
    RUNNING_CONTAINERS=$(docker ps -q --filter "name=rueckgrat" 2>/dev/null | wc -l)

    if [[ $RUNNING_CONTAINERS -gt 0 ]]; then
        echo "⚠️  Found running Rueckgrat containers."
        read -p "Stop and remove previous installation? (y/N): " clean_install
        if [[ "$clean_install" =~ ^[Yy]$ ]]; then
            echo "🛑 Cleaning up..."
            docker ps -q --filter "name=rueckgrat" | xargs -r docker stop 2>/dev/null || true
            docker ps -a -q --filter "name=rueckgrat" | xargs -r docker rm -f 2>/dev/null || true
            for vol in rueckgrat_caddy_data rueckgrat_caddy_config rueckgrat_node_images rueckgrat_hub_db rueckgrat_hub_images; do
                docker volume rm "$vol" 2>/dev/null || true
            done
            echo "✅ Cleanup complete."
        fi
    fi
fi

# ==================== HUB ====================
if $INSTALL_HUB; then
    echo "📦 Installing / Starting Hub + Caddy..."
    install_caddy

    pushd rueckgrat > /dev/null
    if [[ -f .env.example ]]; then
        cp -n .env.example .env 2>/dev/null || true
        echo "✅ .env created from template."
    fi
    docker compose up --build -d hub caddy || echo "❌ Docker compose failed."
    popd > /dev/null
fi

# ==================== NODE ====================
if $INSTALL_NODE; then
    echo "📦 Installing / Starting Node..."

    if ! $INSTALL_HUB; then
        read -p "Hub IP/hostname (default: localhost): " HUB_ADDR
        HUB_ADDR=${HUB_ADDR:-localhost}

        pushd rueckgrat > /dev/null
        if [[ -f .env.example && ! -f .env ]]; then
            cp .env.example .env
        fi
        sed -i "s|^#HUB_IP=.*|HUB_IP=${HUB_ADDR}|" .env 2>/dev/null || true
        popd > /dev/null
    fi

    pushd rueckgrat > /dev/null
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
if $INSTALL_HUB || $INSTALL_NODE; then
    echo "→ Services:  docker compose ps"
    echo "→ Logs:      docker compose logs -f"
fi
if $INSTALL_CHAT; then
    echo "→ Chat:      cd chat && ./run.sh"
fi

echo ""
echo "All done! Enjoy Rueckgrat ✨"
