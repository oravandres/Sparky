# Operations

> Status: bootstrap. Filled out by Phase 1 and Phase 10 PRs.

This file is the operator handbook for Sparky. Each section is a stub
that later PRs fill in as they land their phase (per PLAN.md §25).

## Local quality checks (PLAN §22)

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

The same gates run in CI (`.github/workflows/ci.yml`) on every PR and
push to `main`.

## Ansible (PLAN phases 0–2)

Install collections once (required for `roles/base` UFW and timezone
modules):

```bash
ansible-galaxy collection install -r collections/requirements.yml
```

Typical sequence on the appliance (after copying `inventory/group_vars/sparky.yml.example`
to a vault-managed `sparky.yml` if you use vault):

```bash
ansible-playbook -i inventory/hosts.yml playbooks/00-preflight.yml
ansible-playbook -i inventory/hosts.yml playbooks/10-base-os.yml
ansible-playbook -i inventory/hosts.yml playbooks/20-storage.yml   # needs /data (or sparky_data_mount) present
```

GPU container probe (Phase 2, after Docker + NVIDIA Container Toolkit):

```bash
./scripts/check-gpu.sh
```

Use `./scripts/check-gpu.sh --host-only` (or `SPARKY_GPU_CHECK_HOST_ONLY=1`) only when Docker or the NVIDIA Container Toolkit is intentionally absent; a full appliance install should pass the container probe.

## Nemotron 3 Super (Phase 4 — PLAN §13)

Full operator runbook: [`docs/nemotron.md`](nemotron.md). High points:

```bash
# One-time: fetch the reasoning parser plugin
./scripts/download-nemotron-parser.sh

# Start vLLM (cold cache: ~10-30 min for the 70 GB pull on first run)
SPARKY_ENV_FILE=/etc/sparky/sparky.env ./scripts/start-nemotron-vllm.sh up -d

# Smoke through the gateway (gated; HF_TOKEN must be in sparky.env)
SPARKY_API_KEY=... ./scripts/smoke-test-text.sh
```

The compose unit at
[`docker/compose/docker-compose.nemotron.yml`](../docker/compose/docker-compose.nemotron.yml)
follows NVIDIA's [DGX Spark deployment guide](https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html)
verbatim — `vllm/vllm-openai:cu130-nightly` with the four required env
vars (`VLLM_NVFP4_GEMM_BACKEND=marlin`, `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1`,
`VLLM_FLASHINFER_ALLREDUCE_BACKEND=trtllm`, `VLLM_USE_FLASHINFER_MOE_FP4=0`)
and the documented serve flags (FP8 KV cache, FP4 quant, Marlin MoE, MTP
speculative decoding). Don't edit without rerunning the §22 / §23 benchmarks.

TRT-LLM serving (PLAN §13.2) is opt-in; vLLM remains the default until
TRT-LLM has run two consecutive weeks without crashes / OOMs / quality
regressions. `scripts/start-nemotron-trtllm.sh` is a documented stub.

## Sparky Gateway (Phase 3 — PLAN §12)

Local development:

```bash
pip install -e services/sparky-common
pip install -e 'services/sparky-gateway[test]'

export SPARKY_API_KEY="$(openssl rand -hex 32)"
export SPARKY_MODEL_REGISTRY_PATH="$PWD/config/model-registry.yaml"
export SPARKY_LOGGING_CONFIG_PATH="$PWD/config/logging.yaml"

uvicorn --factory sparky_gateway.main:create_app --host 127.0.0.1 --port 8080
```

The `--factory` flag is required so `create_app()` runs once per worker
and fails loudly when `SPARKY_API_KEY` is missing.

### Containerized run

```bash
SPARKY_ENV_FILE=/etc/sparky/sparky.env ./scripts/start-gateway.sh up -d --build
SPARKY_ENV_FILE=/etc/sparky/sparky.env ./scripts/start-gateway.sh logs -f
```

The compose unit at [`docker/compose/docker-compose.gateway.yml`](../docker/compose/docker-compose.gateway.yml)
mounts `/opt/sparky/config` read-only into the container, runs as the
unprivileged `sparky` user, drops all capabilities, and ships logs to
`journald` with `tag=sparky-gateway`.

### Smoke test

