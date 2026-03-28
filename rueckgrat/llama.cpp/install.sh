#!/usr/bin/env bash

set -euo pipefail

echo "installing some dependencies ..."
sudo apt install git build-essential cmake curl libopenblas-dev -y -qq
echo "done"

echo
git -C llama.cpp pull || git clone https://github.com/ggerganov/llama.cpp.git

echo "Choose an option:"
echo "1) Run llama.cpp as service"
echo "2) Run llama.cpp from docker container"
read -p "Enter 1 or 2: " choice

case "$choice" in
  1)
    echo
    echo "======= Installing llama.cpp as a service ======="
    echo

    USER_NAME=$USER
    # TODO
    MODEL_PATH="/home/martin/dev/chat_mk2/rueckgrat/data/models/llm/cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L/cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L.gguf"
    
    PORT="8080"
    SERVICE_NAME="rueckgrat_llama_cpp"
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"    

    echo
    echo "Detecting NVIDIA (CUDA) ..."

    if command -v nvidia-smi &>/dev/null; then
        echo "NVIDIA GPU detected — enabling CUDA"

        sudo apt install -y nvidia-cuda-toolkit
        ENABLE_BACKEND="-DGGML_CUDA=ON"
    else
        echo "no NVIDIA detected"
    fi

    echo
    echo "Detecting AMD GPU..."

    if lspci | grep -Ei 'vga|3d' | grep -i amd &>/dev/null; then
        echo "AMD GPU detected"

        # Try ROCm detection
        if command -v rocminfo &>/dev/null || [ -d "/opt/rocm" ]; then
            echo "ROCm detected — enabling ROCm backend"
            ENABLE_BACKEND="-DGGML_HIPBLAS=ON"

        else
            echo "ROCm not found — attempting install"

            # Basic ROCm install (Ubuntu-based, may need version-specific repo in real setups)
            sudo apt update
            sudo apt install -y \
                rocm-dev \
                rocm-hip-runtime \
                rocblas \
                hipblas || true

            if command -v rocminfo &>/dev/null; then
                echo "ROCm installed successfully — enabling ROCm backend"
                ENABLE_BACKEND="-DGGML_HIPBLAS=ON"
            else
                echo "ROCm unavailable — falling back to Vulkan"

                sudo apt install -y \
                    mesa-vulkan-drivers \
                    vulkan-tools \
                    libvulkan-dev \
                    glslc

                ENABLE_BACKEND="-DGGML_VULKAN=ON"
            fi
        fi

    else
        echo "No AMD GPU detected"
        ENABLE_BACKEND=""
    fi


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

    # use at least one but not all CPUs
    TOTAL_CPUS=$(nproc)
    USE_CPUS=$(( TOTAL_CPUS -1 ))
    if [ "$USE_CPUS" -lt 1 ]; then
        USE_CPUS=1
    fi
    CPU_MAX=$(( USE_CPUS - 1 ))
    CPUAFFINITY_LINE="CPUAffinity=0-$CPU_MAX"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=llama.cpp LLM Server
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$(dirname "$LLAMA_SERVER")
$CPUAFFINITY_LINE
ExecStart=$LLAMA_SERVER \\
    -m $MODEL_PATH \\
    --port $PORT \\
    --host 0.0.0.0 \\
    --chat-template chatml \\
    --threads $USE_CPUS \\
    --n-gpu-layers -1

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
    ;;
  *)
    echo "Invalid choice. Please enter 1 or 2."
    ;;
esac


cd llama.cpp
# todo this keeps failing. always missing something
# docker build -t rueckgrat_llama.cpp --target server -f .devops/cuda.Dockerfile .
