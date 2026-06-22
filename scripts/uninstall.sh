#!/bin/bash
#
# uninstall.sh — remove the Zahosts Health WHM plugin.
#
# Unregisters the plugin from WHM and removes code, UI, cron, and AppConfig.
# By default it KEEPS /etc/zahosts-health.json and the cache/logs so a reinstall
# preserves your settings and history. Pass --purge to remove those too.
#
# Usage:  sudo ./scripts/uninstall.sh [--purge]
#
set -euo pipefail

CODE_DIR="/usr/local/zahosts-health"
UI_DIR="/usr/local/cpanel/whostmgr/docroot/cgi/zahosts_health"
CONFIG_PATH="/etc/zahosts-health.json"
CRON_PATH="/etc/cron.d/zahosts-health"
APPCONF_PATH="/var/cpanel/apps/zahosts-health.conf"
CACHE_DIR="/var/cache/zahosts-health"
LOG_DIR="/var/log/zahosts-health"

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

log()  { printf '\033[0;34m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "must run as root"

# --- 1. unregister from WHM (before removing the AppConfig file) --------------
log "unregistering plugin from WHM"
if [ -x /usr/local/cpanel/bin/unregister_appconfig ]; then
    /usr/local/cpanel/bin/unregister_appconfig zahosts-health || warn "unregister_appconfig returned non-zero"
else
    warn "unregister_appconfig not found — skipping"
fi

# --- 2. remove deployed files ------------------------------------------------
log "removing code, UI, cron, AppConfig"
rm -rf "${CODE_DIR}"
rm -rf "${UI_DIR}"
rm -f  "${CRON_PATH}"
rm -f  "${APPCONF_PATH}"

# --- 3. config + state -------------------------------------------------------
if [ "${PURGE}" -eq 1 ]; then
    log "purging config, cache, and logs"
    rm -f  "${CONFIG_PATH}"
    rm -rf "${CACHE_DIR}"
    rm -rf "${LOG_DIR}"
else
    warn "kept ${CONFIG_PATH}, ${CACHE_DIR}, ${LOG_DIR} (re-run with --purge to remove)"
fi

log "done."
