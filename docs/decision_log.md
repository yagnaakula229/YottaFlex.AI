# Schema Decision Log

No standalone architecture blueprint or unresolved-decision log existed when Phase 2 began. `docs/implementation_plan.md` is the available architecture/phasing source, and `docs/business_rules.md` is the business decision source. This log records schema-level implementation defaults and the unresolved items that must not be mistaken for approved policy.

## Provisional choices used for Phase 2

| Topic | Phase 2 representation | Status / consequence |
| --- | --- | --- |
| Business IDs | Opaque `VARCHAR(64)` primary keys, exact string comparison, unique by primary-key constraint, immutable by PostgreSQL update trigger | Does not establish a prefix grammar or ID generator. Supplied samples fit without normalization. |
| `MSG--01` | No entity mapping, fixture, alias, or transformation. Message-template business ID columns accept the exact string if later assigned there. | Meaning is unresolved. No current row claims ownership of this ID. |
| Currency and money | `NUMERIC(19,4)` and a required per-record `CHAR(3)` currency code on monetary records | No default currency. ISO-4217 uppercase is the intended code format. Precision/scale and rounding must be confirmed before monetary calculations are implemented. |
| Consent history | Current state in unique `(customer_id, channel)` `Consent`; immutable timestamped `ConsentEvent` records | History/current-state reconciliation, effective-time semantics, and event ordering remain open. |
| Sessions | Python/table name `CustomerSession` / `customer_session` | Corresponds to the requested `Session`; avoids ambiguity with SQLAlchemy's ORM session type. |
| State values | PostgreSQL checks for customer, consent, cart, campaign, schedule, send-attempt, order, issue, and generation-run lifecycle values | Initial sets are structural defaults, not approved workflow. Expanding a state requires a migration. |
| Schedule idempotency | Required opaque unique key on `SendSchedule` | Schema guarantees one row per key. Key composition, retention, and policy-version behavior remain open. |
| Event idempotency | Required source system/key pair with a unique constraint on `MessageEvent`; equivalent source keys on cart/consent events | Upstream source identity and conflicting duplicate-payload handling remain open. |
| Event/audit immutability | PostgreSQL triggers reject updates/deletes on consent/cart/message events, audit events, attribution decisions/candidates, and ground-truth labels | Corrections must be represented as additional facts/decisions, not edits to history. Operational master/current-state tables remain mutable under later service rules. |
| Attribution | `Attribution` is the canonical credit table with a unique `order_id`; candidate/decision history is separate | Allows at most one canonical row per order. Touch eligibility, amount, conversion window, and tie-break are not determined by this schema. |
| Evaluation isolation | Separate PostgreSQL `evaluation` schema and `EvaluationBase.metadata`; labels reference operational entity type/ID as plain strings, never as operational foreign keys | Code and ORM metadata are separated. Database role grants must be configured so runtime operational credentials cannot read the evaluation schema in production. |
| Polymorphic audit/issue targets | Entity type plus opaque business ID strings, without polymorphic foreign keys | Preserves diagnostic history without pretending a single FK can cover several tables. |

## Initial constrained state values

These sets make invalid/unknown lifecycle values fail visibly in PostgreSQL. They are not substitutes for policy approval.

- Customer: `active`, `suppressed`, `deleted`
- Consent: `unknown`, `granted`, `denied`
- Cart: `open`, `converted`, `closed`, `abandoned`
- Campaign: `draft`, `active`, `paused`, `ended`
- Message template: `draft`, `active`, `archived`
- Send schedule: `scheduled`, `processing`, `sent`, `suppressed`, `cancelled`, `failed`
- Send attempt: `started`, `accepted`, `failed`
- Order: `pending`, `paid`, `cancelled`, `refunded`
- Issue: `open`, `acknowledged`, `resolved`, `false_positive`
- Generation run: `running`, `completed`, `failed`
- Ground-truth label code: `message_sent_after_opt_out`, `cart_abandoned_after_purchase`, `attribution_double_counted`, `stale_cart_total_after_quantity_update`

Event type columns remain strings rather than PostgreSQL enum types so provider-specific event names can be stored without a schema migration. Required event timestamps are timezone-aware.

## Decisions still requiring owner confirmation

1. Meaning and ownership of `MSG--01`; the Phase 2 schema intentionally does not assign it to a message or template.
2. Currency set, maximum precision, scale, rounding, and currency-specific minor units. The selected `NUMERIC(19,4)` is only a storage default.
3. Approved lifecycle states and transitions, including whether `deleted`, `abandoned`, `suppressed`, and `refunded` are required states or should be represented as events only.
4. Consent source of truth, event effective-time semantics, backdated opt-outs, and treatment of late/out-of-order consent events.
5. Cart/order cardinality, partial purchase behavior, and whether a cart may be linked to multiple orders.
6. Exact source idempotency scope and duplicate key/different-payload policy for events.
7. Schedule idempotency-key derivation and behavior when the campaign or policy version changes.
8. Attribution candidate eligibility, conversion-window anchor, refunds, decision versioning, and tie-breaking.
9. Evaluation-schema runtime permissions and whether evaluation should use a separate PostgreSQL role or separate database.
10. Audit-event retention, actor identity, deletion policy, and whether audit rows need cryptographic tamper evidence.

These choices do not prevent the structural migration below: unresolved behavior is represented with opaque identifiers, independent currency columns, append-only event tables, nullable links where semantics are not fixed, and explicit checks for the current provisional state sets. Do not implement domain services based on these provisional defaults until they are approved.

## Phase 3 generation boundary

- Normal profile generation produces clean operational records only. The four evaluation labels are present with `expected=false`; no deliberate anomaly facts are injected into operational tables. Constructing positive anomaly fixtures remains separate work because some cases intentionally contradict operational policy and need explicit fixture authorization.
- No attribution decisions, candidates, or canonical credits are generated until attribution touch eligibility, window anchoring, and tie-breaking are approved. Generated orders remain unattributed.
- Scale profile `abandoned_carts=20,000` means carts whose generated `Cart.status` is `abandoned`, whose `updated_at` is at least the configured inactivity interval before `reference_time`, and which have no linked order. Consent/frequency eligibility is applied after that cart state; actual schedules/attempts may be lower.

## Phase 4 provisional recovery policy

The first recovery-decision implementation uses the configurable defaults in `business_rules.md`: inclusive 60-minute inactivity; qualifying cart activity event types; accepted send attempts in `(lower, upper]` rolling windows; fail-closed effective channel consent; and deterministic campaign-ID/template-priority/template-ID selection. Every decision records policy version and a hash of the complete policy configuration. These defaults are not approved business rules and can be changed by settings plus a new version; decision history is retained.

`RecoveryDecision` is an operational append-only history record. `SendSchedule` records the authorizing decision, policy version, and policy hash. Equivalent idempotency-key reuse replays the stored schedule; incompatible reuse returns a conflict. Evaluation-label data remains under the separate `evaluation` schema and is not imported by `app.services`.

`Consent.last_event_id` references the latest event by `(occurred_at, business_id)`. Current-state upserts use the same ordering predicate, preventing late or concurrent older events from regressing the projection while preserving each immutable `ConsentEvent`.