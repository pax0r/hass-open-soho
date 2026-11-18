# Changelog

## 0.1.0

- Package pinned OpenSOHO and PocketBase for Home Assistant OS on amd64 and aarch64.
- Use the Home Assistant Ingress identity to authorize administrators throughout the panel.
- Isolate the OpenWISP LAN endpoints and persist controller state in Supervisor backups.

- Preserve Ingress authorization for backup downloads and settings changes.
- Validate native amd64 and arm64 images in GitHub Actions with browser smoke tests.
