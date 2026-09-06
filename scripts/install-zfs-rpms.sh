#!/usr/bin/env bash
# Fresh, unpublished container only. Unsigned mode is local proof, not trust.
set -euo pipefail
export LC_ALL=C

fail() { printf 'ZFS runtime installation failed: %s\n' "$*" >&2; exit 1; }
[[ $# == 0 ]] || fail 'no arguments expected; use the runtime Containerfile'
[[ -f /run/.containerenv || -f /.dockerenv ]] || fail 'container required'
mode=${ZFS_RPM_TRUST_MODE:-unsigned-proof}
fingerprint=${ZFS_RPM_SIGNING_FINGERPRINT:-}
case "$mode" in
    unsigned-proof)
        [[ -z $fingerprint ]] || fail 'fingerprint requires verified mode'
        localpkg_gpgcheck=0 ;;
    verified)
        [[ $fingerprint =~ ^[A-F0-9]{40}$ ]] || fail 'expected full uppercase OpenPGP v4 signing fingerprint'
        localpkg_gpgcheck=1 ;;
    *) fail 'expected unsigned-proof or verified trust mode' ;;
esac
artifacts=/run/zfs-rpms
if [[ $mode == verified ]]; then
    [[ -s $artifacts/zfs-rpm-signing-key.asc ]] || fail 'RPM public key required'
    export GNUPGHOME
    GNUPGHOME=$(mktemp -d /tmp/zfs-rpm-trust.XXXXXX)
    trap 'gpgconf --kill all; rm -rf -- "$GNUPGHOME"' EXIT
    gpg --batch --no-tty --import "$artifacts/zfs-rpm-signing-key.asc"
    actual=$(gpg --batch --with-colons --list-keys | awk -F: '$1 == "pub" { primary=1; next } primary && $1 == "fpr" { print $10; primary=0 }')
    [[ $actual == "$fingerprint" ]] || fail 'RPM public fingerprint mismatch'
    mkdir "$GNUPGHOME/rpmdb"
    rpm --dbpath "$GNUPGHOME/rpmdb" --import "$artifacts/zfs-rpm-signing-key.asc"
