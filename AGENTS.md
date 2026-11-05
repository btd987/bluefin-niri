# AGENTS.md

## Working Guidelines

- Inspect the code first. State assumptions and ask when requirements are unclear.
- Make the smallest correct change. Avoid unrequested features and abstractions.
- Preserve unrelated work and existing style. Remove only dead code your changes create.
- For multi-step work, track and report verified progress.
- Do not add new tests or test cases unless explicitly requested. Keep existing tests compatible with requested changes, run relevant existing tests, and report failures, limitations, and untested behavior honestly.
- Keep public documentation generic: no personal hardware inventories, local usernames/paths, private logs, or personal contact details. Use the public maintainer handle and a noreply address for project-authored commits; preserve third-party attribution.

## Images

- Keep `bluefin-niri`, `bazzite-niri`, and `bazzite-niri-nvidia` maintained.
- `fedora-niri` is retired; its standalone build, publication, and support files have been removed.
- `bluefin-niri-nvidia` and `fedora-44-niri` are retired. Exclude them from build, publish, and cleanup matrices; their GHCR packages were deleted.
- Preserve existing Bluefin/Bazzite base mappings, `stable`/`stable-daily` channels, schedules, and retention.

## Desktop and Custom Features

- Stage `system_files/` at `/tmp/system_files` for installation by `build.sh`.
- Use stable DMS (`dms` and `dms-cli`) from the isolated `duxlabs/dms` COPR with Fedora Quickshell and matugen.
- Upstream: https://github.com/duxlabs-dev/dux-shell and https://danklinux.com/docs/dms/ (formerly DankMaterialShell, now Dux Modular Shell).
- Image defaults belong in `/etc/niri/config.kdl`, with exactly one `spawn-at-startup "dms" "run"`; keep the `dms.service` preset disabled.
- `dms ipc call` bindings: launcher `Mod+Space`, control center `Mod+S`, settings `Mod+Comma`, lock `Mod+Alt+L`, plus audio and brightness keys. See README for commands.
- Never replace existing user configs automatically. Document backup-first targeted edits, preserve customizations, remove obsolete Noctalia startup references and rules, and avoid duplicate shell starts. Disable competing user services/autostart before switching to Niri-managed DMS startup.
- Preserve non-shell packages, custom recipes, kanshi, and existing Bluefin/Bazzite ThinkPad fan defaults.
- Preserve each existing image's display manager; do not assume Bazzite uses GDM.

## Build Commands

```bash
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite --build-arg VARIANT=bazzite-niri -t bazzite-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite-nvidia --build-arg VARIANT=bazzite-niri-nvidia -t bazzite-niri-nvidia:test .
```
