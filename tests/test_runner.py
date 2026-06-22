"""Tests for runner-level behaviour: atomic writes, schema versioning,
self-observability, and graceful degradation when a collector fails.
"""
from __future__ import annotations

import json
import os

from zahosts_health import runner


def test_write_snapshot_atomic_is_compact_and_versioned(tmp_path):
    path = tmp_path / "status.json"
    runner.write_snapshot_atomic(str(path), {"overall_status": "ok"})
    raw = path.read_text(encoding="utf-8")

    # Compact (no pretty-print newlines inside the document).
    assert "\n" not in raw.strip()
    data = json.loads(raw)
    assert data["schema_version"] == 3
    assert data["overall_status"] == "ok"
    # 0640 permissions per the handoff security posture. Windows chmod does not
    # round-trip POSIX mode bits, so keep the permission guard for Linux/WHM.
    if os.name != "nt":
        assert (os.stat(path).st_mode & 0o777) == 0o640


def test_write_snapshot_leaves_no_temp_files(tmp_path):
    path = tmp_path / "status.json"
    runner.write_snapshot_atomic(str(path), {"overall_status": "ok"})
    leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
    assert leftovers == []


def _stub_collectors(monkeypatch, *, mail_status="warn", fail=None):
    """Replace MailCollector and the legacy delegating calls with deterministic data."""
    from zahosts_health.collectors.base import CollectorResult, Status

    class FakeServer:
        def collect(self, cfg):
            if fail == "server":
                raise RuntimeError("boom")
            return CollectorResult(
                name="server",
                status=Status.OK,
                metrics={
                    "hostname": "host.example.com",
                    "whm_version": None,
                    "loadavg": "0.1",
                    "disk_root": "df",
                    "contact_email": "a@b.c",
                },
            )

    class FakeMail:
        def collect(self, cfg):
            if fail == "mail":
                raise RuntimeError("boom")
            return CollectorResult(
                name="mail",
                status=Status(mail_status),
                metrics={
                    "queue_count": 9, "null_sender_count": 8, "queue_preview": [],
                    "microsoft_error_counts": {}, "microsoft_recent": [],
                    "auth_fail_count": 506, "auth_fail_recent": [],
                },
            )

    class FakeDnsbl:
        def collect(self, cfg):
            if fail == "dnsbl":
                raise RuntimeError("boom")
            return CollectorResult(
                name="dnsbl",
                status=Status.OK,
                metrics={"ip": "203.0.113.10", "results": []},
            )

    class FakeSecurity:
        def collect(self, cfg):
            if fail == "security":
                raise RuntimeError("boom")
            return CollectorResult(
                name="security",
                status=Status.WARN,
                metrics={
                    "cphulk_enabled": True,
                    "excessive_brutes": [],
                    "exim_auth_fail_count": 506,
                    "top_auth_fail_ips": [],
                    "top_auth_fail_users": [],
                    "top_auth_fail_subnets": [],
                    "imunify_health": "ok",
                },
            )

    class FakeBackup:
        def collect(self, cfg):
            if fail == "backup":
                raise RuntimeError("boom")
            return CollectorResult(
                name="backup",
                status=Status.WARN,
                metrics={
                    "enabled": True,
                    "backup_dir": "/b",
                    "latest_dates": ["2026-06-20"],
                    "remote_destinations": 0,
                    "latest_log": "/x.log",
                    "latest_success": True,
                    "in_progress": False,
                    "active_processes": [],
                    "latest_errors": [],
                },
            )

    class FakeAutossl:
        def collect(self, cfg):
            if fail == "autossl":
                raise RuntimeError("boom")
            return CollectorResult(
                name="autossl",
                status=Status.OK,
                metrics={"pending_count": 0, "pending": [], "latest_logs": []},
            )

    class FakeEmailAuth:
        def collect(self, cfg):
            if fail == "email_auth":
                raise RuntimeError("boom")
            return CollectorResult(
                name="email_auth",
                status=Status.WARN,
                metrics={"checked": 7, "problems": 1, "records": []},
            )

    class FakeWordpress:
        def collect(self, cfg):
            if fail == "wordpress":
                raise RuntimeError("boom")
            return CollectorResult(
                name="wordpress",
                status=Status.WARN,
                metrics={"total": 13, "risky_count": 0, "plugin_updates": 48, "theme_updates": 11, "risky_sites": []},
            )

    monkeypatch.setattr(runner, "ServerCollector", FakeServer)
    monkeypatch.setattr(runner, "MailCollector", FakeMail)
    monkeypatch.setattr(runner, "DnsblCollector", FakeDnsbl)
    monkeypatch.setattr(runner, "SecurityCollector", FakeSecurity)
    monkeypatch.setattr(runner, "BackupCollector", FakeBackup)
    monkeypatch.setattr(runner, "AutoSSLCollector", FakeAutossl)
    monkeypatch.setattr(runner, "EmailAuthCollector", FakeEmailAuth)
    monkeypatch.setattr(runner, "WordpressCollector", FakeWordpress)


def test_collect_all_overall_status(monkeypatch, tmp_cache):
    _stub_collectors(monkeypatch, mail_status="warn")
    data = runner.collect_all(str(tmp_cache["state"]))
    assert data["overall_status"] == "warn"
    assert data["schema_version"] == 3
    assert data["last_successful_collect"] == data["generated_at"]
    assert "collector_errors" not in data


def test_collect_all_writes_run_log(monkeypatch, tmp_cache):
    _stub_collectors(monkeypatch)
    runner.collect_all(str(tmp_cache["state"]))
    run_log = tmp_cache["logs"] / "run.log"
    assert run_log.exists()
    record = json.loads(run_log.read_text().splitlines()[-1])
    assert record["action"] == "collect"
    assert "duration_seconds" in record
    assert record["collector_statuses"]["mail"] == "warn"


def test_collector_failure_is_isolated(monkeypatch, tmp_cache):
    # A failing collector must not crash the run; it degrades and is recorded.
    _stub_collectors(monkeypatch, fail="security")
    data = runner.collect_all(str(tmp_cache["state"]))
    assert "collector_errors" in data
    assert any(e["collector"] == "security" for e in data["collector_errors"])
    # Overall still computed; failed collector reported its fallback status.
    assert data["overall_status"] in {"warn", "critical"}


def test_collector_failure_degrades_to_warn(monkeypatch, tmp_cache):
    _stub_collectors(monkeypatch, mail_status="ok", fail="dnsbl")
    data = runner.collect_all(str(tmp_cache["state"]))
    assert data["dnsbl"]["status"] == "warn"
    assert data["overall_status"] == "warn"


def test_text_report_written(monkeypatch, tmp_cache):
    _stub_collectors(monkeypatch)
    runner.collect_all(str(tmp_cache["state"]))
    report = tmp_cache["report"].read_text()
    assert "Zahosts WHM Health Report" in report
    assert "Overall: WARN" in report
