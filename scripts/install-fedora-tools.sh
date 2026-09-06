#!/usr/bin/env bash
# Image installation only; never configure a user's shell, keys, or services.
set -euo pipefail
export LC_ALL=C

[[ $# == 0 ]] || { printf 'No arguments expected\n' >&2; exit 1; }
[[ -f /run/.containerenv || -f /.dockerenv ]] || {
    printf 'Run in an image build or disposable container, not on the host\n' >&2
    exit 1
}

# First matching preset wins, including when RPM scriptlets apply presets.
# Leave explicit user enrollment possible; do not mask or disable existing users.
install -Dm644 /dev/stdin /usr/lib/systemd/user-preset/00-fedora-tools.preset <<'EOF'
disable syncthing.service
EOF
install -Dm644 /dev/stdin /usr/lib/systemd/system-preset/00-fedora-tools.preset <<'EOF'
disable syncthing@.service
EOF

# Verified in Fedora 44 fedora/updates. No COPR or external binary substitutes.
packages=(
    helix syncthing chezmoi git git-delta git-lfs gnupg2 openssh-clients
    pinentry pinentry-gnome3 fzf zoxide atuin direnv eza bat glow podman-compose jq
)
dnf5 -y --repo=fedora --repo=updates --setopt=install_weak_deps=False install "${packages[@]}"
rpm -q "${packages[@]}"

# Version-only probes: no shell hooks, agent startup, key generation, or git setup.
for cli in hx syncthing chezmoi git delta git-lfs gpg gpg-agent gpgconf \
           pinentry pinentry-gnome3 fzf zoxide atuin direnv eza bat podman-compose jq; do
    "$cli" --version
done
ssh -V
command -v ssh-agent ssh-keygen

# Glow initializes configuration even for --version; keep it out of user homes.
config=$(mktemp -d)
trap 'rm -rf "$config"' EXIT
XDG_CONFIG_HOME="$config" glow --version

# Offline global state only. Fail rather than rewrite existing user enrollment.
units=$(systemctl --root=/ --global list-unit-files --no-legend --no-pager syncthing.service)
[[ $units == 'syncthing.service disabled disabled' ]] || {
    printf 'Unexpected Syncthing user unit state: %s\n' "$units" >&2
    exit 1
}
