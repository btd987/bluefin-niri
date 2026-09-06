#!/usr/bin/bash
set -euo pipefail

readonly version=0.9.0
readonly source_sha256=82478b606e560f82f59c8f580da0a9eb88448c08b69996cba55029aa03cabfbe
readonly source_url="https://static.crates.io/crates/nirius/nirius-${version}.crate"
readonly archive="nirius-${version}.crate"

curl --fail --location --proto '=https' --proto-redir '=https' \
    "$source_url" --output "$archive"
printf '%s  %s\n' "$source_sha256" "$archive" | sha256sum --check --strict
tar -xzf "$archive"
cd "nirius-${version}"
if [[ ! -s Cargo.lock ]]; then
    printf '%s\n' 'The verified crate must contain a nonempty Cargo.lock' >&2
    exit 1
fi
cargo build --locked --release --bin nirius --bin niriusd
install -Dm755 target/release/nirius /out/nirius
install -Dm755 target/release/niriusd /out/niriusd

# Record actual linkage, not an assumed list of runtime packages. No stripping.
{
    printf 'name=nirius\nversion=%s\nsource_url=%s\nsource_sha256=%s\n' \
        "$version" "$source_url" "$source_sha256"
    printf '%s\n' 'builder_base=quay.io/fedora/fedora-bootc:44@sha256:cc0e99fb83e3cf2bd34b073535cfa656dc817dfd29911a1c47546bb013e1c845'
    printf 'architecture=%s\n' "$(uname -m)"
    rustc --version
    cargo --version
    printf '%s\n' 'build_command=cargo build --locked --release --bin nirius --bin niriusd'
    sha256sum Cargo.lock
    printf '%s\n' '[runtime-linkage]'
    ldd /out/nirius /out/niriusd
    rpm -q glibc libgcc
    printf '%s\n' '[artifact-sha256]'
    (cd /out && sha256sum nirius niriusd)
} > /out/provenance.txt
