FROM python:3.11-slim

WORKDIR /node

RUN useradd -m nodeuser \
 && groupadd -f video \
 && groupadd -f render \
 && usermod -aG video,render nodeuser \
 && mkdir -p /node/images /node/voices \
 && chown -R nodeuser:nodeuser /node/images /node/voices

COPY requirements_base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements_base.txt

COPY requirements_image_gen.txt requirements_tts.txt requirements_stt.txt requirements_embedding.txt requirements_decision.txt ./
ARG INSTALL_IMAGE_GEN=false
ARG INSTALL_TTS=false
ARG INSTALL_STT=false
ARG INSTALL_EMBEDDING=false
ARG INSTALL_DECISION=false
ARG TORCH_BACKEND=cpu
ENV USE_IMAGE_GEN=$INSTALL_IMAGE_GEN
ENV USE_TTS=$INSTALL_TTS
ENV USE_STT=$INSTALL_STT
ENV USE_EMBEDDING=$INSTALL_EMBEDDING
ENV USE_DECISION=$INSTALL_DECISION
ENV TORCH_BACKEND=$TORCH_BACKEND

# insightface (face reference, requirements_image_gen.txt) ships as source only and compiles a c++ extension
RUN if [ "$INSTALL_IMAGE_GEN" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*; \
    fi

ARG TORCH_CUDA_INDEX=cu128
ARG TORCH_ROCM_INDEX=rocm6.3

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_IMAGE_GEN" = "true" ] || [ "$INSTALL_TTS" = "true" ] || [ "$INSTALL_DECISION" = "true" ]; then \
      case "$TORCH_BACKEND" in \
        rocm) IDX="https://download.pytorch.org/whl/${TORCH_ROCM_INDEX}" ;; \
        cuda) IDX="https://download.pytorch.org/whl/${TORCH_CUDA_INDEX}" ;; \
        xpu)  IDX="https://download.pytorch.org/whl/xpu" ;; \
        *)    IDX="https://download.pytorch.org/whl/cpu" ;; \
      esac; \
      pip install --index-url "$IDX" torch torchvision torchaudio; \
    fi && \
    if [ "$INSTALL_IMAGE_GEN" = "true" ]; then \
      pip install Cython numpy && \
      pip install --no-build-isolation -r requirements_image_gen.txt; \
    fi && \
    if [ "$INSTALL_TTS" = "true" ]; then \
      pip install -r requirements_tts.txt && \
      pip install --no-deps chatterbox-tts; \
    fi && \
    if [ "$INSTALL_STT" = "true" ]; then \
      pip install -r requirements_stt.txt; \
    fi && \
    if [ "$INSTALL_EMBEDDING" = "true" ]; then \
      pip install -r requirements_embedding.txt; \
    fi && \
    if [ "$INSTALL_DECISION" = "true" ]; then \
      pip install -r requirements_decision.txt; \
    fi

ARG INSTALL_LLAMA=false
ENV USE_LLAMA=$INSTALL_LLAMA

COPY app app
COPY data data

RUN mkdir -p /node/app/config && chown -R nodeuser:nodeuser /node/app/config

USER nodeuser

EXPOSE ${NODE_PORT}
CMD ["sh", "-c", "exec python -u -m uvicorn app.main:app --host 0.0.0.0 --port ${NODE_PORT}"]