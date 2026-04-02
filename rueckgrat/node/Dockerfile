FROM python:3.11-slim

WORKDIR /node

RUN useradd -m nodeuser

RUN mkdir -p /node/images && chown -R nodeuser:nodeuser /node/images

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app app

USER nodeuser

# Expose port
EXPOSE 8000

ENTRYPOINT ["python", "-u", "-m", "uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "7346"]