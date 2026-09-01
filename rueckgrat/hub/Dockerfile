FROM python:3.11-slim

WORKDIR /hub

RUN useradd -m hubuser \
 && mkdir -p /hub/images /hub/db \
 && chown -R hubuser:hubuser /hub

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY app app

USER hubuser

EXPOSE 14223

ENTRYPOINT ["uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "14223"]