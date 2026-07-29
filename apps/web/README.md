# Talli web

Independent Next.js presentation application.

```bash
npm ci --prefix apps/web
npm --prefix apps/web run build
TALLI_BACKEND_URL=http://127.0.0.1:8000 npm --prefix apps/web run start
```

The app consumes business HTTP operations only through the committed
`@talli/talli-api-client` package. `TALLI_BACKEND_URL` configures the server-side
FastAPI origin. It is required in every environment; local development normally
uses `http://127.0.0.1:8000`. Missing or invalid configuration fails readiness
closed instead of silently selecting a backend.

Until later serialized capability migrations remove the legacy runtime seams,
the scripts load the repository-root `.env` file to preserve existing behavior.
