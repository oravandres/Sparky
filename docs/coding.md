# Coding intelligence

Sparky exposes four **premium coding review** endpoints on the gateway,
all backed by the always-hot Nemotron text runtime (Tier A of the §4.3
co-residency policy). The source of truth for request/response shapes
is [`config/api-contract.yaml`](../config/api-contract.yaml); PLAN
authority: §5.4, §15.

## Endpoints exposed by the gateway

Every route below requires `Authorization: Bearer <SPARKY_API_KEY>`
(PLAN §5, §10). All four routes share one request schema
(`CodingReviewRequest`) and one response schema (`CodingReviewResponse`)
— the only difference is the `task` value the caller is allowed to
send and the system prompt the gateway uses.

| Method | Path                          | Allowed `task` values       | PLAN §§ |
| ------ | ----------------------------- | --------------------------- | ------- |
| POST   | `/v1/coding/review`           | `review`, `debug`           | §15     |
| POST   | `/v1/coding/architecture`     | `architecture`              | §15     |
| POST   | `/v1/coding/refactor-plan`    | `refactor-plan`             | §15     |
| POST   | `/v1/coding/security-review`  | `security-review`           | §15     |

`debug` does not have a dedicated route — debug reviews go to
`/v1/coding/review` (debug is an investigative variant of code review).

## Request payload

At least one of `files`, `diff`, or `instructions` must carry a
*materially non-empty* signal — `files` must have at least one entry,
and `diff` / `instructions` must contain at least one non-whitespace
character. The gateway returns HTTP **422** for payloads that only set
blank or empty values for all three, so the model is never prompted
with nothing to review.

```json
{
  "task": "review|architecture|debug|refactor-plan|security-review",
  "repository": "string (optional, ≤ 512 chars)",
  "language": "go|typescript|python|yaml|mixed",
  "files": [
    { "path": "string (unique)", "content": "string (≤ 200k chars)" }
  ],
  "diff": "string (optional, ≤ 500k chars)",
  "instructions": "string (optional, ≤ 16k chars)",
  "max_tokens": 4096
}
```

Per-field caps plus an aggregate input ceiling keep prompts
predictable; out-of-policy requests fail validation before reaching
Nemotron.

## Response payload

```json
{
  "summary": "string",
  "findings": [
    {
      "severity": "critical|high|medium|low|nit",
      "path": "string or null",
      "line": 42,
      "title": "string",
      "explanation": "string",
      "recommendation": "string"
    }
  ],
  "architecture_notes": ["string"],
  "tests_to_add": ["string"],
  "final_recommendation": "approve|request_changes|needs_human_review"
}
```

## Gateway-enforced integrity

The gateway never trusts Nemotron's output to be self-consistent with
the caller's request. Schema drift or the following inconsistencies
return HTTP **502** (`runtime_error`), not a silently corrupted 200:

- **Approve with a critical finding** — `final_recommendation="approve"`
  is rejected when at least one finding has `severity="critical"`
  (PLAN §15 quality rule: critical issues are not silently approved).
- **Line without a path** — a finding with `path=null` and a non-null
  `line` is rejected. Responses are emitted with `exclude_none=true`,
  so this shape would surface to callers as a bare line number with
  no file to anchor it. Cross-cutting findings must set both `path`
  and `line` to `null`.
- **Unknown path** — when the caller supplied `files[]`, every
  finding's `path` must match one of those entries. Cross-cutting
  findings use `path=null` (and `line=null`).
- **Line out of range** — when a finding references a supplied file,
  `line` must be a 1-indexed line inside that file's content.

Diff-only reviews (no `files[]` supplied) skip the unknown-path /
line-out-of-range checks since the gateway has no snapshot to
validate against, but the line-without-a-path invariant still
applies — every finding must either anchor itself to a path or be
fully cross-cutting.

## Model and budget defaults

All four routes default to the premium reasoning model
(`nemotron-3-super-120b-a12b-nvfp4`, PLAN §3). Tunable through
`config/sparky.env`:

```bash
SPARKY_CODING_MODEL_ID=nemotron-3-super-120b-a12b-nvfp4
SPARKY_CODING_TEMPERATURE=0.2
SPARKY_CODING_MAX_TOKENS=4096
```

Caller-supplied `max_tokens` is clamped to `SPARKY_CODING_MAX_TOKENS`
so a single review cannot monopolize the always-hot text runtime.
Concurrency shares the Nemotron semaphore
(`SPARKY_NEMOTRON_MAX_INFLIGHT`) with chat, reasoning, and agentic-rag.

## Quality bar (PLAN §15)

- Findings are structured (severity + path/line + title + explanation +
  recommendation) so Maestro / PR-review pipelines can route them
  without reparsing prose.
- Critical issues are separated from style issues via severity and
  cannot be silently approved.
- Architecture notes are returned alongside findings so refactor
  plans and security reviews produce actionable follow-ups, not just
  a list of complaints.
- Source paths and line numbers round-trip the request; the gateway
  rejects invented references.

## Acceptance tests (PLAN §15, §21)

Unit coverage lives in
[`services/sparky-gateway/tests/test_coding.py`](../services/sparky-gateway/tests/test_coding.py)
and covers, per route: auth, schema validation, task-route coupling,
happy-path proxy, upstream failure, and the gateway-enforced
integrity checks above.

[`scripts/smoke-test-coding.sh`](../scripts/smoke-test-coding.sh)
(PLAN §21) exercises the `/v1/coding/review` route end-to-end against
a running gateway — useful when the Nemotron runtime is up and the
operator wants to confirm the full proxy path.
