#!/usr/bin/env bash
# Build-time only: invoke with bash inside the disposable Fedora image build.
set -euo pipefail
umask 022

[[ $(uname -m) == x86_64 ]] || { printf 'Native editors require x86_64\n' >&2; exit 1; }
[[ -f /run/.containerenv || -f /.dockerenv ]] || { printf 'Container required\n' >&2; exit 1; }

# Official release metadata audited with gh api on 2026-09-06:
# https://api.github.com/repos/zed-industries/zed/releases/tags/v1.18.1
# Computed SHA256 matches the release asset's sha256 digest.
zed_version=1.18.1
zed_sha256=eea62268d8ec5fd3587df06fa76e072c104cca5e0b0b0abecbc28ae5b87c0bad
# https://api.github.com/repos/loft-sh/devpod/releases/tags/v0.6.15
# API digest is null: computed from the official HTTPS asset, NOT independently
# authenticated by an upstream checksum/signature. This pin detects later changes.
devpod_version=0.6.15
devpod_sha256=cc50bce09229d5a6d448ac1d4494327f4b8f7a20321e5fcee3bfec1aef0d20c5

# Fedora 44 disposable proof: ldd resolves the bundled Zed libraries plus direct
# system dependencies glibc, libgcc, glib2, alsa-lib. glib2 pulls in libmount,
# libblkid, libselinux, libffi, pcre2 and zlib-ng-compat. DevPod is static.
# The parent image must also provide its graphical runtime (Vulkan loader/driver,
# Wayland/X11, desktop portals and keyring); no compilers or SDKs are needed here.
workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

curl --fail --location --proto '=https' --proto-redir '=https' \
    --output "$workdir/zed.tar.gz" \
    "https://github.com/zed-industries/zed/releases/download/v${zed_version}/zed-linux-x86_64.tar.gz"
printf '%s  %s\n' "$zed_sha256" "$workdir/zed.tar.gz" | sha256sum --check --strict -
curl --fail --location --proto '=https' --proto-redir '=https' \
    --output "$workdir/devpod" \
    "https://github.com/loft-sh/devpod/releases/download/v${devpod_version}/devpod-linux-amd64"
printf '%s  %s\n' "$devpod_sha256" "$workdir/devpod" | sha256sum --check --strict -

# Keep the inspected bundle layout: bin/zed locates ../libexec/zed-editor,
# whose library search path includes ../lib. Extract only after BOTH pins pass.
tar --extract --gzip --no-same-owner --file "$workdir/zed.tar.gz" --directory "$workdir" zed.app

# No supported /etc/zed/settings.json in v1.18.1 (crates/paths/src/paths.rs).
# Official packaging guidance instead supports this runtime environment variable:
# https://zed.dev/docs/development/linux#notes-for-packaging-zed
# It disables automatic AND manual self-update, explaining image-managed updates.
# Use the wrapper for CLI and desktop launches; never seed/modify user homes.
printf '%s\n' '#!/bin/sh' \
    'export ZED_UPDATE_EXPLANATION="Zed is image-managed. Update the operating system image to update Zed."' \
    'exec /usr/lib/zed/bin/zed "$@"' > "$workdir/zeditor"
sed -e 's|^Exec=zed|Exec=/usr/bin/zeditor|' \
    -e 's|^TryExec=zed$|TryExec=/usr/bin/zeditor|' \
    -e 's|^Icon=zed$|Icon=/usr/share/icons/hicolor/512x512/apps/zed.png|' \
    "$workdir/zed.app/share/applications/dev.zed.Zed.desktop" > "$workdir/dev.zed.Zed.desktop"

install -dm0755 /usr/lib/zed
cp -R "$workdir/zed.app/." /usr/lib/zed/
# /sbin/zed resolves to /usr/bin/zed on merged Fedora; it belongs to ZFS.
install -Dm0755 "$workdir/zeditor" /usr/bin/zeditor
install -Dm0644 "$workdir/dev.zed.Zed.desktop" /usr/share/applications/dev.zed.Zed.desktop
for size in 512 1024; do
    install -Dm0644 "$workdir/zed.app/share/icons/hicolor/${size}x${size}/apps/zed.png" \
        "/usr/share/icons/hicolor/${size}x${size}/apps/zed.png"
done
# CLI only. Do not run setup, trust, provider registration, or self-update.
install -Dm0755 "$workdir/devpod" /usr/bin/devpod
