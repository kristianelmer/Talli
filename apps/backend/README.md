# Talli backend

Independent FastAPI application for Talli's production HTTP boundary.

```bash
uv sync --project apps/backend --locked
uv run --project apps/backend uvicorn talli_backend.main:app \
  --app-dir apps/backend/src --host 127.0.0.1 --port 8000
```

The committed OpenAPI artifact is generated from this application:

```bash
uv run --project apps/backend python apps/backend/scripts/generate_openapi.py
```
