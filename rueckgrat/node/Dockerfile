FROM python:3.11-slim

WORKDIR /node

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY app app
COPY config config

# Expose port
EXPOSE 8000

ENTRYPOINT ["python", "-u", "-m", "uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "7346"]