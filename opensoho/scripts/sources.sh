#!/bin/sh
set -eu

if [ -f /run/secrets/build_ca ]; then
    export GIT_SSL_CAINFO=/run/secrets/build_ca
    export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca
fi

checkout() {
    if [ ! -d "$3/.git" ]; then
        git init -q "$3"
    fi
    if ! git -C "$3" cat-file -e "$2^{commit}" 2>/dev/null; then
        git -C "$3" fetch --no-tags --depth 1 "$1" "$2"
    fi
    git -C "$3" checkout --detach --force "$2"
    test "$(git -C "$3" rev-parse HEAD)" = "$2"
}

addon_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
target=${2:?supply an absolute build directory}
case "$target" in /*) ;; *) exit 2 ;; esac
case "${1:?supply ui or go}" in
    ui)
        checkout https://github.com/pocketbase/pocketbase.git 6f370ea741f33adf889eef02e3c1b884a47aa522 "$target/pocketbase"
        git -C "$target/pocketbase" apply "$addon_dir/patches/pocketbase-ui.patch"
        cd "$target/pocketbase/ui"
        npm ci --no-audit --no-fund
        npm exec --offline -- vite build
        ;;
    go)
        checkout https://github.com/rubenbe/opensoho.git 6349f37abcc43bc7f5d68db581fd4c1e328aaf2f "$target/opensoho"
        git -C "$target/opensoho" apply "$addon_dir/patches/opensoho.patch"
        cp "$addon_dir"/overlay/*.go "$target/opensoho/"
        rm -rf "$target/opensoho/ha_ui"
        mkdir -p "$target/opensoho/ha_ui"
        cp -R "$target/pocketbase/ui/dist/." "$target/opensoho/ha_ui/"
        ;;
    *) exit 2 ;;
esac
