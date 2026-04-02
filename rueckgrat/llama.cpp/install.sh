#!/usr/bin/env bash

set -euo pipefail

echo
git -C llama.cpp pull || git clone https://github.com/ggerganov/llama.cpp.git

echo "Choose an option:"
echo "1) Run llama.cpp as service (recommended)"
echo "2) Run llama.cpp from docker container (TODO not implemented)"
read -p "Enter 1 or 2: " choice

case "$choice" in
  1)
    echo
    echo "======= Installing llama.cpp as a service ======="
    echo

    DEFAULT_SERVICE_NAME="rueckgrat_llama_cpp"
    DEFAULT_PORT="8080"
    DEFAULT_GPU_LAYERS=-1
    DEFAULT_CONTEXT_SIZE=4000
    USER_NAME=$USER    
    # TODO
    DEFAULT_MODEL_PATH="/home/martin/dev/Rueckgrat/rueckgrat/models/llm/cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L/cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L.gguf"

    read -p "Enter llama.cpp user [${DEFAULT_SERVICE_NAME}]: " USER_SERVICE_NAME
    SERVICE_NAME="${USER_SERVICE_NAME:-$DEFAULT_SERVICE_NAME}"

    read -p "Enter llama.cpp port [${DEFAULT_PORT}]: " USER_PORT
    PORT="${USER_PORT:-$DEFAULT_PORT}"

    read -p "Enter model path [${DEFAULT_MODEL_PATH}]: " USER_MODEL_PATH
    MODEL_PATH="${USER_MODEL_PATH:-$DEFAULT_MODEL_PATH}"

    read -p "Enter gpu layer count (-1 for max) [${DEFAULT_GPU_LAYERS}]: " USER_GPU_LAYERS
    GPU_LAYERS="${USER_GPU_LAYERS:-$DEFAULT_GPU_LAYERS}"

    read -p "Enter gpu layer count (-1 for max) [${DEFAULT_CONTEXT_SIZE}]: " USER_CONTEXT_SIZE
    CONTEXT_SIZE="${USER_CONTEXT_SIZE:-$DEFAULT_CONTEXT_SIZE}"

    read -p "Enter llama.cpp service user [${USER_NAME}]: " USER_USER_NAME
    USER_NAME="${USER_USER_NAME:-$USER_NAME}"

    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"    

    ENABLE_BACKEND=""

    echo
    echo "Detecting NVIDIA (CUDA) ..."

    if command -v nvidia-smi &>/dev/null; then
        echo "NVIDIA GPU detected — enabling CUDA"
        ENABLE_BACKEND="-DGGML_CUDA=ON"
    else
        echo "no NVIDIA detected"
    fi

    echo
    echo "Detecting AMD GPU..."
    if lspci | grep -Ei 'vga|3d' | grep -i amd &>/dev/null; then
        echo "AMD GPU detected - enabling Vulkan"
        ENABLE_BACKEND="$ENABLE_BACKEND -DGGML_VULKAN=ON"

        if command -v rocminfo &>/dev/null || [ -d "/opt/rocm" ]; then
            echo "ROCm detected — enabling HIPBLAS"
            ENABLE_BACKEND="$ENABLE_BACKEND -DGGML_HIPBLAS=ON"
        fi
    else
        echo "No AMD GPU detected"
    fi

    ENABLE_BACKEND=$(echo "$ENABLE_BACKEND" | sed 's/^ //')

    # -------------------------
    # Build optimized version
    # -------------------------

    echo
    echo "Building optimized version"

    cd llama.cpp
    cmake -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_NATIVE=ON \
        ${ENABLE_BACKEND}

    cmake --build build --config Release -j"$(nproc)"
    cd ..

    # -----------------------------
    # Create service
    # -----------------------------

    LLAMA_SERVER="./llama.cpp/build/bin/llama-server"
    LLAMA_SERVER=$(realpath "$LLAMA_SERVER")

    echo
    echo "Creating systemd service at $SERVICE_FILE ..."

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=llama.cpp LLM Server
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$(dirname "$LLAMA_SERVER")

ExecStart=$LLAMA_SERVER \\
    -m $MODEL_PATH \\
    --port $PORT \\
    --host 0.0.0.0 \\
    --chat-template chatml \\
    --ctx-size $CONTEXT_SIZE \\
    --n-gpu-layers $GPU_LAYERS

Restart=always
RestartSec=5
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

    # -----------------------------
    # Start service
    # -----------------------------

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
    ;;
  2)
    echo "You chose Option B"
    cd llama.cpp
    # todo this keeps failing. always missing something
    # docker build -t rueckgrat_llama.cpp --target server -f .devops/cuda.Dockerfile .
    ;;
  *)
    echo "Invalid choice. Please enter 1 or 2."
    ;;
esac
