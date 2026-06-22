from __future__ import annotations

from tests.conftest import fixture_text
from zahosts_health.collectors import dnsbl as dnsbl_mod
from zahosts_health.collectors.base import Status
from zahosts_health.collectors.dnsbl import DNSBL_ZONES, DnsblCollector


def _patch(monkeypatch, listed_zone: str | None = None):
    calls = []

    def fake_run(args, timeout=30):
        calls.append((list(args), timeout))
        out = fixture_text("dig_listed.txt") if listed_zone and args[-1].endswith(listed_zone) else fixture_text("dig_clean.txt")
        return dnsbl_mod.CommandResult(ok=True, code=0, out=out, err="", cmd=list(args))

    monkeypatch.setattr(dnsbl_mod, "_run", fake_run)
    return calls


def test_all_zones_clean(monkeypatch, base_config):
    _patch(monkeypatch)
    result = DnsblCollector().collect(base_config)
    assert result.status is Status.OK
    assert all(row["listed"] is False for row in result.metrics["results"])


def test_one_zone_listed_is_critical(monkeypatch, base_config):
    _patch(monkeypatch, listed_zone="zen.spamhaus.org")
    result = DnsblCollector().collect(base_config)
    assert result.status is Status.CRITICAL
    assert result.metrics["results"][0]["answer"] == "127.0.0.2"


def test_ip_comes_from_config(monkeypatch, base_config):
    _patch(monkeypatch)
    base_config["server_ip"] = "192.0.2.10"
    result = DnsblCollector().collect(base_config)
    assert result.metrics["ip"] == "192.0.2.10"


def test_empty_server_ip_skips_dnsbl_lookups(monkeypatch, base_config):
    calls = []

    def fail_run(args, timeout=30):
        calls.append((list(args), timeout))
        raise AssertionError("dnsbl lookup should not run when server_ip is empty")

    monkeypatch.setattr(dnsbl_mod, "SERVER_IP", "")
    monkeypatch.setattr(dnsbl_mod, "_run", fail_run)
    base_config["server_ip"] = ""

    result = DnsblCollector().collect(base_config)

    assert result.status is Status.OK
    assert result.metrics["ip"] == ""
    assert result.metrics["results"] == []
    assert calls == []


def test_dig_query_uses_reversed_ip(monkeypatch, base_config):
    calls = _patch(monkeypatch)
    base_config["server_ip"] = "203.0.113.9"
    DnsblCollector().collect(base_config)
    queries = [args[-1] for args, _timeout in calls]
    assert "9.113.0.203.zen.spamhaus.org" in queries
    assert len(queries) == len(DNSBL_ZONES)


def test_legacy_payload_keys_present(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = DnsblCollector().collect(base_config).legacy_payload()
    assert set(payload) == {"status", "ip", "results"}