```bash
SPARKY_API_KEY=... SPARKY_GATEWAY_URL=http://127.0.0.1:8080 \
  ./scripts/smoke-test-health.sh
```

Verifies `/health`, `/ready`, and that `/v1/models` is 401 unauthenticated /
200 authenticated.

### `/metrics` is authenticated

Per `config/api-contract.yaml`, MiMi Prometheus must scrape Sparky with
`Authorization: Bearer <SPARKY_API_KEY>` — bare scraping returns 401.
Configure the scrape job to read the key from a file mirrored via
sealed-secret:

```yaml
# (MiMi-side; lives in mimi-monitoring repo, not Sparky)
- job_name: sparky-gateway
  bearer_token_file: /etc/prometheus/secrets/sparky-api-key
  static_configs:
    - targets: ["sparky.mimi.local:8080"]
```

## Hardware & storage (Phase 0 — preflight, PLAN §9)

Before installs, run the host script (reports hostname, aarch64, RAM, block devices,
GPU, Docker, and free space on the data mount):

```bash
chmod +x scripts/preflight.sh   # once after clone
./scripts/preflight.sh
```

Optional:

```bash
SPARKY_DATA_MOUNT=/mnt/your-nvme ./scripts/preflight.sh
SPARKY_PREFLIGHT_MIN_FREE_GB=600 ./scripts/preflight.sh   # default; lower only if documented
./scripts/preflight.sh --quick   # dev only: skips 600 GiB check and aarch64 requirement
```

Full preflight (non-`--quick`) requires `SPARKY_DATA_MOUNT` to be a **mountpoint**, not only a directory on the root filesystem, so operators cannot confuse NVMe-backed storage with `/` free space.

Recorded after Ansible Phase 1 lands (hostname IP DNS SSH etc.):

- Hostname, LAN IP, DNS resolution from MiMi.
- Architecture: `aarch64` (DGX Spark / GB10 Grace Blackwell).
- Unified memory available (target 128 GB).
- NVMe mount path, total / free space (PLAN §3 storage budget:
  ≥ 600 GB free before full model pulls).

## Secrets (PLAN §10)

- `SPARKY_API_KEY` — generated once with `openssl rand -hex 32`,
  registered as the sealed secret `sparky-api-key` in MiMi-Secrets,
  mirrored to `/etc/sparky/sparky.env` on the host (mode 0640,
  root:sparky). MiMi's AI Router resolves it for callers.
- `HF_TOKEN`, `NGC_API_KEY` — kept in
  `inventory/group_vars/sparky.yml` (ansible-vault encrypted; the
  vault password lives in `~/.ansible-vault-pass` on the operator
  workstation, never in the repo).
- Compose services receive secrets only via
  `env_file: /etc/sparky/sparky.env` or Docker secrets — never via
  `environment:` literals in tracked YAML.

### Rotation

`SPARKY_API_KEY` rotation procedure (Phase 11, PLAN §20) lands when
that PR ships. Until then: regenerate locally, update the MiMi-Secrets
sealed secret, redeploy the gateway.

## Firewall (PLAN §10)

Allow:

```text
22/tcp     from admin network
8080/tcp   from MiMi / DarkBase network
9100/tcp   from MiMi monitoring only
9400/tcp   from MiMi monitoring only (if GPU exporter enabled)
```

Block direct external access to `8000`, `8001`, `8188`, `9001`, `9002`
unless explicitly proxied through the authenticated gateway.

## Logging (PLAN §19)

- Structured JSON to stdout for every Sparky service; format defined in
  `config/logging.yaml`.
- Compose services use the journald driver with `tag={{.Name}}` so
  `journalctl -u sparky-*` works.
- Log rotation via `/etc/logrotate.d/sparky`: daily, 14-day retention,
  compressed, copytruncate.
- Mirrored to `/var/log/sparky/<service>/<service>.log`.
- Forwarding logs to MiMi (Loki / promtail) is out of scope for
  Phase 10; document here when MiMi is ready to pull.

## Backups

To be defined in a later phase. Outputs under `/data/outputs/*` are
disposable; jobs metadata under `/var/lib/sparky/jobs` is keyable.
Models can be re-downloaded from the pinned revisions in
`config/model-registry.yaml`.

## Troubleshooting

See [`troubleshooting.md`](troubleshooting.md).
