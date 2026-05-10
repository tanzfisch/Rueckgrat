#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <project_dir> --target <target_host> --hubs <comma,separated,ips>"
  echo "Example: $0 ./project --target user@server"
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

PROJECT_DIR="$(cd "$1" && pwd)"
shift

TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || usage
      TARGET="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "Missing required option: --target"
  usage
fi

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

echo "Starting compose..."
ssh "${SSH_OPTS[@]}" "$TARGET" "
  set -e
  cd '$REMOTE_DIR/rueckgrat'
  docker compose up -d --build node
"

echo "Deployment complete."