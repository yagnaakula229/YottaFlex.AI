# Synthetic Source Manifest

When a generated dataset is committed, its authoritative source manifest is the `public.generation_run` row. It records `business_id`, seed, profile, generator version, configuration hash, requested and actual counts, reference timestamp, scenario timestamp, status, and canonical configuration. `actual_counts.dataset_sha256` is the logical dataset checksum. A separate `evaluation.evaluation_run` references the generation manifest, and labels remain outside operational metadata. The verification snapshot below was generated twice in rollback-only transactions, so its manifest rows were not retained in the test database.

## Verified Small Run

| Field | Value |
| --- | --- |
| Generator version | `1.0.0` |
| Profile | `small` |
| Seed | `20261022` |
| Reference timestamp | `2026-10-22T00:00:00+00:00` |
| Generation run ID | `GEN-small-a14fe7dd0f6dcc9e9419` |
| Configuration SHA-256 | `a14fe7dd0f6dcc9e9419434cf2198e2c780f408a9291b6651caf9444ab377fb1` |
| Logical dataset SHA-256 | `c6089965b87828a464e82cdbdb922e19e18e9d0f2c0f4b4589252c1d3a66d2f1` |
| Operational JSONL export SHA-256 | `29d7be7a62a0864dd24ae47cba43cecced263dc551fb7060d28c061dd4e3a45e` |

Actual counts: 50 customers, 100 carts (40 abandoned and 10 converted), 193 cart lines, 91 sessions, 3 campaigns, 6 templates, 10 orders, 30 schedules, 30 attempts (29 accepted and 1 failed), 71 message events, 1 evaluation run, and 4 clean-baseline labels. Ten abandoned carts lacked email consent and were not scheduled. Attribution, candidates, and decisions are zero in this clean run.

Both independent small-profile runs produced identical counts and logical hashes. The operational JSONL export was then run twice from the generated database and its byte checksums matched. The logical generator checksum is computed from canonical operational and evaluation rows in stable schema/table/primary-key order, excluding `GenerationRun` to avoid a self-reference. Export checksums are separate: JSONL contains operational rows and the source manifest, while CSV and SQL include only operational tables and never evaluation labels.

The final small-profile manifest is persisted in the isolated `yottaflex_test` database for demonstration. Separately, the scale generator ran in a rollback-only PostgreSQL transaction and produced 50,000 carts, 20,000 abandoned carts, 10,000 campaigns, 20,000 templates, 5,000 orders, 10,000 schedules/attempts, 9,794 accepted attempts, and 206 failed attempts. Its logical dataset checksum was `185a56ab810c8fe56321205e922cfc53ee28322bdbbd7abdbf4faf9b00d4974d`; no scale rows were retained. The normal generator creates only negative clean-baseline labels; anomaly fixtures run separately in evaluation tests.
