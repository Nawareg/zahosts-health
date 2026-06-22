"""Contract guard for the WHM PHP UI (index.php).

index.php dereferences a fixed set of keys from status.json. If a refactor drops
or renames any of them, the dashboard silently breaks. This test fails loudly
instead. The required-key map below is derived directly from index.php — update
both together, deliberately, when the UI contract changes.
"""
from __future__ import annotations

import json

from tests.test_runner import _stub_collectors
from zahosts_health import runner

# Every key index.php reads, grouped by the section it lives under.
REQUIRED = {
    None: ["generated_at", "overall_status", "recommendations"],
    "mail": ["status", "queue_count", "null_sender_count",
             "microsoft_error_counts", "microsoft_recent"],
    "dnsbl": ["status", "ip"],
    "backup": ["status", "in_progress", "latest_success", "latest_dates",
               "enabled", "backup_dir", "remote_destinations", "latest_log",
               "active_processes"],
    "autossl": ["status", "pending_count"],
    "wordpress": ["status", "total", "plugin_updates", "theme_updates", "risky_sites"],
    "security": ["status", "exim_auth_fail_count", "top_auth_fail_ips",
                 "top_auth_fail_subnets", "excessive_brutes"],
    "email_auth": ["records"],
}


def test_status_json_satisfies_php_contract(monkeypatch, tmp_cache):
    _stub_collectors(monkeypatch)
    runner.collect_all(str(tmp_cache["state"]))
    data = json.loads(tmp_cache["state"].read_text(encoding="utf-8"))

    missing = []
    for section, keys in REQUIRED.items():
        scope = data if section is None else data.get(section, {})
        for key in keys:
            if key not in scope:
                missing.append(key if section is None else f"{section}.{key}")

    assert not missing, f"status.json is missing UI-required keys: {missing}"


def test_overall_status_is_lowercase_enum(monkeypatch, tmp_cache):
    _stub_collectors(monkeypatch)
    runner.collect_all(str(tmp_cache["state"]))
    data = json.loads(tmp_cache["state"].read_text(encoding="utf-8"))
    assert data["overall_status"] in {"ok", "warn", "critical"}


def test_new_fields_are_additive_only(monkeypatch, tmp_cache):
    """Guard against accidental removal of legacy top-level keys."""
    _stub_collectors(monkeypatch)
    runner.collect_all(str(tmp_cache["state"]))
    data = json.loads(tmp_cache["state"].read_text(encoding="utf-8"))
    legacy_top = {"generated_at", "config", "server", "mail", "dnsbl", "email_auth",
                  "backup", "autossl", "wordpress", "security", "overall_status",
                  "recommendations"}
    assert legacy_top.issubset(set(data)), "a legacy top-level key was dropped"
