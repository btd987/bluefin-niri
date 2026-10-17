#!/usr/bin/env bash
# Run from the repository root; all dependencies are built on this machine.
set -euo pipefail

DIGEST=$(skopeo inspect docker://quay.io/fedora/fedora-bootc:44 | jq -er '
  .Digest | select(type == "string") |
  select(test("^sha256:[0-9a-f]{64}$") and length == 71)')
FEDORA_BASE="quay.io/fedora/fedora-bootc:44@${DIGEST}"
podman build -f Containerfile.zfs --target zfs-rpms \
    --build-arg FEDORA_BASE="$FEDORA_BASE" \
    --build-arg ZFS_BUILD_MODE=unsigned-testing \
    -t localhost/zfs-rpms:testing .
podman build --no-cache -f Containerfile.zfs-runtime \
    --build-arg FEDORA_BASE="$FEDORA_BASE" \
    --build-arg ZFS_RPM_IMAGE=localhost/zfs-rpms:testing \
    --build-arg ZFS_RPM_TRUST_MODE=unsigned-testing \
    -t localhost/zfs-runtime:testing .
podman build -f Containerfile.nirius \
    --build-arg FEDORA_BASE="$FEDORA_BASE" \
    -t localhost/nirius-artifact:testing .
podman build -f Containerfile.fedora \
    --build-arg BASE_IMAGE=localhost/zfs-runtime:testing \
    --build-arg NIRIUS_IMAGE=localhost/nirius-artifact:testing \
    --build-arg ZFS_BUILD_MODE=unsigned-testing \
    -t localhost/fedora-niri:testing .
printf '%s\n' \
    "Fedora base used: ${FEDORA_BASE}" \
    'Fedora testing assembly and container checks completed on this machine.' \
    'Unsigned RPMs and ZFS modules: hardware testing requires Secure Boot disabled.' \
    'Boot, storage, and update/rollback acceptance are not established by this build.' \
    >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
