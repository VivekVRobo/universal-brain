from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from universal_brain.engineering import (
    EnduranceCycleResult,
    EnduranceRunReport,
    EvidenceStatus,
    TargetMachineEvidenceReport,
    V52TargetEvidenceCollector,
)


def test_target_evidence_report_digest_is_self_verifying(tmp_path: Path):
    report = TargetMachineEvidenceReport(
        platform="TestOS",
        platform_release="1",
        python_version="3.13",
        workspace=str(tmp_path),
    ).seal()
    assert report.verify_digest()
    tampered = report.model_copy(update={"workspace": str(tmp_path / "other")})
    assert not tampered.verify_digest()


@pytest.mark.asyncio
async def test_target_evidence_collector_distinguishes_skipped_target_checks(tmp_path: Path):
    collector = V52TargetEvidenceCollector(tmp_path)
    report = await collector.collect()
    ids = {item.check_id: item for item in report.checks}
    assert report.verify_digest()
    assert ids["platform"].status == EvidenceStatus.PASS
    assert ids["distributed_leases"].status == EvidenceStatus.PASS
    assert ids["multi_hour_endurance"].status == EvidenceStatus.SKIP
    # On non-Windows CI these are explicit skips rather than fabricated passes.
    if report.platform != "Windows":
        assert ids["wsl2"].status == EvidenceStatus.SKIP
        assert ids["hyperv"].status == EvidenceStatus.SKIP
        assert report.overall_status == "partial"


def test_endurance_evidence_gate_requires_completed_two_hour_run(tmp_path: Path):
    now = datetime.now(timezone.utc)
    short = EnduranceRunReport(
        started_at=now,
        finished_at=now + timedelta(minutes=30),
        requested_duration_seconds=1800,
        cycles=[EnduranceCycleResult(cycle=1, passed=True, duration_ms=1, evidence_refs=["x"])],
        passed=True,
    )
    short_path = tmp_path / "short.json"
    short_path.write_text(json.dumps(short.model_dump(mode="json"), default=str), encoding="utf-8")
    item = V52TargetEvidenceCollector(tmp_path)._endurance_record_check(short_path)
    assert item.status == EvidenceStatus.FAIL

    long = short.model_copy(
        update={
            "finished_at": now + timedelta(hours=2, minutes=5),
            "requested_duration_seconds": 7500,
        }
    )
    long_path = tmp_path / "long.json"
    long_path.write_text(json.dumps(long.model_dump(mode="json"), default=str), encoding="utf-8")
    item = V52TargetEvidenceCollector(tmp_path)._endurance_record_check(long_path)
    assert item.status == EvidenceStatus.PASS
    assert item.details["record_sha256"]


def test_target_evidence_report_is_written_atomically(tmp_path: Path):
    collector = V52TargetEvidenceCollector(tmp_path)
    report = TargetMachineEvidenceReport(
        platform="Test",
        platform_release="1",
        python_version="3.13",
        workspace=str(tmp_path),
    ).seal()
    output = collector.write_report(tmp_path / "evidence" / "report.json", report)
    loaded = TargetMachineEvidenceReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert loaded.verify_digest()
