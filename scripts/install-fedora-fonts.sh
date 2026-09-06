#!/usr/bin/env bash
# Build-time only: invoke with bash inside the disposable Fedora image build.
set -euo pipefail
umask 022

[[ -f /run/.containerenv || -f /.dockerenv ]] || { printf 'Container required\n' >&2; exit 1; }

# Official releases/latest API audited 2026-09-06: v3.5.1, not draft/prerelease.
# https://api.github.com/repos/ryanoasis/nerd-fonts/releases/tags/v3.5.1
# Asset digest also matches releases/download/v3.5.1/SHA-256.txt.
version=3.5.1
sha256=3b94ea1dc3955756762f977b7677bca671947dd56bc755a6f8465a8e83b5f257
workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

curl --fail --location --proto '=https' --proto-redir '=https' \
    --output "$workdir/Iosevka.tar.xz" \
    "https://github.com/ryanoasis/nerd-fonts/releases/download/v${version}/Iosevka.tar.xz"
printf '%s  %s\n' "$sha256" "$workdir/Iosevka.tar.xz" | sha256sum --check --strict -

# Kitty requests this family, not the distinct Nerd Font Mono or Propo families.
fonts=(IosevkaNerdFont-{Regular,Bold,Italic,BoldItalic}.ttf)
tar --extract --xz --no-same-owner --file "$workdir/Iosevka.tar.xz" \
    --directory "$workdir" "${fonts[@]}" LICENSE.md
[[ -s "$workdir/LICENSE.md" ]] || { printf 'Missing font license\n' >&2; exit 1; }
for font in "${fonts[@]}"; do
    [[ $(fc-scan --format '%{family[0]}' "$workdir/$font") == 'Iosevka Nerd Font' ]] || {
        printf 'Unexpected font family: %s\n' "$font" >&2; exit 1;
    }
done

for font in "${fonts[@]}"; do
    install -Dm0644 "$workdir/$font" "/usr/share/fonts/niri-iosevka/$font"
done
install -Dm0644 "$workdir/LICENSE.md" /usr/share/licenses/niri-iosevka/LICENSE.md
# System-only cache: never populate the build user's home cache.
fc-cache --system-only --force /usr/share/fonts/niri-iosevka
