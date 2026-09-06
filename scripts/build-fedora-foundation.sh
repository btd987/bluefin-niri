#!/usr/bin/env bash
set -euo pipefail

test -f /run/.containerenv || test -f /.dockerenv
kernel=$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core)
[[ $kernel =~ ^[[:alnum:]_+]+([.][[:alnum:]_+]+)*-[[:alnum:]_+]+([.][[:alnum:]_+]+)+$ ]]
case "$ZFS_BUILD_MODE" in
    unsigned-testing)
        test ! -e /usr/share/zfs/zfs-signing-cert.der
        test ! -L /usr/share/zfs/zfs-signing-cert.der
        key=--unsigned-testing
        ;;
    signed)
        serial=$(openssl x509 -inform DER -in /usr/share/zfs/zfs-signing-cert.der -noout -serial)
        [[ $serial =~ ^serial=([[:xdigit:]]{2})+$ ]]
        key=$(printf '%s' "${serial#serial=}" | sed 's/../&:/g; s/:$//')
        ;;
    *) printf 'Invalid ZFS_BUILD_MODE: %s\n' "$ZFS_BUILD_MODE" >&2; exit 1 ;;
esac
VARIANT=fedora-niri bash /tmp/build.sh
test "$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core)" = "$kernel"
depmod -a "$kernel"
bash /tmp/validate-zfs.sh 2.4.4 "$key"
dnf5 clean all
rm -rf /tmp/build.sh /tmp/system_files /tmp/fedora_files /tmp/validate-zfs.sh \
    /var/cache/libdnf5 /var/lib/dnf /var/lib/dnf5 /run/dnf /run/selinux-policy \
    /run/gluster /run/openvpn-client /run/openvpn-server \
    /var/cache/swcatalog /var/cache/ibus
rm -f /var/log/dnf* /var/cache/ldconfig/aux-cache
bootc container lint
