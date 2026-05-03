"""File-backed async job registry — see PLAN.md §18 (job execution model) and §5.7.

Phase-9 contract: long-running media/audio work must not block the gateway.
The gateway accepts the request, creates a `queued` record on disk, returns
``202`` with ``{job_id, type, status}``, and a worker (PLAN §7.2
``services/sparky-worker``) picks up the record and drives state forward.

The store is intentionally minimal:

* one JSON file per job under ``JOBS_DIR`` (default ``/var/lib/sparky/jobs``),
* atomic creates / updates via tempfile + ``os.replace`` so a partial write
  never produces a corrupt record a reader could parse,
* per-job ``asyncio.Lock`` so cancel-vs-update inside one process serializes
  cleanly without burning a thread on ``fcntl``,
* read-only listing via ``glob`` for ops debugging — not used by the public
  API in Phase 9 so it stays unauthenticated-internal.

Multi-node scheduling, durable queues, and fan-out across workers are out of
scope here — MiMi owns the platform queue (PLAN §1.2). When MiMi schedules
Sparky jobs through Maestro, this store remains the single-node ledger the
worker reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("sparky_gateway")

JobType = Literal["image", "video", "tts", "asr"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]

# Terminal statuses cannot transition further. Cancel against a terminal
# status that is *not* already cancelled is rejected with HTTP 409 by the
# /v1/jobs/{id}/cancel handler (cancelled itself is idempotent).
_TERMINAL_STATUSES: Final[frozenset[JobStatus]] = frozenset({"completed", "failed", "cancelled"})

# Conservative ``job_id`` shape. We only ever hand out UUID4s but accept any
# UUID-ish input from callers so the path validator is forgiving but never
# permits filesystem traversal — every byte of the id appears as a filename
# component, so we pin it to lowercase hex + hyphens before opening files.
_JOB_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
)


def _now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with second precision (`Z` suffix)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class JobRecord(BaseModel):
    """Persisted job record — schema mirrors ``Job`` in ``config/api-contract.yaml``."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    type: JobType
    model: str
    status: JobStatus = "queued"
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    output_uri: str | None = None
    error: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)


def _safe_job_id(job_id: str) -> str:
    """Normalize and validate a caller-supplied id before touching the FS."""
    if not isinstance(job_id, str):
        raise ValueError("job_id must be a string")
    canonical = job_id.strip().lower()
    if not _JOB_ID_PATTERN.fullmatch(canonical):
        raise ValueError("job_id is not a valid UUID")
    return canonical


def is_valid_job_id(job_id: str) -> bool:
    """Cheap predicate for routes that want to return 404 instead of 422."""
    try:
        _safe_job_id(job_id)
    except ValueError:
        return False
    return True


class JobNotFoundError(LookupError):
    """Raised when a caller asks for a job_id that has no on-disk record."""


class JobConflictError(RuntimeError):
    """Raised when a state transition is illegal (e.g. cancel a completed job)."""


