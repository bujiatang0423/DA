# DA development

Run PostgreSQL with `docker compose up -d postgres`, then apply migrations with
`python -m alembic upgrade head`. Start the API with `python -m backend.app.main` and the
web app with `cd web && npm run dev`. Run `make verify` before submitting changes.
