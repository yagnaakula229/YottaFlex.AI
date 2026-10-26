# Implementation Plan

The target is a Python modular monolith using FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, and pytest. Keep the boundaries below distinct within one deployable application. This plan is intentionally not implementation: no application models, routes, or business services are part of this documentation phase.

## Phases

1. **Resolve decisions and establish the project.** Confirm the open items in `business_rules.md`, especially `MSG--01`, consent semantics, policy windows, attribution touch rules, and cart/order relationships. Establish the Python package, dependency/developer tooling, environment configuration, PostgreSQL test strategy, and exact documented run/test commands. Keep the architecture a modular monolith.
2. **Define persistence boundaries and migrations.** Design operational entities, append-only event records, idempotency keys, policy/configuration representation, and database invariants. Define a physically/logically isolated ground-truth boundary with access rules. Add SQLAlchemy 2.0 mappings and Alembic migrations only after the schema decisions are approved. Add PostgreSQL integration tests for constraints and transaction behavior.
3. **Build deterministic synthetic data.** Implement seed `20261022`, stable ID and ordering strategies, a fixed scenario/as-of timestamp, and dependency-ordered generation: master data first, then transactions, then events. Preserve supplied IDs exactly. Keep labels isolated from operational data and make anomaly fixtures deterministic.
4. **Implement policy services.** Add testable services for abandonment, channel-specific consent, frequency caps, and eligibility. Make provisional thresholds configurable and policy-versioned. Use explicit UTC instants and deterministic ordering; never call current wall-clock time to decide generated outcomes.
5. **Implement schedule creation and execution.** Define schedule idempotency and database uniqueness. At execution, re-evaluate consent, cart/purchase state, caps, and campaign eligibility in a transaction-safe manner. Record durable outcomes/suppression reasons and preserve the send event history.
6. **Implement event ingestion.** Ingest send, delivery, open, and click events with stable source idempotency keys, duplicate/conflict handling, UTC timestamps, and immutable history. Add tests for duplicate delivery, retries, late arrivals, and stable event ordering.
7. **Implement attribution and anomaly validation.** Apply the approved deterministic attribution policy and enforce one canonical credit per order in PostgreSQL. Build read-only validation that detects all four specified anomalies and compare detections to isolated ground-truth labels; operational services must not access labels. Do not auto-correct records.
8. **Expose the API and secure operations.** Add schemas, repositories, service-wired API routes, authentication/authorization boundaries, and protected administrative/destructive operations. Keep the API as the modular monolith's interface, not a separate service. Add route and authorization tests.
9. **Run end-to-end verification and document operations.** Run the documented unit suite and PostgreSQL integration suite against a supported PostgreSQL instance; verify reproducibility, migration up/down expectations, idempotency, invariants, and anomaly detection. Document exact setup, run, migration, seed, validation, and test commands. Report only checks actually executed.

## Unresolved schema decisions

- Whether `MSG--01` is a message ID or template ID, and the message/template/send relationship.
- Customer consent representation: current state versus append-only history, channel enumeration, source, effective time, and backdated updates.
- Cart and line-item model: concurrent carts per customer, lifecycle states, quantity/price snapshots, decimal precision, currencies, and derived-total semantics.
- Cart-to-order cardinality, partial purchase behavior, order lifecycle, refunds/cancellations, and the timestamp used by attribution.
- Event envelope fields, event/source identity, idempotency-key scope, deduplication conflict rules, event immutability, and ordering ties.
- Schedule uniqueness dimensions and policy-version behavior; send attempt versus provider-accepted event semantics for frequency caps.
- Attribution candidates versus canonical credits, click identity, tie-break, conversion-window anchoring, and database enforcement shape (unique constraint or unique partial index).
- Ground-truth physical separation, permissions, label-to-fixture references, and validation-only access path.
- Policy storage/versioning, scenario/as-of timestamp, and supported time precision.

## Principal risks and controls

| Risk | Control to design and test |
| --- | --- |
| Consent changes after scheduling create an ineligible send | Re-check current channel consent at execution; fail closed on unknown consent unless policy is explicitly approved otherwise. |
| Concurrent workers bypass frequency caps or create duplicate schedules | Use database uniqueness and transaction/locking strategy; test concurrent PostgreSQL transactions, not only in-memory logic. |
| Duplicate or retried provider events distort history or caps | Stable idempotency keys, durable event uniqueness, and explicit handling for same-key/different-payload conflicts. |
| Multiple campaigns receive canonical credit for one order | Database-enforced single canonical credit per order, plus a validator for historical/fixture violations. |
| Synthetic results drift between runs | Fixed seed and scenario time, deterministic ID derivation and sorting, controlled random generator only where needed, and a reproducibility test. |
| Anomaly examples are “fixed” by projections or labels leak into behavior | Preserve source events; isolate labels by schema/permissions and assert operational services cannot import/query them. |
| Mutable cart totals hide stale-snapshot anomaly | Define event/snapshot versus projection semantics; retain quantity and total history and validate against the intended source of truth. |
| Provisional thresholds become accidental production policy | Explicit configuration, policy versioning, documentation of approval state, and tests around window boundaries. |
| Destructive scripts or administrative routes damage data | Explicit authorization, safe defaults, environment checks, and separate confirmation/guardrails for destructive actions. |

## Current repository baseline

Phase 1 infrastructure is established: the repository has a synchronous FastAPI entry point, centralized environment settings, SQLAlchemy 2.0/psycopg connection and session management, PostgreSQL-backed liveness/readiness routes, structured JSON logging, pytest unit/integration markers, and an Alembic environment. Local PostgreSQL is available through Docker Compose with a separate test database. Exact Windows PowerShell commands are documented in `README.md` and the command summary in `.github/copilot-instructions.md`.

There are intentionally no domain models, migration revisions, recovery services, synthetic-data generators, or frontend. Those remain for later phases after business/schema decisions are resolved. Phase 1 unit and PostgreSQL connectivity tests have been added; run the PostgreSQL marker with `TEST_DATABASE_URL` configured and do not count a skipped integration test as verification.