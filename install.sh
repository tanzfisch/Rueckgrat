#!/bin/bash
# ===============================================
# Rueckgrat Linux One-Line Installer
# ===============================================

set -euo pipefail

echo "🚀 Rueckgrat Linux Installer"
echo "============================="

# ==================== REPOSITORY SETUP ====================
echo "📥 Checking repository..."

if [[ -d ".git" ]]; then
  echo "✅ Already running inside the Rueckgrat repository."
elif [[ -d "Rueckgrat-temp" ]]; then
  echo "✅ Found 'Rueckgrat-temp' directory, entering it..."
  cd Rueckgrat-temp
else
  echo "📥 Repository not found. Cloning fresh copy..."
  git clone https://github.com/tanzfisch/Rueckgrat.git Rueckgrat-temp
  cd Rueckgrat-temp
  echo "✅ Repository cloned successfully."
fi

# Ask main components
read -p "Install Chat Client? (y/N): " install_chat
read -p "Install Hub (the server the chat client connects to)? (y/N): " install_hub
read -p "Install Node (servers that work for the hub)? (y/N): " install_node

INSTALL_HUB=false
INSTALL_NODE=false
INSTALL_LLAMA=false
INSTALL_CHAT=false

[[ "$install_hub"  =~ ^[Yy]$ ]] && INSTALL_HUB=true
[[ "$install_node" =~ ^[Yy]$ ]] && INSTALL_NODE=true
[[ "$install_chat" =~ ^[Yy]$ ]] && INSTALL_CHAT=true

if $INSTALL_NODE; then
  read -p "Install llama-server (recommended for LLM)? (Y/n): " install_llama
  [[ -z "$install_llama" || "$install_llama" =~ ^[Yy]$ ]] && INSTALL_LLAMA=true
fi

if ! $INSTALL_HUB && ! $INSTALL_NODE && ! $INSTALL_CHAT; then
  echo "❌ Nothing selected. Exiting."
  exit 0
fi

# ==================== DOCKER INSTALLATION (only if needed) ====================
if $INSTALL_HUB || $INSTALL_NODE; then
  echo "📦 Checking Docker installation..."

  if ! command -v docker &> /dev/null; then
    echo "🐳 Docker not found. Installing Docker..."

    sudo apt update -y
    sudo apt install -y extrepo curl

    sudo extrepo enable docker-ce
    sudo apt update -y

    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-model-plugin

    echo "✅ Docker installed successfully."

    sudo usermod -aG docker "$USER"
    echo "✅ Added user to docker group (you may need to log out and log back in)."

    docker model install-runner || echo "⚠️ Could not install docker model runner."
  else
    echo "✅ Docker is already installed."
  fi
fi

# ==================== VOLUME CHECK (before starting services) ====================
if $INSTALL_HUB || $INSTALL_NODE; then
  echo ""
  echo "🔍 Checking for existing Rueckgrat installation..."

  RUNNING_CONTAINERS=$(docker ps -q --filter "name=rueckgrat" 2>/dev/null | wc -l)

  if [[ $RUNNING_CONTAINERS -gt 0 ]]; then
    echo "⚠️  Found running Rueckgrat containers. There is no guarantee they are compatible with the new installation."
    read -p "Do you want to stop and remove the previous installation? (y/N): " clean_install
    
    if [[ "$clean_install" =~ ^[Yy]$ ]]; then
      echo "🛑 Stopping all Rueckgrat containers..."
      docker ps -q --filter "name=rueckgrat" | xargs -r docker stop 2>/dev/null || true
      
      echo "🗑️  Removing containers..."
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
  echo "📦 Installing / Starting Hub + Caddy..."

  # Install Caddy if not present
  if ! command -v caddy &> /dev/null; then
      echo "📦 Installing Caddy..."
      sudo apt update -y
      sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
      sudo apt update -y
      sudo apt install caddy -y
  fi  

  pushd rueckgrat > /dev/null

    if [[ -f .env.example ]]; then
      cp -n .env.example .env 2>/dev/null || true
      echo "✅ Created new .env from template"
    else
      echo "❌ .env.example not found."
    fi

  docker compose up --build -d hub caddy || echo "❌ Docker compose failed (is Docker running?)"
  popd > /dev/null
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

    pushd rueckgrat > /dev/null
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
    popd > /dev/null
  fi

  pushd rueckgrat > /dev/null
  docker compose up --build -d node || {
    echo "❌  Docker compose failed (is Docker running?)"
    popd > /dev/null
    exit 1         
  }
  popd > /dev/null
  
  if $INSTALL_LLAMA; then
    echo "📦 Installing / Starting llama-server..."
    pushd rueckgrat > /dev/null
    docker compose up --build -d llama-server || {
      echo "❌  Docker compose failed (is Docker running?)"
      popd > /dev/null 
      exit 1         
    }
    popd > /dev/null
  fi
  
  echo "💡 Tip: For ComfyUI run 'cd ComfyUI && ./install.sh' separately if needed."
fi

# ==================== CHAT CLIENT ====================
if $INSTALL_CHAT; then
  echo "📦 Installing Chat Client..."
  pushd chat > /dev/null
  ./install.sh || {
    echo "❌ Chat client installation failed!"
    popd > /dev/null
    exit 1 
  }
  echo "✅ Chat client ready"
  popd > /dev/null
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