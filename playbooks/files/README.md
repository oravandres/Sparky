# Vendored files for `playbooks/join-k3s.yml`

## `k3s-install-get-k3s-io.sh`

Upstream source: `https://get.k3s.io` (mutable remote).

This copy is **checked in** so Ansible deploys a deterministic script instead of
fetching root-executed code from the network at runtime.

| Field | Value |
|-------|-------|
| Vendored SHA256 (human provenance) | `46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad` |
| Vendored SHA1 (`ansible.builtin.copy` `checksum`) | `dc3ac628d2881f0a1d7e0d495e991287c110d7ad` |
| K3s release paired in playbook | `v1.29.0+k3s1` (see `playbooks/join-k3s.yml`) |

Update policy: when bumping `k3s_version` in the playbook, refresh this file from
the upstream URL in a controlled environment, verify SHA256/SHA1, update both
digests in this table and the `checksum:` line in `join-k3s.yml`, and commit in
the same PR as the version bump.

ShellCheck in **pre-commit** skips this path (see `.pre-commit-config.yaml`): we keep the
vendored bytes aligned with upstream rather than rewriting them for lint cleanliness.
The standalone CI `shellcheck` job only scans `scripts/*.sh`.
