from __future__ import annotations

from tests.conftest import fixture_text
from zahosts_health.collectors import email_auth as email_auth_mod
from zahosts_health.collectors.base import Status
from zahosts_health.collectors.email_auth import EmailAuthCollector

KEYS = {"status", "checked", "problems", "records"}
RECORD_KEYS = {"domain", "user", "spf", "dkim", "dmarc"}


def _patch(
    monkeypatch,
    *,
    domains=None,
    users=None,
    spf: str = "emailauth_spf_valid.json",
    dkim: str = "emailauth_dkim_valid.json",
    dmarc: str = "dmarc_present.txt",
):
    calls = []
    domains = ["example.com"] if domains is None else domains
    users = {"example.com": "zauser"} if users is None else users

    def fake_run(args, timeout=30):
        calls.append(list(args))
        if "validate_current_spfs" in args:
            out = fixture_text(spf)
        elif "validate_current_dkims" in args:
            out = fixture_text(dkim)
        elif args[0] == "dig":
            out = fixture_text(dmarc)
        else:
            out = ""
        return email_auth_mod.CommandResult(ok=True, code=0, out=out, err="", cmd=list(args))

    monkeypatch.setattr(email_auth_mod, "_load_userdomains", lambda: users)
    monkeypatch.setattr(email_auth_mod, "_discover_auth_domains", lambda cfg: domains)
    monkeypatch.setattr(email_auth_mod, "_run", fake_run)
    return calls


def test_valid_spf_dkim_and_dmarc_is_ok(monkeypatch, base_config):
    _patch(monkeypatch)
    result = EmailAuthCollector().collect(base_config)
    assert result.status is Status.OK
    assert result.metrics["problems"] == 0


def test_invalid_spf_is_warn(monkeypatch, base_config):
    _patch(monkeypatch, spf="emailauth_spf_invalid.json")
    result = EmailAuthCollector().collect(base_config)
    assert result.status is Status.WARN
    assert result.metrics["problems"] == 1


def test_invalid_dkim_is_warn(monkeypatch, base_config):
    _patch(monkeypatch, dkim="emailauth_dkim_invalid.json")
    assert EmailAuthCollector().collect(base_config).status is Status.WARN


def test_missing_dmarc_is_warn(monkeypatch, base_config):
    _patch(monkeypatch, dmarc="dmarc_missing.txt")
    assert EmailAuthCollector().collect(base_config).status is Status.WARN


def test_domain_without_user_counts_as_problem_and_skips_uapi(monkeypatch, base_config):
    calls = _patch(monkeypatch, domains=["nouser.example"], users={})
    result = EmailAuthCollector().collect(base_config)
    record = result.metrics["records"][0]
    assert result.status is Status.WARN
    assert result.metrics["problems"] == 1
    assert record["spf"] == "unknown"
    assert record["dkim"] == "unknown"
    assert all("EmailAuth" not in call for call in calls)


def test_records_shape_and_checked_count(monkeypatch, base_config):
    _patch(monkeypatch, domains=["example.com", "other.com"], users={"example.com": "zauser", "other.com": "other"})
    result = EmailAuthCollector().collect(base_config)
    assert result.metrics["checked"] == 2
    assert all(set(row) == RECORD_KEYS for row in result.metrics["records"])


def test_legacy_payload_keys_present(monkeypatch, base_config):
    _patch(monkeypatch)
    payload = EmailAuthCollector().collect(base_config).legacy_payload()
    assert set(payload) == KEYS
