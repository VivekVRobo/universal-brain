"""
Universal Brain - Milestone M5 Ephemeral Worker Fabric Tests

Implements M5 Sections 91, 94, 95:
Tests pull-based leasing, monotonic checkpoint recovery, zombie worker fencing,
idempotent completion, worker token authentication, and ZipSlip traversal defense.
"""

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
from uuid import uuid4
import zipfile
import pytest

from universal_brain.kernel.errors import CapabilityDeniedError
from universal_brain.tools.workers.artifacts import ArtifactValidationError, ArtifactValidator
from universal_brain.tools.workers.auth import WorkerAuthService
from universal_brain.tools.workers.queue import (
    CheckpointSequenceError,
    EphemeralJobQueue,
    FencedLeaseError,
)
from universal_brain.tools.workers.schemas import JobStatus


@pytest.fixture
def worker_env():
    queue = EphemeralJobQueue()
    auth = WorkerAuthService()
    yield queue, auth


def test_worker_registration_and_auth_cycle(worker_env):
    """Verify worker registration, HMAC token issuance, and validation."""
    queue, auth = worker_env
    worker_id = "colab-gpu-worker-01"

    reg = queue.register_worker(worker_id, "colab_t4", {"vram_gb": 16})
    assert reg.worker_id == worker_id

    # Generate token
    token = auth.generate_worker_token(worker_id, str(reg.worker_session_id), ttl_seconds=3600)
    assert auth.verify_worker_token(token) is True

    # Tampered token rejected
    tampered = token[:-4] + "ffff"
    with pytest.raises(CapabilityDeniedError, match="HMAC signature mismatch"):
        auth.verify_worker_token(tampered)

    # Expired token rejected
    expired = auth.generate_worker_token(worker_id, str(reg.worker_session_id), ttl_seconds=-10)
    with pytest.raises(CapabilityDeniedError, match="expired"):
        auth.verify_worker_token(expired)


def test_normal_worker_job_lifecycle(worker_env):
    """Verify complete normal execution: enqueue -> poll -> lease -> progress -> complete."""
    queue, _ = worker_env
    worker_id = "kaggle-p100-worker"
    session_id = uuid4()
    queue.register_worker(worker_id, "kaggle_p100", session_id=session_id)

    # 1. Enqueue Job
    job = queue.enqueue_job(
        project_id=uuid4(),
        task_id=uuid4(),
        job_type="simulation_run",
        payload={"world": "gazebo_warehouse", "steps": 1000},
    )
    assert job.status == JobStatus.QUEUED

    # 2. Worker Polls and Leases
    leased = queue.poll_and_lease(worker_id, session_id)
    assert leased is not None
    leased_job, lease = leased
    assert leased_job.job_id == job.job_id
    assert lease.lease_generation == 1
    assert leased_job.status == JobStatus.LEASED

    # 3. Report Monotonic Progress
    cp1 = queue.record_progress(job.job_id, worker_id, lease.lease_generation, sequence=1, progress_pct=25.0)
    assert cp1.sequence == 1

    cp2 = queue.record_progress(job.job_id, worker_id, lease.lease_generation, sequence=2, progress_pct=60.0)
    assert cp2.sequence == 2

    # 4. Complete Job
    completed = queue.complete_job(
        job.job_id,
        worker_id,
        lease.lease_generation,
        completion_evidence={"sim_exit_code": 0, "frames_rendered": 1000},
    )
    assert completed.status == JobStatus.COMPLETED
    assert completed.completion_evidence["frames_rendered"] == 1000


def test_worker_disconnect_and_resumption_from_checkpoint(worker_env):
    """Verify that when a worker drops, the job re-queues from its 50% checkpoint."""
    queue, _ = worker_env
    worker_a = "colab-worker-a"
    worker_b = "colab-worker-b"
    session_a = uuid4()
    session_b = uuid4()
    queue.register_worker(worker_a, "colab_t4", session_id=session_a)
    queue.register_worker(worker_b, "colab_t4", session_id=session_b)

    # 1. Enqueue Job
    job = queue.enqueue_job(uuid4(), uuid4(), "model_train", {"epochs": 10})

    # 2. Worker A leases and reaches 50% checkpoint
    _, lease_a = queue.poll_and_lease(worker_a, session_a, lease_duration_seconds=10)
    queue.record_progress(job.job_id, worker_a, lease_a.lease_generation, sequence=1, progress_pct=50.0)

    # 3. Worker A drops connection -> Lease expires
    simulated_future = datetime.now(timezone.utc) + timedelta(seconds=20)
    reaped = queue.reap_stale_leases(current_time=simulated_future)
    assert job.job_id in reaped

    # Job is back in QUEUED state with checkpoint 1 intact
    assert job.status == JobStatus.QUEUED
    assert job.last_checkpoint_seq == 1
    assert len(job.checkpoints) == 1
    assert job.checkpoints[0].progress_pct == 50.0

    # 4. Worker B leases the job with newer lease_generation (2)
    leased_b = queue.poll_and_lease(worker_b, session_b)
    assert leased_b is not None
    _, lease_b = leased_b
    assert lease_b.lease_generation == 2
    assert lease_b.worker_id == worker_b

    # Worker B finishes the remaining work (sequence 2)
    queue.record_progress(job.job_id, worker_b, lease_b.lease_generation, sequence=2, progress_pct=100.0)
    completed = queue.complete_job(job.job_id, worker_b, lease_b.lease_generation, {"accuracy": 0.98})
    assert completed.status == JobStatus.COMPLETED


