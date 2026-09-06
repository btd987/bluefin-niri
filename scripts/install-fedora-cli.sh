#!/usr/bin/env bash
# Build-time only: invoke with bash inside the disposable Fedora image build.
set -euo pipefail
umask 022

[[ $(uname -m) == x86_64 ]] || { printf 'Native CLI tools require x86_64\n' >&2; exit 1; }
[[ -f /run/.containerenv || -f /.dockerenv ]] || { printf 'Container required\n' >&2; exit 1; }

# Official releases and downloaded SHA256 audited on 2026-09-06. All three
# match non-null GitHub release asset digests at /repos/OWNER/REPO/releases/tags/TAG.
# Starship also matches starship-x86_64-unknown-linux-musl.tar.gz.sha256;
# Lazygit also matches checksums.txt. Yazi publishes no separate checksum asset.
starship_version=1.26.0
starship_sha256=b7c232b0e8249d8e55a40beb79c5c43a7d370f3f9408bd215deb0170daeaadf3
yazi_version=26.9.1
yazi_sha256=9b9c39decccf8cb0ff53a7d637d38f8a79d93bbd0099f4ea9c619ef6bb392f5d
lazygit_version=0.65.0
lazygit_sha256=44d8e7dd1484b4a66e191bd4ab25a71e8b4b3a65ab122f838e65677ef58c5506
# Lazygit has no musl-labelled asset: upstream .goreleaser.yml uses CGO_ENABLED=0.
# Install prerequisites: curl, CA certificates, coreutils, tar/gzip, unzip.
# Runtime: Yazi needs file(1), Lazygit needs git. No extra runtimes are installed.
# https://yazi-rs.github.io/docs/installation/ lists optional preview tools:
# ffmpeg (video), 7-Zip (archives), jq (JSON), poppler (PDF), resvg (SVG),
# ImageMagick (fonts/HEIC/JPEG XL). These are deliberately not installed here.
workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

curl --fail --location --proto '=https' --proto-redir '=https' \
    --output "$workdir/starship.tar.gz" \
    "https://github.com/starship/starship/releases/download/v${starship_version}/starship-x86_64-unknown-linux-musl.tar.gz"
printf '%s  %s\n' "$starship_sha256" "$workdir/starship.tar.gz" | sha256sum --check --strict -
curl --fail --location --proto '=https' --proto-redir '=https' \
    --output "$workdir/yazi.zip" \
    "https://github.com/sxyazi/yazi/releases/download/v${yazi_version}/yazi-x86_64-unknown-linux-musl.zip"
printf '%s  %s\n' "$yazi_sha256" "$workdir/yazi.zip" | sha256sum --check --strict -
curl --fail --location --proto '=https' --proto-redir '=https' \
    --output "$workdir/lazygit.tar.gz" \
    "https://github.com/jesseduffield/lazygit/releases/download/v${lazygit_version}/lazygit_${lazygit_version}_linux_x86_64.tar.gz"
printf '%s  %s\n' "$lazygit_sha256" "$workdir/lazygit.tar.gz" | sha256sum --check --strict -

# Verify ALL pins before extracting; select only the intended binaries.
tar --extract --gzip --no-same-owner --file "$workdir/starship.tar.gz" --directory "$workdir" starship
unzip -q "$workdir/yazi.zip" 'yazi-x86_64-unknown-linux-musl/yazi' \
    'yazi-x86_64-unknown-linux-musl/ya' -d "$workdir"
tar --extract --gzip --no-same-owner --file "$workdir/lazygit.tar.gz" --directory "$workdir" lazygit

install -Dm0755 "$workdir/starship" /usr/bin/starship
install -Dm0755 "$workdir/yazi-x86_64-unknown-linux-musl/yazi" /usr/bin/yazi
install -Dm0755 "$workdir/yazi-x86_64-unknown-linux-musl/ya" /usr/bin/ya
install -Dm0755 "$workdir/lazygit" /usr/bin/lazygit
