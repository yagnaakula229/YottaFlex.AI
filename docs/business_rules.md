# Business Rules and Open Decisions

This document separates confirmed assignment requirements from provisional defaults. None of the proposed thresholds below are confirmed business requirements. Make policy values configurable and versioned so a later decision does not require changing historical event facts.

## Confirmed contract

- Identify abandoned carts using an explicit, documented policy.
- Enforce consent independently for each communication channel and apply frequency caps.
- Re-evaluate eligibility at scheduled-send execution time, not only at schedule creation.
- Make schedule creation and event ingestion idempotent; record send, delivery, open, and click events.
- Attribute orders under a deterministic documented policy and allow no more than one canonical credit per order.
- Preserve the four deliberate anomalies as detectable historical facts; do not silently repair them.
- Keep ground-truth labels separate from operational data. Operational services must not read labels.
- Use deterministic synthetic generation (seed `20261022`), stable ordering, immutable supplied IDs, and timezone-aware UTC timestamps. Business outcomes must not depend on wall-clock time or uncontrolled randomness.

## Provisional policy defaults

These values are starting assumptions for discussion, not approved requirements:

| Policy | Provisional default | Decision still needed |
| --- | --- | --- |
| Cart abandonment | No qualifying cart activity for 60 minutes | Which activities reset inactivity; whether the threshold is inclusive; what explicit `as_of` time is used for evaluation |
| Frequency cap | At most one send per channel per 24 hours and three per channel in a rolling seven-day window | Confirm channel scope, eligible event counted as a send, rolling-window boundary, timezone, and whether suppressed/failed attempts count |
| Conversion window | Seven days before an order | Confirm whether the window is measured from send, delivery, open, or click, and whether endpoints are inclusive |
| Attribution candidate | Last qualifying campaign click before the order within the conversion window; no click means no campaign credit | Confirm click-only eligibility, treatment of multiple sends/campaigns, click identity, tie behavior, and treatment of refunds/cancellations |

An initial deterministic tie-break for otherwise-equal qualifying clicks can use the stable event ID as a final ordering key. This is a proposed implementation detail, not a confirmed business rule. Attribution must still produce at most one canonical credit per order even if input history contains multiple campaign candidates.

## Consent and eligibility questions

- What is the authoritative consent source and how are consent changes represented over time: current state, append-only history, or both?
- Which channel values are supported, and what does unknown, missing, or conflicting consent mean? Proposed fail-closed behavior is to suppress a send unless affirmative channel consent is current at execution time.
- Which timestamp determines consent at execution, and how are late-arriving or backdated opt-outs handled?
- What other send-time eligibility checks apply (cart still open, purchase status, customer suppression, campaign status, deliverability)? Define their order and durable suppression reasons.
- Is a consent change required to cancel already scheduled sends immediately, or is execution-time re-evaluation sufficient? The assignment requires re-evaluation at execution; cancellation timing remains open.

## Identity, schedule, and event semantics

- Preserve all supplied identifiers byte-for-byte, especially `CUS-000001`, `CART-2026-000001`, `CMP-2026-000001`, `SEND-2026-000001`, and `ORD-2026-000001`.
- Preserve `MSG--01` exactly as the supplied example. Its meaning is unresolved: it may identify a message or a template. Do not rename it, normalize its punctuation, infer an entity mapping, or use it to establish a foreign-key relationship until clarified.
- Decide the idempotency key for a schedule (likely a stable combination of cart, campaign, channel, and policy/trigger version) and whether a later policy change permits another schedule.
- Decide the external/source idempotency key for each event and behavior for duplicate payloads with conflicting contents. Store source event time separately from ingestion time; ingestion time must not choose reproducible business outcomes.
- Define event ordering for equal timestamps, retry semantics, and whether event payloads are immutable. Preserve send, delivery, open, and click facts even when they arrive late or contradict an anomaly label.
- Define what constitutes a successful send for caps (attempt, accepted send event, or provider confirmation) and how provider retries map to one logical send.

## Cart, order, and attribution semantics

- Define cart status transitions, whether multiple carts can be active per customer, and what purchase closes a cart. Define how partial purchases and multiple orders relate to one cart.
- Choose decimal precision, currency handling, and the source of truth for cart totals. A quantity update must not silently rewrite event history; define whether the cart total is a live projection or a versioned snapshot so the stale-total anomaly is observable.
- Define order identity, order event time, and how cancellations, refunds, or duplicate order imports affect canonical credit.
- Confirm attribution touch eligibility and precedence (click, open, send, or other touch). Proposed default is click-only last-touch within seven days, with no credit absent a qualifying click.
- Enforce one canonical attribution row/credit per order with a database unique constraint or unique partial index. Any noncanonical candidate/diagnostic rows must be distinguishable from the one canonical credit.

## Anomalies and ground truth

Generate and detect these four distinct cases without repairing source facts: (1) a message sent after opt-out, (2) a cart considered abandoned after purchase, (3) the same order credited canonically to multiple campaigns, and (4) a cart total stale after a quantity update. Define the exact fixture IDs, event sequence, detection query/result shape, and whether each anomaly is injected at source generation or in a separate anomaly fixture before implementation.

Store labels in a separate ground-truth boundary (for example, a distinct schema or isolated dataset) with explicit access controls. The generation/validation harness may compare detections to labels; operational repositories and services must have no label dependency, import, or query path. Decide whether labels can reference operational IDs and how that reference is protected from accidental operational access.

