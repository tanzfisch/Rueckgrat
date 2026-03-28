#!/usr/bin/env bash
set -euo pipefail

trap 'echo "Error on line $LINENO"' ERR

package_available() {
    local package="$1"

    # Check if the package is available in apt
    if apt-cache show "$package" >/dev/null 2>&1; then
        return 0  # package exists
    else
        return 1  # package does not exist
    fi
}

sudo apt update
sudo apt install git python3 build-essential pkg-config

if package_exists python3.13-dev; then
  sudo apt install python3.13-dev
else
  sudo apt install python3.11-dev
fi

# Resolve script directory
CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Virtualenv setup
VENV="$CURRENT_DIR/.venv"
PIP="$VENV/bin/pip"
PYTHON="$VENV/bin/python"

[ -d "$VENV" ] || python3 -m venv "$VENV"

"$PIP" install --upgrade pip
"$PIP" install -r "$CURRENT_DIR/requirements.txt"

# Helper function
clone_or_pull() {
  local repo_url=$1
  local dir=$2

  if [ -d "$dir/.git" ]; then
    echo "Updating $dir"
    git -C "$dir" pull
  else
    echo "Cloning $dir"
    git clone "$repo_url" "$dir"
  fi
}

# ComfyUI
clone_or_pull https://github.com/comfyanonymous/ComfyUI.git "$CURRENT_DIR/ComfyUI"
cd "$CURRENT_DIR/ComfyUI"

if command -v nvidia-smi >/dev/null; then
  echo "Installing CUDA PyTorch"
  "$PIP" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

elif command -v rocminfo >/dev/null; then
  echo "Installing ROCm PyTorch"

  if ! "$PIP" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.1; then
    echo "ROCm wheel failed, falling back to default PyTorch"
    "$PIP" install torch torchvision torchaudio
  fi

else
  echo "Installing CPU PyTorch"
  "$PIP" install torch torchvision torchaudio
fi

"$PIP" install -r requirements.txt

# Systemd service
SERVICE_NAME="comfyui"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
USER_NAME="$(whoami)"

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


sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ComfyUI
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$CURRENT_DIR/ComfyUI
$CPUAFFINITY_LINE
ExecStart=$PYTHON main.py --listen 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Custom nodes
cd custom_nodes

clone_or_pull https://github.com/ltdrdata/ComfyUI-Manager.git ComfyUI-Manager

#clone_or_pull https://github.com/westNeighbor/ComfyUI-ultimate-openpose-editor.git ComfyUI-ultimate-openpose-editor
#"$PIP" install -r ComfyUI-ultimate-openpose-editor/requirements.txt

#clone_or_pull https://github.com/Fannovel16/comfyui_controlnet_aux.git comfyui_controlnet_aux
#"$PIP" install -r comfyui_controlnet_aux/requirements.txt

#clone_or_pull https://github.com/Gourieff/ComfyUI-ReActor.git ComfyUI-ReActor
#"$PIP" install -r ComfyUI-ReActor/requirements.txt

BASE_PATH="$CURRENT_DIR/../data/models/ComfyUI"
EXTRA_MODEL_PATHS="$CURRENT_DIR/ComfyUI/extra_model_paths.yaml"
bash -c "cat > $EXTRA_MODEL_PATHS" <<EOF
comfyui:
     base_path: $BASE_PATH/
     is_default: true
     checkpoints: checkpoints/
     text_encoders: |
          text_encoders/
          clip/  # legacy location still supported
     clip_vision: clip_vision/
     configs: configs/
     controlnet: controlnet/
     diffusion_models: |
                  diffusion_models
                  unet
     embeddings: embeddings/
     loras: loras/
     upscale_models: upscale_models/
     vae: vae/
     audio_encoders: audio_encoders/
     model_patches: model_patches/
EOF
mkdir -p "$BASE_PATH"

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