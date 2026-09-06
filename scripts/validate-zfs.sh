#!/usr/bin/env bash
# Build-time metadata validation only; does not prove cryptographic signature
# validity, signing-key trust, or bootability. Run bootc lint separately.
# Usage: bash scripts/validate-zfs.sh MAJOR.MINOR.PATCH AA:BB:...
# The key ID must match modinfo sig_key exactly (including case).
set -euo pipefail
export LC_ALL=C

fail() {
    printf 'ZFS validation failed: %s\n' "$*" >&2
    exit 1
}

[[ $# == 2 ]] || fail 'expected ZFS version and signing key ID arguments'
version=$1
key=$2
[[ $version =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || fail 'invalid ZFS version (expected MAJOR.MINOR.PATCH)'
[[ $key =~ ^[[:xdigit:]]{2}(:[[:xdigit:]]{2})+$ ]] || fail 'invalid signing key ID (expected colon-separated hex bytes)'

kernel=$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core) || fail 'cannot query installed kernel-core'
# A single safe token also rejects zero/multiple kernels and path traversal.
[[ $kernel =~ ^[[:alnum:]_+]+([.][[:alnum:]_+]+)*-[[:alnum:]_+]+([.][[:alnum:]_+]+)+$ ]] || fail 'expected exactly one installed kernel-core VERSION-RELEASE.ARCH'
userspace=$(rpm -q --qf '%{VERSION}\n' zfs) || fail 'cannot query installed zfs userspace'
[[ $userspace == "$version" ]] || fail 'zfs userspace version mismatch'
packages=$(rpm -qa --qf '%{NAME}\n') || fail 'cannot query installed package names'
[[ -n $packages ]] || fail 'empty installed package list'
while IFS= read -r package; do
    case "$package" in
        dkms|zfs-dkms|akmod-zfs) fail "forbidden runtime package: $package" ;;
    esac
done <<< "$packages"

for module in spl zfs; do
    for field in version vermagic filename signer sig_key sig_hashalgo; do
        value=$(modinfo -k "$kernel" -F "$field" "$module") || fail "$module: cannot read $field"
        [[ $value =~ [^[:space:]] && $value != *$'\n'* ]] || fail "$module: empty or multiline $field"
        case "$field" in
            version)
                [[ $value == "$version" || $value == "$version-"* ]] || fail "$module: version mismatch"
                ;;
            vermagic)
                read -r token _ <<< "$value"
                [[ $token == "$kernel" ]] || fail "$module: vermagic mismatch"
                ;;
            filename)
                case "$value" in
                    /lib/modules/"$kernel"/*) relative=${value#"/lib/modules/$kernel/"} ;;
                    /usr/lib/modules/"$kernel"/*) relative=${value#"/usr/lib/modules/$kernel/"} ;;
                    *) fail "$module: module path outside target kernel tree" ;;
                esac
                [[ $relative =~ ^[[:alnum:]_+-]+([.][[:alnum:]_+-]+)*(/[[:alnum:]_+-]+([.][[:alnum:]_+-]+)*)*$ ]] || fail "$module: invalid module path"
                ;;
            sig_key) [[ $value == "$key" ]] || fail "$module: signing key mismatch" ;;
            sig_hashalgo) [[ $value == sha256 ]] || fail "$module: signature hash must be sha256" ;;
        esac
    done
done

dependencies=$(modprobe --set-version "$kernel" --show-depends zfs) || fail 'cannot resolve zfs module dependencies'
[[ $dependencies =~ [^[:space:]] ]] || fail 'empty zfs dependency resolution'
printf 'ZFS %s metadata validated for %s (not a signature or bootability proof)\n' "$version" "$kernel"