def test_zombie_worker_fencing_token_protection(worker_env):
    """Verify Invariant M5-INV-09: stale worker updates are rejected with FencedLeaseError."""
    queue, _ = worker_env
    worker_a = "worker-a-stale"
    worker_b = "worker-b-active"
    session_a = uuid4()
    session_b = uuid4()
    queue.register_worker(worker_a, "colab_t4", session_id=session_a)
    queue.register_worker(worker_b, "colab_t4", session_id=session_b)

    job = queue.enqueue_job(uuid4(), uuid4(), "batch_eval", {"samples": 500})

    # Worker A gets generation 1
    _, lease_a = queue.poll_and_lease(worker_a, session_a, lease_duration_seconds=5)

    # Timeout expires -> Worker B gets generation 2
    simulated_future = datetime.now(timezone.utc) + timedelta(seconds=10)
    queue.reap_stale_leases(current_time=simulated_future)
    _, lease_b = queue.poll_and_lease(worker_b, session_b)
    assert lease_b.lease_generation == 2

    # Zombie Worker A wakes up and attempts progress under generation 1
    with pytest.raises(FencedLeaseError, match="FENCED_LEASE"):
        queue.record_progress(job.job_id, worker_a, lease_a.lease_generation, sequence=1, progress_pct=40.0)

    # Zombie Worker A attempts completion under generation 1
    with pytest.raises(FencedLeaseError):
        queue.complete_job(job.job_id, worker_a, lease_a.lease_generation, {"done": True})


def test_checkpoint_monotonic_sequence_enforcement(worker_env):
    """Verify CheckpointSequenceError if worker regresses checkpoint sequence."""
    queue, _ = worker_env
    worker_id = "test-worker"
    session_id = uuid4()
    queue.register_worker(worker_id, "local_gpu", session_id=session_id)

    job = queue.enqueue_job(uuid4(), uuid4(), "task", {})
    _, lease = queue.poll_and_lease(worker_id, session_id)

    # Sequence 1 and 2
    queue.record_progress(job.job_id, worker_id, lease.lease_generation, sequence=1, progress_pct=10.0)
    queue.record_progress(job.job_id, worker_id, lease.lease_generation, sequence=2, progress_pct=20.0)

    # Attempt to send sequence 1 again (or regressive sequence 0)
    with pytest.raises(CheckpointSequenceError):
        queue.record_progress(job.job_id, worker_id, lease.lease_generation, sequence=1, progress_pct=15.0)


def test_idempotent_job_completion(worker_env):
    """Verify Section 58: repeated completion requests return existing completed job."""
    queue, _ = worker_env
    worker_id = "idempotent-worker"
    session_id = uuid4()
    queue.register_worker(worker_id, "local_gpu", session_id=session_id)

    job = queue.enqueue_job(uuid4(), uuid4(), "task", {}, idempotency_key="job-idem-999")
    _, lease = queue.poll_and_lease(worker_id, session_id)

    # Complete 1st time
    res1 = queue.complete_job(
        job.job_id, worker_id, lease.lease_generation, {"score": 100}, idempotency_key="job-idem-999"
    )
    assert res1.status == JobStatus.COMPLETED

    # Complete 2nd time with same key -> idempotent return
    res2 = queue.complete_job(
        job.job_id, worker_id, lease.lease_generation, {"score": 100}, idempotency_key="job-idem-999"
    )
    assert res2.job_id == res1.job_id
    assert res2.status == JobStatus.COMPLETED


def test_artifact_intake_blocks_zipslip_traversal():
    """Verify Section 64: ZipSlip path traversal in uploaded archive is blocked."""
    with tempfile.TemporaryDirectory() as temp_dir:
        dest_dir = Path(temp_dir) / "extracted"
        malicious_zip = Path(temp_dir) / "evil.zip"

        # Create malicious zip with traversal path
        with zipfile.ZipFile(malicious_zip, "w") as z:
            z.writestr("../../escaped_payload.sh", "#!/bin/bash\necho pwned")

        # Extraction must fail closed
        with pytest.raises(ArtifactValidationError, match="ZipSlip traversal"):
            ArtifactValidator.safe_extract_zip(malicious_zip, dest_dir)
