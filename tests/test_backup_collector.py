from __future__ import annotations

import pytest

from tests.conftest import fixture_text
from zahosts_health.collectors import backup as backup_mod
from zahosts_health.collectors.backup import BackupCollector
from zahosts_health.collectors.base import Status

KEYS = {
    "status",
    "enabled",
    "backup_dir",
    "latest_dates",
    "remote_destinations",
    "latest_log",
    "latest_success",
    "in_progress",
    "active_processes",
    "latest_errors",
}


def _patch(
    monkeypatch,
    *,
    config: str = "backup_config_enabled.json",
    dates: str = "backup_dates.json",
    dest: str = "backup_destinations.json",
    log: str = "backup_log_success.txt",
    ps: str = "ps_idle.txt",
):
    outputs = {
        ("whmapi1", "--output=json", "backup_config_get"): fixture_text(config),
        ("whmapi1", "--output=json", "backup_date_list"): fixture_text(dates),
        ("whmapi1", "--output=json", "backup_destination_list"): fixture_text(dest),
        ("ps", "-eo", "pid=,args="): fixture_text(ps),
    }

    def fake_run(args, timeout=30):
        return backup_mod.CommandResult(ok=True, code=0, out=outputs[tuple(args)], err="", cmd=list(args))

    monkeypatch.setattr(backup_mod, "_run", fake_run)
    monkeypatch.setattr(backup_mod, "_latest_log_path", lambda: "/log")
    monkeypatch.setattr(backup_mod, "_tail_file", lambda path, max_lines: fixture_text(log).splitlines())


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"config": "backup_config_disabled.json"}, Status.CRITICAL),
        ({"dates": "backup_dates_empty.json"}, Status.CRITICAL),
        ({"log": "backup_log_failed.txt", "ps": "ps_backup_running.txt"}, Status.WARN),
        ({"log": "backup_log_failed.txt", "ps": "ps_idle.txt"}, Status.CRITICAL),
        ({"log": "backup_log_success.txt", "dest": "backup_destinations_empty.json"}, Status.WARN),
        ({"log": "backup_log_success.txt", "dest": "backup_destinations.json"}, Status.OK),
    ],
)
def test_status_matrix(monkeypatch, base_config, kwargs, status):
    _patch(monkeypatch, **kwargs)
    assert BackupCollector().collect(base_config).status is status


def test_running_process_detection_excludes_self(monkeypatch, base_config):
    _patch(monkeypatch, log="backup_log_failed.txt", ps="ps_backup_running.txt")
    payload = BackupCollector().collect(base_config).legacy_payload()
    assert payload["in_progress"] is True
    assert payload["active_processes"] == ["12345 /usr/local/cpanel/bin/backup --force"]
    assert "zahosts_health.py" not in "\n".join(payload["active_processes"])


def test_idle_process_detection(monkeypatch, base_config):
    _patch(monkeypatch, ps="ps_idle.txt")
    payload = BackupCollector().collect(base_config).legacy_payload()
    assert payload["in_progress"] is False
    assert payload["active_processes"] == []


def test_payload_values(monkeypatch, base_config):
    _patch(monkeypatch, log="backup_log_failed.txt", dest="backup_destinations.json")
    payload = BackupCollector().collect(base_config).legacy_payload()
    assert payload["latest_dates"] == ["2026-06-20", "2026-06-19", "2026-06-18", "2026-06-18", "2026-06-17"]
    assert payload["remote_destinations"] == 1
    assert payload["latest_errors"] == ["ERROR: account backup failed"]
    assert len(payload["latest_errors"]) <= 20
    assert payload["latest_log"] == "/log"
    assert payload["backup_dir"] == "/backup"


def test_legacy_payload_keys_present(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = BackupCollector().collect(base_config).legacy_payload()
    assert set(payload) == KEYS
