# Sparky — NVIDIA DGX Spark

Ansible configuration for **Sparky**, an NVIDIA DGX Spark joining the MiMi K3s cluster as an ARM64 worker node.

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

## Quick Start

```bash
# Join the MiMi K3s cluster (requires sudo password)
ansible-playbook playbooks/join-k3s.yml --ask-become-pass
```

## Overview

```text
┌───────────────────────────────────────────────────────────────────────┐
│                         Sparky (DGX Spark)                            │
│           GB10 Grace Blackwell · 128GB Unified · ARM64                │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                  K3s Agent (MiMi Cluster)                        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    MiMi K3s Cluster (6 nodes)                         │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                         │
│  │   pi-c1    │ │   pi-c2    │ │   pi-c3    │  Control Plane          │
│  └────────────┘ └────────────┘ └────────────┘                         │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                         │
│  │   pi-n1    │ │   pi-n2    │ │   pi-n3    │  Workers                │
│  └────────────┘ └────────────┘ └────────────┘                         │
└───────────────────────────────────────────────────────────────────────┘
```

## Troubleshooting

```bash
# Check agent status
sudo systemctl status k3s-agent

# View agent logs
sudo journalctl -u k3s-agent -f

# Check node status from the cluster
kubectl get nodes
```

## Local quality checks

CI runs lint + tests + secret scan on every PR and push to `main` (see `PLAN.md` §22).
Run the same gates locally before pushing:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Individual tools used (all wired into `.pre-commit-config.yaml` and `.github/workflows/ci.yml`):
`ruff`, `mypy`, `pytest`, `yamllint`, `ansible-lint`, `shellcheck`, `markdownlint-cli2`, `gitleaks`.

## Project Structure

```text
Sparky/
├── inventory/
│   ├── hosts.yml                  # Target hosts
│   └── group_vars/                # Per-host vars (gitignored, ansible-vault)
│       └── sparky.yml.example     # Vault template (PLAN.md §10)
├── playbooks/
│   └── join-k3s.yml               # Optional K3s agent join (PLAN.md §2.1)
├── PLAN.md                        # Architecture & phases (authoritative)
├── AGENTS.md                      # Agent/editor orientation (with PLAN.md)
├── .cursor/rules/                 # Cursor Rules (*.mdc); PLAN.md wins on conflicts
└── README.md                      # This file
```

## Dependencies

This repository depends on the [MiMi](../MiMi) repository being checked out as a sibling directory for the `k3s_agent` role:

```text
Projects/
├── MiMi/          # K3s cluster management (provides k3s_agent role)
├── Sparky/        # This repo
└── DarkBase/      # GPU node (reference implementation)
```

## Architecture Notes

- **ARM64**: The DGX Spark uses an ARM64 CPU. The k3s join playbook downloads the `k3s-arm64` binary.
- **Unified Memory**: 128GB LPDDR5x shared between CPU and GPU — no separate VRAM pool.
- **10GbE**: High-bandwidth connectivity to the MiMi cluster.

## License

MIT
