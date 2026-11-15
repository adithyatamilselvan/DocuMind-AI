FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache TOKENIZERS_PARALLELISM=false

# Tesseract (OCR) + language data, and libs PyMuPDF/Pillow need.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Local embeddings (sentence-transformers) need PyTorch. Install the CPU-only build first: the default
# PyPI wheel bundles CUDA libraries (several GB) that Render's CPU instances can never use.
# pip then sees torch as already satisfied when it resolves ".[local]".
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY app ./app
RUN pip install ".[local]"

# Bake the embedding model into the image so the first upload does not download it at runtime.
# Keep ARG in sync with EMBEDDING_MODEL (a different runtime model is still downloaded on demand).
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# LOCAL_STORAGE_DIR defaults to the relative path ".local-data/objects" (= /app/.local-data/objects).
# /app is root-owned, so the runtime user can only create it if it already exists and is owned by it.
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data /app/.local-data/objects \
    && chown -R appuser /data /app/.local-data /opt/hf-cache
USER appuser

EXPOSE 10000

HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD curl -fsS "http://localhost:${PORT:-10000}/health" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
