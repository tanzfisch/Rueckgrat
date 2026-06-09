FROM python:3.11-slim

WORKDIR /hub

RUN useradd -m hubuser

RUN mkdir -p /hub/db && chown -R hubuser:hubuser /hub/db
RUN mkdir -p /hub/images && chown -R hubuser:hubuser /hub/images

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app app

USER hubuser

# Expose port
EXPOSE 14223

ENTRYPOINT ["uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "14223"]