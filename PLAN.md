# Sparky — DGX Spark Setup Plan

> **Status:** In progress
> **Date:** 2026-04-26
> **Scope:** Add the NVIDIA DGX Spark to the MiMi K3s cluster as an ARM64 worker node. Purpose TBD — this plan covers infrastructure only.

---

## 1. Summary

Sparky is a DGX Spark desktop AI supercomputer (GB10 Grace Blackwell Superchip, 128GB unified memory, ARM64). The only concrete goal right now is to **join it to the MiMi K3s cluster** as an additional worker node.

What we'll run on it is to be decided. This repo exists to manage the machine's base infrastructure via Ansible, not to prescribe workloads.

---

## 2. Hardware

| Component | Specification |
|-----------|---------------|
| **SoC** | NVIDIA GB10 Grace Blackwell Superchip |
| **CPU** | 20-core ARM (10× Cortex-X925 + 10× Cortex-A725) |
| **GPU** | NVIDIA Blackwell (5th Gen Tensor Cores, integrated) |
| **Memory** | 128 GB LPDDR5x (unified CPU+GPU, 273 GB/s) |
| **Storage** | Up to 4 TB NVMe M.2 |
| **Network** | 10GbE RJ-45, ConnectX-7, Wi-Fi 7 |
| **AI Perf** | 1 PetaFLOP (FP4 with sparsity) |
| **Arch** | `aarch64` (ARM64) |
| **OS** | DGX OS (Ubuntu-based) |

---

## 3. Plan

### Phase 1 — Base Setup ✅

- [x] Repository structure (Ansible scaffolding)
- [x] Inventory with Sparky as local host
- [x] Ansible configuration with MiMi `k3s_agent` role path
- [x] K3s join playbook (ARM64 binary)

### Phase 2 — K3s Cluster Join (Next)

- [ ] Verify DGX OS network connectivity to MiMi cluster
- [ ] Run `join-k3s.yml` to install k3s agent (ARM64)
- [ ] Verify node appears in `kubectl get nodes`
- [ ] Confirm ARM64 node scheduling works

---

## 4. Open Questions

1. **Data directory**: What is the NVMe mount path on the DGX Spark? Defaulting to `/data`.
2. **Hostname/IP**: What is Sparky's hostname and IP on the LAN?
3. **K3s version**: DarkBase uses `v1.29.0+k3s1` — should Sparky match, or use a newer version?
4. **Node labels/taints**: Should Sparky have any labels or taints applied, or just join as a plain worker?
5. **Workloads**: What will run on Sparky? To be decided after the machine is in the cluster.

---

## 5. What We Are Intentionally Not Doing (Yet)

- **No Ollama** — purpose TBD
- **No AI platform setup** — purpose TBD
- **No adapter services** — purpose TBD
- **No image generation** — purpose TBD
- **No MinIO** — DarkBase handles cluster backups
- **No node labels/taints** — will apply once we know what runs here
