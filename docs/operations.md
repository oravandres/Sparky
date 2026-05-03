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

Install collections once (required for `roles/base` UFW + timezone modules
and `roles/storage` mount module):

```bash
ansible-galaxy collection install -r collections/requirements.yml
```

Typical sequence on the appliance (after copying `inventory/group_vars/sparky.yml.example`
to a vault-managed `sparky.yml` if you use vault). All `become: true` so
run with `--ask-become-pass` or pre-configure NOPASSWD for the operator
account:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/00-preflight.yml
ansible-playbook -i inventory/hosts.yml playbooks/10-base-os.yml --ask-become-pass
ansible-playbook -i inventory/hosts.yml playbooks/20-storage.yml --ask-become-pass
ansible-playbook -i inventory/hosts.yml playbooks/30-container-runtime.yml --ask-become-pass
ansible-playbook -i inventory/hosts.yml playbooks/40-nvidia-validation.yml --ask-become-pass
```

### Single-NVMe DGX Spark (no separate `/data` partition)

DGX Spark ships with the entire 4 TB NVMe as `/`. PLAN §8 explicitly
allows this layout — set the bind-mount flags in
`inventory/group_vars/sparky.yml` and `roles/storage` will create a
`/var/sparky-data` directory on `/`, record a bind mount in `/etc/fstab`,
and mount it as `/data` so the rest of the playbook tree treats it as
a normal filesystem path:

```yaml
sparky_data_mount: /data
sparky_data_use_bind_mount: true
sparky_data_bind_source: /var/sparky-data
```

After this, `mountpoint -q /data` returns 0 (bind mounts are
mountpoints) and `playbooks/20-storage.yml` builds the
`models/cache/outputs` tree as usual. Don't enable this on appliances
with a real separate NVMe — provide a real filesystem mount instead.

### Phase 2 — container runtime + NVIDIA validation (PLAN §11)

`playbooks/30-container-runtime.yml` validates that Docker, the Compose
plugin, and the NVIDIA Container Toolkit are all present and meet the
minimum versions the rest of the stack relies on
(`docker>=24.0.0`, `compose>=2.20.0`, `nvidia-ctk>=1.14.0`). It writes
`/var/lib/sparky/container-runtime.json` so later phase playbooks can
read the resolved versions. The role refuses to (re)install the vendor
stack — DGX Spark ships preconfigured.

`playbooks/40-nvidia-validation.yml` runs `nvidia-smi` on the host and
the equivalent inside `--gpus all` of `nvidia/cuda:12.6.3-runtime-ubuntu22.04`,
then writes `/var/lib/sparky/nvidia-validation.json`. Override the CUDA
image when DGX Spark needs the vendor's tag:

```yaml
sparky_nvidia_cuda_image: nvcr.io/nvidia/cuda:13.0.0-base-arm64v8   # example
```

Quick CLI alternative (same probes, no Ansible):

```bash
./scripts/check-gpu.sh
./scripts/check-gpu.sh --host-only   # skip the container probe
SPARKY_CUDA_IMAGE=nvcr.io/nvidia/cuda:13.0.0-base-arm64v8 ./scripts/check-gpu.sh
```

### Phase 2 — installing on a clean (non-DGX) host

Sparky's `roles/containers` does not auto-install Docker / NVIDIA
Container Toolkit — DGX Spark ships preconfigured and rebuilding the
vendor stack is risky. On a non-DGX dev host, follow the upstream
docs once and rerun the Phase 2 playbook:

- Docker engine + Compose plugin: <https://docs.docker.com/engine/install/ubuntu/>
- NVIDIA Container Toolkit: <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html>

Then `nvidia-ctk runtime configure --runtime=docker && systemctl restart docker`.

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

### Recorded values — DGX Spark (sparky)

Reference values from the production appliance (`hostname=sparky`,
2026-05-03). Update in-place when hardware or driver versions change:

| Property | Value |
|----------|-------|
| Architecture | `aarch64` (`arm64`) |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.17.0-1014-nvidia |
| Hardware | MSI MS-C931 (DGX Spark / GB10 Grace Blackwell) |
| Memory | 121 GiB unified, 15 GiB swap |
| GPU | NVIDIA GB10, Driver 580.142, CUDA 13.0 |
| Docker | 29.2.1 |
| Docker Compose plugin | v5.0.2 |
| NVIDIA Container Toolkit | 1.19.0 |
| NVMe layout | single `nvme0n1p2` (3.7 TB, ext4) mounted at `/` |
| `/data` strategy | bind-mount via `sparky_data_use_bind_mount=true` |

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
