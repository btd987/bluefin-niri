#!/usr/bin/env bash
# Fedora image installation only. Enrollment is a separate, explicit operation.
set -euo pipefail
export LC_ALL=C
[[ $# == 0 && $EUID == 0 ]] || { printf 'Root and no arguments required\n' >&2; exit 1; }
[[ -f /run/.containerenv || -f /.dockerenv ]] || { printf 'Container required\n' >&2; exit 1; }
. /etc/os-release
[[ $ID == fedora ]] || { printf 'Fedora required\n' >&2; exit 1; }
packages=(perl-interpreter perl-Config-IniFiles perl-Capture-Tiny perl-Data-Dumper
    perl-File-Path perl-File-Copy perl-Getopt-Long perl-Pod-Usage perl-Time-Local
    perl-Sys-Hostname openssh-clients pv gzip lzop mbuffer python3 util-linux
    curl ca-certificates tar procps-ng)
dnf5 -y --repo=fedora --repo=updates --setopt=install_weak_deps=False install "${packages[@]}"
rpm -q "${packages[@]}"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
    https://codeload.github.com/jimsalterjrs/sanoid/tar.gz/refs/tags/v2.3.0 -o "$work/source.tar.gz"
printf '%s  %s\n' 1d8735a271a34ec87ea46313a66f6f20bd38b583886924574d3c1f72ea173620 "$work/source.tar.gz" | sha256sum -c -
tar --extract --gzip --file="$work/source.tar.gz" --directory="$work" --no-same-owner
for executable in sanoid syncoid; do
    install -Dm755 "$work/sanoid-2.3.0/$executable" "/usr/sbin/$executable"
    perl -c "/usr/sbin/$executable"
done
install -Dm644 "$work/sanoid-2.3.0/sanoid.defaults.conf" /usr/share/sanoid/sanoid.defaults.conf
install -Dm644 "$work/sanoid-2.3.0/LICENSE" /usr/share/licenses/sanoid/LICENSE
# No /etc policy, pools, imports, service activation, or user/SSH configuration.
