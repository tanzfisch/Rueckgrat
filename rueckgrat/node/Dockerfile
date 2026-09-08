FROM python:3.11-slim

WORKDIR /node

RUN useradd -m nodeuser \
 && groupadd -f video \
 && groupadd -f render \
 && usermod -aG video,render nodeuser \
 && mkdir -p /node/images \
 && chown -R nodeuser:nodeuser /node/images

COPY requirements_base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements_base.txt

COPY requirements_image_gen.txt .
ARG INSTALL_IMAGE_GEN=false
ARG TORCH_BACKEND=cpu
ENV USE_IMAGE_GEN=$INSTALL_IMAGE_GEN
ENV TORCH_BACKEND=$TORCH_BACKEND

ARG TORCH_CUDA_INDEX=cu128
ARG TORCH_ROCM_INDEX=rocm6.3

RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_IMAGE_GEN" = "true" ]; then \
      pip install -r requirements_image_gen.txt; \
      case "$TORCH_BACKEND" in \
        rocm) pip install --force-reinstall \
                --index-url "https://download.pytorch.org/whl/${TORCH_ROCM_INDEX}" \
                torch torchvision torchaudio ;; \
        cuda) pip install --force-reinstall \
                --index-url "https://download.pytorch.org/whl/${TORCH_CUDA_INDEX}" \
                torch torchvision torchaudio ;; \
        xpu)  pip install --force-reinstall \
                --index-url https://download.pytorch.org/whl/xpu \
                torch torchvision torchaudio ;; \
      esac; \
    fi

ARG INSTALL_LLAMA=false
ENV USE_LLAMA=$INSTALL_LLAMA

COPY app app
COPY data data

RUN mkdir -p /node/app/config && chown -R nodeuser:nodeuser /node/app/config

USER nodeuser

EXPOSE 7346

ENTRYPOINT ["python", "-u", "-m", "uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "7346"]