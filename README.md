# Zahosts Health - WHM Server Health Monitor

One-glance health for cPanel/WHM servers: mail queue, DNSBL, email auth, backups, AutoSSL, WordPress, and security checks in one WHM panel.

![screenshot](docs/screenshot.png)

## Requirements

- cPanel/WHM server with root access.
- Python 3.8+ for the collector package.
- On CloudLinux, use an alt-python 3.8+ binary and point the installed script shebang at it, for example `/opt/alt/python311/bin/python3.11`.

## Install (5 minutes)

```bash
git clone https://github.com/your-org/zahosts-health
cd zahosts-health
sudo ./scripts/install.sh
sudo cp zahosts-health.json.example /etc/zahosts-health.json
sudo editor /etc/zahosts-health.json
```

The installer places the plugin files, sets root-owned permissions, registers the WHM AppConfig entry, and installs the hourly cron.

## How it works

The cron runs the Python collector hourly. The collector writes a compact `/var/cache/zahosts-health/status.json` snapshot with `schema_version` 2, then `index.php` renders that snapshot inside WHM.

Collectors:

- `server`
- `mail`
- `dnsbl`
- `email_auth`
- `backup`
- `autossl`
- `wordpress`
- `security`

## Configuration

Copy `zahosts-health.json.example` to `/etc/zahosts-health.json` and edit:

- `report_email`: recipient for text reports.
- `server_ip`: public server IP checked against DNSBL zones.
- `auth_domains`: domains checked for SPF, DKIM, and DMARC.
- `max_auth_domains`: safety cap for discovered email-auth domains.
- `mail_log_tail_lines`: number of Exim log lines scanned for mail signals.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
```

Tests are fully offline and use captured fixtures; no WHM server is required.

## License

MIT. See `LICENSE`.
