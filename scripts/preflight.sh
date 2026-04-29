#!/usr/bin/env bash
# Preflight checks for Sparky (PLAN §9 Phase 0, §3 storage budget).
# Run on the DGX Spark host before heavy installs and model downloads.
#
# Usage:
#   ./scripts/preflight.sh
#   SPARKY_DATA_MOUNT=/mnt/data ./scripts/preflight.sh
#   ./scripts/preflight.sh --quick    # skip disk threshold + aarch64 requirement (dev laptops only)
#
# Environment:
#   SPARKY_DATA_MOUNT       Path to NVMe/data mount (default: /data)
#   SPARKY_PREFLIGHT_MIN_FREE_GB  Minimum free space in GiB (default: 600 per PLAN §3)

set -euo pipefail

readonly ME="${0##*/}"
MIN_FREE_GB="${SPARKY_PREFLIGHT_MIN_FREE_GB:-600}"
DATA_MOUNT="${SPARKY_DATA_MOUNT:-/data}"
QUICK=0

usage() {
  sed -n '1,19p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    -q | --quick)
      QUICK=1
      shift
      ;;
    *)
      echo "${ME}: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

pass() {
  echo "[ok] $*"
}

warn() {
  echo "[warn] $*" >&2
}

fail() {
  echo "[fail] $*" >&2
  exit 1
}

echo "=== Sparky preflight (${ME}) ==="
echo "Date: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

echo "--- System ---"
uname -a || true
if [[ "$(uname -m)" != "aarch64" ]]; then
  if [[ "${QUICK}" -eq 1 ]]; then
    warn "architecture is $(uname -m); production Sparky expects aarch64 (--quick skips this)"
  else
    fail "architecture is $(uname -m); production Sparky expects aarch64 (PLAN §9)."
  fi
else
  pass "architecture is aarch64"
fi

hostnamectl 2>/dev/null || true
pass "hostname: $(hostname)"

echo ""
echo "--- Memory ---"
if command -v free >/dev/null 2>&1; then
  free -h
else
  warn "free(1) not available"
fi

echo ""
echo "--- Block devices ---"
if command -v lsblk >/dev/null 2>&1; then
  lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS 2>/dev/null || lsblk
else
  warn "lsblk not available"
fi

echo ""
echo "--- Data mount (${DATA_MOUNT}) ---"
if [[ ! -d "$DATA_MOUNT" ]]; then
  fail "directory missing: ${DATA_MOUNT}. Create or set SPARKY_DATA_MOUNT."
fi
pass "mount path exists"

if [[ "${QUICK}" -eq 0 ]]; then
  if command -v mountpoint >/dev/null 2>&1; then
    if ! mountpoint -q "$DATA_MOUNT"; then
      fail "${DATA_MOUNT} is not a mountpoint — use the dedicated NVMe/data filesystem (PLAN §8). Try mountpoint -v \"${DATA_MOUNT}\"."
    fi
    pass "${DATA_MOUNT} is a mountpoint"
  elif command -v findmnt >/dev/null 2>&1; then
    if ! findmnt --target "$DATA_MOUNT" >/dev/null 2>&1; then
      fail "${DATA_MOUNT} is not listed by findmnt — ensure it is mounted."
    fi
    pass "${DATA_MOUNT} is a mounted filesystem path"
  else
    fail "need mountpoint(1) or findmnt(1) to verify ${DATA_MOUNT} is mounted (install util-linux)."
  fi
else
  warn "--quick: skipping mountpoint check"
fi

# df -P: POSIX portability; with -k on Linux/GNU: 1024-byte blocks (Avail column).
avail_kb="$(df -Pk "$DATA_MOUNT" 2>/dev/null | awk 'NR==2 { print $4 }')"
if [[ -z "${avail_kb}" ]] || ! [[ "${avail_kb}" =~ ^[0-9]+$ ]]; then
  fail "could not parse free space for ${DATA_MOUNT}"
fi
# avail_kb is in 1 KiB units
avail_gb=$((avail_kb / 1024 / 1024))
echo "free_space_gib: ${avail_gb} (threshold: ${MIN_FREE_GB}, quick=${QUICK})"

if [[ "${QUICK}" -eq 0 ]]; then
  if [[ "${avail_gb}" -lt "${MIN_FREE_GB}" ]]; then
    fail "free space ${avail_gb} GiB < ${MIN_FREE_GB} GiB on ${DATA_MOUNT} (PLAN §3). Install priority order or expand storage."
  fi
  pass "free space meets minimum (${MIN_FREE_GB} GiB)"
else
  warn "--quick: skipping disk threshold check"
fi

df -Ph "$DATA_MOUNT" || true

echo ""
echo "--- GPU ---"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi || warn "nvidia-smi exited non-zero"
else
  warn "nvidia-smi not found (install NVIDIA drivers / toolkit before Phase 2)"
fi

echo ""
echo "--- Docker ---"
if command -v docker >/dev/null 2>&1; then
  docker --version
else
  warn "docker not found (Phase 2 installs container runtime)"
fi

echo ""
pass "preflight finished successfully"
