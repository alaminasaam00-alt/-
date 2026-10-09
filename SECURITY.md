# Security baseline

- Helmet security headers are enabled.
- Request bodies are size-limited.
- API rate limiting is enabled.
- Secrets are environment variables and are not committed.
- Database access uses parameterized queries.
- The application runs as a non-root container user.
- Database credentials are provisioned by Render, not stored in source control.
- Audit events are stored in PostgreSQL.
- Production deployment must use HTTPS and a verified custom domain when available.

## Secrets
Never commit API keys, payment credentials, WhatsApp tokens, database passwords, or admin secrets to Git.
