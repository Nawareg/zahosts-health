from __future__ import annotations

import json

import pytest

from tests.conftest import fixture_text
from zahosts_health.collectors import wordpress as wordpress_mod
from zahosts_health.collectors.base import Status
from zahosts_health.collectors.wordpress import RISK_FLAGS, WP_TOOLKIT_CMD, WordpressCollector

KEYS = {"status", "total", "risky_count", "plugin_updates", "theme_updates", "risky_sites"}


def _patch(monkeypatch, fixture: str, *, ok: bool = True, err: str = ""):
    def fake_run(args, timeout=30):
        assert list(args) == WP_TOOLKIT_CMD
        return wordpress_mod.CommandResult(ok=ok, code=0 if ok else 1, out=fixture_text(fixture), err=err, cmd=list(args))

    monkeypatch.setattr(wordpress_mod, "_run", fake_run)


def test_invalid_output_is_warn_with_consistent_keys(monkeypatch, base_config):
    _patch(monkeypatch, "wp_invalid.txt", ok=False, err="wp-toolkit: command failed")
    payload = WordpressCollector().collect(base_config).legacy_payload()
    assert payload["status"] == "warn"
    assert payload["total"] == 0
    assert payload["plugin_updates"] == 0
    assert payload["theme_updates"] == 0
    assert payload["risky_count"] == 0
    assert payload["risky_sites"] == []
    assert payload["error"] == "wp-toolkit: command failed"


def test_risky_site_is_critical(monkeypatch, base_config):
    _patch(monkeypatch, "wp_risky.json")
    result = WordpressCollector().collect(base_config)
    risky = result.metrics["risky_sites"][0]
    assert result.status is Status.CRITICAL
    assert result.metrics["risky_count"] == 1
    assert set(risky) == {"id", "siteUrl", "version", "flags"}
    assert "infected" in risky["flags"]


def test_updates_are_warn(monkeypatch, base_config):
    _patch(monkeypatch, "wp_updates.json")
    result = WordpressCollector().collect(base_config)
    assert result.status is Status.WARN
    assert result.metrics["plugin_updates"] == 1
    assert result.metrics["theme_updates"] == 1


def test_clean_site_is_ok(monkeypatch, base_config):
    _patch(monkeypatch, "wp_clean.json")
    result = WordpressCollector().collect(base_config)
    assert result.status is Status.OK
    assert result.metrics["total"] == 1


@pytest.mark.parametrize("flag", RISK_FLAGS)
def test_each_risk_flag_is_critical(monkeypatch, base_config, flag):
    site = [{"id": 1, "siteUrl": "flag.test", "version": "6.5", flag: True, "plugins": {}, "themes": {}}]

    def fake_run(args, timeout=30):
        return wordpress_mod.CommandResult(ok=True, code=0, out=json.dumps(site), err="", cmd=list(args))

    monkeypatch.setattr(wordpress_mod, "_run", fake_run)
    result = WordpressCollector().collect(base_config)
    assert result.status is Status.CRITICAL
    assert result.metrics["risky_sites"][0]["flags"] == [flag]


def test_legacy_payload_keys_present(monkeypatch, base_config):
    _patch(monkeypatch, "wp_clean.json")
    payload = WordpressCollector().collect(base_config).legacy_payload()
    assert set(payload) == KEYS
