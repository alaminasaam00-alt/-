# RevenueFlow

RevenueFlow is a lightweight revenue-operations engine for turning incoming customer inquiries into prioritized sales actions.

## What it does

1. Captures a lead.
2. Scores buying intent from the lead's message and contact data.
3. Assigns priority.
4. Produces the next sales action.
5. Generates a ready-to-send reply in Arabic.
6. Records the operation and exposes dashboard metrics.

## Run

```bash
npm start
```

Then open `http://localhost:3000`.

## API

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/leads`
- `GET /api/runs`
- `POST /api/leads`
- `POST /api/leads/:id/run`

The current deployment is intentionally dependency-light and stores demo data in `data/store.json`. For durable production data, the next infrastructure step is a managed database.