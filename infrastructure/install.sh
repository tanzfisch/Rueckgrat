#!/bin/bash

set -euo pipefail

SERVICE_NAME="Rueckgrat_infrastructure"
DOMAIN="localhost"
PORT="7346"

echo
echo "=== Install infrastructure node ==="

# Ask for domain
echo
read -p "Enter your public domain or IP (default ${DOMAIN}): " USER_DOMAIN

if [ -z "$USER_DOMAIN" ]; then
    echo "Use default domain ${DOMAIN}"
else
    DOMAIN=$USER_DOMAIN
    echo "Using domain ${DOMAIN}"
fi

# Ask for port
echo
read -p "Enter service port (default ${PORT}): " USER_PORT

if [ -z "$USER_PORT" ]; then
    echo "Use default port ${PORT}"
else
    PORT=$USER_PORT
    echo "Use port ${PORT}"
fi

# Ask for username
echo
read -p "Enter name of user that should run the service: " USER_NAME
if [ -z "$USER_NAME" ]; then
    echo "Username cannot be empty."
    exit 1
fi
echo "Using user name ${USER_NAME}"

# Detect project directory
PROJECT_DIR="$(pwd)"
VENV_PATH="$PROJECT_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# prep venv
if [ ! -d "$VENV_PATH" ]; then
    echo "venv not found at $VENV_PATH"
    echo "Running install_dep.sh to set up environment..."

    if [ -f "$PROJECT_DIR/install_dep.sh" ]; then
        chmod +x "$PROJECT_DIR/install_dep.sh"
        "$PROJECT_DIR/install_dep.sh"

        # Check again after install
        if [ ! -d "$VENV_PATH" ]; then
            echo "ERROR: install_dep.sh did not create venv."
            exit 1
        fi
    else
        echo "ERROR: install_dep.sh not found in project directory."
        exit 1
    fi
fi

echo
echo "Creating systemd service at $SERVICE_FILE..."

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=chat mk2 infrastructure
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PATH}/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=5
LimitNOFILE=65535
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Enabling service..."
sudo systemctl enable ${SERVICE_NAME}

echo "Starting/restarting service..."
sudo systemctl restart ${SERVICE_NAME}

echo
echo "Service created successfully."
echo "Check status with:"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"

echo
read -rp "Do you want to install llama.cpp as a service? (y/N): " INSTALL_LLAMA

case "$INSTALL_LLAMA" in
    [yY][eE][sS]|[yY])

    if [ -f "$PROJECT_DIR/install_llama.cpp.sh" ]; then
        chmod +x "$PROJECT_DIR/install_llama.cpp.sh"
        "$PROJECT_DIR/install_llama.cpp.sh"
    fi
        ;;
    *)
        echo "Skipping llama.cpp installation."
        ;;
esac