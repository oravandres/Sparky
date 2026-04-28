# Sparky — NVIDIA DGX Spark

**Sparky** is the **premium local intelligence appliance** for the MiMi
platform — Nemotron-class reasoning, agentic-RAG synthesis, deep coding
review, and premium image / video / audio generation behind one
authenticated gateway.

Authoritative architecture, phases, contracts, and constraints live in
[`PLAN.md`](PLAN.md). When this README disagrees with PLAN, PLAN wins.

## Hardware

| Component | Specification |
|-----------|---------------|
| **SoC** | NVIDIA GB10 Grace Blackwell Superchip |
| **CPU** | 20-core ARM (10× Cortex-X925 + 10× Cortex-A725) |
| **GPU** | NVIDIA Blackwell (5th Gen Tensor Cores, integrated) |
| **Memory** | 128 GB LPDDR5x (unified CPU+GPU, 273 GB/s) |
| **Storage** | Up to 4 TB NVMe M.2 |
| **Network** | 10GbE RJ-45, ConnectX-7, Wi-Fi 7 |
| **Arch** | `aarch64` (ARM64) |
| **OS** | DGX OS (Ubuntu-based) |

## What Sparky exposes

External callers (Maestro, AI Router, MaestroUI, DarkBase, future
coding/media agents) reach Sparky **only** through the authenticated
gateway:

```text
http://sparky.mimi.local:8080
Authorization: Bearer <SPARKY_API_KEY>
```

Endpoint families (full contract in
[`config/api-contract.yaml`](config/api-contract.yaml)):

- `GET /health`, `GET /ready`, `GET /metrics`, `GET /v1/models`.
- `POST /v1/chat/completions` (OpenAI-compatible, served by Nemotron).
- `POST /v1/reasoning/{analyze,compare}`.
- `POST /v1/agentic-rag/{plan,evaluate-evidence,synthesize,verify,finalize}`.
- `POST /v1/coding/{review,architecture,refactor-plan,security-review}`.
- `POST /v1/{media/image,media/video,audio/tts,audio/asr}/jobs`,
  `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`.

The approved model set lives in
[`config/model-registry.yaml`](config/model-registry.yaml); only those
models are installed (PLAN §2.2, §3) and revisions are pinned at
install time.

## Optional K3s join

Sparky's primary surface is host-level systemd + Docker Compose.
Joining MiMi's K3s cluster is optional and only for visibility /
observability — it must not move service ownership (PLAN §2.1).

```bash
# Join the MiMi K3s cluster (requires sudo password)
ansible-playbook playbooks/join-k3s.yml --ask-become-pass
```

## Local quality checks (PLAN §22)

CI runs lint + tests + secret scan on every PR and push to `main`.
Run the same gates locally before pushing:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Tools wired into `.pre-commit-config.yaml` and
`.github/workflows/ci.yml`: `ruff`, `mypy`, `pytest`, `yamllint`,
`ansible-lint`, `shellcheck`, `markdownlint-cli2`, `gitleaks`.

## Repository layout

```text
Sparky/
├── ansible.cfg                       # roles_path = roles:../MiMi/roles
├── PLAN.md                           # Architecture & phases (authoritative)
├── AGENTS.md                         # Agent/editor orientation
├── README.md                         # This file
├── .cursor/rules/                    # Cursor Rules; PLAN.md wins on conflict
├── .github/workflows/ci.yml          # Lint + tests + secret scan
├── .pre-commit-config.yaml           # Local mirror of CI
│
├── inventory/
│   ├── hosts.yml                     # Inventory
│   └── group_vars/
│       └── sparky.yml.example        # Vault template (PLAN §10)
│
├── playbooks/                        # Phase playbooks (00-130, see PLAN §7.2)
│   └── join-k3s.yml                  # Optional K3s join (PLAN §2.1)
├── roles/                            # Sparky-specific roles
│
├── services/                         # Python services (FastAPI)
│   ├── sparky-gateway/               # Authenticated public API (PLAN §12)
│   └── sparky-worker/                # Async media/audio jobs (PLAN §18)
│
├── config/
│   ├── sparky.env.example            # Runtime env template (PLAN §7.4)
│   ├── model-registry.yaml           # Approved model set (PLAN §3, §7.3)
│   ├── api-contract.yaml             # OpenAPI 3.1 surface (PLAN §5)
│   ├── logging.yaml                  # Structured JSON logging (PLAN §19)
│   └── comfyui/workflows/            # Image/video pipelines
│
├── docker/compose/                   # Compose stacks (PLAN §7.2)
├── scripts/                          # Smoke tests, start scripts (PLAN §21)
└── docs/                             # Architecture, ops, troubleshooting, benchmarks
```

## Sibling repository

This repo expects [MiMi](../MiMi) checked out as a sibling for the
shared `k3s_agent` role:

```text
Projects/
├── MiMi/          # K3s cluster management (provides k3s_agent role)
├── Sparky/        # This repo (DGX Spark main intelligence)
└── DarkBase/      # RTX 5090 fast worker (reference implementation)
```

## License

MIT
