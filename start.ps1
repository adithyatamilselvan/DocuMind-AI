# Starts DocuMind AI for local use: API on :8000 and web app on :3000.  Usage:  .\start.ps1
# First time only:  cd backend; python -m venv .venv; .venv\Scripts\python -m pip install -e ".[dev,local]"
#                   cd frontend; npm install
$root = $PSScriptRoot
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env"; Write-Host "Created .env: set APP_SECRET_KEY and ANTHROPIC_API_KEY, then run again."; exit 1 }
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\frontend'; npm run dev"
Write-Host "API:  http://localhost:8000/health"
Write-Host "App:  http://localhost:3000   (register, enable AI processing in Settings, upload, ask)"
