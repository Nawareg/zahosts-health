from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .base import Collector, CollectorResult, Status

MAIL_LOG = "/var/log/exim_mainlog"


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


def _tail_file(path: str, max_lines: int) -> list[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= max_lines:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
        return data.decode("utf-8", "replace").splitlines()[-max_lines:]
    except Exception:
        return []


class SecurityCollector(Collector):
    name = "security"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        cphulk, _ = _run_json(["whmapi1", "--output=json", "cphulk_status"], timeout=30)
        excessive, _ = _run_json(["whmapi1", "--output=json", "get_cphulk_excessive_brutes"], timeout=45)
        brutes = (excessive or {}).get("data", {}).get("excessive_brutes", [])

        log_lines = _tail_file(MAIL_LOG, int(cfg.get("mail_log_tail_lines", 7000)))
        auth_fails = [
            line
            for line in log_lines
            if "authenticator failed" in line or "Incorrect authentication data" in line
        ]

        by_ip: Counter[str] = Counter()
        by_user: Counter[str] = Counter()
        by_subnet: Counter[str] = Counter()
        for line in auth_fails:
            ip = re.search(r"\[([0-9a-fA-F:.]+)\]", line)
            user = re.search(r"set_id=([^)]+)", line)
            if ip:
                raw = ip.group(1)
                by_ip[raw] += 1
                try:
                    addr = ipaddress.ip_address(raw)
                except ValueError:
                    addr = None
                if addr is not None and addr.version == 4:
                    by_subnet[str(ipaddress.ip_network(f"{raw}/24", strict=False))] += 1
            if user:
                by_user[user.group(1)] += 1

        im = _run(["imunify360-agent", "health"], timeout=30)
        imunify_health = im.out[-2000:] if im.ok else im.err
        enabled = (cphulk or {}).get("data", {}).get("is_enabled") == 1
        if not enabled:
            status = Status.CRITICAL
        elif auth_fails:
            status = Status.WARN
        else:
            status = Status.OK

        return CollectorResult(
            name=self.name,
            status=status,
            metrics={
                "cphulk_enabled": enabled,
                "excessive_brutes": brutes[:20],
                "exim_auth_fail_count": len(auth_fails),
                "top_auth_fail_ips": by_ip.most_common(10),
                "top_auth_fail_users": by_user.most_common(10),
                "top_auth_fail_subnets": by_subnet.most_common(10),
                "imunify_health": imunify_health,
            },
        )
