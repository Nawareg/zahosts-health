#!/usr/bin/env python3
import argparse
import datetime as _dt
import glob
import json
import os
import re
import socket
import subprocess
import tempfile
from collections import Counter

BASE_DIR = "/usr/local/zahosts-health"
CACHE_DIR = "/var/cache/zahosts-health"
LOG_DIR = "/var/log/zahosts-health"
STATE_PATH = os.path.join(CACHE_DIR, "status.json")
TEXT_REPORT_PATH = os.path.join(CACHE_DIR, "daily-report.txt")
CONFIG_PATH = "/etc/zahosts-health.json"
DEFAULT_EMAIL = "root@localhost"
SERVER_IP = ""
DNSBL_ZONES = [
    "zen.spamhaus.org",
    "bl.spamcop.net",
    "b.barracudacentral.org",
    "dnsbl.sorbs.net",
]
DEFAULT_AUTH_DOMAINS = []


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def ensure_dirs():
    for path in (CACHE_DIR, LOG_DIR):
        if not os.path.isdir(path):
            os.makedirs(path, mode=0o750, exist_ok=True)


def read_config():
    cfg = {
        "report_email": DEFAULT_EMAIL,
        "server_ip": SERVER_IP,
        "auth_domains": DEFAULT_AUTH_DOMAINS,
        "max_auth_domains": 25,
        "mail_log_tail_lines": 7000,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as fh:
                user_cfg = json.load(fh)
            if isinstance(user_cfg, dict):
                cfg.update(user_cfg)
        except Exception as exc:
            cfg["config_error"] = str(exc)
    return cfg


def run_cmd(args, timeout=30):
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        out, err = proc.communicate(timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": out.strip(),
            "stderr": err.strip(),
            "cmd": args,
        }
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": False, "code": 124, "stdout": "", "stderr": "timeout", "cmd": args}
    except Exception as exc:
        return {"ok": False, "code": 1, "stdout": "", "stderr": str(exc), "cmd": args}


def run_json(args, timeout=45):
    res = run_cmd(args, timeout=timeout)
    if not res["ok"]:
        return None, res
    try:
        return json.loads(res["stdout"]), res
    except Exception as exc:
        res["ok"] = False
        res["stderr"] = "json parse error: %s" % exc
        return None, res


def tail_file(path, max_lines):
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
        lines = data.decode("utf-8", "replace").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def int_from_output(text, default=0):
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else default


def status_from_score(score):
    if score >= 2:
        return "critical"
    if score == 1:
        return "warn"
    return "ok"


def collect_server():
    hostname = socket.getfqdn()
    whm_version, _ = run_json(["whmapi1", "--output=json", "version"], timeout=20)
    load = ""
    try:
        with open("/proc/loadavg", "r") as fh:
            load = fh.read().strip()
    except Exception:
        pass
    disk = run_cmd(["df", "-h", "/"], timeout=10)["stdout"]
    contact = ""
    try:
        with open("/etc/wwwacct.conf", "r") as fh:
            for line in fh:
                if line.startswith("CONTACTEMAIL "):
                    contact = line.split(None, 1)[1].strip()
                    break
    except Exception:
        pass
    return {
        "hostname": hostname,
        "whm_version": whm_version,
        "loadavg": load,
        "disk_root": disk,
        "contact_email": contact,
    }


def collect_mail(cfg):
    queue_count = int_from_output(run_cmd(["/usr/sbin/exim", "-bpc"], timeout=20)["stdout"])
    null_res = run_cmd(["exiqgrep", "-f", "<>", "-c"], timeout=20)
    null_sender = int_from_output(null_res["stdout"])
    queue_text = run_cmd(["/usr/sbin/exim", "-bp"], timeout=30)["stdout"]
    queue_items = []
    for line in queue_text.splitlines():
        if re.search(r"\b1[a-zA-Z0-9]{5,}-", line):
            queue_items.append(line.strip())
    log_lines = tail_file("/var/log/exim_mainlog", int(cfg.get("mail_log_tail_lines", 7000)))
    ms_lines = [
        line for line in log_lines
        if "S77719" in line or "mail.protection.outlook.com" in line or "ATTR5" in line
    ]
    auth_fail_lines = [
        line for line in log_lines
        if "authenticator failed" in line or "Incorrect authentication data" in line
    ]
    ms_counter = Counter()
    for line in ms_lines:
        if "S77719" in line:
            ms_counter["S77719"] += 1
        if "ATTR5" in line:
            ms_counter["ATTR5"] += 1
        if "451 4.7.500" in line:
            ms_counter["451_4_7_500"] += 1
        if "451 4.4.4" in line:
            ms_counter["451_4_4_4"] += 1
    score = 0
    if queue_count > 100 or null_sender > 20:
        score = 2
    elif queue_count > 25 or null_sender > 0 or ms_counter:
        score = 1
    return {
        "status": status_from_score(score),
        "queue_count": queue_count,
        "null_sender_count": null_sender,
        "queue_preview": queue_items[:25],
        "microsoft_error_counts": dict(ms_counter),
        "microsoft_recent": ms_lines[-12:],
        "auth_fail_count": len(auth_fail_lines),
        "auth_fail_recent": auth_fail_lines[-12:],
    }


def collect_dnsbl(cfg):
    ip = cfg.get("server_ip") or SERVER_IP
    reversed_ip = ".".join(reversed(ip.split(".")))
    results = []
    listed = 0
    for zone in DNSBL_ZONES:
        query = "%s.%s" % (reversed_ip, zone)
        res = run_cmd(["dig", "+short", query], timeout=15)
        answer = res["stdout"].strip()
        is_listed = bool(answer)
        if is_listed:
            listed += 1
        results.append({"zone": zone, "listed": is_listed, "answer": answer})
    return {"status": "critical" if listed else "ok", "ip": ip, "results": results}


def load_userdomains():
    mapping = {}
    for path in ("/etc/userdomains", "/etc/trueuserdomains"):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r") as fh:
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


def discover_auth_domains(cfg):
    domains = set(d.lower() for d in cfg.get("auth_domains", []) if d)
    for line in tail_file("/var/log/exim_mainlog", 5000):
        match = re.search(r"Sender identification U=\S+ D=([A-Za-z0-9_.-]+)", line)
        if match:
            domain = match.group(1).lower()
            if domain not in ("-system-", "localhost"):
                domains.add(domain)
    max_domains = int(cfg.get("max_auth_domains", 25))
    return sorted(domains)[:max_domains]


def collect_email_auth(cfg):
    userdomains = load_userdomains()
    domains = discover_auth_domains(cfg)
    records = []
    problems = 0
    for domain in domains:
        user = userdomains.get(domain)
        rec = {"domain": domain, "user": user, "spf": "unknown", "dkim": "unknown", "dmarc": "unknown"}
        if user:
            spf, _ = run_json(
                ["uapi", "--user=%s" % user, "--output=json", "EmailAuth", "validate_current_spfs", "domain=%s" % domain],
                timeout=30,
            )
            dkim, _ = run_json(
                ["uapi", "--user=%s" % user, "--output=json", "EmailAuth", "validate_current_dkims", "domain=%s" % domain],
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
        dmarc_res = run_cmd(["dig", "+short", "TXT", "_dmarc.%s" % domain], timeout=15)
        rec["dmarc"] = "present" if dmarc_res["stdout"].strip() else "missing"
        if rec["spf"] != "VALID" or rec["dkim"] != "VALID" or rec["dmarc"] == "missing":
            problems += 1
        records.append(rec)
    return {"status": "warn" if problems else "ok", "checked": len(records), "problems": problems, "records": records}


def collect_backup():
    cfg, _ = run_json(["whmapi1", "--output=json", "backup_config_get"], timeout=30)
    dates, _ = run_json(["whmapi1", "--output=json", "backup_date_list"], timeout=30)
    dest, _ = run_json(["whmapi1", "--output=json", "backup_destination_list"], timeout=30)
    backup_cfg = (cfg or {}).get("data", {}).get("backup_config", {})
    backup_dates = (dates or {}).get("data", {}).get("backup_set", [])
    destinations = (dest or {}).get("data", {}).get("destination_list", [])
    latest_log = ""
    latest_log_tail = []
    logs = sorted(glob.glob("/usr/local/cpanel/logs/cpbackup/*.log"), key=os.path.getmtime, reverse=True)
    if logs:
        latest_log = logs[0]
        latest_log_tail = tail_file(latest_log, 120)
    log_text = "\n".join(latest_log_tail)
    errors = []
    for line in latest_log_tail:
        if re.search(r"\b(error|failed|failure|fatal)\b", line, re.I) and "Final state is Backup::Success" not in line:
            errors.append(line)
    success = "Final state is Backup::Success" in log_text
    enabled = str(backup_cfg.get("backupenable", "0")) == "1"
    active_processes = collect_backup_processes()
    in_progress = bool(active_processes)
    score = 0
    if not enabled or not backup_dates:
        score = 2
    elif not success and in_progress:
        score = 1
    elif not success:
        score = 2
    elif not destinations:
        score = 1
    return {
        "status": status_from_score(score),
        "enabled": enabled,
        "backup_dir": backup_cfg.get("backupdir", ""),
        "latest_dates": backup_dates[:5],
        "remote_destinations": len(destinations),
        "latest_log": latest_log,
        "latest_success": success,
        "in_progress": in_progress,
        "active_processes": active_processes[:10],
        "latest_errors": errors[:20],
    }


def collect_backup_processes():
    res = run_cmd(["ps", "-eo", "pid=,args="], timeout=15)
    if not res["ok"]:
        return []
    active = []
    for line in res["stdout"].splitlines():
        if "zahosts_health.py" in line:
            continue
        if re.search(r"(/usr/local/cpanel/bin/backup\b|/usr/local/cpanel/bin/pkgacct\b|\bpkgacct\b.*\bbackup\b|\bpkgacct\b\s+-\s+)", line):
            active.append(line.strip())
    return active


def collect_autossl():
    pending, _ = run_json(["whmapi1", "--output=json", "get_autossl_pending_queue"], timeout=30)
    catalog, _ = run_json(["whmapi1", "--output=json", "get_autossl_logs_catalog"], timeout=45)
    pending_certs = (pending or {}).get("data", {}).get("pending_certificates", [])
    logs = (catalog or {}).get("data", {}).get("payload", [])
    latest = sorted(logs, key=lambda x: x.get("start_time", ""), reverse=True)[:10] if isinstance(logs, list) else []
    return {
        "status": "warn" if pending_certs else "ok",
        "pending_count": len(pending_certs),
        "pending": pending_certs[:20],
        "latest_logs": latest,
    }


def collect_wordpress():
    sites, res = run_json(["/usr/local/bin/wp-toolkit", "--list", "-plugins", "-themes", "-format", "json"], timeout=120)
    if not isinstance(sites, list):
        return {"status": "warn", "total": 0, "error": res.get("stderr", "wp-toolkit failed"), "sites": []}
    risky = []
    plugin_updates = 0
    theme_updates = 0
    for site in sites:
        flags = []
        for key in ("broken", "infected", "unsupportedPhp", "unsupportedWp", "outdatedPhp", "outdatedWp"):
            if site.get(key):
                flags.append(key)
        for plugin in (site.get("plugins") or {}).values():
            if plugin.get("update_version"):
                plugin_updates += 1
        for theme in (site.get("themes") or {}).values():
            if theme.get("update_version"):
                theme_updates += 1
        if flags:
            risky.append({
                "id": site.get("id"),
                "siteUrl": site.get("siteUrl"),
                "version": site.get("version"),
                "flags": flags,
            })
    score = 2 if risky else (1 if plugin_updates or theme_updates else 0)
    return {
        "status": status_from_score(score),
        "total": len(sites),
        "risky_count": len(risky),
        "plugin_updates": plugin_updates,
        "theme_updates": theme_updates,
        "risky_sites": risky[:30],
    }


def collect_security():
    cphulk_status, _ = run_json(["whmapi1", "--output=json", "cphulk_status"], timeout=30)
    excessive, _ = run_json(["whmapi1", "--output=json", "get_cphulk_excessive_brutes"], timeout=45)
    brutes = (excessive or {}).get("data", {}).get("excessive_brutes", [])
    log_lines = tail_file("/var/log/exim_mainlog", 7000)
    auth_fails = [line for line in log_lines if "authenticator failed" in line or "Incorrect authentication data" in line]
    by_ip = Counter()
    by_user = Counter()
    for line in auth_fails:
        ip = re.search(r"\[([0-9a-fA-F:.]+)\]", line)
        user = re.search(r"set_id=([^)]+)", line)
        if ip:
            by_ip[ip.group(1)] += 1
        if user:
            by_user[user.group(1)] += 1
    im_health = run_cmd(["imunify360-agent", "health"], timeout=30)
    enabled = (cphulk_status or {}).get("data", {}).get("is_enabled") == 1
    score = 0 if enabled else 2
    if auth_fails and score == 0:
        score = 1
    return {
        "status": status_from_score(score),
        "cphulk_enabled": enabled,
        "excessive_brutes": brutes[:20],
        "exim_auth_fail_count": len(auth_fails),
        "top_auth_fail_ips": by_ip.most_common(10),
        "top_auth_fail_users": by_user.most_common(10),
        "imunify_health": im_health["stdout"][-2000:] if im_health["ok"] else im_health["stderr"],
    }


def collect_all():
    ensure_dirs()
    cfg = read_config()
    data = {
        "generated_at": utc_now(),
        "config": {"report_email": cfg.get("report_email"), "server_ip": cfg.get("server_ip")},
        "server": collect_server(),
        "mail": collect_mail(cfg),
        "dnsbl": collect_dnsbl(cfg),
        "email_auth": collect_email_auth(cfg),
        "backup": collect_backup(),
        "autossl": collect_autossl(),
        "wordpress": collect_wordpress(),
        "security": collect_security(),
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
    data["recommendations"] = build_recommendations(data)
    atomic_write_json(STATE_PATH, data)
    write_text_report(data)
    return data


def build_recommendations(data):
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


def atomic_write_json(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".status-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def write_text_report(data):
    lines = []
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
    with open(TEXT_REPORT_PATH, "w") as fh:
        fh.write(text)
    os.chmod(TEXT_REPORT_PATH, 0o640)
    return text


def send_report():
    data = collect_all()
    email = data.get("config", {}).get("report_email") or DEFAULT_EMAIL
    with open(TEXT_REPORT_PATH, "r") as fh:
        body = fh.read()
    subject = "[%s] Zahosts WHM Health: %s" % (data["overall_status"].upper(), data["server"]["hostname"])
    message = "To: %s\nFrom: Zahosts Health <root@%s>\nSubject: %s\nContent-Type: text/plain; charset=utf-8\n\n%s" % (
        email,
        data["server"]["hostname"],
        subject,
        body,
    )
    proc = subprocess.Popen(["/usr/sbin/sendmail", "-t"], stdin=subprocess.PIPE, universal_newlines=True)
    proc.communicate(message)
    return proc.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="collect", choices=["collect", "send-report", "print-report"])
    args = parser.parse_args()
    if args.action == "collect":
        data = collect_all()
        print(json.dumps({"status": data["overall_status"], "generated_at": data["generated_at"]}))
        return 0
    if args.action == "send-report":
        return send_report()
    if args.action == "print-report":
        collect_all()
        with open(TEXT_REPORT_PATH, "r") as fh:
            print(fh.read())
        return 0
    return 1


if __name__ == "__main__":
    try:
        from zahosts_health.__main__ import main as package_main
    except Exception:
        raise SystemExit(main())
    raise SystemExit(package_main())
