FROM --platform=$BUILDPLATFORM node:24.22.1-bookworm-slim@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c AS ui
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY scripts/sources.sh scripts/sources.sh
COPY upstream.env upstream.env
COPY patches/pocketbase-ui.patch patches/pocketbase-ui.patch
RUN --mount=type=cache,target=/root/.npm --mount=type=secret,id=build_ca \
    sh scripts/sources.sh ui /build

FROM --platform=$BUILDPLATFORM golang:1.27.4-bookworm@sha256:4fa7c968ba93f1635670522dbb01a2c78150443e1385746924566079f36570ea AS build
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src
COPY scripts/sources.sh scripts/sources.sh
COPY upstream.env upstream.env
COPY patches/opensoho.patch patches/opensoho.patch
COPY overlay/ overlay/
COPY --from=ui /build/pocketbase/ui/dist/ /build/pocketbase/ui/dist/
RUN --mount=type=secret,id=build_ca sh scripts/sources.sh go /build
WORKDIR /build/opensoho
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    go mod download && go mod verify

FROM build AS test
COPY --from=ui /usr/local/bin/node /usr/local/bin/node
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go vet -mod=readonly ./... && CGO_ENABLED=0 go test -mod=readonly ./... \
    && node --test ui/tests/*.test.mjs

FROM build AS binary
ARG TARGETOS
ARG TARGETARCH
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" go build -mod=readonly -trimpath -buildvcs=false \
    -ldflags="-s -w" -o /opensoho .

FROM scratch
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=build /usr/local/go/lib/time/zoneinfo.zip /zoneinfo.zip
COPY --from=binary /opensoho /opensoho
ENV ZONEINFO=/zoneinfo.zip
EXPOSE 8090/tcp 8091/tcp
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opensoho"]
