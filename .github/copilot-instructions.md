# Copilot Instructions

## Project contract

Build a consent-aware abandoned-cart recovery and attribution platform as a Python modular monolith. The intended stack is FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, and pytest. Do not introduce microservices or a frontend unless the project owner changes this direction.

Keep API routes, schemas, models, repositories, services, synthetic-data generation, validation, migrations, tests, and scripts in distinct, purposeful modules. Put business rules in testable service functions. Use SQLAlchemy 2.0 APIs and Alembic migrations. Enforce invariants in PostgreSQL with constraints and indexes wherever possible; application checks supplement, not replace, database constraints.

## Data and behavior requirements

- Generate reproducible synthetic data with seed `20261022`; use deterministic ID generation and stable ordering. Never use the current wall clock or uncontrolled randomness to decide reproducible business outcomes. Use timezone-aware UTC timestamps and an explicit scenario/as-of time.
- Generate master data before dependent transactions and events.
- Preserve supplied business IDs exactly, including `CUS-000001`, `CART-2026-000001`, `CMP-2026-000001`, `MSG--01`, `SEND-2026-000001`, and `ORD-2026-000001`. Do not normalize, regenerate, or reinterpret them without an approved decision. `MSG--01` is unresolved: preserve it exactly and do not assume whether it identifies a message or a template.
- Apply the documented, configurable abandoned-cart policy, channel-specific consent, and frequency caps. Re-evaluate eligibility when executing a scheduled send; creation-time eligibility is not sufficient.
- Make schedule creation and event ingestion idempotent. Record send, delivery, open, and click events. Preserve event history; do not silently repair or erase anomalies.
- Apply a documented deterministic order-attribution policy and enforce at most one canonical attribution credit per order at the database level.
- Detect the four deliberate anomalies: a message sent after opt-out; a cart considered abandoned after purchase; attribution double-counted across campaigns; and a stale cart total after a quantity update. Keep ground-truth labels separate from operational data, and never allow operational services to read those labels.
- Protect administrative and destructive operations. Do not expose privileged behavior without an explicit authorization boundary.

## Design and change discipline

Before implementing business behavior, read `docs/business_rules.md` and record unresolved decisions and provisional assumptions there. Keep assumptions configurable and clearly distinguish them from confirmed requirements. Follow the phase boundaries in `docs/implementation_plan.md`; do not build application models, routes, or services as part of documentation-only work.

Preserve useful existing work. Keep changes scoped, add focused tests for behavior and database invariants in later implementation phases, and use PostgreSQL integration tests for PostgreSQL-specific behavior. Never report tests or commands as passing unless they were actually run.

## Repository commands

The infrastructure setup provides these commands from an activated project virtual environment:

- Run the API: `python -m uvicorn app.main:app --reload`
- Run unit tests: `python -m pytest -m unit`
- Run PostgreSQL integration tests: `python -m pytest -m integration` (requires `TEST_DATABASE_URL`; otherwise the integration test is skipped)
- Run all tests: `python -m pytest`

Alembic is configured in `alembic.ini` and reads `DATABASE_URL`; no migration revisions exist until a later schema phase. Do not report PostgreSQL integration tests as passing when they were skipped. Follow the exact PowerShell setup in `README.md`.