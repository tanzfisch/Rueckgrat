FROM python:3.11-slim

WORKDIR /hub

RUN useradd -m hubuser \
 && mkdir -p /hub/images /hub/voices /hub/db \
 && chown -R hubuser:hubuser /hub

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install -r requirements.txt

COPY app app

USER hubuser

EXPOSE ${HUB_PORT}
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${HUB_PORT}"]