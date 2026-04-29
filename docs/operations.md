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

## Hardware & storage (Phase 0 — preflight, PLAN §9)

Recorded after `playbooks/00-preflight.yml` runs against Sparky:

- Hostname, LAN IP, DNS resolution from MiMi.
- Architecture: `aarch64` (DGX Spark / GB10 Grace Blackwell).
- Unified memory available (target 128 GB).
- NVMe mount path, total / free space (PLAN §3 storage budget:
  ≥ 600 GB free).

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
