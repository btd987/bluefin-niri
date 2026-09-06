#!/usr/bin/env bash
set -euo pipefail

# Tony Hutter, confirmed against the official OpenZFS maintainer list:
# https://openzfs.github.io/openzfs-docs/Project%20and%20Community/Signing%20Keys.html
readonly fingerprint=4F3BA9AB6D1F8D683DC2DFB56AD860EED4598027
readonly release=https://github.com/openzfs/zfs/releases/download/zfs-2.4.4
export GNUPGHOME
GNUPGHOME=$(mktemp -d)
trap 'rm -rf -- "$GNUPGHOME"' EXIT
chmod 700 "$GNUPGHOME"

curl --fail --location --proto '=https' --proto-redir '=https' \
    "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${fingerprint}" \
    --output "$GNUPGHOME/maintainer.asc"
curl --fail --location --proto '=https' --proto-redir '=https' \
    "$release/zfs-2.4.4.tar.gz.asc" --output "$GNUPGHOME/source.asc"

# Reject substituted keys and bundles containing any additional primary key.
actual=$(gpg --batch --no-options --with-colons --show-keys "$GNUPGHOME/maintainer.asc" |
    awk -F: '$1 == "pub" { primary = 1; next } primary && $1 == "fpr" { print $10; primary = 0 }')
if [[ "$actual" != "$fingerprint" ]]; then
    printf '%s\n' 'OpenZFS maintainer fingerprint mismatch' >&2
    exit 1
fi
gpg --batch --no-options --import "$GNUPGHOME/maintainer.asc"
gpg --batch --no-options --no-auto-key-retrieve \
    --verify "$GNUPGHOME/source.asc" zfs-2.4.4.tar.gz
