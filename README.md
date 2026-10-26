# YottaFlex AI - Abandoned Cart Recovery Platform

An end-to-end platform to identify abandoned shopping carts, enforce customer consent, coordinate personalized recovery campaigns, and measure attributed conversions.

## Phase 1: Infrastructure

The API is a synchronous FastAPI application using SQLAlchemy 2.0 sessions with the psycopg 3 PostgreSQL driver. Synchronous database access keeps transaction boundaries explicit and avoids mixing async and sync session patterns in this assignment. The readiness check executes `SELECT 1` against PostgreSQL; liveness does not depend on the database. Phase 2 adds the operational and isolated evaluation schemas; recovery services and domain API routes do not exist yet.

### Requirements

- Python 3.11 or newer
- Docker Desktop with Docker Compose

### Install (Windows PowerShell)

Run from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, allow scripts for the current user with `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, then activate the environment.

### Configure PostgreSQL

Create a local `.env` with development-only values and start PostgreSQL. The Compose service creates both the application database and a separate integration-test database on first initialization of its data volume.

```powershell
Copy-Item .env.example .env
@'
APP_NAME=YottaFlex AI
ENVIRONMENT=development
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg://yottaflex:local-dev-only@localhost:5432/yottaflex
TEST_DATABASE_URL=postgresql+psycopg://yottaflex:local-dev-only@localhost:5432/yottaflex_test
DATABASE_CONNECT_TIMEOUT_SECONDS=5
'@ | Set-Content -Encoding ascii .env
docker compose up -d postgres
```

These credentials are only for local development. Do not use them outside a local environment. The init script runs only when PostgreSQL initializes an empty data volume. If the volume already existed before the test database was added, create it once with:

```powershell
docker compose exec -T postgres createdb -U yottaflex yottaflex_test
```

### Apply migrations

Migrate the application database using `DATABASE_URL` from `.env`, then migrate the separate test database by temporarily overriding that setting:

```powershell
python -m alembic upgrade head
$env:DATABASE_URL = "postgresql+psycopg://yottaflex:local-dev-only@localhost:5432/yottaflex_test"
python -m alembic upgrade head
Remove-Item Env:DATABASE_URL
```

Alembic creates the operational tables and the separate PostgreSQL `evaluation` schema. No domain data is seeded by migrations.

### Run the API

```powershell
python -m uvicorn app.main:app --reload
```

Open Swagger UI at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Health endpoints are `/health/live` and `/health/ready`.

### Run tests

```powershell
python -m pytest -m unit
python -m pytest -m integration
python -m pytest
python -m pytest -q
```

PostgreSQL integration tests require `TEST_DATABASE_URL` to point at a database migrated to the current Alembic head. If the URL is absent, pytest reports those tests as skipped; a skipped integration test is not PostgreSQL verification. Constraint tests run inside transactions that are rolled back.
