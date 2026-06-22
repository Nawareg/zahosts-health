from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import subprocess
import tempfile
import time
import traceback
from typing import Any, Callable, Mapping

from .collectors.autossl import AutoSSLCollector
from .collectors.backup import BackupCollector
from .collectors.dnsbl import DnsblCollector
from .collectors.email_auth import EmailAuthCollector
from .collectors.mail import MailCollector
from .collectors.security import SecurityCollector
from .collectors.server import ServerCollector
from .collectors.wordpress import WordpressCollector

BASE_DIR = "/usr/local/zahosts-health"
CACHE_DIR = "/var/cache/zahosts-health"
LOG_DIR = "/var/log/zahosts-health"
STATE_PATH = os.path.join(CACHE_DIR, "status.json")
TEXT_REPORT_PATH = os.path.join(CACHE_DIR, "daily-report.txt")
CONFIG_PATH = "/etc/zahosts-health.json"
DEFAULT_EMAIL = "root@localhost"
SERVER_IP = ""
DEFAULT_AUTH_DOMAINS = []

def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def ensure_dirs() -> None:
    for path in (CACHE_DIR, LOG_DIR):
        os.makedirs(path, mode=0o750, exist_ok=True)


def read_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "report_email": DEFAULT_EMAIL,
        "server_ip": SERVER_IP,
        "auth_domains": DEFAULT_AUTH_DOMAINS,
        "max_auth_domains": 25,
        "mail_log_tail_lines": 7000,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                user_cfg = json.load(fh)
            if isinstance(user_cfg, dict):
                cfg.update(user_cfg)
        except Exception as exc:
            cfg["config_error"] = str(exc)
    return cfg


def write_snapshot_atomic(path: str, payload: dict[str, Any]) -> None:
    payload["schema_version"] = 3
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o750, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o640)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def collect_all(path: str = STATE_PATH) -> dict[str, Any]:
    ensure_dirs()
    started = time.monotonic()
    cfg = read_config()
    errors: list[dict[str, str]] = []

    data: dict[str, Any] = {
        "generated_at": utc_now(),
        "config": {"report_email": cfg.get("report_email"), "server_ip": cfg.get("server_ip")},
        "server": _safe_collect("server", lambda: ServerCollector().collect(cfg).metrics, _server_fallback, errors),
        "mail": _safe_collect("mail", lambda: MailCollector().collect(cfg).legacy_payload(), _mail_fallback, errors),
        "dnsbl": _safe_collect(
            "dnsbl",
            lambda: DnsblCollector().collect(cfg).legacy_payload(),
            lambda: _dnsbl_fallback(cfg),
            errors,
        ),
        "email_auth": _safe_collect(
            "email_auth",
            lambda: EmailAuthCollector().collect(cfg).legacy_payload(),
            _email_auth_fallback,
            errors,
        ),
        "backup": _safe_collect(
            "backup",
            lambda: BackupCollector().collect(cfg).legacy_payload(),
            _backup_fallback,
            errors,
        ),
        "autossl": _safe_collect(
            "autossl",
            lambda: AutoSSLCollector().collect(cfg).legacy_payload(),
            _autossl_fallback,
            errors,
        ),
        "wordpress": _safe_collect(
            "wordpress",
            lambda: WordpressCollector().collect(cfg).legacy_payload(),
            _wordpress_fallback,
            errors,
        ),
        "security": _safe_collect(
            "security",
            lambda: SecurityCollector().collect(cfg).legacy_payload(),
            _security_fallback,
            errors,
        ),
    }

    statuses = [
        data["mail"]["status"],
        data["dnsbl"]["status"],
        data["email_auth"]["status"],
        data["backup"]["status"],
        data["autossl"]["status"],
        data["wordpress"]["status"],
        data["security"]["status"],
    ]
    data["overall_status"] = "critical" if "critical" in statuses else ("warn" if "warn" in statuses else "ok")
    if errors:
        data["collector_errors"] = errors
        data["last_successful_collect"] = _previous_success(path)
    else:
        data["last_successful_collect"] = data["generated_at"]
    data["recommendations"] = _build_recommendations(data)

    write_snapshot_atomic(path, data)
    write_text_report(data)
    _write_run_log("collect", data, time.monotonic() - started, errors)
    return data


