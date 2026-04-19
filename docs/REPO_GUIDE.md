# NagaCon Repo Guide

This repo currently has two primary application folders:

- `backend`
- `nagacon_ui`

Recommended working structure going forward:

- Keep product and architecture notes in `docs/`
- Use `docs/NAGACON_PRODUCT_ROADMAP.md` as the current product roadmap/source of truth
- Keep one-off diagnostics and patch notes out of the repo root
- Keep generated files like `backend/exports/`, `dist/`, and zip archives untracked
- Add new automated tests under `backend/tests/`

Current reliability baseline added in this phase:

- backend API smoke tests for opportunities, workspace, company, pipeline
- backend tests for ingest matching and file endpoints
- frontend env-based API configuration
- route-level error boundary
- lazy-loaded route pages
- pipeline board view

Suggested next engineering slice:

- expand tests for DIBBS and SAM ingestion adapters
- move historical patch/readme artifacts into a dedicated `docs/archive/` folder
- continue consolidating older backend routes around the core domains:
  opportunities, workspace, pipeline, files, company, ingestion

Archive staging:

- use `docs/archive/README.md` as the destination pattern for older patch-note files
