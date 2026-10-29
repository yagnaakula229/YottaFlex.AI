# Implementation Plan

The target is a Python modular monolith using FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, and pytest. Keep the boundaries below distinct within one deployable application. This plan is intentionally not implementation: no application models, routes, or business services are part of this documentation phase.

## Phases

1. **Resolve decisions and establish the project.** Confirm the open items in `business_rules.md`, especially `MSG--01`, consent semantics, policy windows, attribution touch rules, and cart/order relationships. Establish the Python package, dependency/developer tooling, environment configuration, PostgreSQL test strategy, and exact documented run/test commands. Keep the architecture a modular monolith.
2. **Define persistence boundaries and migrations.** Completed with the provisional schema posture recorded in `business_rules.md` and `decision_log.md`: SQLAlchemy 2.0 operational mappings, isolated evaluation metadata, reversible Alembic migrations, PostgreSQL constraints/triggers, and integration tests. Remaining semantic decisions must be confirmed before service behavior depends on the provisional state and currency defaults.
3. **Build deterministic synthetic data.** Implement seed `20261022`, stable ID and ordering strategies, a fixed scenario/as-of timestamp, and dependency-ordered generation: master data first, then transactions, then events. Preserve supplied IDs exactly. Keep labels isolated from operational data and make anomaly fixtures deterministic.
4. **Implement policy services.** Completed with configurable, versioned policy and testable services for abandonment, effective channel consent, frequency caps, campaign/template selection, and eligibility. Decisions are append-only and use explicit UTC evaluation instants and stable ordering.
5. **Implement schedule creation and execution.** Logical schedule creation, execution-time eligibility re-evaluation, and deterministic simulated provider outcomes are implemented as services. External provider delivery and operational execution HTTP routes are not implemented.
6. **Implement event ingestion.** Send, delivery, open, and click ingestion has stable source idempotency keys, duplicate/conflict handling, UTC timestamps, and append-only history. Unit and PostgreSQL tests cover equivalent retries, conflicts, late arrivals, and database constraints.
7. **Implement attribution and anomaly validation.** A service implements provisional click-last-touch attribution within seven days, stable event-ID tie-breaking, no-credit behavior, and one canonical credit per order. PostgreSQL fixtures and validation detect post-withdrawal sends, abandoned-after-purchase carts, and stale cart totals. A separate evaluation-only legacy-credit fixture detects a double-credit anomaly across campaigns without weakening the operational unique-order constraint. Ground-truth labels remain in the isolated evaluation schema and are read only by evaluation/test code.
8. **Expose the API and secure operations.** Health routes and a synthetic demo-summary route are implemented. The dashboard consumes that demo endpoint; business workflows remain service-level. Authentication/authorization, operational workflow routes, and protected administration remain incomplete.
9. **Run end-to-end verification and document operations.** Unit, PostgreSQL integration, full-suite, frontend build, API/UI smoke, small-profile reproducibility, and rollback-only scale count checks have been run in the local environment. Positive anomaly detection remains outstanding. Document exact setup, run, migration, seed, validation, and test commands; report only checks actually executed.

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

The repository has a synchronous FastAPI entry point, environment settings, SQLAlchemy 2.0/psycopg session management, PostgreSQL-backed readiness, operational and isolated evaluation schemas, deterministic generation, recovery/execution/attribution services, message-event ingestion, and a React/Vite synthetic dashboard. Docker Compose provides a separate PostgreSQL test service on loopback port 5433; integration tests require `TEST_DATABASE_URL` to target a database migrated to Alembic head. Alembic independently reads `DATABASE_URL`. A skipped integration test is not verification.

Current completion gaps: the DB constraint prevents persisting a second canonical attribution, so cross-campaign double credit is represented and detected only in evaluation fixture data; the dashboard is intentionally synthetic under the current route scope. Scale counts were verified in a rollback-only PostgreSQL run, but no scale dataset was persisted. External provider delivery and authentication/authorization are also outside the implemented scope.