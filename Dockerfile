FROM python:3.11-slim

# Instalar Tesseract OCR com suporte a português e inglês
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-por \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Criar pasta para a base de dados persistente
RUN mkdir -p /data

ENV DATABASE_URL=/data/tuna.db

EXPOSE 8000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2"]
