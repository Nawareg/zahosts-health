from __future__ import annotations

from zahosts_health.collectors import server as server_mod
from zahosts_health.collectors.server import ServerCollector

KEYS = {"hostname", "whm_version", "loadavg", "disk_root", "contact_email"}


def test_server_metrics_shape(monkeypatch, base_config):
    def fake_run(args, timeout=30):
        out = '{"version":"120.0"}' if args[-1] == "version" else "Filesystem Size Used Avail Use% Mounted on"
        return server_mod.CommandResult(ok=True, code=0, out=out, err="", cmd=list(args))

    monkeypatch.setattr(server_mod, "_run", fake_run)
    monkeypatch.setattr(server_mod.socket, "getfqdn", lambda: "host.example.com")
    monkeypatch.setattr(server_mod, "_read_loadavg", lambda: "0.1 0.2 0.3")
    monkeypatch.setattr(server_mod, "_read_contact_email", lambda: "admin@example.com")

    metrics = ServerCollector().collect(base_config).metrics
    assert set(metrics) == KEYS
    assert "status" not in metrics
    assert metrics == {
        "hostname": "host.example.com",
        "whm_version": {"version": "120.0"},
        "loadavg": "0.1 0.2 0.3",
        "disk_root": "Filesystem Size Used Avail Use% Mounted on",
        "contact_email": "admin@example.com",
    }
