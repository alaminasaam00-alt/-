# RevenueFlow

RevenueFlow is a lightweight revenue-operations engine for turning incoming customer inquiries into prioritized sales actions.

## What it does
- Captures leads manually or through an authenticated ingestion API.
- Scores buying intent and assigns a priority.
- Generates a recommended next action and Arabic reply.
- Tracks lead lifecycle: new → contacted → qualified → won/lost.
- Provides dashboard and time/source/status analytics.
- Supports idempotent API ingestion so retries do not create duplicate leads.
- Supports search, status filtering and pagination for leads/runs.

## Run locally
```bash
npm start
```
Open `http://localhost:3000`.

## API
- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/analytics?days=30`
- `GET /api/leads?q=...&status=...&limit=50&offset=0`
- `GET /api/runs?limit=50&offset=0`
- `POST /api/leads`
- `POST /api/ingest`
- `POST /api/leads/:id/run`
- `PATCH /api/leads/:id`

Set `REVENUEFLOW_API_KEY` in production to protect `/api/ingest`. For safe retries, send an `Idempotency-Key` header.

## Storage
Local mode uses `data/store.json` for simplicity. Production should use a managed database and externalized secrets before handling customer data at scale.
