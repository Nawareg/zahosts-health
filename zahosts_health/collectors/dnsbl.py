from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .base import Collector, CollectorResult, Status

SERVER_IP = ""
DNSBL_ZONES = [
    "zen.spamhaus.org",
    "bl.spamcop.net",
    "b.barracudacentral.org",
    "dnsbl.sorbs.net",
]


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


class DnsblCollector(Collector):
    name = "dnsbl"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        ip = cfg.get("server_ip") or SERVER_IP
        if not ip:
            return CollectorResult(
                name=self.name,
                status=Status.OK,
                metrics={"ip": "", "results": []},
            )

        reversed_ip = ".".join(reversed(str(ip).split(".")))
        results: list[dict[str, Any]] = []
        listed = 0

        for zone in DNSBL_ZONES:
            query = f"{reversed_ip}.{zone}"
            answer = _run(["dig", "+short", query], timeout=15).out.strip()
            is_listed = bool(answer)
            if is_listed:
                listed += 1
            results.append({"zone": zone, "listed": is_listed, "answer": answer})

        return CollectorResult(
            name=self.name,
            status=Status.CRITICAL if listed else Status.OK,
            metrics={"ip": ip, "results": results},
        )
