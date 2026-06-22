"""Shared test fixtures.

These tests run fully offline: no exim/whmapi1/wp-toolkit/cPanel binaries are
invoked. Collector subprocess calls are replaced with captured fixture output so
the rule logic can be exercised on any machine (including CI).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the package importable when pytest is run from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def base_config() -> dict:
    """Mirrors the defaults the runner loads from /etc/zahosts-health.json."""
    return {
        "report_email": "you@example.com",
        "server_ip": "203.0.113.10",
        "auth_domains": ["example.com"],
        "max_auth_domains": 25,
        "mail_log_tail_lines": 7000,
    }


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    """Redirect all runner write paths into a temp dir so nothing touches /var."""
    from zahosts_health import runner

    cache = tmp_path / "cache"
    logs = tmp_path / "logs"
    cache.mkdir()
    logs.mkdir()
    state = cache / "status.json"
    report = cache / "daily-report.txt"

    monkeypatch.setattr(runner, "CACHE_DIR", str(cache))
    monkeypatch.setattr(runner, "LOG_DIR", str(logs))
    monkeypatch.setattr(runner, "STATE_PATH", str(state))
    monkeypatch.setattr(runner, "TEXT_REPORT_PATH", str(report))
    monkeypatch.setattr(runner, "ensure_dirs", lambda: None)
    return {"cache": cache, "logs": logs, "state": state, "report": report}
