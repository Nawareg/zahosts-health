# Security Policy

## Reporting

Email security@zahosts.com with details. Please do not open public issues for vulnerabilities. We aim to acknowledge reports within 72 hours.

## Security Posture

- The plugin runs on a cPanel/WHM server as root and expects root-owned files.
- Installed directories are `750`; runtime snapshots and reports are `640`; config is `640`; WHM AppConfig is `600`.
- `status.json` contains operational health data only, no passwords or API secrets, and is written as `640`.
- The WHM UI accepts no free-form input; the refresh action is parameterless.
- Collectors shell out only to fixed cPanel and system binaries. User-provided values are never passed through a shell.

## Supported Versions

The latest minor release receives security fixes.
