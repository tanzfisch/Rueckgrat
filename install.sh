#!/usr/bin/env bash

#set -euo pipefail

echo
echo "=== Rückgrat installer ==="
echo 

echo "installing some dependencies ..."
sudo apt-get update -qq
sudo apt-get install python3.11-venv python-is-python3 -y -qq
echo "done"

# install infrastructure
echo
read -rp "Do you want this machine to run as infrastructure node? (y/N): " INSTALL_INFRASTRUCTURE

case "$INSTALL_INFRASTRUCTURE" in
    [yY][eE][sS]|[yY])
        cd infrastructure
        ./install.sh
        cd ..
        ;;
    *)
        echo "Skipping infrastructure installation."
        ;;
esac

# install backend
echo
read -rp "Do you want this machine to run as backend? (y/N): " INSTALL_BACKEND

case "$INSTALL_BACKEND" in
    [yY][eE][sS]|[yY])
        cd backend
        ./install.sh
        cd ..
        ;;
    *)
        echo "Skipping backend installation."
        ;;
esac

# install chat
echo
read -rp "Do you want to install chat? (y/N): " INSTALL_CHAT

case "$INSTALL_CHAT" in
    [yY][eE][sS]|[yY])
        cd chat
        ./install.sh
        cd ..
        ;;
    *)
        echo "Skipping chat installation."
        ;;
esac