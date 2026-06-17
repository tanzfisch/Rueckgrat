#!/bin/bash
# ===============================================
# Rueckgrat Linux One-Line Installer
# ===============================================

set -euo pipefail

echo "🚀 Rueckgrat Linux Installer"
echo "============================="

# If not running from inside the repo, clone it first
if [[ ! -d "rueckgrat" && ! -d ".git" ]]; then
  echo "📥 Repository not found. Cloning Rueckgrat..."
  git clone https://github.com/tanzfisch/Rueckgrat.git Rueckgrat-temp
  cd Rueckgrat-temp
  echo "✅ Repository cloned successfully."
else
  echo "✅ Running from existing repository."
fi

# Ask main components
read -p "Install Hub? (y/N): " install_hub
read -p "Install Node? (y/N): " install_node
read -p "Install Chat Client? (y/N): " install_chat

INSTALL_HUB=false
INSTALL_NODE=false
INSTALL_LLAMA=false
INSTALL_CHAT=false

[[ "$install_hub"  =~ ^[Yy]$ ]] && INSTALL_HUB=true
[[ "$install_node" =~ ^[Yy]$ ]] && INSTALL_NODE=true
[[ "$install_chat" =~ ^[Yy]$ ]] && INSTALL_CHAT=true

# Extra question for llama-server if Node is selected
if $INSTALL_NODE; then
  read -p "Install llama-server (recommended for LLM)? (Y/n): " install_llama
  [[ -z "$install_llama" || "$install_llama" =~ ^[Yy]$ ]] && INSTALL_LLAMA=true
fi

if ! $INSTALL_HUB && ! $INSTALL_NODE && ! $INSTALL_CHAT; then
  echo "❌ Nothing selected. Exiting."
  exit 0
fi

echo "📦 update system packages..."
sudo apt-get update -y

# ==================== HUB ====================
if $INSTALL_HUB; then
  echo "📦 Installing / Starting Hub + Caddy..."

  # Install Caddy if not present
  if ! command -v caddy &> /dev/null; then
      echo "Installing Caddy..."
      sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
      sudo apt update -y
      sudo apt install caddy -y
  fi  

  cd rueckgrat

    if [[ -f .env.example ]]; then
      cp -n .env.example .env 2>/dev/null || true
      echo "✅ Created new .env from template"
    else
      echo "❌ .env.example not found."
    fi

  docker compose up --build -d hub caddy || echo "❌ Docker compose failed (is Docker running?)"
  cd -
fi

# ==================== NODE ====================
if $INSTALL_NODE; then
  echo "📦 Installing / Starting Node..."

  # If installing Node without Hub → ask for Hub address
  if ! $INSTALL_HUB; then
    echo ""
    echo "Since you're installing Node without the Hub, please provide the Hub address."
    read -p "Hub IP or hostname (default: localhost): " HUB_ADDR
    HUB_ADDR=${HUB_ADDR:-localhost}

    cd rueckgrat
    if [[ -f .env.example ]]; then
      if [[ ! -f .env ]]; then
        cp .env.example .env
        echo "✅ Created new .env from template"
      fi
      sed -i "s|^#HUB_IP=.*|HUB_IP=${HUB_ADDR}|" .env 2>/dev/null || true
      echo "✅ Updated .env with HUB_IP=${HUB_ADDR}"
    else
      echo "❌ .env.example not found. Please configure HUB_IP manually."
    fi
    cd -
  fi

  cd rueckgrat
  docker compose up --build -d node || {
    echo "❌  Docker compose failed (is Docker running?)"
    cd -
    exit 1         
  }
  cd -
  
  if $INSTALL_LLAMA; then
    echo "📦 Installing / Starting llama-server..."
    cd rueckgrat
    docker compose up --build -d llama-server || {
      echo "❌  Docker compose failed (is Docker running?)"
      cd - 
      exit 1         
    }
    cd -
  fi
  
  echo "💡 Tip: For ComfyUI run 'cd ComfyUI && ./install.sh' separately if needed."
fi

# ==================== CHAT CLIENT ====================
if $INSTALL_CHAT; then
  echo "📦 Installing Chat Client..."
  cd chat
  ./install.sh || {
    echo "❌ Chat client installation failed!"
    cd -
    exit 1 
  }
  echo "✅ Chat client ready"
  cd -
fi

echo ""
echo "🎉 Installation finished!"
echo ""

if $INSTALL_HUB || $INSTALL_NODE; then
  echo "→ Check services:   docker compose ps"
  echo "→ View logs:        docker compose logs -f"
fi

if $INSTALL_CHAT; then
  echo "→ Start Chat:       cd chat && ./run.sh"
fi

echo ""
echo "All done! Enjoy Rueckgrat ✨"