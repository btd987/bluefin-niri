# Bluefin Niri

Fedora Atomic desktops with [Niri](https://github.com/YaLTeR/niri) and native [Noctalia v5](https://github.com/noctalia-dev/noctalia). See the [Noctalia documentation](https://docs.noctalia.dev/noctalia/).

## Images

All images use the public namespace `ghcr.io/btd987`.

| Image | Base | Channels |
| --- | --- | --- |
| `bluefin-niri` | [Bluefin DX](https://projectbluefin.io/), AMD/Intel | `stable`, `stable-daily` |
| `bazzite-niri` | [Bazzite](https://bazzite.gg/), AMD/Intel | `stable`, `stable-daily` |
| `bazzite-niri-nvidia` | Bazzite NVIDIA | `stable`, `stable-daily` |
| `fedora-niri` | Pinned Fedora 44 bootc, AMD/Intel, ZFS | `testing`, `testing-YYYYMMDD` |

Bluefin/Bazzite retain weekly Tuesday `stable`, daily `stable-daily`, dated tags and existing retention. Bluefin follows the matching upstream channel; Bazzite uses upstream `stable`, or `latest` for `stable-daily`. `bluefin-niri-nvidia` and `fedora-44-niri` are retired, their packages deleted, and excluded from builds, publication and cleanup.

**Fedora is unsigned testing only, with Secure Boot disabled, not production-ready.** The published testing image lacks Intel Wi-Fi firmware. The hardware-expanded source has built locally with package integrity and exact-kernel ZFS checks passing, but is not published; hardware retesting remains pending. Package presence does not prove Wi-Fi recovery or working audio, cameras, readers, modems, GPU decoding or suspend/resume. Lint retains extlinux and `/var` tmpfiles warnings; do not delete files blindly to silence them.

## Installation

Back up data and configuration first; keep a known-working deployment and recovery media. From a compatible Fedora Atomic installation, choose **one** rebase, then reboot. For a fresh installation, install a compatible Fedora Atomic system first.

```bash
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bluefin-niri:stable
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bazzite-niri:stable
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bazzite-niri-nvidia:stable
systemctl reboot
```

For Fedora testing, opt in from a compatible bootc installation **only with Secure Boot disabled**:

```bash
sudo bootc switch ghcr.io/btd987/fedora-niri:testing
sudo systemctl reboot
```

Switching images does not migrate user configurations or storage. OS rollback does not undo persistent data or pool-feature changes. Select Niri in the login screen's session menu; each image retains its existing display manager.

## Desktop and Migration

Images include native `noctalia` (not `noctalia-shell` or Quickshell), xwayland-satellite, Kitty, kanshi, gamescope, khal and shared custom recipes. Defaults live in `/etc/niri/config.kdl`; existing user configs are never replaced automatically.

1. Back up `${XDG_CONFIG_HOME:-$HOME/.config}/niri`, any custom `NIRI_CONFIG`, and all external included files before editing. Preserve rules, outputs, inputs, shortcuts and appearance; do not replace entire configs or apply unrelated dotfiles.
2. Preferably before updating, keep a terminal open and run `systemctl --user disable --now dms.service`. If the unit is already removed, inspect user units and autostart entries for obsolete DMS activation; preserve its settings for rollback.
3. Compare the active config with `/etc/niri/config.kdl` and make targeted edits. Remove obsolete DMS and `qs`/`quickshell -c noctalia-shell` startup references, including includes/scripts. Retain legacy settings for reference; v5 does not migrate v4 settings.
4. Keep exactly one `spawn-at-startup "noctalia"` in the active Niri config, with no competing user service or desktop autostart. Merge these native bindings into the existing `binds` block, replacing conflicts rather than duplicating them:

```kdl
Mod+Space { spawn "noctalia" "msg" "panel-toggle" "launcher"; }
Mod+S { spawn "noctalia" "msg" "panel-toggle" "control-center"; }
Mod+Comma { spawn "noctalia" "msg" "settings-toggle"; }
Mod+Alt+L { spawn "noctalia" "msg" "session" "lock"; }
XF86AudioRaiseVolume { spawn "noctalia" "msg" "volume-up"; }
XF86AudioLowerVolume { spawn "noctalia" "msg" "volume-down"; }
XF86AudioMute { spawn "noctalia" "msg" "volume-mute"; }
XF86MonBrightnessUp { spawn "noctalia" "msg" "brightness-up"; }
XF86MonBrightnessDown { spawn "noctalia" "msg" "brightness-down"; }
```

5. Run `niri validate` (use `--config` for a custom path), then log out and back in; reload alone does not rerun startup commands. Check `rpm -q noctalia`, `noctalia msg status`, and test panels, lock/password unlock, audio and brightness.

Fedora keeps Thinkfan inactive until appropriate setup; existing Bluefin/Bazzite fan defaults remain. Keep firmware-managed fans and stock thermald platform/Intel checks. Camera, modem and reader support depends on actual device IDs. No automatic fingerprint/PAM enrollment, token/key changes, FCC unlocking or fan tuning is provided. Preserve password/recovery access before optional authentication changes; fingerprint login does not unlock a password-encrypted keyring. Do not overwrite custom PAM settings or reset tokens to diagnose hardware.

## Optional Commands

Discover the installed inventory instead of assuming commands from another image:

```bash
just --justfile /usr/share/niri-system/justfile --list
just --justfile /usr/share/niri-system/justfile storage-status
```

Use an explicit justfile to preserve project-local `just`; existing custom `ujust` entry points and upstream behavior remain on Bluefin/Bazzite. Setup is interactive and opt-in, never automatic during builds. Inspect helper help and confirmation prompts before enrollment.

- Backup: `setup-backup home`, `setup-backup --reuse home`, and `backup-status home` use named jobs. Enrollment validates an existing mount/SSH repository or explicitly initializes an encrypted repository, writes root-private config/passphrase under `/etc/niri-backup/NAME`, and asks before timer activation or initial backup. Provision root SSH keys and verified host trust separately. Existing enrollments and legacy `home-borgmatic` jobs are not replaced; inspect schedules to avoid overlap.
- Storage boundaries: inventory and backup enrollment never format disks, create RAID/LUKS/pools, change mounts or import pools. Keep independent offline/remote backups and a separate Borg key/passphrase copy. Test restore into an empty directory, including permissions/SELinux labels. Live backups and snapshots are crash-consistent, not coordinated database/VM backups; quiesce applications separately. A green timer is not restore proof.
- Snapper: `setup-snapshots` and `enable-snapshot-timers` require `sudo just`; review all eligible configs and retention before activation. Persistent timers may run immediately and cleanup deletes snapshots. Schedule changes and activation are separate choices; stop future automation with `sudo systemctl disable --now snapper-timeline.timer snapper-cleanup.timer`.
- RAID: `setup-raid-maintenance` enrolls checks for one existing md array, not provisioning or repair. Checks affect performance and kernel error handling may write. Disabling `raid-maintenance.timer` does not stop an already-running kernel check. Named backups skip work, including retention, during detected maintenance; never unlink `/run/raid-maintenance.lock` to bypass contention. Legacy jobs and external recovery do not share universal exclusion.
- Fedora ZFS: `zfs-storage-status`, `zfs-storage-enroll data`, and `configure-zfs data-snapshots` are separate status, mount/import/unlock, and maintenance interfaces. Enrollment requires existing imported storage, confirmed identities and safe root-owned paths; no root-on-ZFS, provisioning, data migration, feature upgrades or occupied-directory replacement. Data mounts must be simple paths below `/var/mnt`; `/var/home` must already be mounted from the selected dataset. Nested mounts are unsupported.
- ZFS activation imports only the recorded pool GUID, unlocks the selected encryption root using a prompt or existing root-owned 0600 keyfile, and mounts only the selected dataset. Prepare keys and mount ownership first. Home activation failure blocks sessions: test independent root recovery access. Stopping a service does not unmount or unload keys; partial enrollment requires manual review, not blind replacement. Replication requires a manually seeded, read-only, unmounted destination on a distinct pool with a common snapshot; no forced rollback or destination retention management. Read the [ZFS operations guide](fedora_files/usr/share/fedora-zfs/OPERATIONS.md) before enrollment.

User tools remain opt-in: back up actual Syncthing state and identity after stopping old instances, then enable only one reviewed startup path. For Niri helpers, inspect `type -a nirius niriusd` and replace only obsolete executable references with `/usr/bin/nirius` or `/usr/bin/niriusd`, preserving arguments; `niriusd --version` starts the daemon and is not a safe probe. Do not apply dotfiles, trust mise projects, enable sockets or migrate credentials automatically.

Use rootless Podman as a regular user; review Compose/devcontainer mounts, SELinux labels, ports and secrets. Keep API sockets local and user-private. `setup-podman-desktop` requests an interactive system-wide Flathub install; `setup-devpod-podman` explicitly enrolls/initializes a provider without changing defaults or existing providers. Inspect partial failures before retrying. Workspace provisioning and SSH/editor acceptance remain unverified on the updated image. Launch the editor with `zeditor`; `zed` is the ZFS event daemon. Verify SSH host trust, never bypass it.

## Building and CI

Build the three maintained release variants from the repository root:

```bash
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite --build-arg VARIANT=bazzite-niri -t bazzite-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite-nvidia --build-arg VARIANT=bazzite-niri-nvidia -t bazzite-niri-nvidia:test .
```

`TAG` defaults to `stable`; `BASE_REF` accepts an explicit digest and otherwise defaults to `${BASE_IMAGE}:${TAG}`. For the complete Fedora image, build every dependency in order on the same machine:

```bash
podman build -f Containerfile.zfs --target zfs-rpms --build-arg ZFS_BUILD_MODE=unsigned-testing -t localhost/zfs-rpms:testing .
podman build --no-cache -f Containerfile.zfs-runtime --build-arg ZFS_RPM_IMAGE=localhost/zfs-rpms:testing --build-arg ZFS_RPM_TRUST_MODE=unsigned-testing -t localhost/zfs-runtime:testing .
podman build -f Containerfile.nirius -t localhost/nirius-artifact:testing .
podman build -f Containerfile.fedora --build-arg BASE_IMAGE=localhost/zfs-runtime:testing --build-arg NIRIUS_IMAGE=localhost/nirius-artifact:testing --build-arg ZFS_BUILD_MODE=unsigned-testing -t localhost/fedora-niri:testing .
```

Fedora uses the Containerfiles' pinned Fedora 44 digest; repository packages still resolve at build time, so this is not bit-for-bit reproducibility. `system_files/` is staged at `/tmp/system_files` for installation by `build.sh`.

Source checksum/signature verification, exact-kernel ZFS checks, dependency validation, runtime artifact allowlists, tests and container validation remain required. Unsigned local RPM trust is limited to explicit testing mode and trusted-build packages; Fedora repository signature checks stay enabled with no silent fallback. Hash pins alone do not authenticate publishers; DevPod's pin lacks independent upstream checksum/signature authentication.

`.github/workflows/fedora-testing.yml` (**Fedora Niri Testing**) builds all dependency images/packages on the same runner, never from developer-local artifacts. PRs/pushes validate only; scheduled/manual trusted `main` runs may publish through a separate narrowly scoped `packages: write` job using `GITHUB_TOKEN`. Release publication waits for all three release builds. No signing keys, generated test keys, certificate enrollment, protected environment or additional reviewers are required for Fedora testing. Never put private keys or credentials in images, artifacts, logs or Git, or imply Secure Boot support.

Run `/usr/bin/python3 -m unittest discover -s tests -v` with PyYAML and Just 1.57.0 available. Container/artifact tests are opt-in; skips are not passes. Build/source checks are separate from booted hardware, storage/restore and update/rollback acceptance, which remain pending for the hardware-expanded image. No flag may assert unperformed tests passed; hardware acceptance is not a production gate on test publication. See [active tasks](todo.md).
