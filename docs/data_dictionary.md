# Data Dictionary

Operational tables use opaque `VARCHAR(64)` business IDs as primary keys unless noted. Timestamps are timezone-aware PostgreSQL timestamps. Lifecycle values and monetary constraints are enforced by database checks where defined. `CustomerSession` is the Python model name for the required Session entity.

## Customer and Commerce

| Table / model | Purpose and key relationships |
| --- | --- |
| `customer` / `Customer` | Customer identity, optional email, lifecycle status, creation time. Parent of consent, sessions, carts, and orders. |
| `consent` / `Consent` | Current per-customer/channel state; unique customer/channel pair; optional pointer to latest `ConsentEvent`. |
| `consent_event` / `ConsentEvent` | Append-only consent facts with source idempotency key and occurred/recorded timestamps; FK to customer. |
| `customer_session` / `CustomerSession` | Customer activity interval with optional end time and JSONB attributes; FK to customer. |
| `cart` / `Cart` | Customer cart lifecycle, currency, total, created/updated timestamps; FK to customer. |
| `cart_line` / `CartLine` | Cart item, quantity, unit price, line total, currency, and JSONB attributes; FK to cart; unique cart/item pair. |
| `cart_event` / `CartEvent` | Append-only cart event history with source idempotency key and occurred/recorded timestamps; FK to cart. |
| `orders` / `Order` | Customer purchase status, total, currency, placement time, and optional cart link; FK to customer and cart. |

## Campaign and Messaging

| Table / model | Purpose and key relationships |
| --- | --- |
| `campaign` / `Campaign` | Campaign identity, lifecycle status, and creation time. |
| `message_template` / `MessageTemplate` | Channel-specific template identity, status, content, and creation time. |
| `campaign_template` / `CampaignTemplate` | Campaign/template mapping with priority; unique campaign/template pair and campaign/priority. |
| `send_schedule` / `SendSchedule` | Logical scheduled send, customer/cart/campaign, channel, policy provenance, status, and schedule time; unique idempotency key and FKs to parents. |
| `send_attempt` / `SendAttempt` | Provider-attempt history and status; FK to schedule; unique attempt number per schedule. |
| `message_event` / `MessageEvent` | Append-only sent/delivered/opened/clicked facts with source key and occurred/recorded timestamps; FK to attempt; unique source system/event key. |

## Attribution, Audit, and Generation

| Table / model | Purpose and key relationships |
| --- | --- |
| `attribution_decision` / `AttributionDecision` | Append-only order attribution decision and evidence; FK to order. |
| `attribution_candidate` / `AttributionCandidate` | Ranked candidate events for a decision; FKs to decision, campaign, and message event. |
| `attribution` / `Attribution` | Canonical optional campaign/event credit for an order; unique order FK ensures at most one row per order. |
| `issue` / `Issue` | Validation issue type, target, status, detection time, and details; optional FK to generation run. |
| `audit_event` / `AuditEvent` | Append-only audit facts with entity target, action, actor, time, and JSONB details. |
| `generation_run` / `GenerationRun` | Source manifest: seed/profile/version, configuration hash, requested/actual counts, reference timestamp, status, and logical dataset SHA-256 in `actual_counts`. |

## Evaluation Boundary

`evaluation.evaluation_run` stores run metadata and optional evaluation-only anomaly fixture facts in `results`. `evaluation.ground_truth_label` stores label code, entity reference as plain strings, expected value, payload, and recording time. These tables use separate SQLAlchemy metadata and are not operational foreign-key targets. Normal clean-baseline generation creates four labels with `expected=false`; positive fixtures are created only by evaluation tests. Operational export formats exclude these tables and labels.

## Constraints and Policy Caveats

Primary/foreign keys, unique keys, lifecycle checks, positive quantity/rank, nonnegative monetary values, and timestamp ordering checks provide structural integrity. The database does not currently enforce cart total equals the sum of line totals, consent effective-time semantics, or a full workflow transition graph. Currency precision is `NUMERIC(19,4)` with a three-character code. Status values and recovery/attribution policies remain provisional as described in [business_rules.md](business_rules.md) and [decision_log.md](decision_log.md).
