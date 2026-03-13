#!/bin/bash

set -euo pipefail

SERVICE_NAME="Rueckgrat_backend"
DOMAIN="localhost"
PORT="14223"
CADDYFILE="/etc/caddy/Caddyfile"

echo
echo "=== Setup backend service + Caddy HTTPS reverse proxy ==="
echo

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
read -p "Enter Linux username that should run the services: " USER_NAME
if [ -z "$USER_NAME" ]; then
    echo "Username cannot be empty."
    exit 1
fi
echo "Using user name ${USER_NAME}"

# Detect project directory
PROJECT_DIR="$(pwd)"
VENV_PATH="$PROJECT_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo
echo "Detected project directory: $PROJECT_DIR"
echo "Backend will run on port $PORT"
echo "Caddy will serve https://$DOMAIN → localhost:$PORT"
echo

# Prepare venv
if [ ! -d "$VENV_PATH" ]; then
    echo "venv not found → running install_dep.sh..."
    if [ -f "$PROJECT_DIR/install_dep.sh" ]; then
        chmod +x "$PROJECT_DIR/install_dep.sh"
        "$PROJECT_DIR/install_dep.sh"
        if [ ! -d "$VENV_PATH" ]; then
            echo "ERROR: install_dep.sh did not create venv."
            exit 1
        fi
    else
        echo "ERROR: install_dep.sh not found."
        exit 1
    fi
fi

echo
echo "Creating systemd service at $SERVICE_FILE ..."

# Create backend service
echo "Creating backend systemd service..."
sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=chat mk2 backend
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${VENV_PATH}/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

# Reload & enable/start service
echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Enabling service..."
sudo systemctl enable ${SERVICE_NAME}

echo "Starting/restarting service..."
sudo systemctl restart ${SERVICE_NAME}

# temp configure caddy to force certificate creation
echo "Configure Caddy at $CADDYFILE"
sudo bash -c "cat > $CADDYFILE" <<EOF
:18080 {
    respond "Backend not ready" 503
}
EOF
sudo systemctl restart caddy
sleep 3

# Real config with internal CA
sudo bash -c "cat > $CADDYFILE" <<EOF
$DOMAIN {
    reverse_proxy /ws* http://127.0.0.1:14223 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    tls internal
    reverse_proxy http://127.0.0.1:14223
}
EOF

# Export root CA so clients/browsers can trust it
sudo mkdir -p /var/www/html
CA_PATH="/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"
sudo test -f "$CA_PATH" && sudo cp "$CA_PATH" /var/www/html/rueckgrad_backend.crt && sudo chmod 644 /var/www/html/rueckgrad_backend.crt


sudo systemctl reload caddy

echo
echo "Done."
echo
echo "Check status:"
echo "   sudo systemctl status caddy"
echo "   sudo systemctl status ${SERVICE_NAME}"
echo "   sudo journalctl -u caddy -f"
echo "   sudo journalctl -u ${SERVICE_NAME} -f"
echo
echo "Your API should now be available at: https://$DOMAIN"