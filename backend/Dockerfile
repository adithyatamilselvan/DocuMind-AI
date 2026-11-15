FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Tesseract (OCR) + language data, and libs PyMuPDF/Pillow need.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data && chown appuser /data
USER appuser

EXPOSE 10000

HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD-SHELL curl -fsS "http://localhost:${PORT:-10000}/health" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]