# Working on hass-open-soho

## Project layout

This repository packages OpenSOHO as a Home Assistant OS add-on with administrator access through Supervisor Ingress.

- `opensoho/config.yaml` defines add-on options, ports and supported architectures.
- `opensoho/Dockerfile` builds the PocketBase UI and the OpenSOHO Go binary.
- `opensoho/upstream.env` pins upstream stable releases and their immutable commits.
- `opensoho/scripts/sources.sh` fetches sources and applies local patches.
- `opensoho/overlay/` contains the HA entry point, authorization gateway and Go tests.
- `opensoho/patches/` contains source changes applied to the pinned upstream releases.
- `tests/smoke.py` exercises the real image with a mock Supervisor and optional Chromium.
- `tests/HA-OS-E2E.md` covers validation requiring a real Supervisor and physical devices.

Use the existing checkout in isolated cloud tasks. Create a worktree only when explicitly requested. Treat `opensoho/.build/` as generated build output. Make durable changes in the overlay, patches or source preparation scripts.

## Security and compatibility

Authorize panel requests using the trusted Supervisor TCP peer and the administrator group supplied by Ingress. Keep the panel and administrative API on internal port 8091. The LAN listener on port 8090 accepts the specific OpenWISP methods and paths in the gateway.

Keep HA session validation on the backend. Browser state must carry no PocketBase administrative token. Keep secrets, device keys, configuration contents and Ingress tokens out of logs.

Preserve agent authentication, persistent data under `/data/opensoho/`, cold Supervisor backups and graceful SIGTERM handling. Check compatibility on both `amd64` and `aarch64`. Review changes to these boundaries with the authorization and image smoke tests.

## Dependencies and patches

Use published stable upstream releases. Record the release tag and its resolved commit together in `opensoho/upstream.env`. Match the PocketBase UI version to the PocketBase module required by the selected OpenSOHO release.

Keep HA integration patches focused on required entry points and session behavior. Leave upstream cleanup to upstream maintainers. The add-on entry point suppresses raw upstream stdout to prevent generated configuration from leaking through diagnostic prints. Prefer public upstream APIs and keep adapter code in the overlay. Apply each patch against the pinned source and build from those sources when validating an update.

## Validation

Run commands from the repository root. Docker Buildx is required for image checks.

```sh
docker buildx build --check opensoho
docker buildx build --target test opensoho
docker buildx build --platform linux/amd64 --load -t hass-open-soho:local opensoho
docker buildx build --platform linux/arm64 --load -t hass-open-soho:arm64 opensoho
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/smoke.py --http-only
```

The test build target runs module verification, Go vet, Go tests and the upstream JavaScript tests. For browser coverage, install `playwright==1.62.0` and Chromium, then run `python3 tests/smoke.py`. Set `CHROMIUM_BIN` to use an installed browser. The smoke test manages its own containers, network and volume.

For builds behind a managed TLS proxy, pass a trusted CA bundle using `--secret id=build_ca,src=/path/to/bundle.pem`. Keep TLS and module verification enabled.

Choose validation appropriate to the change. For documentation-only edits, check wording, links and commands. Report real HA OS checks as unrun until executed on that platform. The mock Supervisor verifies the adapter's behavior under supplied identities.

## Documentation

Write project documentation and code comments in English. Keep installation, security limitations, backup instructions and release maintenance guidance in sync with the implementation. The add-on help is in `opensoho/DOCS.md`; the full guide is in `README.md`.
