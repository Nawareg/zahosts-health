from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .base import Collector, CollectorResult, Status

WP_TOOLKIT_CMD = ["/usr/local/bin/wp-toolkit", "--list", "-plugins", "-themes", "-format", "json"]
RISK_FLAGS = ("broken", "infected", "unsupportedPhp", "unsupportedWp", "outdatedPhp", "outdatedWp")


@dataclass
class CommandResult:
    ok: bool
    code: int
    out: str
    err: str
    cmd: list[str]


def _run(args: Sequence[str], timeout: int = 30) -> CommandResult:
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            ok=proc.returncode == 0,
            code=proc.returncode,
            out=proc.stdout.strip(),
            err=proc.stderr.strip(),
            cmd=list(args),
        )
    except subprocess.TimeoutExpired:
        return CommandResult(False, 124, "", "timeout", list(args))
    except Exception as exc:
        return CommandResult(False, 1, "", str(exc), list(args))


def _run_json(args: Sequence[str], timeout: int) -> tuple[dict[str, Any] | None, CommandResult]:
    res = _run(args, timeout=timeout)
    if not res.ok:
        return None, res
    try:
        data = json.loads(res.out)
    except Exception:
        return None, res
    return data if isinstance(data, dict) else None, res


class WordpressCollector(Collector):
    name = "wordpress"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        res = _run(WP_TOOLKIT_CMD, timeout=120)
        try:
            sites = json.loads(res.out) if res.ok else None
        except Exception:
            sites = None

        if not isinstance(sites, list):
            return CollectorResult(
                name=self.name,
                status=Status.WARN,
                metrics={
                    "total": 0,
                    "risky_count": 0,
                    "plugin_updates": 0,
                    "theme_updates": 0,
                    "risky_sites": [],
                    "error": res.err or "wp-toolkit failed",
                },
            )

        risky = []
        plugin_updates = 0
        theme_updates = 0
        for site in sites:
            flags = [key for key in RISK_FLAGS if site.get(key)]
            for plugin in (site.get("plugins") or {}).values():
                if plugin.get("update_version"):
                    plugin_updates += 1
            for theme in (site.get("themes") or {}).values():
                if theme.get("update_version"):
                    theme_updates += 1
            if flags:
                risky.append(
                    {
                        "id": site.get("id"),
                        "siteUrl": site.get("siteUrl"),
                        "version": site.get("version"),
                        "flags": flags,
                    }
                )

        if risky:
            status = Status.CRITICAL
        elif plugin_updates or theme_updates:
            status = Status.WARN
        else:
            status = Status.OK

        return CollectorResult(
            name=self.name,
            status=status,
            metrics={
                "total": len(sites),
                "risky_count": len(risky),
                "plugin_updates": plugin_updates,
                "theme_updates": theme_updates,
                "risky_sites": risky[:30],
            },
        )