fi
kernel=$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core)
[[ $kernel =~ ^[[:alnum:]_+]+([.][[:alnum:]_+]+)*-[[:alnum:]_+]+([.][[:alnum:]_+]+)+$ ]] || fail 'expected exactly one installed kernel-core'
[[ $(< "$artifacts/kernel-uname-r") == "$kernel" ]] || fail 'artifact kernel mismatch'
cert=$artifacts/zfs-signing-cert.der
serial=$(openssl x509 -inform DER -in "$cert" -noout -serial)
serial=${serial#serial=}
[[ $serial =~ ^([[:xdigit:]]{2}){2,}$ ]] || fail 'invalid certificate serial'
sig_key=$(printf '%s' "$serial" | sed 's/../&:/g; s/:$//')

names=(zfs libnvpair3 libuutil3 libzfs7 libzpool7 "kmod-zfs-$kernel")
declare -A selected=()
shopt -s nullglob
rpms=("$artifacts"/*.rpm)
[[ ${#rpms[@]} == 6 ]] || fail 'expected exactly six runtime RPMs'
for package in "${rpms[@]}"; do
    [[ ${package##*/} =~ ^[[:alnum:]_.+-]+[.]rpm$ ]] || fail 'invalid RPM filename'
    if [[ $mode == verified ]]; then
        # An isolated RPM DB excludes unrelated base-image keys. Digest-only OK
        # is not a signature, even when rpm --checksig exits successfully.
        check=$(rpm --dbpath "$GNUPGHOME/rpmdb" --checksig --verbose "$package") || fail 'RPM signature verification failed'
        grep -Eq '^[[:space:]]+.*[Ss]ignature.*: OK$' <<< "$check" || fail 'RPM has no trusted signature'
        ! grep -Eq 'NOT OK|NOKEY|NOTTRUSTED|BAD' <<< "$check" || fail 'untrusted RPM signature'
    fi
    name=$(rpm -qp --qf '%{NAME}' "$package")
    case "$name" in
        zfs|libnvpair3|libuutil3|libzfs7|libzpool7|"kmod-zfs-$kernel") ;;
        *) fail "unexpected runtime RPM: $name" ;;
    esac
    [[ ! ${selected[$name]+present} ]] || fail "duplicate runtime RPM: $name"
    [[ $(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' "$package") == "0:2.4.4-1.fc44.${kernel##*.}" ]] || fail "RPM version/architecture mismatch: $name"
    if [[ $name == "kmod-zfs-$kernel" ]]; then
        requires=$(rpm -qp --requires "$package")
        provides=$(rpm -qp --provides "$package")
        grep -Fxq "kernel-uname-r = $kernel" <<< "$requires" || fail 'missing exact kernel requirement'
        grep -Eq '^zfs-kmod = (0:)?2\.4\.4-1\.fc44$' <<< "$provides" || fail 'missing real zfs-kmod capability'
    fi
    selected[$name]=1
done
for name in "${names[@]}"; do
    [[ ${selected[$name]+present} ]] || fail "missing runtime RPM: $name"
done

# First matching preset wins. Do this BEFORE the RPM %post invokes presets.
# No masks: explicit future enrollment can enable selected units normally.
units=(zfs-import-cache.service zfs-import-scan.service zfs-import.service
       zfs-import.target zfs-load-key.service zfs-mount.service zfs-mount@.service
       zfs-share.service zfs-zed.service zfs-volume-wait.service zfs-volumes.target
       zfs.target zfs-scrub@.service zfs-scrub-monthly@.timer zfs-scrub-weekly@.timer
       zfs-trim@.service zfs-trim-monthly@.timer zfs-trim-weekly@.timer)
mkdir -p /usr/lib/systemd/system-preset
printf 'disable %s\n' "${units[@]}" > /usr/lib/systemd/system-preset/00-zfs-unpublished.preset
if [[ $mode == verified ]]; then
    rpm --import "$artifacts/zfs-rpm-signing-key.asc"
    gpgconf --kill all
    rm -rf -- "$GNUPGHOME"
    trap - EXIT
fi
# Fedora repository GPG policy is unchanged in either mode.
dnf5 -y --setopt=localpkg_gpgcheck="$localpkg_gpgcheck" --exclude='kernel*' install "${rpms[@]}"
[[ $(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core) == "$kernel" ]] || fail 'kernel changed during installation'
for name in "${names[@]}"; do
    [[ $(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' "$name") == "0:2.4.4-1.fc44.${kernel##*.}" ]] || fail "installed RPM mismatch: $name"
done
# Fail rather than hide a preset/scriptlet regression by disabling units later.
# Offline query only; never talk to a running systemd or start services.
unit_files=$(systemctl --root=/ list-unit-files --no-legend --no-pager 'zfs*')
[[ $unit_files =~ [^[:space:]] ]] || fail 'missing ZFS unit inventory'
while read -r unit state _; do
    case "$state" in
        enabled|enabled-runtime|linked|linked-runtime|alias) fail "enabled or linked ZFS unit remains: $unit" ;;
    esac
done <<< "$unit_files"
install -Dm644 "$cert" /usr/share/zfs/zfs-signing-cert.der
depmod -a "$kernel"
bash /tmp/zfs-runtime/validate-zfs.sh 2.4.4 "$sig_key"

# Only fresh-image transaction residue, never host or persistent storage data.
# RPMs are a read-only build mount and need no deletion.
dnf5 clean all
rm -rf /tmp/zfs-runtime
rm -rf /var/cache/libdnf5 /var/lib/dnf /var/lib/dnf5
rm -rf /run/dnf /run/selinux-policy
rm -f /var/log/dnf5.log* /var/log/dnf.rpm.log*
rm -f /var/cache/ldconfig/aux-cache
bootc container lint
