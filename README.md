# Task Management API

REST API on FastAPI for managing tasks: JWT auth, task CRUD, comments, a status workflow,
search / filter / sort / pagination, overdue list, statistics and a background job that
cancels tasks whose deadline has passed.

Stack: FastAPI, SQLAlchemy 2 (async, asyncpg), PostgreSQL 16, Alembic, Pydantic v2, pytest.

## Run

```bash
echo "SECRET_KEY=$(openssl rand -hex 32)" > .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up --build
```

There are no built-in credentials: compose refuses to start without `SECRET_KEY` and
`POSTGRES_PASSWORD`, and the app refuses to start with a placeholder or a `SECRET_KEY` shorter than
32 bytes. Postgres is published on `127.0.0.1:5432` only.

The `api` container waits for a healthy Postgres, applies migrations (`alembic upgrade head`)
and serves on <http://localhost:8000> (Swagger UI at `/docs`).
Settings come from `.env` (see `.env.example`): `SECRET_KEY`, `POSTGRES_PASSWORD`,
`ACCESS_TOKEN_EXPIRE_MINUTES`, `WORKER_ENABLED`, `WORKER_INTERVAL_SECONDS`.

## Tests

```bash
docker compose run --rm api pytest -q
```

Tests run against the real Postgres from compose, in a separate `app_test` database that the
suite creates itself. The background worker is disabled in tests (`WORKER_ENABLED=false`).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | email + password (min 8 chars) |
| POST | `/auth/login` | OAuth2 password form (`username` = email), returns a 30 min JWT |
| GET | `/users/me`, `/users` | current user / list users (to pick assignees) |
| POST | `/tasks` | create |
| GET | `/tasks` | list: `q`, `status`, `priority`, `assignee_id`, `deadline_from`, `deadline_to`, `sort_by` (`created_at`/`deadline`/`priority`), `order`, `limit` (1-100), `offset` |
| GET | `/tasks/overdue` | deadline passed and status not Done/Cancelled (paginated) |
| GET | `/tasks/stats` | totals by status/priority, overdue, active |
| GET / PATCH / DELETE | `/tasks/{id}` | read / edit / delete |
| PATCH | `/tasks/{id}/status` | the only way to change status |
| POST / GET | `/tasks/{id}/comments` | add / list comments |

Lists return `{items, total, limit, offset}`. Default order: priority High > Medium > Low,
then nearest deadline (tasks without a deadline last).

## Business rules

- Statuses: Backlog, In Progress, Review, Done, Cancelled. Allowed transitions:
  Backlog -> In Progress / Cancelled, In Progress -> Review / Cancelled, Review -> Done.
  Anything else (including going back) returns `409`.
- Done needs an assignee and a deadline that has not passed (a task with no deadline can be Done).
- Deadline must not be in the past on create or when it is sent in an edit (`422`).
- Assignee cannot change once the task is in Review; Done / Cancelled tasks cannot be edited.
- Delete is allowed only in Backlog, Done or Cancelled (hard delete, comments cascade).
- An assignee may hold at most 10 active tasks (Backlog, In Progress, Review); the assignee row
  is locked while counting so concurrent assignments cannot exceed the limit. The spec's
  "Todo" is treated as Backlog.
- Known limitation: any user can assign a task to any other user (as the spec describes), so one user
  can fill another's 10-task quota. A consent or team-membership model would be needed to prevent it.
- Permissions: only the author edits or deletes; the author or assignee changes status; any
  authenticated user can read tasks and comment.

## Background job

An asyncio task started in the FastAPI lifespan runs every `WORKER_INTERVAL_SECONDS` (default 60)
and cancels every Backlog / In Progress / Review task whose deadline has passed with a single
`UPDATE`. This is an intentional system action: it bypasses the user transition map, so
Review -> Cancelled is possible here even though users cannot do it.

Because the job cancels overdue tasks, `/tasks/overdue` is normally only non-empty between sweeps;
it queries live data, so it reports everything the job has not processed yet.
