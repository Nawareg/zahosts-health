from __future__ import annotations

import json
import socket
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


def _read_loadavg() -> str:
    try:
        with open("/proc/loadavg", encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _read_contact_email() -> str:
    try:
        with open("/etc/wwwacct.conf", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("CONTACTEMAIL "):
                    return line.split(None, 1)[1].strip()
    except Exception:
        pass
    return ""


class ServerCollector(Collector):
    name = "server"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        whm_version, _ = _run_json(["whmapi1", "--output=json", "version"], timeout=20)
        disk = _run(["df", "-h", "/"], timeout=10)
        return CollectorResult(
            name=self.name,
            status=Status.OK,
            metrics={
                "hostname": socket.getfqdn(),
                "whm_version": whm_version,
                "loadavg": _read_loadavg(),
                "disk_root": disk.out,
                "contact_email": _read_contact_email(),
            },
        )

