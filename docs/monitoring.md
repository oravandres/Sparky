# Monitoring & Logging

> Phase 10 — implements PLAN §19. MiMi owns Prometheus + Grafana
> (PLAN §1.2); Sparky exposes endpoints and ships structured logs.

## What Sparky exposes

| Surface | Bind | Port | Auth | Source |
|---------|------|------|------|--------|
| Sparky Gateway `/metrics` | `0.0.0.0` | 8080 | Bearer `SPARKY_API_KEY` | `sparky-gateway` (FastAPI) |
| node_exporter `/metrics` | host network | 9100 | none (firewall scoped) | `prom/node-exporter:v1.8.2` |
| DCGM exporter `/metrics` | host network | 9400 | none (firewall scoped) | `nvcr.io/nvidia/k8s/dcgm-exporter:3.3.7-3.4.2-ubuntu22.04` |

Per `config/api-contract.yaml`, the gateway's `/metrics` is the only
authenticated scrape target — MiMi Prometheus must include
`bearer_token_file` for that scrape job. The two exporters use the
standard Prometheus exposition without auth; access is scoped by the
host firewall (PLAN §10) to `sparky_monitoring_cidr`.

## Bringing the stack up

The Ansible role only deploys files; the operator brings up the
exporters explicitly so a broken DCGM driver can't take SSH down with
it:

```bash
# 1. Deploy compose unit + logrotate (idempotent)
ansible-playbook -i inventory/hosts.yml playbooks/110-monitoring.yml

# 2. Start the monitoring containers (uses /etc/sparky/sparky.env)
./scripts/start-monitoring.sh up -d

# 3. Verify (locally on the appliance)
SPARKY_API_KEY=... ./scripts/smoke-test-monitoring.sh
```

The DCGM exporter is gated by the `gpu` Compose profile and only
activates when `ENABLE_GPU_EXPORTER=true` in
`/etc/sparky/sparky.env` (default in `config/sparky.env.example`).
On a host where DCGM is unavailable or not yet validated by Phase 2
(`playbooks/40-nvidia-validation.yml`), set
`ENABLE_GPU_EXPORTER=false` and rerun `start-monitoring.sh up -d` —
node-exporter still comes up clean.

## MiMi-side scrape config

A documented example lives at
[`config/prometheus/sparky-scrape.example.yml`](../config/prometheus/sparky-scrape.example.yml).
MiMi consumes it from the `mimi-monitoring` repo — Sparky never owns the
scrape configuration (PLAN §1.2).

The gateway scrape job needs the API key mounted at
`bearer_token_file`. The recommended source is the
`sparky-api-key` sealed secret from `MiMi-Secrets` (already mirrored
into `/etc/sparky/sparky.env` for the gateway itself), surfaced into
Prometheus via the same sealed-secret machinery.

## Metrics worth alerting on

PLAN §19 lists the required series. Concrete starter alerts (move to
MiMi Alertmanager / Grafana when those repos are ready):

| Alert | Series | Threshold | Notes |
|-------|--------|-----------|-------|
| Gateway 5xx burst | `rate(sparky_gateway_requests_total{status=~"5.."}[5m])` | > 0.1 req/s for 10 min | Drift between routes & runtimes |
| Gateway p95 latency | `histogram_quantile(0.95, sum by (le, route) (rate(sparky_gateway_request_duration_seconds_bucket[5m])))` | > 30s for `/v1/chat/completions` | Nemotron load / OOM warning |
| Disk pressure on `/data` | `node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes{mountpoint="/data"}` | < 10% | Models cache fill (PLAN §3 budget) |
| GPU memory | `DCGM_FI_DEV_FB_USED / DCGM_FI_DEV_FB_TOTAL` | > 95% sustained | §4.3 co-residency triggers |
| GPU temperature | `DCGM_FI_DEV_GPU_TEMP` | > 85°C for 10 min | Cooling regression |

`/v1/models` (PLAN §4.3) carries the human-readable model state; treat
its `state` field as the source of truth for co-residency, not metrics.

## Logging

PLAN §19 logging rules — what's already in place after Phase 10:

- **Structured JSON to stdout** for every Sparky service. Format and
  redaction live in [`config/logging.yaml`](../config/logging.yaml);
  the `sparky_common.logging_filters.RedactSecretsFilter` strips
  `*_KEY`, `*_TOKEN`, `*_SECRET`, and `Authorization: Bearer *` values
  before lines leave the process (PLAN §10).
- **Compose journald driver** with `tag={{.Name}}` so
  `journalctl -t sparky-gateway` / `journalctl -t sparky-node-exporter`
  / `journalctl -t sparky-dcgm-exporter` works.
- **Logrotate policy** at `/etc/logrotate.d/sparky` (deployed by
  `roles/monitoring`): daily, 14-day retention, compressed,
  `copytruncate` so file appenders / journald shippers do not lose
  their handle. Validate with `logrotate -d /etc/logrotate.d/sparky`.

### What's intentionally out of scope for Phase 10

- **Forwarding to MiMi Loki / promtail.** Phase 10 stops at on-host
  capture. Promtail's `journal` source can pull `sparky-*` units once
  MiMi is ready; no Sparky-side change is required at that point.
- **Persistent journald.** Operators who prefer file-based history can
  set `Storage=persistent` in `/etc/systemd/journald.conf`; the
  logrotate policy above only applies to bind-mounted file mirrors
  under `/var/log/sparky/<service>/<service>.log`.
- **Grafana dashboards.** Authoritative dashboards live in
  `mimi-monitoring`. Suggested starter panels: gateway request rate
  by route, p95 latency, active jobs, GPU memory % used, GPU temp.

## Operator commands

```bash
# Inspect logs (host)
journalctl -t sparky-gateway -f
journalctl -t sparky-node-exporter --since "1h ago"
journalctl -t sparky-dcgm-exporter --since today

# Bring exporters up / down without touching the gateway
./scripts/start-monitoring.sh up -d
./scripts/start-monitoring.sh ps
./scripts/start-monitoring.sh down

# Verify the full surface (gateway, node, dcgm)
SPARKY_API_KEY=... ./scripts/smoke-test-monitoring.sh

# Skip the GPU check when DCGM isn't available yet
ENABLE_GPU_EXPORTER=false SPARKY_API_KEY=... \
  ./scripts/smoke-test-monitoring.sh
```
