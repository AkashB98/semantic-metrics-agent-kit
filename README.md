# semantic-metrics-agent-kit

An agent answers "what was revenue?" with a number nobody can check — this kit makes every answer carry its definition, version, and provenance, and refuses uncertified / wrong-grain asks.

## Problem

Agents and dashboards routinely invent metric definitions, mix versions, or answer a weekly question from daily data without saying so. The number looks confident and is unverifiable.

## What this kit does

- **Certified registry (`metrics.json`, not YAML)** — 8 certified metrics over fictional Helios Home daily rows: `revenue` (v2), `orders`, `conversion_rate`, `avg_order_value`, `refund_rate`, `support_tickets`, `active_users`, `gross_margin`. Each entry carries a formula description, a structured aggregation spec (sum / mean / ratio with numerator and denominator fields), grain `daily`, unit, owner, status `certified`, and supported dimensions. The registry also contains a draft `churn_rate`, a deprecated metric, and `revenue` v1 superseded by v2 on a different field — so misuse is testable, not hypothetical.
- **Strict query contract** — structured request only: `{metric, grain, filters, window, version?}`. No natural-language parsing. Validation happens first; the engine never best-guesses.
- **Typed refusals** — `UNKNOWN_METRIC`, `UNCERTIFIED_METRIC`, `DEPRECATED_METRIC`, `SUPERSEDED_VERSION`, `GRAIN_MISMATCH`, `FILTER_ERROR` (unknown dimension or value-type conflict), `DIMENSION_MISMATCH` (a known dimension the metric does not support).
- **Provenance on every valid answer** — definition id, version, sha256 hash of the canonical filter JSON, source row count after filters, and certification status, alongside the value.
- **In-memory aggregation** — no SQL engine. A deterministic seeded generator (seed 42, 90 days, 12 channel/region rows per day) is shared by the CLI and the evals.
- **Misuse evals** — one case per misuse class plus valid requests whose values are recomputed independently in the eval. Refusal precision, refusal recall, and correct-answer rate on valid requests are reported separately — never as one blended accuracy.
- **Dashboard governance audit (`dashboards.json` + `semantic_metrics/governance.py`)** — the source-of-truth check for dashboards: every tile is traced from what it displays back to the certified definition it claims (tile → declared query → registry definition, with owner, status, and definition fingerprint). The audit recomputes each tile's value with the same engine and flags definition drift, stale versions, stale displayed numbers, and uncertified sources — then a decision-stakes review log records who approved, flagged, or waived each finding.

## Governance audit

Dashboards drift away from the certified definitions they claim to show: a tile keeps summing a legacy field after the metric is redefined, a board pack stays pinned to a superseded version, a cached number goes stale. The audit makes each tile prove its lineage.

- **Tiles (`dashboards.json`)** — each tile declares the metric id + version it claims, the aggregation spec it actually computes, its filters/window, a decision-stakes level (`low` / `medium` / `high`, declared on the tile — never chosen by a reviewer), and the `reported_value` it displays. Five seeded Helios Home tiles: one clean, four planted defects.
- **Lineage** — `trace_tile` resolves the tile's pinned version in the registry and records the definition's owner, certification status, and fingerprints. Two fingerprints, on purpose: `definition_fingerprint` covers the full definition (including formula prose); drift detection compares only `spec_fingerprint` (aggregation + grain + unit), because rewording a formula is not drift. *Fingerprints prove two specs are identical, not that the business meaning is correct.*
- **Findings (typed, precedence-ordered)** — a tile's status is its highest-precedence finding: `UNKNOWN_METRIC` (id or pinned version not in the registry), `INVALID_QUERY` (the certified recompute itself refuses, e.g. an unsupported dimension), `UNCERTIFIED_SOURCE` (draft/deprecated metric), `STALE_VERSION` (pinned version is superseded — drift is judged against the *pinned* spec, so a faithful old tile is stale, not drifted), `DEFINITION_DRIFT` (the tile's spec differs from the definition it claims), `VALUE_MISMATCH` (right definition, wrong displayed number — compared at 2 decimal places, because dashboards display rounded numbers).
- **One aggregator** — tile values and certified values are both computed by the existing query engine, so a mismatch is a data/definition fact, never two code paths disagreeing.
- **Review log** — `record_review` appends a decision (`approved` / `flagged` / `waived`) with the tile's own stakes and current finding. Approving a tile whose finding is not OK is refused (`REVIEW_APPROVES_FINDING`) — that approval is exactly the failure governance exists to prevent. `review_summary` reports decision counts, high-stakes waivers under `requires_escalation`, and `unreviewed_findings` — non-OK tiles nobody has reviewed yet.
- **Exit codes** — `audit` exits 0 when every tile is OK, 1 when findings are present, 2 when the tile file is unreadable or a tile is malformed.

## Quickstart

```bash
python3 -m semantic_metrics.cli list
python3 -m semantic_metrics.cli ask --request '{"metric":"revenue","grain":"daily","filters":{"channel":"online"},"window":{"start":"2026-01-01","end":"2026-01-31"}}'
python3 -m semantic_metrics.cli check   # CI gate: exit 0 ok, 1 registry invalid, 2 registry unreadable
python3 -m semantic_metrics.cli audit   # dashboard governance: exit 0 all tiles OK, 1 findings, 2 tiles unreadable/malformed
python3 -m semantic_metrics.cli demo
python3 demo.py                         # end-to-end, including serve round-trip
python3 -m semantic_metrics.cli serve --port 8765   # POST /ask, GET /health on 127.0.0.1
python3 evals/run_evals.py
python3 -m unittest discover -s tests -v
```

## Design decisions (validated)

1. **JSON registry over YAML** — stdlib `json` parses it with zero dependencies; a YAML registry would need a third-party parser and break the stdlib-only rule.
2. **Validation before aggregation, with typed errors** — callers (and evals) can branch on a stable error code instead of parsing prose, and a refusal is provably not a computed answer.
3. **Filter hash from canonical JSON** — sorting keys and using compact separators makes the provenance hash stable regardless of how the caller ordered the filter dict; this is covered by a dedicated test.

## Scope limits (honest)

- Fictional Helios Home data only; no real business data, no external APIs, no network calls.
- The governance audit reads declared tile specs from JSON — it does not connect to a real BI tool, parse dashboard SQL, or observe what a production dashboard actually computed.
- Daily grain only — weekly/monthly asks are refused by design, not rolled up.
- Python standard library only. No SQL engine, no natural-language parsing, no automatic metric discovery.
- Single-process, in-memory: not a production semantic layer, warehouse, or serving system.

## Layout

```
metrics.json                  certified registry
dashboards.json               dashboard tiles under governance audit (seeded)
semantic_metrics/data.py      deterministic generator (seed 42)
semantic_metrics/registry.py  registry loading
semantic_metrics/engine.py    contract validation + aggregation + provenance
semantic_metrics/governance.py  tile lineage + drift audit + decision-stakes review log
semantic_metrics/cli.py       list / ask / check / audit / demo / serve
evals/run_evals.py            misuse + valid + governance evals -> evals/eval_report.json
tests/test_engine.py          hermetic unittest suite (incl. no-network guard)
tests/test_governance.py      governance tests (planted findings, review log, fingerprints)
demo.py                       end-to-end demo incl. serve round-trip
```

## License

MIT — see `LICENSE`. Copyright Akash Bhargava.
