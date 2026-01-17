# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bluefin Niri is a Fedora Atomic (bootc) OCI image layered on top of ublue-os/bluefin-dx. It adds the Niri scrollable-tiling Wayland compositor and DankMaterialShell (DMS) desktop environment.

## Build Commands

```bash
# Local build - AMD/Intel
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .

# Local build - NVIDIA
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx-nvidia-open --build-arg VARIANT=bluefin-niri-nvidia -t bluefin-niri-nvidia:test .
```

## Architecture

**Image variants:**
- `bluefin-niri` - AMD/Intel GPU (base: bluefin-dx)
- `bluefin-niri-nvidia` - NVIDIA GPU (base: bluefin-dx-nvidia-open)

**Release channels:**
- `stable` - Weekly builds (Tuesdays), pulled from upstream `stable` tag
- `stable-daily` - Daily builds, pulled from upstream `stable-daily` tag

**Key files:**
- `Containerfile` - OCI image definition, accepts BASE_IMAGE, TAG, and VARIANT build args
- `build.sh` - Installation script run during image build; installs packages from COPR repos and Fedora, configures systemd services
- `system_files/` - Files copied directly into the image root filesystem
- `.github/workflows/build.yml` - Unified CI workflow handling both channels
- `.github/workflows/cleanup.yml` - Weekly cleanup of old package versions

**System files:**
- `system_files/etc/modprobe.d/thinkfan.conf` - Enables thinkpad_acpi fan control
- `system_files/usr/share/ublue-os/just/60-niri.just` - ujust recipes for Niri

**Variant-specific packages (VARIANT build arg):**
- Base (all): thinkfan (ThinkPad fan control)
- NVIDIA only: asusctl, rog-control-center (ASUS ROG/TUF laptop support)

**COPR sources:**
- `yalter/niri` - Niri compositor, xwayland-satellite
- `avengemedia/danklinux` - Quickshell, matugen, danksearch
- `avengemedia/dms` - DankMaterialShell
- `lukenukem/asus-linux` - asusctl, rog-control-center (NVIDIA variant only)

The `copr_install_isolated()` helper in build.sh enables a COPR, immediately disables it, then installs with the repo explicitly enabled - this prevents COPR repos from affecting future dnf operations.
