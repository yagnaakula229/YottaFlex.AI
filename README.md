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

## Phase 3: Synthetic data

The generator uses seed `20261022`, the configured `SCENARIO_AS_OF` or an explicit timezone-aware `--reference-time`, namespaced seeded random streams, deterministic string business IDs, stable insert ordering, and bounded Core-insert batches. `GenerationRun` stores profile, seed, generator version, config hash, requested and actual counts, reference time, and a canonical logical-dataset SHA-256. Export rows are streamed in schema/table/primary-key order and canonicalized before hashing; the self-referential `GenerationRun` row is excluded, while evaluation-run metadata and ground-truth rows are included.

### Profiles and abandonment semantics

- `small`: 100 carts, 50 customers, 40 designated for operational abandonment, and 10 converted carts/orders.
- `scale`: 50,000 carts, 25,000 customers, 20,000 designated for operational abandonment, and 5,000 converted carts/orders.

An operationally abandoned cart has `status='abandoned'`, its last activity (`Cart.updated_at`) is at or before the reference timestamp minus the configured 60-minute inactivity threshold, and it has no linked order. The scale target of 20,000 describes this operational cart state; it does not mean 20,000 customers are consented or 20,000 messages are sent.

Schedules are generated only for those abandoned carts with affirmative consent for the configured send channel. No-consent carts are counted as suppressed. At most one attempt is created per customer in this dataset, satisfying a stricter frequency limit than the provisional caps; the configured attempt maximum is 10,000. Provider outcomes are synthetic records, not real network sends. Actual attempts/accepted attempts are reported separately in the manifest and will generally be fewer than the abandoned-cart count. Consent and frequency rules are never bypassed to reach a target count.

The generator creates four clean-baseline evaluation labels with `expected=false`. It does not inject deliberate operational anomalies: anomaly fixture scenarios must remain separate from normal operational generation and require an explicit approved policy for constructing them. Attribution decisions, candidates, and canonical credits are reported as zero because the attribution policy and conversion-window semantics remain unresolved; the generator does not invent an attribution rule.

### Generate, rebuild, and compare

Use the local development database configured in `.env`. `generate` refuses to add a different dataset to a non-empty database; `rebuild` drops/recreates the schema and requires explicit confirmation. Rebuild is limited to `ENVIRONMENT=development`, loopback PostgreSQL, and local allowlisted YottaFlex database names.

```powershell
python -m app.generation rebuild --profile small --seed 20261022 --reference-time "2026-10-22T00:00:00+00:00" --confirm-destructive
python -m app.generation hash
python -m app.generation export --output synthetic-data.jsonl
python -m app.generation generate --profile scale --seed 20261022 --reference-time "2026-10-22T00:00:00+00:00"
```

The rebuild command uses `DATABASE_URL`, migrates to Alembic head, and writes the selected dataset. `generate` is idempotent for the same profile/config/reference time and rejects a different run until an explicit rebuild. Hash and export commands do not change the database. `MSG--01` remains unresolved and is not assigned to a message or template by this generator.
