#!/usr/bin/env bash

set -euo pipefail

SERVICE_NAME="Rueckgrat_llama.cpp"
PROJECT_DIR="$(pwd)"
VENV_PATH="$PROJECT_DIR/.venv"
LLAMA_INSTALL_SCRIPT="./install_llama.cpp.sh"
LLAMA_SERVICE_SCRIPT="./create_service_llama.cpp.sh"
ENGINES_DIR="engines"
PORT="8080"

echo
echo "=== Install llama.cpp as service ==="
echo

if [ ! -d "$VENV_PATH" ]; then
    echo "venv not found at $VENV_PATH"
    exit 1
fi
source .venv/bin/activate

# -------------------------
# Install llama.cpp
# -------------------------
cd $ENGINES_DIR
if [ -f "$LLAMA_INSTALL_SCRIPT" ]; then
    echo "Running llama.cpp installer: $LLAMA_INSTALL_SCRIPT"
    chmod +x "$LLAMA_INSTALL_SCRIPT"
    "$LLAMA_INSTALL_SCRIPT"
else
    echo "Installer script not found: $LLAMA_INSTALL_SCRIPT"
    exit 1
fi
cd ..

# -------------------------
# Show available models
# -------------------------
models_output=$(python registry_manager.py list -t llm)

mapfile -t lines <<< "$models_output"

echo
echo "=== Install llm models === "
echo
echo "Available models:"
echo
for i in "${!lines[@]}"; do
    printf "%d) %s\n" "$i" "${lines[$i]}"
done
echo
read -rp "Select a model (by index): " choice

if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 0 && choice < ${#lines[@]} )); then
    selected="${lines[$choice]}"            
else
    echo "Invalid selection"
    exit 1
fi        

echo "installing selected Model $selected"
python registry_manager.py install $selected

# Find the actual gguf file inside the selected folder
MODEL_PATH=$(find "models/llm/$selected" -name "*.gguf" | head -n 1)
MODEL_PATH=$(realpath "$MODEL_PATH")

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "Error: Model file missing $MODEL_PATH"
    exit 1
fi

MODEL_STARTUP_PARAM=$(python registry_manager.py startup_parameters $selected)

cd $ENGINES_DIR

# Ask for service name
echo
read -p "Enter service name (default ${SERVICE_NAME}) " USER_SERVICE_NAME

if [ -z "$USER_SERVICE_NAME" ]; then
    echo "Use default service name ${SERVICE_NAME}"
else
    SERVICE_NAME=$USER_SERVICE_NAME
    echo "Using service name ${SERVICE_NAME}"
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

if [ -f "$LLAMA_SERVICE_SCRIPT" ]; then
    echo "Creating llama.cpp system service..."
    chmod +x "$LLAMA_SERVICE_SCRIPT"
    $LLAMA_SERVICE_SCRIPT --user "$USER_NAME" --model "$MODEL_PATH" --port "$PORT" --service-name "$SERVICE_NAME" --param "$MODEL_STARTUP_PARAM"
else
    echo "Service creation script not found: $LLAMA_SERVICE_SCRIPT"
    echo "Skipping service setup."
    exit 1
fi
