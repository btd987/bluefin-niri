# AGENTS.md

## Working Guidelines

- Inspect the code first. State assumptions and ask when requirements are unclear.
- Make the smallest correct change. Avoid unrequested features and abstractions.
- Preserve unrelated work and existing style. Remove only dead code your changes create.
- For multi-step work, use tasks and update `todo.md` with verified progress.
- Run relevant tests and report failures, limitations, and untested behavior honestly.
- Keep public documentation generic: no personal hardware inventories, local usernames/paths, private logs, or personal contact details. Use the public maintainer handle and a noreply address for project-authored commits; preserve third-party attribution.

## Images

- Keep `bluefin-niri`, `bazzite-niri`, and `bazzite-niri-nvidia` maintained.
- The Fedora image/package name is `fedora-niri`.
- `bluefin-niri-nvidia` and `fedora-44-niri` are retired. Exclude them from build, publish, and cleanup matrices; their GHCR packages were deleted.
- Preserve existing Bluefin/Bazzite base mappings, `stable`/`stable-daily` channels, schedules, and retention.

## Fedora Builds

- This is a test project. Unsigned RPMs, unsigned ZFS modules, and publication to `ghcr.io/btd987/fedora-niri` are authorized for hardware testing with Secure Boot disabled.
- Do not require production signing keys, generated test keys, a protected GitHub environment, or additional reviewers for this path.
- Use this repository's GitHub Actions and GHCR process with `GITHUB_TOKEN` and narrowly scoped package-write permissions. Publish only from trusted `main` runs, never pull requests.
- Build every dependency image and package on the same runner; never depend on developer-local artifacts.
- Use `testing` and dated testing tags for Fedora. Do not promote it to stable or imply production readiness without an explicit decision and supporting evidence.
- Keep source checksum/signature verification, exact-kernel ZFS checks, dependency validation, runtime artifact allowlists, tests, and container validation.
- Allow unsigned local RPMs only in an explicit test-build mode for packages produced by the trusted build. Keep Fedora repository signature checks enabled; never silently fall back from signed verification.
- Never include private keys or credentials in images, artifacts, logs, or Git. Do not claim Secure Boot support or require temporary certificate enrollment for unsigned builds.
- Record actual build and test results separately from operator-performed hardware acceptance; production acceptance is not required before test publication. Never add a flag falsely asserting tests passed.
- Keep the unsigned-testing workflow and build paths operative, with `.github/workflows/fedora-testing.yml` displayed as `Fedora Niri Testing`, not the retired `fedora-candidate.yml`. Keep tests, README, and `todo.md` aligned; editing this document alone does not enable publication.
- Fedora currently uses the Containerfiles' pinned Fedora 44 digest.

## Desktop and Custom Features

- Stage `system_files/` at `/tmp/system_files` for installation by `build.sh`.
- Use native Fedora `noctalia` v5, not `noctalia-shell`, Quickshell, or the retired Terra setup.
- Upstream: https://github.com/noctalia-dev/noctalia and https://docs.noctalia.dev/noctalia/.
- Image defaults belong in `/etc/niri/config.kdl`, with exactly one `spawn-at-startup "noctalia"`.
- Native `noctalia msg` bindings: launcher `Mod+Space`, control center `Mod+S`, settings `Mod+Comma`, lock `Mod+Alt+L`, plus audio and brightness keys. See README for commands.
- Never replace existing user configs automatically. Document backup-first targeted edits, preserve customizations, remove obsolete DMS/Quickshell startup references, and avoid duplicate shell starts. Prefer disabling `dms.service` before an update removes it.
- Preserve non-shell packages, custom recipes, kanshi, and existing Bluefin/Bazzite ThinkPad fan defaults. Fedora keeps Thinkfan inactive until appropriate setup.
- Preserve each existing image's display manager; do not assume Bazzite uses GDM.

## Build Commands

```bash
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite --build-arg VARIANT=bazzite-niri -t bazzite-niri:test .
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite-nvidia --build-arg VARIANT=bazzite-niri-nvidia -t bazzite-niri-nvidia:test .
```
