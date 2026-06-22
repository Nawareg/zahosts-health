#!/bin/bash
#
# install.sh — deploy the Zahosts Health WHM plugin.
#
# Idempotent: safe to re-run for upgrades. Copies the collector package, the WHM
# UI, config, cron, and AppConfig into place; sets the exact permissions from the
# project handoff; registers the plugin in WHM; runs an initial collect; and
# validates the result.
#
# Usage:  sudo ./scripts/install.sh
#
set -euo pipefail

# --- locations (must match index.php and the cron file) ----------------------
CODE_DIR="/usr/local/zahosts-health"
UI_DIR="/usr/local/cpanel/whostmgr/docroot/cgi/zahosts_health"
CONFIG_PATH="/etc/zahosts-health.json"
CRON_PATH="/etc/cron.d/zahosts-health"
APPCONF_PATH="/var/cpanel/apps/zahosts-health.conf"
CACHE_DIR="/var/cache/zahosts-health"
LOG_DIR="/var/log/zahosts-health"

# Repo root = parent of this script's directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "${SCRIPT_DIR}/.." && pwd)"

log()  { printf '\033[0;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "must run as root"
command -v python3 >/dev/null 2>&1 || die "python3 not found"

# --- 1. directories ----------------------------------------------------------
log "creating directories"
install -d -m 0750 -o root -g root "${CODE_DIR}"
install -d -m 0750 -o root -g root "${CODE_DIR}/zahosts_health"
install -d -m 0750 -o root -g root "${CODE_DIR}/zahosts_health/collectors"
install -d -m 0750 -o root -g root "${UI_DIR}"
install -d -m 0750 -o root -g root "${CACHE_DIR}"
install -d -m 0750 -o root -g root "${LOG_DIR}"

# --- 2. collector code -------------------------------------------------------
# Legacy monolith stays executable (it is the CLI entrypoint + fallback): 0750.
log "installing collector (package + legacy fallback)"
install -m 0750 -o root -g root "${SRC}/zahosts_health.py"                       "${CODE_DIR}/zahosts_health.py"
# Package modules are imported, not executed directly: 0640.
install -m 0640 -o root -g root "${SRC}/zahosts_health/__init__.py"              "${CODE_DIR}/zahosts_health/__init__.py"
install -m 0640 -o root -g root "${SRC}/zahosts_health/__main__.py"              "${CODE_DIR}/zahosts_health/__main__.py"
install -m 0640 -o root -g root "${SRC}/zahosts_health/runner.py"                "${CODE_DIR}/zahosts_health/runner.py"
install -m 0640 -o root -g root "${SRC}/zahosts_health/collectors/__init__.py"  "${CODE_DIR}/zahosts_health/collectors/__init__.py"
install -m 0640 -o root -g root "${SRC}/zahosts_health/collectors/base.py"      "${CODE_DIR}/zahosts_health/collectors/base.py"
install -m 0640 -o root -g root "${SRC}/zahosts_health/collectors/mail.py"      "${CODE_DIR}/zahosts_health/collectors/mail.py"

# --- 3. WHM UI ---------------------------------------------------------------
log "installing WHM UI"
install -m 0644 -o root -g root "${SRC}/index.php" "${UI_DIR}/index.php"

# --- 4. config (do not clobber an existing customised config) ----------------
if [ -f "${CONFIG_PATH}" ]; then
    warn "config exists, leaving ${CONFIG_PATH} untouched"
else
    log "installing default config"
    install -m 0640 -o root -g root "${SRC}/zahosts-health.json" "${CONFIG_PATH}"
fi

# --- 5. cron -----------------------------------------------------------------
log "installing cron"
install -m 0640 -o root -g root "${SRC}/zahosts-health.cron" "${CRON_PATH}"

# --- 6. AppConfig + WHM registration ----------------------------------------
log "registering plugin in WHM"
install -m 0600 -o root -g root "${SRC}/zahosts-health.conf" "${APPCONF_PATH}"
if [ -x /usr/local/cpanel/bin/register_appconfig ]; then
    /usr/local/cpanel/bin/register_appconfig "${APPCONF_PATH}"
else
    warn "register_appconfig not found — is this a cPanel/WHM server? skipping registration"
fi

# --- 7. initial collect + validation ----------------------------------------
log "running initial collect"
if "${CODE_DIR}/zahosts_health.py" collect >/dev/null 2>&1; then
    if python3 -m json.tool "${CACHE_DIR}/status.json" >/dev/null 2>&1; then
        OVERALL="$(python3 -c "import json;print(json.load(open('${CACHE_DIR}/status.json'))['overall_status'])" 2>/dev/null || echo unknown)"
        log "initial collect OK — overall status: ${OVERALL}"
    else
        die "collect ran but ${CACHE_DIR}/status.json is not valid JSON"
    fi
else
    warn "initial collect failed (expected off a real WHM server). Inspect ${LOG_DIR}/run.log"
fi

log "done. Open WHM > Plugins > Zahosts Health."