class JobStore:
    """Single-node, async-friendly file-backed job registry.

    Construction is deliberately FS-light: we record the configured path but
    do **not** create it. The deployed gateway runs read-only and only mounts
    the directories it owns (PLAN §10 / docker-compose.gateway.yml), so a
    missing or non-writable ``jobs_dir`` must not crash boot — health probes
    keep working and submission surfaces a clean 500 with the redacted
    operator hint instead. The dir is created lazily on the first ``create``
    call (idempotent ``mkdir(..., exist_ok=True)``) and ``readiness`` reports
    its state via :meth:`is_writable`.
    """

    def __init__(self, jobs_dir: Path | str) -> None:
        self._dir = Path(jobs_dir)
        # One lock per job_id keeps cancel + worker-update (future) serialised
        # within a single process. Cross-process safety relies on os.replace
        # being atomic on POSIX, which is what the worker also uses.
        self._locks: dict[str, asyncio.Lock] = {}
        self._dir_lock = asyncio.Lock()

    @property
    def jobs_dir(self) -> Path:
        return self._dir

    def is_writable(self) -> bool:
        """Cheap readiness probe — true iff the dir exists and we can write."""
        try:
            return self._dir.is_dir() and os.access(self._dir, os.W_OK)
        except OSError:
            return False

    def _ensure_dir(self) -> None:
        """Create ``jobs_dir`` on first write; raise a redacted ``OSError``
        with the configured path on permission failures so operators can
        diagnose the missing bind mount without leaking arbitrary detail
        through stack traces.
        """
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as exc:
            log.error(
                "jobs_dir_unwritable",
                extra={"jobs_dir": str(self._dir), "error": type(exc).__name__},
            )
            raise OSError(
                f"jobs_dir {self._dir!s} is not writable; mount a writable volume "
                "(see PLAN §8 host paths and docker-compose.gateway.yml)"
            ) from exc

    def _path_for(self, job_id: str) -> Path:
        return self._dir / f"{_safe_job_id(job_id)}.json"

    async def _lock_for(self, job_id: str) -> asyncio.Lock:
        async with self._dir_lock:
            lock = self._locks.get(job_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[job_id] = lock
            return lock

    def _atomic_write(self, path: Path, payload: Mapping[str, Any]) -> None:
        """Write ``payload`` as JSON to ``path`` atomically (tempfile + replace).

        ``os.replace`` is atomic across the same filesystem, so a reader that
        opens ``path`` always sees a fully-written record. Callers MUST have
        called :meth:`_ensure_dir` (or otherwise know the dir exists) before
        invoking this — for create / cancel we route through ``_ensure_dir``
        first so the lazy provisioning in production is honoured.
        """
        # tempfile in the same directory ensures we stay on one fs for replace.
        fd, tmp_name = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(self._dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except Exception:
            # Best-effort cleanup; we re-raise so the caller knows the create
            # failed. Leaving an orphan ``.tmp`` is preferable to swallowing.
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    async def create(
        self,
        *,
        job_type: JobType,
        model: str,
        request: Mapping[str, Any],
    ) -> JobRecord:
        """Create a new ``queued`` job and persist it to disk."""
        record = JobRecord(
            job_id=str(uuid.uuid4()),
            type=job_type,
            model=model,
            status="queued",
            created_at=_now_iso(),
            request=dict(request),
        )
        # Lazy provisioning: gateway boot must succeed even when the host has
        # not yet bind-mounted a writable jobs_dir. The first submission is
        # the natural place to surface the misconfiguration.
        self._ensure_dir()
        path = self._path_for(record.job_id)
        # Brand-new id — collision is astronomically unlikely with uuid4 but
        # we still guard so a freak duplicate fails loudly instead of
        # silently overwriting an existing record.
        if path.exists():
            raise RuntimeError(f"job_id collision for {record.job_id!r} — refusing to overwrite")
        self._atomic_write(path, record.model_dump(exclude_none=False))
        log.info(
            "job_created",
            extra={"job_id": record.job_id, "job_type": job_type, "model": model},
        )
        return record

    async def get(self, job_id: str) -> JobRecord:
        """Return the record for ``job_id`` or raise :class:`JobNotFoundError`."""
        try:
            path = self._path_for(job_id)
        except ValueError as exc:
            raise JobNotFoundError(str(exc)) from exc
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise JobNotFoundError(f"no job with id {job_id!r}") from exc
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            # A corrupt record is an ops bug — surface it loudly. The 500
            # path keeps the gateway honest instead of hiding bad files.
            log.error(
                "job_record_corrupt",
                extra={"job_id": job_id, "error": str(exc)},
            )
            raise
        return JobRecord.model_validate(data)

    async def cancel(self, job_id: str) -> JobRecord:
        """Cancel a non-terminal job; idempotent against an already-cancelled job."""
        lock = await self._lock_for(_safe_job_id(job_id))
        async with lock:
            record = await self.get(job_id)
            if record.status == "cancelled":
                return record
            if record.status in _TERMINAL_STATUSES:
                raise JobConflictError(
                    f"cannot cancel job {job_id!r} in terminal status {record.status!r}"
                )
            updated = record.model_copy(
                update={
                    "status": "cancelled",
                    "completed_at": _now_iso(),
                }
            )
            # The dir already exists (we just read from it); ensure_dir is a
            # no-op but keeps the write path symmetric with create().
            self._ensure_dir()
            self._atomic_write(
                self._path_for(record.job_id),
                updated.model_dump(exclude_none=False),
            )
            log.info(
                "job_cancelled",
                extra={"job_id": record.job_id, "from_status": record.status},
            )
            return updated
