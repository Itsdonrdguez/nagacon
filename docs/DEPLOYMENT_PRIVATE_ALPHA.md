# NagaCon Private Alpha Deployment

This is the current deployment shape for taking NagaCon online as a private alpha.

## Services

- Frontend: Vercel
- Backend API: Render web service
- Background jobs: Render worker
- Database: managed Postgres
- Object storage: R2 or S3-compatible storage

## Backend environment

Use [backend/.env.example](c:/Users/GoFunded/Documents/NagaCon/backend/.env.example) as the base.

Minimum production values:

- `DATABASE_URL`
- `APP_ENV=production`
- `APP_ROLE=web`
- `DEBUG=false`
- `FRONTEND_ORIGIN=https://app.yourdomain.com`
- `CORS_ORIGINS=https://app.yourdomain.com`
- `SESSION_SECRET=...`
- `SESSION_COOKIE_DOMAIN=.yourdomain.com` if frontend and API are on sibling subdomains
- `SESSION_COOKIE_SAMESITE=lax`
- `SESSION_COOKIE_SECURE=true`
- `AUTO_INGEST_ENABLED=true`
- `SEARCH_JOB_RUNNER=worker`
- `SEARCH_JOB_MAX_CONCURRENCY=4`
- `STORAGE_BACKEND=s3`
- `S3_BUCKET`
- `S3_ENDPOINT_URL`
- `S3_REGION`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`

Optional:

- `S3_PUBLIC_BASE_URL` if you want direct public asset URLs instead of presigned downloads
- `SAM_API_KEY`
- `OPENAI_API_KEY`
- SMTP settings

Recommended Render split:

- API service:
  - `APP_ROLE=web`
  - `AUTO_INGEST_ENABLED=true`
  - `SEARCH_JOB_RUNNER=worker`
    - this keeps the API queueing jobs into the database instead of in-process threads
- Worker service:
  - `APP_ROLE=worker`
  - `AUTO_INGEST_ENABLED=false`
  - `SEARCH_JOB_RUNNER=worker`
  - same `DATABASE_URL` and `S3_*` vars as the API

## Frontend environment

Use [nagacon_ui/.env.example](c:/Users/GoFunded/Documents/NagaCon/nagacon_ui/.env.example).

Minimum production value:

- `VITE_API_BASE_URL=https://api.yourdomain.com`

## Lifecycle behavior now in app

- `ACTIVE`: active solicitation workflow
- `RECENTLY_CLOSED`: still eligible for research and follow-up
- `ARCHIVED`: 30+ days closed, treated as archive view

Archived opportunities:

- stay searchable
- stay available in workspace/history views
- are hidden from the Today queue
- keep source link, documents, and extracted intelligence

## Storage behavior now in app

The app can now run with:

- `STORAGE_BACKEND=local`
- `STORAGE_BACKEND=s3`

Current storage-backed flows:

- solicitation PDF download/save
- file download serving
- file parsing
- provider extraction from PDFs
- pricing extraction from PDFs
- export package inclusion of downloaded files

## Recommended deployment order

1. Provision Postgres
2. Provision object storage bucket
3. Set backend env vars
4. Deploy backend API
5. Run `alembic upgrade head`
6. Deploy worker with `SEARCH_JOB_RUNNER=worker` and `APP_ROLE=worker`
7. Deploy frontend
8. Verify login, Today queue, file downloads, provider backfill, and NSN build jobs

## Worker command

Current worker entrypoint:

```bash
python -m app.workers.search_jobs_worker
```

Suggested Render start command:

```bash
python -m app.workers.search_jobs_worker --poll-seconds 2 --concurrency 4
```

Suggested Render API start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Local test for storage mode

Local:

```env
STORAGE_BACKEND=local
SEARCH_JOB_RUNNER=thread
APP_ROLE=web
AUTO_INGEST_ENABLED=true
```

Deployment-style:

```env
STORAGE_BACKEND=s3
SEARCH_JOB_RUNNER=worker
APP_ROLE=worker
AUTO_INGEST_ENABLED=false
```

## Cookie guidance

For a frontend at `https://app.yourdomain.com` and API at `https://api.yourdomain.com`:

- set `FRONTEND_ORIGIN=https://app.yourdomain.com`
- set `CORS_ORIGINS=https://app.yourdomain.com`
- set `SESSION_COOKIE_DOMAIN=.yourdomain.com`
- set `SESSION_COOKIE_SECURE=true`

That keeps session cookies usable across the app/API subdomains once HTTPS is live.
