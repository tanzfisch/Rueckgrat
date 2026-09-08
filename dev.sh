#!/bin/bash
# ===============================================
# Rueckgrat dev up
# Reads infrastructure.json, starts this host's containers.
# Usage: ./dev.sh [-c FILE] [-v] [-f]
# ===============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
# shellcheck source=install.sh
source "$SCRIPT_DIR/install.sh"

dev_usage() {
    echo "Usage: $0 [-c FILE] [-v] [-f] [-h]"
    echo "  -c FILE   infrastructure.json (default: rueckgrat/config/infrastructure.json)"
    echo "  -v        verbose compose"
    echo "  -f        --no-cache build"
}

find_local_host_config() {
    local ip host_config=""
    for ip in $HOST_ADDR $(hostname -I 2>/dev/null || true); do
        host_config=$(jq -c --arg addr "$ip" '.hosts[] | select(.addr == $addr)' "$CONFIG_FILE")
        if [[ -n "$host_config" ]]; then
            HOST_ADDR="$ip"
            echo "$host_config"
            return 0
        fi
    done
    return 1
}

CONFIG_FILE=""
VERBOSE=false
DOCKER_PROGRESS_MODE="quiet"
CLEAN_BUILD=false
NO_CACHE=""
YES=true
KEY_FILE=""
CERT_FILE=""
WORKING_DIR="$SCRIPT_DIR"

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--config)
            [[ -n "${2:-}" ]] || { echo "❌ Error: -c requires a file"; exit 1; }
            CONFIG_FILE="$2"
            shift 2
            ;;
        -v|--verbose) VERBOSE=true; DOCKER_PROGRESS_MODE="auto"; shift ;;
        -f|--fresh) CLEAN_BUILD=true; NO_CACHE="--no-cache"; shift ;;
        -h|--help) dev_usage; exit 0 ;;
        *) echo "Unknown option: $1"; dev_usage; exit 1 ;;
    esac
done

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

get_info

[[ -n "$CONFIG_FILE" ]] || CONFIG_FILE="$WORKING_DIR/rueckgrat/config/infrastructure.json"
[[ -f "$CONFIG_FILE" ]] || { echo "❌ Error: config not found: $CONFIG_FILE"; exit 1; }
jq . "$CONFIG_FILE" >/dev/null 2>&1 || { echo "❌ Error: invalid JSON: $CONFIG_FILE"; exit 1; }

host_config="$(find_local_host_config)" || {
    echo "❌ Error: no host in $CONFIG_FILE matches this machine ($HOST_ADDR / $(hostname -I))"
    exit 1
}

parse_host_config "$host_config"

print_header "🔧 Rückgrat Dev"

echo "Config   $CONFIG_FILE"
echo "Hub      $INSTALL_HUB"
echo "Node     $INSTALL_NODE"
echo "Llama    $INSTALL_LLAMA ${INSTALL_LLAMA_MODEL:+($INSTALL_LLAMA_MODEL)}"
echo "ImageGen $INSTALL_IMAGE_GEN"
echo "Chat     $INSTALL_CHAT_DOCKER"
echo ""

if $INSTALL_HUB; then
    deploy_hub
fi

if $INSTALL_NODE; then
    deploy_node
    if $INSTALL_LLAMA; then
        [[ -n "$INSTALL_LLAMA_MODEL" ]] || { echo "❌ Error: llama-server has no model in config"; exit 1; }
        deploy_llama "$INSTALL_LLAMA_MODEL"
    fi
fi

if $INSTALL_CHAT_DOCKER; then
    CHAT_DIR="$WORKING_DIR/rueckgrat/chat"
    CADDY_CERT="$WORKING_DIR/rueckgrat/caddy/rueckgrat-caddy.cert"
    deploy_chat_docker
fi

print_section
echo "Dev up done."

pushd "$WORKING_DIR/rueckgrat" >/dev/null
COMPOSE_FILES=(-f compose.yml)
case "${GPU_VENDOR:-cpu}" in
    amd)    COMPOSE_FILES+=(-f compose.amd.yml) ;;
    nvidia) COMPOSE_FILES+=(-f compose.nvidia.yml) ;;
esac
print_section
echo "Following logs (Ctrl-C leaves containers running)..."
docker compose "${COMPOSE_FILES[@]}" logs -f --tail=100
popd >/dev/null