# Bluefin Niri

Fedora Atomic desktops with [Niri](https://github.com/YaLTeR/niri) and [DMS](https://github.com/duxlabs-dev/dux-shell) (formerly DankMaterialShell, now Dux Modular Shell). See the [DMS documentation](https://danklinux.com/docs/dms/).

## Images

All images use the public namespace `ghcr.io/btd987`.

| Image | Base | Channels |
| --- | --- | --- |
| `bluefin-niri` | [Bluefin DX](https://projectbluefin.io/), AMD/Intel | `stable`, `stable-daily` |
| `bazzite-niri` | [Bazzite](https://bazzite.gg/), AMD/Intel | `stable`, `stable-daily` |
| `bazzite-niri-nvidia` | Bazzite NVIDIA | `stable`, `stable-daily` |

Bluefin/Bazzite retain weekly Tuesday `stable`, daily `stable-daily`, dated tags and existing retention. Bluefin follows the matching upstream channel; Bazzite uses upstream `stable`, or `latest` for `stable-daily`. `bluefin-niri-nvidia` and `fedora-44-niri` are retired, their packages deleted, and excluded from builds, publication and cleanup.

The standalone `fedora-niri` testing image is retired. Its build, publication workflow, and dedicated support files have been removed.

## Installation

Back up data and configuration first; keep a known-working deployment and recovery media. From a compatible Fedora Atomic installation, choose **one** rebase, then reboot. For a fresh installation, install a compatible Fedora Atomic system first.

```bash
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bluefin-niri:stable
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bazzite-niri:stable
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bazzite-niri-nvidia:stable
systemctl reboot
```

Switching images does not migrate user configurations or storage. OS rollback does not undo persistent data or pool-feature changes. Select Niri in the login screen's session menu; each image retains its existing display manager.

## Desktop and Migration

Images include stable `dms` and `dms-cli` from the upstream `duxlabs/dms` COPR, Quickshell >= 0.3.2 and cpptrace from the scoped `duxlabs/dux-repo` COPR, Fedora matugen, xwayland-satellite, Kitty, Ghostty, kanshi, gamescope, khal and shared custom recipes. Fedora's older Quickshell 0.2 cannot load DMS 2.1's UI. Ghostty comes from the community `scottames/ghostty` COPR listed in its [installation documentation](https://ghostty.org/docs/install/binary#fedora); launch it from the application launcher or run `ghostty`. Kitty remains the default `Mod+T` terminal. Defaults live in `/etc/niri/config.kdl`; existing user configs are never replaced automatically.

Bazzite builds refresh the signed upstream `uupd` package to at least 1.5.0 for corrected update-failure reporting. The inherited `ujust upgrade` service/logging path remains unchanged; this package upgrade alone does not restore its terminal progress bar.

1. Back up `${XDG_CONFIG_HOME:-$HOME/.config}/niri`, any custom `NIRI_CONFIG`, and all external included files before editing. Preserve rules, outputs, inputs, shortcuts and appearance; do not replace entire configs or apply unrelated dotfiles.
2. Preferably before updating, keep a terminal open and disable any Noctalia user service or desktop autostart you previously configured. Inspect `systemctl --user list-unit-files` and your autostart entries to identify it; preserve Noctalia settings for rollback. If returning from an older DMS installation, run `systemctl --user disable --now dms.service` when that unit exists to remove competing service activation.
3. Compare the active config with `/etc/niri/config.kdl` and make targeted edits. Remove Noctalia and `qs`/`quickshell -c noctalia-shell` startup references, including includes/scripts, and obsolete Noctalia-specific window/layer rules. Preserve customizations and old settings; they are not automatically converted to DMS. Avoid `dms setup` when migrating a customized config; merge the changes below instead.
4. Keep exactly one `spawn-at-startup "dms" "run"` in the active Niri config, with no competing user service or desktop autostart. The image disables the `dms.service` preset because Niri starts DMS directly. Merge these bindings into the existing `binds` block, replacing conflicts rather than duplicating them (also replace any old `Mod+D` launcher binding):

```kdl
Mod+Space { spawn "dms" "ipc" "call" "spotlight" "toggle"; }
Mod+D { spawn "dms" "ipc" "call" "spotlight" "toggle"; }
Mod+S { spawn "dms" "ipc" "call" "control-center" "toggle"; }
Mod+Comma { spawn "dms" "ipc" "call" "settings" "toggle"; }
Mod+Alt+L { spawn "dms" "ipc" "call" "lock" "lock"; }
XF86AudioRaiseVolume allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "increment" "5"; }
XF86AudioLowerVolume allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "decrement" "5"; }
XF86AudioMute allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "mute"; }
XF86MonBrightnessUp allow-when-locked=true { spawn "dms" "ipc" "call" "brightness" "increment" "10"; }
XF86MonBrightnessDown allow-when-locked=true { spawn "dms" "ipc" "call" "brightness" "decrement" "10"; }
```

5. Run `niri validate` (use `--config` for a custom path), then log out and back in; reload alone does not rerun startup commands. Check `rpm -q dms dms-cli quickshell`, `dms version`, `dms ipc list`, and test panels, lock/password unlock, audio and brightness.

## Razer Devices (Bazzite)

The Bazzite Niri builds include [OpenRazer](https://openrazer.github.io/) userspace
support and native [Polychromatic](https://polychromatic.app/) for supported
Razer peripherals. Both Bazzite variants retain their upstream kernel modules;
the build checks each variant's own kernel and matches the daemon/library to the
driver's upstream version. Terra packaging revisions of the userspace and common
udev files may advance independently; kernel modules remain unchanged. Bluefin
does not include this integration.

After booting an image containing this change, grant your login user device
access and reboot. On Atomic images, `plugdev` may exist only in the immutable
`/usr/lib/group`. Copy its existing entry into `/etc/group` before using
`gpasswd`; the guarded command preserves its numeric ID and existing members
and does nothing if the local entry already exists:

```bash
sudo bash -c 'if ! grep -q "^plugdev:" /etc/group; then getent group plugdev >> /etc/group; fi'
sudo gpasswd -a "$USER" plugdev
systemctl reboot
```

Launch **Polychromatic** from the application launcher, or run
`polychromatic-controller`. The packaged OpenRazer user service is D-Bus
activated; do not add a duplicate Niri startup command or run the daemon as root.
For settings restoration before opening the GUI, optionally enable the packaged
service with `systemctl --user enable --now openrazer-daemon.service` after reboot.
Custom effects and tray startup are configured through Polychromatic.

For diagnostics, check `id -nG`, `systemctl --user status openrazer-daemon.service`
and `journalctl --user -u openrazer-daemon.service -b`. Device support and available
controls depend on the model and connection mode; consult the upstream supported
device list. Build checks do not establish physical-device or Secure Boot
acceptance.

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

Use rootless Podman as a regular user; review Compose/devcontainer mounts, SELinux labels, ports and secrets. Keep API sockets local and user-private. `setup-podman-desktop` requests an interactive system-wide Flathub install; `setup-devpod-podman` explicitly enrolls/initializes a provider without changing defaults or existing providers. Inspect partial failures before retrying. Verify SSH host trust, never bypass it.

## Building and CI

Build the three maintained release variants from the repository root:

```bash
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite --build-arg VARIANT=bazzite-niri -t bazzite-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite-nvidia --build-arg VARIANT=bazzite-niri-nvidia -t bazzite-niri-nvidia:test .
```

`TAG` defaults to `stable`; `BASE_REF` accepts an explicit digest and otherwise defaults to `${BASE_IMAGE}:${TAG}`. CI resolves upstream tags to immutable references for each build. `system_files/` is staged at `/tmp/system_files` for installation by `build.sh`.

Static desktop templates live in `system_files/usr/share/niri-system/defaults/`. `build.sh` applies them after package installation so RPM defaults cannot replace them; early staging does not activate the templates. Existing user configuration is not replaced.

`.github/workflows/build.yml` validates PRs/pushes; scheduled/manual `main` runs may publish through a separate narrowly scoped `packages: write` job using `GITHUB_TOKEN`. Release publication waits for all three release builds.

Run `/usr/bin/python3 -m unittest discover -s tests -v` with PyYAML and Just 1.57.0 available. Container tests are opt-in; skips are not passes. Build/source checks are separate from booted hardware, storage/restore and update/rollback acceptance.
