FROM python:3.11-slim

WORKDIR /hub

RUN useradd -m hubuser

RUN mkdir -p /hub/images /hub/db && chown -R hubuser:hubuser /hub

COPY requirements.txt .
RUN pip install -r requirements.txt --upgrade

COPY app app

USER hubuser

# Expose port
EXPOSE 14223

ENTRYPOINT ["uvicorn", "app.main:app"]
CMD ["--host", "0.0.0.0", "--port", "14223"]