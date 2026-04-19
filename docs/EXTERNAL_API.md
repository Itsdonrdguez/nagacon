# External API

NagaCon exposes a dedicated integration surface under `/api/integrations`.

## Authentication

Set `EXTERNAL_API_KEYS` in the backend environment as a comma-separated list of valid API keys.

External clients must send:

`X-API-Key: <your-key>`

## Intended Endpoints

- `GET /api/integrations/health`
- `GET /api/integrations/opportunities/search`
- `GET /api/integrations/opportunities/{opportunity_id}`
- `GET /api/integrations/workspace/{opportunity_id}/summary`
- `POST /api/integrations/workspace/{opportunity_id}/run-agent`
- `POST /api/integrations/workspace/{opportunity_id}/run-phase`
- `GET /api/integrations/workspace/{opportunity_id}/usaspending`
- `GET /api/integrations/pipeline/board`

## Notes

- Existing `/api/*` routes remain available for the local UI.
- External clients should prefer `/api/integrations/*` so authentication and compatibility can evolve cleanly.
- FastAPI docs are available at `/docs` and will show the integration routes.
