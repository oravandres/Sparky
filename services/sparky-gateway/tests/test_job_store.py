"""File-backed JobStore — atomic writes, state transitions, validation (PLAN §18)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from sparky_gateway.job_store import (
    JobConflictError,
    JobNotFoundError,
    JobRecord,
    JobStore,
    is_valid_job_id,
)


def test_is_valid_job_id_accepts_uuid_v4() -> None:
    assert is_valid_job_id("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-uuid",
        "../etc/passwd",
        "11111111-1111-1111-1111-11111111111Z",
        "11111111111111111111111111111111",
        "11111111-1111-1111-1111111111111111",
    ],
)
def test_is_valid_job_id_rejects_unsafe_or_malformed(value: str) -> None:
    assert not is_valid_job_id(value)


@pytest.mark.asyncio
async def test_create_persists_record_atomically(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    record = await store.create(
        job_type="image",
        model="flux2-dev",
        request={"prompt": "a kitten"},
    )
    assert record.status == "queued"
    assert record.type == "image"

    on_disk = json.loads((tmp_path / f"{record.job_id}.json").read_text())
    assert on_disk["job_id"] == record.job_id
    assert on_disk["status"] == "queued"
    assert on_disk["request"] == {"prompt": "a kitten"}


@pytest.mark.asyncio
async def test_create_writes_to_a_real_file_no_tempfile_left_behind(tmp_path: Path) -> None:
    """Atomic write must clean up its tempfile (we use os.replace)."""
    store = JobStore(tmp_path)
    record = await store.create(job_type="video", model="ltx-2", request={})
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [f"{record.job_id}.json"]


@pytest.mark.asyncio
async def test_get_returns_persisted_record(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={"prompt": "x"})
    fetched = await store.get(created.job_id)
    assert fetched.job_id == created.job_id
    assert fetched.status == "queued"
    assert fetched.request == {"prompt": "x"}


@pytest.mark.asyncio
async def test_get_unknown_job_raises_not_found(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    with pytest.raises(JobNotFoundError):
        await store.get("11111111-1111-4111-8111-111111111111")


@pytest.mark.asyncio
async def test_get_invalid_id_raises_not_found(tmp_path: Path) -> None:
    """Invalid ids never get the chance to escape into a path operation."""
    store = JobStore(tmp_path)
    with pytest.raises(JobNotFoundError):
        await store.get("../etc/passwd")


@pytest.mark.asyncio
async def test_cancel_queued_marks_cancelled(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={"prompt": "x"})
    cancelled = await store.cancel(created.job_id)
    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is not None
    persisted = await store.get(created.job_id)
    assert persisted.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_already_cancelled_is_idempotent(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={"prompt": "x"})
    once = await store.cancel(created.job_id)
    twice = await store.cancel(created.job_id)
    # Same terminal state, same completed_at — idempotent semantics.
    assert once.status == "cancelled"
    assert twice.status == "cancelled"
    assert once.completed_at == twice.completed_at


@pytest.mark.asyncio
async def test_cancel_terminal_completed_raises_conflict(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={"prompt": "x"})
    # Worker would write completion; emulate that via a direct file write.
    finished = JobRecord(
        job_id=created.job_id,
        type="image",
        model="flux2-dev",
        status="completed",
        created_at=created.created_at,
        completed_at="2026-04-30T12:00:00Z",
        output_uri="file:///data/outputs/images/done.png",
    )
    (tmp_path / f"{created.job_id}.json").write_text(
        json.dumps(finished.model_dump(exclude_none=False), sort_keys=True)
    )
    with pytest.raises(JobConflictError):
        await store.cancel(created.job_id)


@pytest.mark.asyncio
async def test_cancel_terminal_failed_raises_conflict(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={"prompt": "x"})
    failed = JobRecord(
        job_id=created.job_id,
        type="image",
        model="flux2-dev",
        status="failed",
        created_at=created.created_at,
        completed_at="2026-04-30T12:00:00Z",
        error="upstream timeout",
    )
    (tmp_path / f"{created.job_id}.json").write_text(
        json.dumps(failed.model_dump(exclude_none=False), sort_keys=True)
    )
    with pytest.raises(JobConflictError):
        await store.cancel(created.job_id)


@pytest.mark.asyncio
async def test_cancel_running_marks_cancelled(tmp_path: Path) -> None:
    """Cancellation of a `running` job is allowed; the worker honors the
    flag when it picks the record up again (PLAN §18 state machine)."""
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={})
    running = JobRecord(
        job_id=created.job_id,
        type="image",
        model="flux2-dev",
        status="running",
        created_at=created.created_at,
        started_at="2026-04-30T12:00:00Z",
    )
    (tmp_path / f"{created.job_id}.json").write_text(
        json.dumps(running.model_dump(exclude_none=False), sort_keys=True)
    )
    cancelled = await store.cancel(created.job_id)
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_concurrent_cancels_are_serialized(tmp_path: Path) -> None:
    """Two concurrent cancels on the same job converge on a single cancelled
    record and don't tear the on-disk JSON."""
    store = JobStore(tmp_path)
    created = await store.create(job_type="image", model="flux2-dev", request={})
    results = await asyncio.gather(
        store.cancel(created.job_id),
        store.cancel(created.job_id),
        store.cancel(created.job_id),
    )
    statuses = {r.status for r in results}
    assert statuses == {"cancelled"}
    on_disk = json.loads((tmp_path / f"{created.job_id}.json").read_text())
    assert on_disk["status"] == "cancelled"


@pytest.mark.asyncio
async def test_create_fails_loudly_on_id_collision(tmp_path: Path, monkeypatch) -> None:
    """A pre-existing file at the would-be path must surface a clear error
    instead of silently overwriting an existing record."""
    store = JobStore(tmp_path)
    fixed_id = "11111111-1111-4111-8111-111111111111"

    class _Stub:
        hex = fixed_id

        def __str__(self) -> str:
            return fixed_id

    def _fake_uuid4() -> _Stub:
        return _Stub()

    monkeypatch.setattr("sparky_gateway.job_store.uuid.uuid4", _fake_uuid4)

    await store.create(job_type="image", model="flux2-dev", request={})
    with pytest.raises(RuntimeError, match="job_id collision"):
        await store.create(job_type="image", model="flux2-dev", request={})


@pytest.mark.asyncio
async def test_jobs_dir_is_created_if_missing(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "jobs"
    assert not target.exists()
    store = JobStore(target)
    assert target.exists()
    assert store.jobs_dir == target


def test_corrupt_record_raises_on_get(tmp_path: Path) -> None:
    """A malformed JSON file is an ops bug — the gateway must surface it."""
    store = JobStore(tmp_path)
    bad_id = "11111111-1111-4111-8111-111111111111"
    (tmp_path / f"{bad_id}.json").write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        asyncio.run(store.get(bad_id))


@pytest.mark.asyncio
async def test_atomic_write_survives_failure_during_replace(tmp_path: Path, monkeypatch) -> None:
    """If ``os.replace`` raises, the tempfile is cleaned up so the directory
    doesn't accumulate ``*.tmp`` orphans across crashes."""
    store = JobStore(tmp_path)

    real_replace = os.replace

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("sparky_gateway.job_store.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        await store.create(job_type="image", model="flux2-dev", request={})
    monkeypatch.setattr("sparky_gateway.job_store.os.replace", real_replace)

    leftover = sorted(p.name for p in tmp_path.iterdir())
    assert leftover == []
