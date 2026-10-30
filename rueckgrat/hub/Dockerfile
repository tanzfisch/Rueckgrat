FROM python:3.11-slim

WORKDIR /hub

RUN useradd -m hubuser \
 && mkdir -p /hub/images /hub/voices /hub/db \
 && chown -R hubuser:hubuser /hub

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install -r requirements.txt

# headless chromium for javascript pages (fetch_url browser fallback), ~+800 MB
COPY requirements_browser.txt .
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements_browser.txt && \
    playwright install --with-deps --only-shell chromium && \
    rm -rf /var/lib/apt/lists/*

COPY app app

USER hubuser

EXPOSE ${HUB_PORT}
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${HUB_PORT}"]