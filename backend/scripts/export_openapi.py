"""Write the FastAPI OpenAPI schema to docs/openapi.json (used to generate frontend types)."""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("APP_SECRET_KEY", "openapi-export-only-secret-key-0123456789")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

out = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2), encoding="utf-8")
print(f"wrote {out}")
