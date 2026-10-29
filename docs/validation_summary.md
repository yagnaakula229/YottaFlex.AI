# Validation Summary

Verified 2026-10-29 against the local repository, Docker Desktop, and the isolated PostgreSQL test service. No real credentials are recorded here.

## Database and Migrations

- Docker service: `postgres-test`, healthy on `127.0.0.1:5433`.
- Effective Alembic `DATABASE_URL` and integration `TEST_DATABASE_URL` were checked before every DB-mutating test run. Both targeted `yottaflex_test` as `yottaflex_ci`; PostgreSQL confirmed that role is not a superuser.
- `alembic upgrade head` succeeded; `alembic current` reported `8b38919cdbcf (head)`.
- Test fixtures and generator validation used only the isolated Docker test database. Scale generation and second reproducibility runs were enclosed in rollback-only transactions.

## Automated Tests and Build

| Check | Result |
| --- | --- |
| Unit: `.venv\Scripts\python.exe -m pytest -m unit -q` | 52 passed, 37 deselected, 0 failed, 0 skipped |
| PostgreSQL: `.venv\Scripts\python.exe -m pytest -m integration -q` | 31 passed, 58 deselected, 0 failed, 0 skipped |
| Full: `.venv\Scripts\python.exe -m pytest -q` | 89 passed, 0 failed, 0 skipped |
| Frontend: `npm run build` in `frontend/` | Passed with Vite 8.3.5 |

Each pytest command reported one existing `StarletteDeprecationWarning` about using `httpx` with `starlette.testclient`; no test failed because of it.

## API and Browser

- `GET /health/live`: `{"status":"live"}`.
- `GET /health/ready`: `{"status":"ready"}` with PostgreSQL connectivity.
- `GET /api/demo/summary`: verified `synthetic-demo` mode, synthetic flag, candidate/event/order arrays, and integer attribution fields.
- FastAPI ran at `http://127.0.0.1:8000`; Vite ran at `http://127.0.0.1:5173`.
- Browser showed 3 candidates, 3 message events, 2 demo orders, and 2 attributed orders. Browser console errors and uncaught page errors: 0.
- Browser interception verified both empty collection messages and malformed-payload error/retry behavior. This is a demo dashboard backed by a fixed API payload, not a database-backed operational UI.
- Database-backed operational dashboard: not an explicit requirement in the current plan; the documented requirement is the synthetic demo-summary route, so the existing synthetic UI was retained.

## Exports and Anomaly Coverage

- JSONL: deterministic operational rows plus the source `GenerationRun` manifest; evaluation rows/labels excluded.
- CSV: one deterministic CSV per operational table plus an export manifest with table counts. CSV parsing, relationship integrity, and monetary arithmetic were verified.
- SQL: deterministic dependency-ordered PostgreSQL INSERT script for operational tables and source manifest, with evaluation data excluded. The script was imported into a temporary PostgreSQL schema during integration testing; row counts and foreign keys were verified.
- All four required anomalies have deterministic evaluation/test fixtures. Three operational facts are detected from operational rows; a legacy cross-campaign double-credit fixture is stored only in evaluation-run data. The operational unique order constraint remains intact and the attribution service returns the existing canonical credit.

## Small Profile and Reproducibility

Two independent rollback-only generation runs used seed `20261022`, reference time `2026-10-22T00:00:00+00:00`, profile `small`, and separate temporary JSONL output directories. Both returned the same counts and checksums:

- 50 customers, 100 carts, 40 abandoned carts, 10 orders, 3 campaigns, 6 templates, 193 cart lines, and 91 sessions.
- 30 schedules and attempts, 29 accepted attempts, 1 failed attempt, 71 message events, 1 evaluation run, and 4 clean-baseline labels (all `expected=false`). Ten abandoned carts lacked email consent and were not scheduled.
- Orphan line/order/attempt/event counts, arithmetic errors, stale generated cart totals, and date-order violations checked in the small run: 0.
- Configuration SHA-256: `a14fe7dd0f6dcc9e9419434cf2198e2c780f408a9291b6651caf9444ab377fb1`.
- Logical dataset SHA-256, both runs: `c6089965b87828a464e82cdbdb922e19e18e9d0f2c0f4b4589252c1d3a66d2f1`.
- Operational JSONL file SHA-256, repeated exports: `29d7be7a62a0864dd24ae47cba43cecced263dc551fb7060d28c061dd4e3a45e`.

The logical hash and JSONL byte hash use different constructions and are compared separately. The independent small-profile runs were rollback-only; a final small-profile manifest is now present in `yottaflex_test` for demonstration.

## Scale Counts

The scale profile ran once in a rollback-only transaction and generated 50,000 carts, 20,000 abandoned carts, 10,000 campaigns, 20,000 templates, 5,000 orders, 10,000 schedules, and 10,000 attempts. Consent allowed 15,019 email candidates and suppressed 4,981. Deterministic simulated outcomes were 9,794 accepted and 206 failed attempts. Logical dataset SHA-256: `185a56ab810c8fe56321205e922cfc53ee28322bdbbd7abdbf4faf9b00d4974d`. No scale rows were retained. The profile does not guarantee 10,000 accepted sends.

## Assignment Gaps

- Four anomaly cases have deterministic PostgreSQL/evaluation fixtures: sent after withdrawal, abandonment after paid order, stale cart total, and cross-campaign legacy double attribution. Operational facts are detected from operational rows; legacy double credit is detected from evaluation-only fixture data. Ground-truth labels remain in the separate evaluation schema.
- A second canonical attribution is rejected by the unique-order constraint, and the operational attribution service returns the existing row. The impossible duplicate is not persisted in operational tables.
- Attribution implementation and unit tests cover last eligible same-customer/cart click within seven days before placement, exclude clicks at/after placement, break ties by event business ID, and create no credit without a click. This remains a provisional business policy.
- JSONL, CSV, and SQL operational exports are implemented and tested. No external provider delivery, exactly-once delivery guarantee, or authentication/authorization is provided. The dashboard remains synthetic because the current plan does not require a live operational dashboard.
- Scale counts were validated, but no scale dataset remains persisted.
