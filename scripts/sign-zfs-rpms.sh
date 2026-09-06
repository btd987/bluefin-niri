#!/usr/bin/env bash
# Container-only artifact signing. Private key material lives only on tmpfs.
set -euo pipefail
export LC_ALL=C
fail() { printf 'ZFS RPM signing failed: %s\n' "$*" >&2; exit 1; }
[[ $# == 0 ]] || fail 'no arguments expected'
[[ -f /run/.containerenv || -f /.dockerenv ]] || fail 'container required'
fingerprint=${ZFS_RPM_SIGNING_FINGERPRINT:-}
[[ $fingerprint =~ ^[A-F0-9]{40}$ ]] || fail 'expected full uppercase OpenPGP v4 signing fingerprint'
[[ -s /run/secrets/zfs_rpm_signing_key ]] || fail 'RPM signing key required'
[[ $(stat -f -c %T /run/zfs-signing) == tmpfs ]] || fail 'signing workspace must be tmpfs'
umask 077
export GNUPGHOME
GNUPGHOME=$(mktemp -d /run/zfs-signing/gnupg.XXXXXX)
trap 'gpgconf --kill all; rm -rf -- "$GNUPGHOME"' EXIT
gpg --batch --no-tty --import /run/secrets/zfs_rpm_signing_key
actual=$(gpg --batch --with-colons --list-secret-keys | awk -F: '$1 == "sec" { primary=1; next } primary && $1 == "fpr" { print $10; primary=0 }')
[[ $actual == "$fingerprint" ]] || fail 'private signing fingerprint mismatch'
artifacts=/run/zfs-rpms
kernel=$(< "$artifacts/kernel-uname-r")
[[ $kernel =~ ^[[:alnum:]_+]+([.][[:alnum:]_+]+)*-[[:alnum:]_+]+([.][[:alnum:]_+]+)+$ ]] || fail 'invalid artifact kernel'
shopt -s nullglob
rpms=("$artifacts"/*.rpm)
[[ ${#rpms[@]} == 6 ]] || fail 'expected exactly six runtime RPMs'
declare -A selected=()
for package in "${rpms[@]}"; do
    [[ ${package##*/} =~ ^[[:alnum:]_.+-]+[.]rpm$ ]] || fail 'invalid RPM filename'
    name=$(rpm -qp --qf '%{NAME}' "$package")
    case "$name" in
        zfs|libnvpair3|libuutil3|libzfs7|libzpool7|"kmod-zfs-$kernel") ;;
        *) fail "unexpected runtime RPM: $name" ;;
    esac
    [[ ! ${selected[$name]+present} ]] || fail "duplicate runtime RPM: $name"
    [[ $(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' "$package") == "0:2.4.4-1.fc44.${kernel##*.}" ]] || fail "RPM version/architecture mismatch: $name"
    selected[$name]=1
done
# Do not let artifact symlinks copy anything from the secret mount into output.
for file in "${rpms[@]}" "$artifacts/kernel-uname-r" "$artifacts/zfs-signing-cert.der"; do
    [[ -f $file && ! -L $file ]] || fail 'artifact must be a regular non-symlink file'
done
mkdir /out
cp -- "${rpms[@]}" "$artifacts/kernel-uname-r" "$artifacts/zfs-signing-cert.der" /out/
gpg --batch --armor --export "$fingerprint" > /out/zfs-rpm-signing-key.asc
# Force this exact primary signing key, with no passphrase prompts or host agent.
rpmsign --define '_openpgp_sign gpg' \
    --define "_openpgp_sign_id $fingerprint!" \
    --define '_gpg_sign_cmd_extra_args --batch --no-tty --pinentry-mode loopback --passphrase ""' \
    --resign /out/*.rpm
mkdir "$GNUPGHOME/rpmdb"
rpm --dbpath "$GNUPGHOME/rpmdb" --import /out/zfs-rpm-signing-key.asc
for package in /out/*.rpm; do
    check=$(rpm --dbpath "$GNUPGHOME/rpmdb" --checksig --verbose "$package") || fail 'RPM signature verification failed'
    grep -Eq '^[[:space:]]+.*[Ss]ignature.*: OK$' <<< "$check" || fail 'RPM has no trusted signature'
    ! grep -Eq 'NOT OK|NOKEY|NOTTRUSTED|BAD' <<< "$check" || fail 'untrusted RPM signature'
done
chmod 644 /out/*
