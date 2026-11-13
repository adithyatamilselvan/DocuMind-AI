# Windows setup

## 1. Install Docker Desktop (needed for Redis, MinIO, Celery workers)

1. Open **PowerShell as Administrator** and run:
   ```powershell
   winget install -e --id Docker.DockerDesktop
   ```
   (or download the installer from https://www.docker.com/products/docker-desktop/).
2. When asked, keep **"Use WSL 2 instead of Hyper-V"** ticked. If Windows says WSL is missing:
   ```powershell
   wsl --install
   ```
   then **reboot**.
3. Start Docker Desktop, accept the terms, wait until the whale icon says "Engine running".
4. Verify in a new terminal:
   ```powershell
   docker --version
   docker compose version
   ```
5. Start the infrastructure only (Redis + MinIO) and keep running the API locally:
   ```powershell
   cd "C:\Main Imp Projects\DocuMind-AI"
   docker compose up -d redis minio minio-init
   ```
6. Switch the local API to the real queue/storage in `.env`:
   ```
   JOB_BACKEND=celery
   REDIS_URL=redis://localhost:6379/0
   STORAGE_BACKEND=s3
   S3_ENDPOINT_URL=http://localhost:9000
   S3_ACCESS_KEY_ID=minioadmin
   S3_SECRET_ACCESS_KEY=minioadmin
   S3_BUCKET=documind
   ```
7. Run the API and a worker (two terminals, from `backend`):
   ```powershell
   .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
   .venv\Scripts\python -m celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo
   ```
   (`--pool=solo` is required on Windows; Celery's default prefork pool does not work there.)

Full containerised stack: `docker compose --profile app up -d --build` (needs `MONGODB_URI` and `APP_SECRET_KEY` in `.env`).

## 2. Tesseract for local (non-Docker) development, only needed for scanned PDFs

```powershell
winget install -e --id UB-Mannheim.TesseractOCR
```
Then either add `C:\Program Files\Tesseract-OCR` to `PATH` or set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`.
The Docker image already contains Tesseract.

## 3. Without Docker (what works today)

`JOB_BACKEND=inline` and `STORAGE_BACKEND=local` (the defaults) run processing inside the API process and store files under `.local-data/`. This is development-only and loses queued work on restart (it is re-queued at the next start).

## 4. MongoDB Atlas (required for real Vector Search)

1. Create a free **M0** cluster at https://cloud.mongodb.com, add a database user, and allow your IP under *Network Access*.
2. Put the connection string in `.env` as `MONGODB_URI=...` and set `VECTOR_BACKEND=atlas`.
3. Create the search indexes: `python backend/scripts/verify_indexes.py --create` (added in Phase 8). M0 allows 3 search indexes in total.
