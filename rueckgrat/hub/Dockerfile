FROM python:3.11-slim

WORKDIR /hub

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app app

RUN mkdir -p /data && \
    chown -R 1000:1000 /data

COPY config config

# Expose port
EXPOSE 14223

ENTRYPOINT ["uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "14223"]