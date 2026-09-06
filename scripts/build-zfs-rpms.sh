#!/usr/bin/env bash
# Container-only proof builder. Source integrity and signature are checked in
# zfs-source. No keys are generated.
set -euo pipefail
export LC_ALL=C

fail() { printf 'ZFS RPM build failed: %s\n' "$*" >&2; exit 1; }

[[ $# == 0 ]] || fail 'no arguments expected; run using Containerfile.zfs'
[[ -f /run/.containerenv || -f /.dockerenv ]] || fail 'container required'
key=/run/secrets/zfs_signing_key
cert=/run/secrets/zfs_signing_cert
[[ -s $key && -r $key ]] || fail 'secret-mounted signing key required'
[[ -s $cert && -r $cert ]] || fail 'supplied public DER certificate required'
openssl x509 -inform DER -in "$cert" -noout >/dev/null
key_pub=$(openssl pkey -in "$key" -passin pass: -pubout -outform DER | sha256sum)
cert_pub=$(openssl x509 -inform DER -in "$cert" -pubkey -noout |
    openssl pkey -pubin -outform DER | sha256sum)
[[ $key_pub == "$cert_pub" ]] || fail 'signing key and certificate do not match'
sig_key=$(openssl x509 -inform DER -in "$cert" -noout -ext subjectKeyIdentifier |
    sed -n '2s/^[[:space:]]*//p')
[[ $sig_key =~ ^[[:xdigit:]]{2}(:[[:xdigit:]]{2})+$ ]] || fail 'certificate needs a subject key identifier'
# sign-file's CMS issuer-and-serial signer ID is exposed as modinfo sig_key.
serial=$(openssl x509 -inform DER -in "$cert" -noout -serial)
serial=${serial#serial=}
[[ $serial =~ ^([[:xdigit:]]{2})+$ ]] || fail 'invalid certificate serial'
sig_key=$(printf '%s' "$serial" | sed 's/../&:/g; s/:$//')

kernel=$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core) || fail 'cannot query kernel-core'
[[ $kernel =~ ^[[:alnum:]_+]+([.][[:alnum:]_+]+)*-[[:alnum:]_+]+([.][[:alnum:]_+]+)+$ ]] || fail 'expected exactly one installed kernel-core'
dnf5 -y install "kernel-devel-uname-r = $kernel"
[[ $(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core) == "$kernel" ]] || fail 'kernel changed during dependency installation'
[[ $(rpm -q --whatprovides kernel-devel-uname-r --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n') == "$kernel" ]] || fail 'exact kernel-devel required'
ksrc=/usr/src/kernels/$kernel
[[ -f $ksrc/Makefile && -x $ksrc/scripts/sign-file ]] || fail 'incomplete kernel-devel tree'

# kmodtool checks this symlink before /usr/src/kernels and otherwise emits a
# custom-kernel package WITHOUT kernel-uname-r Requires. Restore it on exit.
build_link=/lib/modules/$kernel/build
hidden_link=$build_link.zfs-proof
[[ ! -e $hidden_link && ! -L $hidden_link ]] || fail 'unexpected saved build link'
[[ ! -e $ksrc/certs/signing_key.pem && ! -L $ksrc/certs/signing_key.pem ]] || fail 'existing signing key path'
[[ ! -e $ksrc/certs/signing_key.x509 && ! -L $ksrc/certs/signing_key.x509 ]] || fail 'existing signing certificate path'
cleanup() {
    rm -f "$ksrc/certs/signing_key.pem" "$ksrc/certs/signing_key.x509"
    if [[ -L $hidden_link ]]; then mv "$hidden_link" "$build_link"; fi
}
trap cleanup EXIT
if [[ -L $build_link ]]; then
    mv "$build_link" "$hidden_link"
elif [[ -e $build_link ]]; then
    fail 'expected build path to be a symlink or absent'
fi
mkdir -p "$ksrc/certs"
# Upstream __modsign_install_post signs after stripping. Only symlink the key;
# it must never enter a source archive, RPM payload, or committed image layer.
ln -s "$key" "$ksrc/certs/signing_key.pem"
ln -s "$cert" "$ksrc/certs/signing_key.x509"
cd /build/zfs-2.4.4
./configure --with-config=all --with-spec=generic \
    --with-linux="$ksrc" --with-linux-obj="$ksrc"
# Disable kernel installation compression and RPM brp compression so the
# upstream post-strip hook sees .ko files. Ship signed, uncompressed modules.
# Stripped modules have no debug sources for RPM's automatic debug packages.
make rpm-utils rpm-kmod INSTALL_MOD_STRIP=1 \
    CONFIG_MODULE_COMPRESS_ALL= CONFIG_MODULE_COMPRESS_NONE=y CONFIG_MODULE_SIG_ALL= \
    RPM_DEFINE_COMMON='--define "__brp_kmod_compress %{nil}"' \
    RPM_DEFINE_KMOD="--define \"debug_package %{nil}\" --define \"_wrong_version_format_terminate_build 0\" --define \"kernels $kernel\" --define \"ksrc $ksrc\" --define \"kobj $ksrc\""

mkdir /out
declare -A selected=()
shopt -s nullglob
for package in ./*.rpm; do
    [[ $package != *.src.rpm ]] || continue
    name=$(rpm -qp --qf '%{NAME}' "$package")
    case "$name" in
        zfs|libnvpair3|libuutil3|libzfs7|libzpool7|"kmod-zfs-$kernel") ;;
        *) continue ;;
    esac
    [[ ! ${selected[$name]+present} ]] || fail "duplicate runtime RPM: $name"
    [[ $(rpm -qp --qf '%{VERSION}' "$package") == 2.4.4 ]] || fail 'RPM version mismatch'
    [[ $(rpm -qp --qf '%{ARCH}' "$package") == "${kernel##*.}" ]] || fail 'RPM architecture mismatch'
    if [[ $name == "kmod-zfs-$kernel" ]]; then
        requires=$(rpm -qp --requires "$package")
        provides=$(rpm -qp --provides "$package")
        grep -Fxq "kernel-uname-r = $kernel" <<< "$requires" || fail 'missing exact kernel requirement'
        grep -Eq '^zfs-kmod = (0:)?2\.4\.4-' <<< "$provides" || fail 'missing real zfs-kmod capability'
        mkdir /build/module-check
        (cd /build/module-check; rpm2cpio "/build/zfs-2.4.4/$package" | cpio -idm --quiet)
        modules=(/build/module-check/lib/modules/"$kernel"/extra/zfs/*.ko)
        [[ -f /build/module-check/lib/modules/$kernel/extra/zfs/zfs.ko &&
           -f /build/module-check/lib/modules/$kernel/extra/zfs/spl.ko ]] || fail 'missing module payload'
        for module in "${modules[@]}"; do
            [[ $(modinfo -F vermagic "$module") == "$kernel "* ]] || fail 'module kernel mismatch'
            [[ $(modinfo -F sig_key "$module") == "$sig_key" ]] || fail 'module signing key mismatch'
            [[ $(modinfo -F sig_hashalgo "$module") == sha256 ]] || fail 'missing SHA256 module signature'
        done
    fi
    selected[$name]=1
    cp "$package" /out/
done
for name in zfs libnvpair3 libuutil3 libzfs7 libzpool7 "kmod-zfs-$kernel"; do
    [[ ${selected[$name]+present} ]] || fail "missing runtime RPM: $name"
done
cp "$cert" /out/zfs-signing-cert.der
printf '%s\n' "$kernel" > /out/kernel-uname-r
printf '%s\n' 'Unpublished proof RPMs. Source SHA256 and maintainer signature checked in zfs-source.' \
    'Module signature metadata checked, not cryptographic authentication or Secure Boot acceptance. RPMs are not RPM-signed.' > /out/PROOF.txt
