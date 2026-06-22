from __future__ import annotations

import json

from tests.conftest import fixture_text
from zahosts_health.collectors import autossl as autossl_mod
from zahosts_health.collectors.autossl import AutoSSLCollector
from zahosts_health.collectors.base import Status

KEYS = {"status", "pending_count", "pending", "latest_logs"}


def _patch(monkeypatch, *, pending: str = "autossl_empty.json", logs: str = "autossl_logs.json"):
    outputs = {
        ("whmapi1", "--output=json", "get_autossl_pending_queue"): fixture_text(pending),
        ("whmapi1", "--output=json", "get_autossl_logs_catalog"): fixture_text(logs),
    }

    def fake_run(args, timeout=30):
        return autossl_mod.CommandResult(ok=True, code=0, out=outputs[tuple(args)], err="", cmd=list(args))

    monkeypatch.setattr(autossl_mod, "_run", fake_run)


def test_pending_present_is_warn(monkeypatch, base_config):
    _patch(monkeypatch, pending="autossl_pending.json")
    result = AutoSSLCollector().collect(base_config)
    assert result.status is Status.WARN
    assert result.metrics["pending_count"] == 2
    assert result.metrics["pending"] == [{"domain": "a.com"}, {"domain": "b.com"}]


def test_no_pending_is_ok(monkeypatch, base_config):
    _patch(monkeypatch)
    result = AutoSSLCollector().collect(base_config)
    assert result.status is Status.OK
    assert result.metrics["pending_count"] == 0


def test_latest_logs_sorted_desc_and_capped(monkeypatch, base_config):
    logs = [{"start_time": f"2026-06-{day:02d}"} for day in range(10, 22)]
    _patch(monkeypatch, logs="autossl_logs.json")

    def fake_run(args, timeout=30):
        if args[-1] == "get_autossl_logs_catalog":
            out = json.dumps({"data": {"payload": logs}})
        else:
            out = fixture_text("autossl_empty.json")
        return autossl_mod.CommandResult(ok=True, code=0, out=out, err="", cmd=list(args))

    monkeypatch.setattr(autossl_mod, "_run", fake_run)
    latest = AutoSSLCollector().collect(base_config).metrics["latest_logs"]
    assert latest[0]["start_time"] == "2026-06-21"
    assert len(latest) == 10


def test_legacy_payload_keys_present(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = AutoSSLCollector().collect(base_config).legacy_payload()
    assert set(payload) == KEYS
