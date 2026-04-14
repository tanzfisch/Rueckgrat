#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <image_name[:tag]> <target_host> <project_dir>"
  echo "Example: $0 node:latest user@server ./project"
  exit 1
}

if [[ $# -ne 3 ]]; then
  usage
fi

IMAGE="$1"
TARGET="$2"
PROJECT_DIR="$(cd "$3" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
REMOTE_DIR="/tmp/$PROJECT_NAME"

for dir in models common rueckgrat; do
  if [[ ! -d "$PROJECT_DIR/$dir" ]]; then
    echo "Missing required directory: $PROJECT_DIR/$dir"
    exit 1
  fi
done

SSH_CONTROL="/tmp/deploy-$(whoami)-$(echo "$TARGET" | tr '@:' '__')"

SSH_OPTS=(
  -o ControlMaster=auto
  -o ControlPersist=5m
  -o ControlPath="$SSH_CONTROL"
)

trap 'ssh -O exit "${SSH_OPTS[@]}" "$TARGET" >/dev/null 2>&1 || true' EXIT

ssh "${SSH_OPTS[@]}" -Nf "$TARGET"

echo "Creating remote directory..."
ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p '$REMOTE_DIR'"

echo "Copying models..."
rsync -az --delete --info=progress2 -e "ssh ${SSH_OPTS[*]}" \
  "$PROJECT_DIR/models/" "$TARGET:$REMOTE_DIR/models/"

echo "Copying common..."
rsync -az --delete --info=progress2 -e "ssh ${SSH_OPTS[*]}" \
  "$PROJECT_DIR/common/" "$TARGET:$REMOTE_DIR/common/"

echo "Copying rueckgrat..."
rsync -az --delete --info=progress2 -e "ssh ${SSH_OPTS[*]}" \
  "$PROJECT_DIR/rueckgrat/" "$TARGET:$REMOTE_DIR/rueckgrat/"

echo "Sending docker image..."
docker save "$IMAGE" | ssh "${SSH_OPTS[@]}" "$TARGET" "docker load"

echo "Starting compose..."
ssh "${SSH_OPTS[@]}" "$TARGET" "
  set -e
  cd '$REMOTE_DIR/rueckgrat'
  docker compose up -d node
"

echo "Deployment complete."