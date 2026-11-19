# OpenSOHO for Home Assistant

An unofficial Home Assistant OS add-on for Supervisor installations on `amd64` and `aarch64`. The OpenSOHO panel opens from the Home Assistant sidebar. OpenWrt routers register, download configuration and send monitoring reports through a separate LAN port.

The add-on icon is the unmodified favicon from OpenSOHO v0.16.0. Copyright in the favicon remains with its original rights holders. [Original favicon](https://github.com/rubenbe/opensoho/blob/f54faedea50e5fa9569de3ee634f98f8b1565e32/favicon.png) · [Upstream license](https://github.com/rubenbe/opensoho/blob/f54faedea50e5fa9569de3ee634f98f8b1565e32/LICENSE)

## Installation

1. Ensure the branch available to Supervisor contains `repository.yaml` and the `opensoho/` directory. In the Home Assistant add-on store, open the repositories menu and add `https://github.com/pax0r/hass-open-soho`. For a local installation, place `opensoho/` in the HA OS local add-ons directory and refresh the store.
2. Install **OpenSOHO**. Supervisor builds the image from pinned revisions. The initial build requires access to Docker Hub image downloads, Debian packages, GitHub, npm and the public Go module proxy. The running controller operates locally. The image includes web assets and time zone data.
3. Set `shared_secret` in the add-on configuration. Generate 64 characters with `openssl rand -hex 32` on a trusted computer. The add-on requires at least 32 characters. Keep the value for router registration.
4. Enable **Show in sidebar** on the add-on page. Supervisor stores this as an instance setting. Start the add-on, sign in to HA as an administrator and open **OpenSOHO** in the sidebar. Use your usual local or external HA address.
5. Give the HA host a stable LAN address. Point the routers' OpenWISP **Server URL** at `http://<HA-LAN-IP>:8090` with no trailing slash, and use the same **Shared secret** as the add-on. If you change the published port in the add-on's network settings, update the router URLs. The add-on defaults to `enable_new_devices: false`, so new devices register with configuration delivery disabled.

| Address or path | Purpose |
| --- | --- |
| External or local HA address | Panel and administrative API through Ingress on internal add-on port 8091 |
| `http://<HA-LAN-IP>:8090` | OpenWISP registration, status and metadata reports, checksums, configuration archives and monitoring |
| `/data/opensoho/pb_data` | SQLite databases, PocketBase files and controller configuration |

Restrict port 8090 to trusted routers or a management network. HTTP on this port sends registration secrets, device keys and configuration without encryption. Supervisor accesses port 8091 within the HA network.

For OpenWrt packages, router setup and day-to-day configuration, see the [OpenSOHO documentation](https://opensoho.github.io/docs) and the [router setup guide for v0.16.0](https://github.com/rubenbe/opensoho/blob/f54faedea50e5fa9569de3ee634f98f8b1565e32/docs/content/en/docs/getting-started.md#configure-openwrt-devices).

## SSO and session behavior

Supervisor restricts the panel using `panel_admin`. The add-on also checks the TCP peer address `172.30.32.2` documented by HA, a valid user ID and membership in `system-admin` from `X-Remote-User-Groups`. The inspected Supervisor code removes incoming identity headers and inserts its own. The HA owner receives effective administrator group membership. Header support was confirmed in Supervisor 2026.11.0. Versions without this header receive an access denial. [Ingress documentation](https://developers.home-assistant.io/docs/apps/presentation/#ingress) · [Supervisor Ingress](https://github.com/home-assistant/supervisor/blob/c1c6f0a754c0656eb1af189f11009f1cfc4b3e28/supervisor/api/ingress.py) · [Groups](https://github.com/home-assistant/supervisor/blob/c1c6f0a754c0656eb1af189f11009f1cfc4b3e28/supervisor/const.py)

The adapter supplies the trusted identity through PocketBase's `RequestEvent.Auth`. The internal superuser record receives a random password on first startup. The browser receives a record ID and collection name. Each subsequent request and SSE reconnection passes through the Ingress authorization check. Tokens for protected file and backup downloads are created inside the process. PocketBase continues to enforce its access rules. The gateway blocks the built-in administrative token endpoints and PocketBase installer. [PocketBase Go routing](https://pocketbase.io/docs/go-routing/)

Access depends on the Ingress session and the role supplied by Supervisor. In the inspected HA code, logout revokes the Core session, while the Ingress cookie has its own Supervisor lifecycle. Supervisor extends its validity by 15 minutes on subsequent requests and may cache user roles. Existing SSE streams are limited to one minute. When testing immediate access revocation, remove the `ingress_session` browser cookie and check a fresh session. After emergency role revocation, restart Supervisor to refresh its cached roles, then verify that the former account is denied access. [Supervisor session implementation](https://github.com/home-assistant/supervisor/blob/c1c6f0a754c0656eb1af189f11009f1cfc4b3e28/supervisor/ingress.py)

Agent operation continues independently of panel authorization. The add-on prepares its persistent directory and switches to UID/GID 10001 on startup. PocketBase request logging is disabled to keep Ingress paths and agent keys in query strings out of logs. The add-on suppresses raw upstream stdout, which can contain generated router configuration. Startup and fatal diagnostics remain on stderr in the add-on log. PocketBase structured diagnostics are stored in its log database.

## Backup, restore and updates

- Create a Home Assistant backup including OpenSOHO and protect it as credential material. The `cold` backup mode stops the process for the snapshot. The backup contains add-on data and options. Embedded migrations are extracted from the image at startup.
- To restore, select a Home Assistant backup containing OpenSOHO in Supervisor. A restore from the PocketBase panel restarts the process as its unprivileged user, which cannot read Supervisor's private options file. After a Supervisor restore, check the port, settings and router state, then verify configuration downloads and fresh monitoring reports. Update router URLs if the HA host's LAN address changed.
- Before updating, create a backup and retain access to the previous image and its corresponding data backup. Supervisor preserves `/data` when replacing the image. Downgrading after a migration may require restoring an earlier backup.

## Troubleshooting

- **The panel returns 403.** Check your HA role and active session, open the panel from the sidebar and verify that your Supervisor version supplies the groups header. Clear an earlier Ingress cookie when switching accounts.
- **Panel assets or API calls fail.** In browser developer tools, check that requests to `/_/`, `/api/ha/session`, `/api/collections/` and `/api/realtime` share the prefix `/api/hassio_ingress/<token>/`. With HTTPS, verify that assets use the same origin and protocol as HA.
- **A router cannot reach the add-on.** Check the published port, LAN connectivity and that the shared secret in the add-on matches the router's setting.
- **Startup fails after a restore.** Check that the data volume is writable and Supervisor restored the options file. Use the image corresponding to the backup if a migration fails.

## Building and testing

```sh
docker buildx build --check opensoho
docker buildx build --target test opensoho
docker buildx build --platform linux/amd64 --load -t hass-open-soho:local opensoho
docker buildx build --platform linux/arm64 --load -t hass-open-soho:arm64 opensoho
python3 tests/smoke.py --http-only
```

The full smoke test uses Playwright and Chromium. Install `playwright==1.62.0` in a local Python environment and run `playwright install chromium`, or select an existing Chromium binary through `CHROMIUM_BIN`. Run `python3 tests/smoke.py`. The test creates an isolated Docker network and a temporary volume. Use `--replacement-image` to test a second image against the same volume. In a managed network with a private certificate authority, add `--secret id=build_ca,src=/path/to/trusted/bundle.pem` to the build command.

GitHub Actions runs workflow linting with pinned `actionlint`, script syntax checks, Go formatting checks and Dockerfile validation. Native jobs on `ubuntu-24.04` and `ubuntu-24.04-arm` run Go and JavaScript tests, build the image for their architecture and exercise browser behavior and image replacement. The workflow uses minimal permissions, timeouts and architecture-specific caches, and cancels older runs for the same branch. It runs on pushes, pull requests and manual dispatch.

Installation through a real Supervisor, an external HTTPS domain and physical routers requires the [HA OS E2E scenario](tests/HA-OS-E2E.md).

## Upstream releases and local patches

The dependency versions and immutable commits are recorded in `opensoho/upstream.env`. OpenSOHO uses stable release `v0.16.0` at `f54faedea50e5fa9569de3ee634f98f8b1565e32`. PocketBase UI uses `v0.40.5` at `6f370ea741f33adf889eef02e3c1b884a47aa522`, matching OpenSOHO's Go dependency.

Two source patches provide the integration points needed by this add-on.

- `opensoho.patch` lets the add-on entry point read Supervisor options, initialize persistent storage and register the HA adapter.
- `pocketbase-ui.patch` makes API and asset URLs work below the dynamic Ingress prefix, initializes the UI from the HA session and adapts file downloads and settings changes to that session.

The Go adapter is kept separately in `opensoho/overlay/`. PocketBase's Go library is used through its public API. Upstream support for an exported OpenSOHO startup hook and a configurable PocketBase UI session adapter would allow these patches to shrink.

The **Upstream releases** workflow runs daily and on manual dispatch. It checks published semantic version releases of OpenSOHO and PocketBase, excluding drafts and prereleases. A newer stable release makes the check fail and adds release links to the run summary. Configure GitHub Actions notifications for this repository to receive alerts. Review the latest workflow run in the repository's Actions tab.

For an update, review the release notes, update the release tag and commit together in `opensoho/upstream.env`, and keep the PocketBase UI version aligned with OpenSOHO's `go.mod`. Rebase the patches, review endpoint and Ingress changes, run builds and tests, and test migrations on a copy of existing data. Bump `opensoho/config.yaml` and update the changelog when shipping a new add-on version.

Message Relay was inspected to compare session flows. Its inspected checkout contained no license file. The PocketBase HA App example was used to check the add-on layout and backup options. This repository is licensed under AGPL-3.0. [OpenSOHO](https://github.com/rubenbe/opensoho) · [Message Relay](https://github.com/nazt/wrw-msg/blob/main/pb_hooks/lib/halogin.js) · [PocketBase HA App](https://github.com/fabio-garavini/hassio-addons/tree/main/pocketbase)
