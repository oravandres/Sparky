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

## Monitoring & logging (Phase 10 — PLAN §19)

The full operator runbook for exporters, scrape config, retention, and
log shipping lives in
[`docs/monitoring.md`](monitoring.md). High points:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/110-monitoring.yml
./scripts/start-monitoring.sh up -d
SPARKY_API_KEY=... ./scripts/smoke-test-monitoring.sh
```

Quick reference:

- Gateway `/metrics` requires `Authorization: Bearer <SPARKY_API_KEY>`
  (config/api-contract.yaml). MiMi Prometheus mounts the key via
  `bearer_token_file` — see
  [`config/prometheus/sparky-scrape.example.yml`](../config/prometheus/sparky-scrape.example.yml).
- node_exporter on `:9100` and DCGM exporter on `:9400` (when
  `ENABLE_GPU_EXPORTER=true`) speak unauthenticated Prometheus —
  access is scoped by the host firewall (PLAN §10) to
  `sparky_monitoring_cidr`.
- Structured JSON logs ship to journald with `tag=<container-name>`;
  `/etc/logrotate.d/sparky` handles file mirrors under
  `/var/log/sparky/<service>/<service>.log` (daily, 14-day retention,
  copytruncate). Forwarding to MiMi Loki / promtail is intentionally
  out of scope for Phase 10.

## Backups

To be defined in a later phase. Outputs under `/data/outputs/*` are
disposable; jobs metadata under `/var/lib/sparky/jobs` is keyable.
Models can be re-downloaded from the pinned revisions in
`config/model-registry.yaml`.

## Troubleshooting

See [`troubleshooting.md`](troubleshooting.md).
