# -----------------------------
# Stage 1: Build with CUDA 12.3
# -----------------------------
FROM nvidia/cuda:12.3.1-devel-ubuntu22.04 AS builder

RUN apt-get update && \
    apt-get install -y build-essential cmake python3 python3-pip git libssl-dev libgomp1

WORKDIR /app

# Clone fresh (avoids host contamination)
RUN git clone https://github.com/ggerganov/llama.cpp.git .

# Build with CUDA
RUN cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_NATIVE=OFF \
    -DLLAMA_OPENSSL=OFF \
    -DGGML_CPU_ALL_VARIANTS=ON \
    -DLLAMA_BUILD_TESTS=OFF \
    -DGGML_BACKEND_DL=ON \
    -DCMAKE_CUDA_ARCHITECTURES=default \
    -DGGML_CUDA=ON \
    && cmake --build build --config Release -j$(nproc)

RUN mkdir -p /app/lib && \
    find build -name "*.so*" -exec cp -P {} /app/lib \;

RUN mkdir -p /app/full \
    && cp build/bin/* /app/full \
    && cp *.py /app/full \
    && cp -r gguf-py /app/full \
    && cp -r requirements /app/full \
    && cp requirements.txt /app/full \
    && cp .devops/tools.sh /app/full/tools.sh

# -----------------------------
# Stage 2: Runtime (small)
# -----------------------------
FROM nvidia/cuda:12.3.1-runtime-ubuntu22.04

RUN apt-get update \
    && apt-get install -y libgomp1 curl\
    && apt autoremove -y \
    && apt clean -y \
    && rm -rf /tmp/* /var/tmp/* \
    && find /var/cache/apt/archives /var/lib/apt/lists -not -name lock -type f -delete \
    && find /var/cache -type f -delete

WORKDIR /app

COPY --from=build /app/lib/ /app
COPY --from=build /app/full/llama-server /app

ENV LLAMA_ARG_HOST=0.0.0.0

HEALTHCHECK CMD [ "curl", "-f", "http://localhost:8080/health" ]

ENTRYPOINT [ "/app/llama-server" ]
