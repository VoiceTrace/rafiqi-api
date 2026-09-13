"""
Exports the OpenAPI schema to docs/openapi.json without needing a DB connection.
FastAPI generates the schema from route/model definitions at import time.

Run with: python scripts/export_openapi.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub DATABASE_URL so config doesn't fail without a real .env
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://stub:stub@localhost/stub")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://stub:stub@localhost/stub")
os.environ.setdefault("SECRET_KEY", "stub")

from app.main import app

out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "openapi.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, indent=2)

print(f"Exported OpenAPI schema to {os.path.abspath(out_path)}")