## Configuration and audit decisions

- Decide where policy versions and values live (configuration file, database policy records, or both), how they are audited, and which administrative roles can change them.
- Define retention and privacy requirements for customer, consent, message, and event records. Synthetic fixtures should contain no real personal data.
- Define authorization for administrative/destructive endpoints and migration/data-reset scripts. Require explicit environment safeguards for destructive operations.
- Use a fixed scenario/as-of timestamp for deterministic generation and evaluation. Decide its value and whether it is a generation parameter or a versioned dataset property; never substitute the machine's current time implicitly.

## Phase 2 schema posture (provisional)

The following storage choices are implementation defaults, not approved business policy. Their rationale and remaining questions are recorded in `docs/decision_log.md`.

- Store business IDs as opaque `VARCHAR(64)` primary keys. Do not apply entity-specific formatting, parsing, or normalization. This keeps `MSG--01` representable without deciding whether it is a message or template ID.
- Store monetary values as `NUMERIC(19, 4)` with a required three-character currency code on each monetary aggregate/line/order. Do not assume a single platform currency. Confirm minor-unit and rounding rules before services calculate totals.
- Store one current consent row per customer/channel and append consent changes to `ConsentEvent`; event facts are not updated or deleted by application flows.
- Use `CustomerSession` as the Python/database name for the required `Session` entity to avoid collisions with SQLAlchemy's `Session` class.
- Use an opaque, required unique `idempotency_key` for each `SendSchedule`; its derivation and policy-version behavior are not encoded in the schema.
- Model `Attribution` as the canonical per-order credit row, with a unique `order_id`. Candidate and decision history remain separate records.
- Put ground-truth labels and evaluation-run metadata under PostgreSQL schema `evaluation`, with their own SQLAlchemy metadata and no ORM relationships to operational entities. Labels may store entity type and business ID as plain values; they do not create foreign keys into operational tables.
- Use PostgreSQL check constraints for the initial lifecycle-state sets listed in `docs/decision_log.md`. Revisit those values with the domain owner before business services rely on them.

## Phase 4 recovery decision defaults (provisional)

These assumptions remain configurable through application settings and are captured by a policy version and configuration hash on every recovery decision/schedule. They do not change the confirmation status of the earlier business rules.

- Abandonment threshold: cart inactivity of 60 minutes, inclusive at the lower boundary (`last_activity_at <= evaluated_at - threshold`). Qualifying activity types default to `cart_created`, `cart_activity`, `cart_line_added`, `cart_line_updated`, and `cart_line_removed`; conversion/closure/abandonment marker events do not reset inactivity. At least one qualifying event must exist at or before the evaluation timestamp. The current cart projection timestamp may be used only as a fallback when a qualifying event exists and the projection is later; deployments with stricter event sourcing may disable that fallback.
- Cart validity: at least one line; quantities and amounts nonnegative/positive as constrained by PostgreSQL; each line total equals quantity times unit price at stored precision; all line currency codes match the cart currency; sum of line totals equals the current cart total. A mismatch suppresses with `stale_cart_total` rather than being repaired.
- Purchase state: any linked order in `pending`, `paid`, or `refunded` blocks recovery. A `cancelled` order does not block by default. This remains configurable pending confirmation of refund/cancellation semantics.
- Consent: resolve the latest `ConsentEvent` with `occurred_at <= evaluated_at`, ordered by event time and stable event business ID; fall back to the current projection only if no qualifying event exists and its `updated_at <= evaluated_at`. The `Consent.last_event_id` pointer is advanced monotonically using the same ordering, so late events remain history without regressing current state. Only `granted` permits a send. Missing, `unknown`, `denied`, invalid, or withdrawn state blocks.
- Frequency caps: only `SendAttempt.status='accepted'` qualifies. Evaluate open-left/closed-right rolling windows `(evaluated_at - 24 hours, evaluated_at]` and `(evaluated_at - 7 days, evaluated_at]`; defaults are one and three qualifying accepted attempts per customer/channel. Failed attempts and mere schedules do not count.
- Campaign/template selection: only active campaigns created by evaluation time, with an active channel-matched template, nonblank content, and a valid active mapping qualify. Stable selection is ascending campaign business ID, then mapping priority, then template business ID.
- Conversion window: seven days is retained in the policy snapshot for downstream use; Phase 4 does not create orders, attribution candidates, or credits.
- Every evaluation is append-only and records an explicit UTC evaluation timestamp, outcome, machine-readable reason, policy version, config hash, and evidence. No service reads evaluation ground-truth labels.
- Primary suppression reason follows a deterministic first-failure order: blocking purchase; cart status/contents/totals; qualifying activity and inactivity threshold; customer status; channel-specific consent; frequency caps; compatible active campaign/template. Later checks are not run after an earlier failure, and the decision evidence contains the checks that were reached. Thus missing/withdrawn consent takes precedence over a simultaneously reached frequency cap.
- Canonical machine-readable reasons include `FREQUENCY_CAP` (with `triggered_window` identifying `24h` or `7d`) and `NO_CAMPAIGN_TEMPLATE`. Other reasons remain stable snake-case codes such as `empty_cart`, `prior_purchase`, `stale_cart_total`, `consent_missing`, and `consent_withdrawn`.