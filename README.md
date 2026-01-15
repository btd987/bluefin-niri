# Bluefin Niri

A custom Fedora Atomic desktop image built on top of [Bluefin](https://projectbluefin.io/), featuring the [Niri](https://github.com/YaLTeR/niri) scrollable-tiling Wayland compositor and [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell) desktop shell.

## Images

| Image | Base | GPU Support |
|-------|------|-------------|
| `ghcr.io/btd987/bluefin-niri:stable` | bluefin-dx | AMD/Intel |
| `ghcr.io/btd987/bluefin-niri:stable-daily` | bluefin-dx | AMD/Intel |
| `ghcr.io/btd987/bluefin-niri-nvidia:stable` | bluefin-dx-nvidia-open | NVIDIA |
| `ghcr.io/btd987/bluefin-niri-nvidia:stable-daily` | bluefin-dx-nvidia-open | NVIDIA |

### Release Streams

- **stable**: Weekly builds (Tuesdays) with gated kernel updates
- **stable-daily**: Daily builds for fresher packages, same kernel gating

## Installation

### Rebase from existing Fedora Atomic

```bash
# AMD/Intel GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bluefin-niri:stable

# NVIDIA GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bluefin-niri-nvidia:stable
```

### Fresh Install

Use the [Fedora Silverblue ISO](https://fedoraproject.org/atomic-desktops/silverblue/) and rebase after first boot.

## What's Included

### Compositor & Shell
- **Niri** - Scrollable-tiling Wayland compositor
- **DankMaterialShell (DMS)** - Material Design desktop shell
- **Quickshell** - DMS dependency with Polkit/IdleMonitor support
- **xwayland-satellite** - X11 compatibility layer

### Utilities
- **kitty** - GPU-accelerated terminal
- **kanshi** - Display configuration daemon
- **gamescope** - Gaming compositor
- **khal** - Calendar application

### Configuration
- ZSH set as default shell for new users
- DMS and kanshi services auto-enabled
- GNOME portal configured for Niri

## Usage

After rebooting, select "Niri" from the session menu at the GDM login screen.

### ujust Recipes

```bash
# Show session info
ujust niri-session

# Reload Niri configuration
ujust niri-reload

# Show version info
ujust niri-version
```

## Building Locally

```bash
# AMD/Intel
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx -t bluefin-niri:test .

# NVIDIA
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx-nvidia-open -t bluefin-niri-nvidia:test .
```

## Credits

- [Universal Blue](https://universal-blue.org/) - For the amazing ublue-os project
- [Project Bluefin](https://projectbluefin.io/) - Base image
- [Niri](https://github.com/YaLTeR/niri) - Compositor
- [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell) - Desktop shell
