from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .base import Collector, CollectorResult, Status


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


class AutoSSLCollector(Collector):
    name = "autossl"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        pending, _ = _run_json(["whmapi1", "--output=json", "get_autossl_pending_queue"], timeout=30)
        catalog, _ = _run_json(["whmapi1", "--output=json", "get_autossl_logs_catalog"], timeout=45)
        pending_certs = (pending or {}).get("data", {}).get("pending_certificates", [])
        logs = (catalog or {}).get("data", {}).get("payload", [])
        latest = sorted(logs, key=lambda x: x.get("start_time", ""), reverse=True)[:10] if isinstance(logs, list) else []

        return CollectorResult(
            name=self.name,
            status=Status.WARN if pending_certs else Status.OK,
            metrics={
                "pending_count": len(pending_certs),
                "pending": pending_certs[:20],
                "latest_logs": latest,
            },
        )

