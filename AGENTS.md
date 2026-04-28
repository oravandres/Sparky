# AGENTS.md

This repository implements **Sparky**: the DGX Spark main intelligence appliance—premium local reasoning, agentic RAG, coding intelligence, and media/audio generation behind an authenticated **Sparky Gateway** API. MiMi owns orchestration; DarkBase owns fast daily workloads; Sparky owns highest-quality runs.

Canonical architecture, phases, API contracts, and constraints live in **[PLAN.md](PLAN.md)**. Treat `PLAN.md` as the source of truth when it conflicts with generic advice.

## Primary goals

- Stable **API-first** surface (`sparky.mimi.local:8080`); external callers use the gateway, not raw runtime ports.
- **Approved model set only**—no silent fallbacks to older or excluded models (see PLAN §2.2, §3).
- **Secrets safety**: keys/tokens only via MiMi-Secrets sealed flows and ansible-vault as described in PLAN §10—never commit real env files or inline secrets in YAML.
- **Operational clarity**: structured logs, metrics, health/ready, documented smoke tests and CI gates (PLAN §22).

## Required working style

- Make the smallest change that fully satisfies the task; match existing layout (flat Ansible root per PLAN §7.1).
- Read nearby code and `PLAN.md` sections before implementing endpoints, Ansible roles, or compose stacks.
- Keep the gateway thin: proxy/coordinate; put policy (co-residency, job state) in documented modules (e.g. worker) per PLAN §4.3.
- Fail loudly with clear errors when a model or runtime is unavailable—do not substitute an unapproved model.

## Python (gateway, worker, tests)

- Python 3.12+; FastAPI, Pydantic v2, httpx, pytest; follow ruff + mypy expectations in PLAN §22.
- OpenAI-compatible routes where PLAN specifies; preserve request IDs and normalize errors.
- Redact `*_KEY`, `*_TOKEN`, `*_SECRET`, and `Authorization: Bearer` values in logs (PLAN §10, §20).

## Ansible & layout

- `roles_path` includes `../MiMi/roles` via [ansible.cfg](ansible.cfg); keep [inventory/hosts.yml](inventory/hosts.yml) and add machine-specific vars under `inventory/group_vars/` (gitignored; commit `*.example` only).
- Prefer idempotent playbooks and documented variables; do not encode secrets in tracked files.

## Docker / Compose / host paths

- Use paths and compose layout from PLAN §8 and §7.2; configurable hostname/IP—no hard-coded LAN IPs in committed defaults.
- Tiered model residency (Nemotron hot; one media slot; eviction policy) is mandatory when implementing runtime switching (PLAN §4.3).

## Change checklist

Before finishing:

- [ ] Behavior matches the relevant PLAN section (API schema, phases, security).
- [ ] No secrets or real tokens in commits; only `.env.example` / `sparky.env.example` patterns.
- [ ] If you add or change HTTP routes, update `config/api-contract.yaml` when it exists (PLAN §7.4–§7.5).
- [ ] If you add models, update `config/model-registry.yaml` with pinned revisions (PLAN §3, §7.3).
- [ ] CI expectations: lint, tests, gitleaks—see PLAN §22.

## Cursor rules

Additional editor/agent rules live under [`.cursor/rules/`](.cursor/rules/) (`.mdc` files). They narrow scope per file type; `PLAN.md` remains authoritative for product decisions.
