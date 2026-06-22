from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .base import Collector, CollectorResult, Status

BACKUP_LOG_GLOB = "/usr/local/cpanel/logs/cpbackup/*.log"


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


def _latest_log_path() -> str:
    logs = sorted(glob.glob(BACKUP_LOG_GLOB), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else ""


def _backup_processes() -> list[str]:
    res = _run(["ps", "-eo", "pid=,args="], timeout=15)
    if not res.ok:
        return []
    active = []
    for line in res.out.splitlines():
        if "zahosts_health.py" in line:
            continue
        if re.search(
            r"(/usr/local/cpanel/bin/backup\b|/usr/local/cpanel/bin/pkgacct\b|\bpkgacct\b.*\bbackup\b|\bpkgacct\b\s+-\s+)",
            line,
        ):
            active.append(line.strip())
    return active


class BackupCollector(Collector):
    name = "backup"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        backup_conf_json, _ = _run_json(["whmapi1", "--output=json", "backup_config_get"], timeout=30)
        dates_json, _ = _run_json(["whmapi1", "--output=json", "backup_date_list"], timeout=30)
        dest_json, _ = _run_json(["whmapi1", "--output=json", "backup_destination_list"], timeout=30)

        backup_config = (backup_conf_json or {}).get("data", {}).get("backup_config", {})
        backup_dates = (dates_json or {}).get("data", {}).get("backup_set", [])
        destinations = (dest_json or {}).get("data", {}).get("destination_list", [])

        latest_log = _latest_log_path()
        latest_log_tail = _tail_file(latest_log, 120) if latest_log else []
        log_text = "\n".join(latest_log_tail)
        errors = [
            line
            for line in latest_log_tail
            if re.search(r"\b(error|failed|failure|fatal)\b", line, re.I)
            and "Final state is Backup::Success" not in line
        ]
        success = "Final state is Backup::Success" in log_text
        enabled = str(backup_config.get("backupenable", "0")) == "1"
        active_processes = _backup_processes()
        in_progress = bool(active_processes)

        if not enabled or not backup_dates:
            status = Status.CRITICAL
        elif not success and in_progress:
            status = Status.WARN
        elif not success:
            status = Status.CRITICAL
        elif not destinations:
            status = Status.WARN
        else:
            status = Status.OK

        return CollectorResult(
            name=self.name,
            status=status,
            metrics={
                "enabled": enabled,
                "backup_dir": backup_config.get("backupdir", ""),
                "latest_dates": backup_dates[:5],
                "remote_destinations": len(destinations),
                "latest_log": latest_log,
                "latest_success": success,
                "in_progress": in_progress,
                "active_processes": active_processes[:10],
                "latest_errors": errors[:20],
            },
        )

