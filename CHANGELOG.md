# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.1.0] - 2026-06-22

### Added

- Security: /24 subnet aggregation of Exim auth failures (`top_auth_fail_subnets`), surfacing distributed brute-force where individual IPs stay below per-IP thresholds. Shown in the WHM Security card.
- UI: "Microsoft Delivery Status" section now renders parsed events (Time, Sender, Recipient, Status, Detail) instead of raw log lines.

### Changed

- status.json schema_version bumped to 3 (additive: new security.top_auth_fail_subnets).

## [2.0.0] - 2026-06-22

### Changed

- Rewrote the collector as a modular Python package (eight collectors behind a common interface) with atomic snapshot writes, schema_version 2, structured run logging, and a full offline pytest suite. Hardened install/permissions; legacy monolith retained as a thin fallback shim.
