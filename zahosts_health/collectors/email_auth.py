from __future__ import annotations

import json
import os
import re
import subprocess
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


def _load_userdomains() -> dict[str, str]:
    mapping = {}
    for path in ("/etc/userdomains", "/etc/trueuserdomains"):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if ":" not in line:
                        continue
                    domain, user = line.split(":", 1)
                    domain = domain.strip().lower()
                    user = user.strip()
                    if domain and user:
                        mapping[domain] = user
        except Exception:
            pass
    return mapping


def _discover_auth_domains(cfg: Mapping[str, Any]) -> list[str]:
    domains = {str(d).lower() for d in cfg.get("auth_domains", []) if d}
    for line in _tail_file(MAIL_LOG, 5000):
        match = re.search(r"Sender identification U=\S+ D=([A-Za-z0-9_.-]+)", line)
        if match:
            domain = match.group(1).lower()
            if domain not in ("-system-", "localhost"):
                domains.add(domain)
    max_domains = int(cfg.get("max_auth_domains", 25))
    return sorted(domains)[:max_domains]


class EmailAuthCollector(Collector):
    name = "email_auth"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        userdomains = _load_userdomains()
        domains = _discover_auth_domains(cfg)
        records = []
        problems = 0

        for domain in domains:
            user = userdomains.get(domain)
            rec = {"domain": domain, "user": user, "spf": "unknown", "dkim": "unknown", "dmarc": "unknown"}
            if user:
                spf, _ = _run_json(
                    ["uapi", f"--user={user}", "--output=json", "EmailAuth", "validate_current_spfs", f"domain={domain}"],
                    timeout=30,
                )
                dkim, _ = _run_json(
                    ["uapi", f"--user={user}", "--output=json", "EmailAuth", "validate_current_dkims", f"domain={domain}"],
                    timeout=30,
                )
                try:
                    data = spf.get("result", {}).get("data", [])
                    rec["spf"] = data[0].get("state", "unknown") if data else "unknown"
                except Exception:
                    pass
                try:
                    data = dkim.get("result", {}).get("data", [])
                    rec["dkim"] = data[0].get("state", "unknown") if data else "unknown"
                except Exception:
                    pass

            dmarc = _run(["dig", "+short", "TXT", f"_dmarc.{domain}"], timeout=15)
            rec["dmarc"] = "present" if dmarc.out.strip() else "missing"
            if rec["spf"] != "VALID" or rec["dkim"] != "VALID" or rec["dmarc"] == "missing":
                problems += 1
            records.append(rec)

        return CollectorResult(
            name=self.name,
            status=Status.WARN if problems else Status.OK,
            metrics={"checked": len(records), "problems": problems, "records": records},
        )

