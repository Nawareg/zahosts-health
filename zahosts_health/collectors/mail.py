from __future__ import annotations

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


def _int_from_output(text: str, default: int = 0) -> int:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else default


def _cfg_int(cfg: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def _threshold(cfg: Mapping[str, Any], key: str, default: int) -> int:
    thresholds = cfg.get("thresholds", {})
    if isinstance(thresholds, Mapping):
        return _cfg_int(thresholds, key, default)
    return default


class MailCollector(Collector):
    name = "mail"

    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        queue_count = _int_from_output(_run(["/usr/sbin/exim", "-bpc"], timeout=20).out)
        null_sender = _int_from_output(_run(["exiqgrep", "-f", "<>", "-c"], timeout=20).out)

        queue_text = _run(["/usr/sbin/exim", "-bp"], timeout=30).out
        queue_items = [
            line.strip()
            for line in queue_text.splitlines()
            if re.search(r"\b1[a-zA-Z0-9]{5,}-", line)
        ]

        log_lines = _tail_file(MAIL_LOG, _cfg_int(cfg, "mail_log_tail_lines", 7000))
        ms_lines = [
            line
            for line in log_lines
            if "S77719" in line or "mail.protection.outlook.com" in line or "ATTR5" in line
        ]
        auth_fail_lines = [
            line
            for line in log_lines
            if "authenticator failed" in line or "Incorrect authentication data" in line
        ]

        ms_counter: Counter[str] = Counter()
        for line in ms_lines:
            if "S77719" in line:
                ms_counter["S77719"] += 1
            if "ATTR5" in line:
                ms_counter["ATTR5"] += 1
            if "451 4.7.500" in line:
                ms_counter["451_4_7_500"] += 1
            if "451 4.4.4" in line:
                ms_counter["451_4_4_4"] += 1

        queue_critical = _threshold(cfg, "mail_queue_critical", 100)
        queue_warn = _threshold(cfg, "mail_queue_warn", 25)
        if queue_count > queue_critical or null_sender > 20:
            status = Status.CRITICAL
        elif queue_count > queue_warn or null_sender > 0 or ms_counter:
            status = Status.WARN
        else:
            status = Status.OK

        recommendations = (
            ["Investigate null-sender bounces; they should stay near zero."]
            if null_sender
            else []
        )
        return CollectorResult(
            name=self.name,
            status=status,
            metrics={
                "queue_count": queue_count,
                "null_sender_count": null_sender,
                "queue_preview": queue_items[:25],
                "microsoft_error_counts": dict(ms_counter),
                "microsoft_recent": ms_lines[-12:],
                "auth_fail_count": len(auth_fail_lines),
                "auth_fail_recent": auth_fail_lines[-12:],
            },
            recommendations=recommendations,
        )
