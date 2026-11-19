# Changelog

## 0.1.2

- Accept OpenWISP monitoring reports with a device UUID in the URL.
- Use the original OpenSOHO icon in Home Assistant.
- Link to the upstream OpenSOHO documentation for router setup.

## 0.1.1

- Base the add-on on stable OpenSOHO v0.16.0 and record upstream release pins centrally.
- Reduce OpenSOHO patches to HA startup integration and suppress raw configuration output in the add-on entry point.
- Check for new published stable OpenSOHO and PocketBase releases daily.
- Translate project documentation to English and add contributor instructions in AGENTS.md.

## 0.1.0

- Package pinned OpenSOHO and PocketBase for Home Assistant OS on amd64 and aarch64.
- Use the Home Assistant Ingress identity to authorize administrators throughout the panel.
- Isolate the OpenWISP LAN endpoints and persist controller state in Supervisor backups.

- Preserve Ingress authorization for backup downloads and settings changes.
- Validate native amd64 and arm64 images in GitHub Actions with browser smoke tests.
