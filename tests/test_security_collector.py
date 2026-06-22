from __future__ import annotations

import json

from tests.conftest import fixture_text
from zahosts_health.collectors import security as security_mod
from zahosts_health.collectors.base import Status
from zahosts_health.collectors.security import SecurityCollector

KEYS = {
    "status",
    "cphulk_enabled",
    "excessive_brutes",
    "exim_auth_fail_count",
    "top_auth_fail_ips",
    "top_auth_fail_users",
    "top_auth_fail_subnets",
    "imunify_health",
}


def _patch(monkeypatch, *, cphulk: str = "cphulk_enabled.json", log: str = "security_mainlog_tail.txt"):
    outputs = {
        ("whmapi1", "--output=json", "cphulk_status"): fixture_text(cphulk),
        ("whmapi1", "--output=json", "get_cphulk_excessive_brutes"): fixture_text("cphulk_brutes.json"),
        ("imunify360-agent", "health"): "imunify ok",
    }

    def fake_run(args, timeout=30):
        return security_mod.CommandResult(ok=True, code=0, out=outputs[tuple(args)], err="", cmd=list(args))

    monkeypatch.setattr(security_mod, "_run", fake_run)
    monkeypatch.setattr(security_mod, "_tail_file", lambda path, max_lines: fixture_text(log).splitlines())


def test_cphulk_disabled_is_critical_even_with_auth_failures(monkeypatch, base_config):
    _patch(monkeypatch, cphulk="cphulk_disabled.json")
    result = SecurityCollector().collect(base_config)
    assert result.status is Status.CRITICAL
    assert result.metrics["cphulk_enabled"] is False
    assert result.metrics["exim_auth_fail_count"] == 3


def test_cphulk_enabled_with_auth_failures_is_warn(monkeypatch, base_config):
    _patch(monkeypatch)
    result = SecurityCollector().collect(base_config)
    assert result.status is Status.WARN


def test_cphulk_enabled_without_auth_failures_is_ok(monkeypatch, base_config):
    _patch(monkeypatch)
    monkeypatch.setattr(security_mod, "_tail_file", lambda path, max_lines: ["quiet line"])
    result = SecurityCollector().collect(base_config)
    assert result.status is Status.OK
    assert result.metrics["exim_auth_fail_count"] == 0


def test_auth_failure_aggregation(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = SecurityCollector().collect(base_config).legacy_payload()
    serialized = json.loads(json.dumps(payload))
    assert serialized["exim_auth_fail_count"] == 3
    assert serialized["top_auth_fail_ips"][0] == ["203.0.113.5", 2]
    assert serialized["top_auth_fail_subnets"][0] == ["203.0.113.0/24", 2]
    assert ["alice@example.com", 2] in serialized["top_auth_fail_users"]
    assert ["bob@example.com", 1] in serialized["top_auth_fail_users"]


def test_top_auth_fail_ip_rows_are_php_compatible(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = json.loads(json.dumps(SecurityCollector().collect(base_config).legacy_payload()))
    assert len(payload["top_auth_fail_ips"][0]) == 2
    assert payload["top_auth_fail_ips"][0][0] == "203.0.113.5"
    assert payload["top_auth_fail_ips"][0][1] == 2


def test_distributed_subnet_aggregation(monkeypatch, base_config):
    _patch(monkeypatch, log="security_mainlog_distributed.txt")
    payload = json.loads(json.dumps(SecurityCollector().collect(base_config).legacy_payload()))
    assert payload["top_auth_fail_subnets"][0] == ["203.0.113.0/24", 5]
    assert max(row[1] for row in payload["top_auth_fail_ips"]) == 1


def test_ipv6_auth_failure_skips_subnet_aggregation(monkeypatch, base_config):
    _patch(monkeypatch)
    monkeypatch.setattr(security_mod, "_tail_file", lambda path, max_lines: [
        "2026-06-21 authenticator failed for ([2001:db8::1]) [2001:db8::1]: 535 Incorrect authentication data",
    ])
    result = SecurityCollector().collect(base_config)
    assert result.metrics["exim_auth_fail_count"] == 1
    assert result.metrics["top_auth_fail_subnets"] == []


def test_excessive_brutes_passed_through_and_capped(monkeypatch, base_config):
    _patch(monkeypatch)
    brutes = SecurityCollector().collect(base_config).metrics["excessive_brutes"]
    assert brutes == [{"ip": "203.0.113.5", "country_name": "NL", "exptime": "2026-06-21", "notes": "brute"}]
    assert len(brutes) <= 20


def test_imunify_health_from_stdout(monkeypatch, base_config):
    _patch(monkeypatch)
    result = SecurityCollector().collect(base_config)
    assert result.metrics["imunify_health"] == "imunify ok"


def test_legacy_payload_keys_present(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = SecurityCollector().collect(base_config).legacy_payload()
    assert set(payload) == KEYS
