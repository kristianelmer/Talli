# Talli web

Independent Next.js presentation application.

```bash
npm ci --prefix apps/web
npm --prefix apps/web run build
npm --prefix apps/web run start
```

The app consumes business HTTP operations only through the committed
`@talli/talli-api-client` package. `TALLI_BACKEND_URL` configures the server-side
FastAPI origin and defaults to `http://127.0.0.1:8000` for local development.

Until later serialized capability migrations remove the legacy runtime seams,
the scripts load the repository-root `.env` file to preserve existing behavior.
