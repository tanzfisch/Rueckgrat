FROM python:3.11-slim

WORKDIR /hub

RUN useradd -m hubuser \
 && mkdir -p /hub/images /hub/voices /hub/db /hub/files \
 && chown -R hubuser:hubuser /hub

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install -r requirements.txt

# headless chromium for javascript pages (fetch_url browser fallback), ~+800 MB
COPY requirements_browser.txt .
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN --mount=type=cache,target=/root/.cache/pip \
    apt-get update && apt-get install -y --no-install-recommends libatomic1 && \
    pip install -r requirements_browser.txt && \
    playwright install --with-deps --only-shell chromium && \
    rm -rf /var/lib/apt/lists/*

# Noto fonts for the offline map's place names in every script, Latin to CJK, ~+135 MB of which ~90 MB CJK
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-core fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

COPY app app

USER hubuser

EXPOSE ${HUB_PORT}
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${HUB_PORT}"]