def write_text_report(data: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Zahosts WHM Health Report")
    lines.append("Generated: %s" % data["generated_at"])
    lines.append("Overall: %s" % data["overall_status"].upper())
    lines.append("")
    lines.append("Mail: queue=%s null_sender=%s ms_errors=%s" % (
        data["mail"]["queue_count"],
        data["mail"]["null_sender_count"],
        data["mail"]["microsoft_error_counts"],
    ))
    lines.append("DNSBL: %s" % data["dnsbl"]["status"].upper())
    lines.append("Backups: enabled=%s dates=%s remote_destinations=%s latest_success=%s in_progress=%s" % (
        data["backup"]["enabled"],
        ",".join(data["backup"]["latest_dates"]),
        data["backup"]["remote_destinations"],
        data["backup"]["latest_success"],
        data["backup"].get("in_progress"),
    ))
    lines.append("AutoSSL: pending=%s" % data["autossl"]["pending_count"])
    lines.append("WordPress: total=%s risky=%s plugin_updates=%s theme_updates=%s" % (
        data["wordpress"]["total"],
        data["wordpress"]["risky_count"],
        data["wordpress"]["plugin_updates"],
        data["wordpress"]["theme_updates"],
    ))
    lines.append("Security: cPHulk=%s auth_fail_count=%s excessive_brutes=%s" % (
        data["security"]["cphulk_enabled"],
        data["security"]["exim_auth_fail_count"],
        len(data["security"]["excessive_brutes"]),
    ))
    lines.append("")
    lines.append("Recommendations:")
    if data["recommendations"]:
        for item in data["recommendations"]:
            lines.append("- %s" % item)
    else:
        lines.append("- No immediate action.")
    lines.append("")
    lines.append("Recent Microsoft lines:")
    for line in data["mail"]["microsoft_recent"][-6:]:
        lines.append("- %s" % line)
    text = "\n".join(lines) + "\n"
    _write_text_atomic(TEXT_REPORT_PATH, text)
    return text


def send_report() -> int:
    data = collect_all()
    email = _mail_header(data.get("config", {}).get("report_email") or DEFAULT_EMAIL)
    hostname = _mail_header(data["server"]["hostname"])
    subject = _mail_header("[%s] Zahosts WHM Health: %s" % (data["overall_status"].upper(), hostname))
    with open(TEXT_REPORT_PATH, encoding="utf-8") as fh:
        body = fh.read()
    message = (
        "To: %s\nFrom: Zahosts Health <root@%s>\nSubject: %s\n"
        "Content-Type: text/plain; charset=utf-8\n\n%s"
    ) % (email, hostname, subject, body)
    proc = subprocess.Popen(
        ["/usr/sbin/sendmail", "-t"],
        stdin=subprocess.PIPE,
        universal_newlines=True,
    )
    proc.communicate(message)
    return int(proc.returncode or 0)


def print_report() -> str:
    collect_all()
    with open(TEXT_REPORT_PATH, encoding="utf-8") as fh:
        return fh.read()


def _safe_collect(
    name: str,
    collect: Callable[[], dict[str, Any]],
    fallback: Callable[[], dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    try:
        return collect()
    except Exception as exc:
        errors.append(
            {
                "collector": name,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=4),
            }
        )
        payload = fallback()
        payload["error"] = str(exc)
        return payload


def build_recommendations(data: dict[str, Any]) -> list[str]:
    recs = []
    if data["mail"]["null_sender_count"]:
        recs.append("Investigate null-sender bounces; they should remain near zero.")
    if data["mail"]["microsoft_error_counts"]:
        recs.append("Avoid manual Deliver Now for Microsoft deferrals; let queue retries cool down.")
    if data["backup"]["remote_destinations"] == 0:
        recs.append("No WHM backup remote destination is listed. Add or verify off-server backup storage.")
    if data["backup"].get("in_progress") and not data["backup"].get("latest_success"):
        recs.append("WHM backup is currently running; wait for completion before treating latest backup as failed.")
    if data["email_auth"]["problems"]:
        recs.append("Review SPF/DKIM/DMARC rows marked unknown/missing.")
    if data["wordpress"]["plugin_updates"] or data["wordpress"]["theme_updates"]:
        recs.append("Review WP Toolkit updates; premium plugins may need manual handling.")
    if data["security"]["exim_auth_fail_count"]:
        recs.append("cPHulk is active; monitor repeated SMTP auth attempts before tightening thresholds.")
    return recs


def _build_recommendations(data: dict[str, Any]) -> list[str]:
    try:
        recs = build_recommendations(data)
    except Exception:
        recs = []
    if data.get("collector_errors"):
        recs.append("Review Zahosts Health collector errors in /var/log/zahosts-health/run.log.")
    return recs


def _write_text_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o750, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o640)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_run_log(action: str, data: Mapping[str, Any], duration: float, errors: list[dict[str, str]]) -> None:
    record = {
        "ts": utc_now(),
        "action": action,
        "duration_seconds": round(duration, 3),
        "overall": data.get("overall_status"),
        "collector_statuses": {
            key: value.get("status")
            for key, value in data.items()
            if isinstance(value, dict) and "status" in value
        },
        "errors": errors,
    }
    path = os.path.join(LOG_DIR, "run.log")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    os.chmod(path, 0o640)


def _previous_success(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            previous = json.load(fh)
        value = previous.get("last_successful_collect") or previous.get("generated_at")
        return str(value) if value else None
    except Exception:
        return None


def _mail_header(value: Any) -> str:
    return str(value).replace("\r", "").replace("\n", "")


def _server_fallback() -> dict[str, Any]:
    return {
        "hostname": socket.getfqdn(),
        "whm_version": None,
        "loadavg": "",
        "disk_root": "",
        "contact_email": "",
    }


def _mail_fallback() -> dict[str, Any]:
    return _fallback_with_status(
        queue_count=0,
        null_sender_count=0,
        queue_preview=[],
        microsoft_error_counts={},
        microsoft_recent=[],
        auth_fail_count=0,
        auth_fail_recent=[],
    )


def _dnsbl_fallback(cfg: Mapping[str, Any]) -> dict[str, Any]:
    return _fallback_with_status(ip=cfg.get("server_ip") or SERVER_IP, results=[])


def _email_auth_fallback() -> dict[str, Any]:
    return _fallback_with_status(checked=0, problems=0, records=[])


def _backup_fallback() -> dict[str, Any]:
    return _fallback_with_status(
        enabled=False,
        backup_dir="",
        latest_dates=[],
        remote_destinations=0,
        latest_log="",
        latest_success=False,
        in_progress=False,
        active_processes=[],
        latest_errors=[],
    )


def _autossl_fallback() -> dict[str, Any]:
    return _fallback_with_status(pending_count=0, pending=[], latest_logs=[])


def _wordpress_fallback() -> dict[str, Any]:
    return _fallback_with_status(
        total=0,
        risky_count=0,
        plugin_updates=0,
        theme_updates=0,
        risky_sites=[],
    )


def _security_fallback() -> dict[str, Any]:
    return _fallback_with_status(
        cphulk_enabled=False,
        excessive_brutes=[],
        exim_auth_fail_count=0,
        top_auth_fail_ips=[],
        top_auth_fail_users=[],
        top_auth_fail_subnets=[],
        imunify_health="",
    )


def _fallback_with_status(**values: Any) -> dict[str, Any]:
    return {"status": "warn", **values}
