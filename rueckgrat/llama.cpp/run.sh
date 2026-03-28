#!/usr/bin/env bash

docker stop rueckgrat_llama_cpp
docker rm rueckgrat_llama_cpp

# -------- Detect system resources --------
CPU_CORES=$(nproc)
echo "CPU cores detected: $CPU_CORES"

# Detect total memory in GB
MEM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
echo "Memory detected: ${MEM_GB}GB"

# -------- Configuration --------
CONTAINER_NAME="rueckgrat_llama_cpp"
DOCKER_IMAGE="ghcr.io/ggml-org/llama.cpp:server"

docker run -d \
    --name $CONTAINER_NAME \
    --gpus all \
    --cpus $CPU_CORES \
    --memory ${MEM_GB}g \
    --network rueckgrat-net-local \
    -v /media/martin/dev/dev/ai_models/models:/models \
    -p 8080:8080 $DOCKER_IMAGE \
    -m /models/meta-llama-3.1-8b-instruct-abliterated.Q6_K/meta-llama-3.1-8b-instruct-abliterated.Q6_K.gguf \
    --threads $CPU_CORES \
    --n-gpu-layers 32

