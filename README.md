# Photoprint backend

Bare FastAPI + PostgreSQL (SQLAlchemy 2.0 async, Alembic) backend scaffold for
the hackathon project.

## Layout

```
app/
  main.py            FastAPI app factory and lifespan
  core/config.py     Settings (env + .env via pydantic-settings)
  db/                Engine, async session factory, get_db dependency
  models/            SQLAlchemy ORM models (import them in __init__.py)
  schemas/           Pydantic request/response models
  api/router.py      Aggregated /api/v1 router
  api/routes/        Route modules (health example included)
alembic/             Alembic async migration environment
```

## Setup

```sh
uv sync
cp .env.example .env   # then edit DATABASE_URL
```

Create the database and apply migrations:

```sh
uv run alembic upgrade head
```

Run the server:

```sh
uv run python main.py
# or: uv run uvicorn app.main:app --reload
```

## Endpoints

- `GET /health` — liveness (no database access)
- `GET /health/db` — readiness (verifies `SELECT 1`)
- `GET /docs` — Swagger UI

## Adding a model + migration

1. Add a model in `app/models/` and import it in `app/models/__init__.py`.
2. Generate a migration: `uv run alembic revision --autogenerate -m "..."`.
3. Apply it: `uv run alembic upgrade head`.
