"""Unit tests for MailCollector rule logic, driven by captured fixtures.

We patch the collector's `_run` (subprocess wrapper) and `_tail_file` so no real
exim/exiqgrep calls happen. This pins the WARN/CRITICAL/OK thresholds so future
refactors cannot silently change operator-facing behaviour.
"""
from __future__ import annotations

import pytest

from tests.conftest import fixture_text
from zahosts_health.collectors import mail as mail_mod
from zahosts_health.collectors.base import Status
from zahosts_health.collectors.mail import MailCollector


def _patch(monkeypatch, *, bpc: str, null: str, bp: str = "", log: str = ""):
    cmd_outputs = {
        ("/usr/sbin/exim", "-bpc"): bpc,
        ("exiqgrep", "-f", "<>", "-c"): null,
        ("/usr/sbin/exim", "-bp"): bp,
    }

    def fake_run(args, timeout=30):
        out = cmd_outputs.get(tuple(args), "")
        return mail_mod.CommandResult(ok=True, code=0, out=out, err="", cmd=list(args))

    monkeypatch.setattr(mail_mod, "_run", fake_run)
    monkeypatch.setattr(mail_mod, "_tail_file", lambda path, n: log.splitlines())


def test_ok_when_quiet(monkeypatch, base_config):
    _patch(monkeypatch, bpc="0", null="0", bp="", log="")
    result = MailCollector().collect(base_config)
    assert result.status is Status.OK
    assert result.metrics["queue_count"] == 0
    assert result.metrics["null_sender_count"] == 0


def test_warn_on_null_sender(monkeypatch, base_config):
    # Matches the documented current server state: queue 9, null-sender 8 => WARN.
    _patch(
        monkeypatch,
        bpc=fixture_text("exim_bpc.txt"),
        null=fixture_text("exiqgrep_null.txt"),
        bp=fixture_text("exim_bp.txt"),
        log=fixture_text("exim_mainlog_tail.txt"),
    )
    result = MailCollector().collect(base_config)
    assert result.status is Status.WARN
    assert result.metrics["queue_count"] == 9
    assert result.metrics["null_sender_count"] == 8
    assert any("null-sender" in r.lower() for r in result.recommendations)


def test_warn_on_queue_over_25(monkeypatch, base_config):
    _patch(monkeypatch, bpc="40", null="0")
    assert MailCollector().collect(base_config).status is Status.WARN


def test_critical_on_queue_over_100(monkeypatch, base_config):
    _patch(monkeypatch, bpc="150", null="0")
    assert MailCollector().collect(base_config).status is Status.CRITICAL


def test_critical_on_many_null_senders(monkeypatch, base_config):
    _patch(monkeypatch, bpc="5", null="30")
    assert MailCollector().collect(base_config).status is Status.CRITICAL


def test_thresholds_are_configurable(monkeypatch, base_config):
    # Lowering the warn threshold via config must change the verdict.
    base_config["thresholds"] = {"mail_queue_warn": 5}
    _patch(monkeypatch, bpc="6", null="0")
    assert MailCollector().collect(base_config).status is Status.WARN


def test_microsoft_errors_counted(monkeypatch, base_config):
    _patch(
        monkeypatch,
        bpc="3",
        null="0",
        log=fixture_text("exim_mainlog_tail.txt"),
    )
    counts = MailCollector().collect(base_config).metrics["microsoft_error_counts"]
    assert counts.get("S77719") == 1
    assert counts.get("451_4_7_500") == 1


def test_auth_failures_counted(monkeypatch, base_config):
    _patch(monkeypatch, bpc="0", null="0", log=fixture_text("exim_mainlog_tail.txt"))
    result = MailCollector().collect(base_config)
    assert result.metrics["auth_fail_count"] == 3


@pytest.mark.parametrize(
    "key",
    [
        "queue_count",
        "null_sender_count",
        "queue_preview",
        "microsoft_error_counts",
        "microsoft_recent",
        "auth_fail_count",
        "auth_fail_recent",
    ],
)
def test_legacy_payload_keys_present(monkeypatch, base_config, key):
    """legacy_payload() must carry exactly the keys index.php / the report read."""
    _patch(monkeypatch, bpc="9", null="8")
    payload = MailCollector().collect(base_config).legacy_payload()
    assert "status" in payload
    assert key in payload
