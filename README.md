# Bluefin Niri

A custom Fedora Atomic desktop image built on top of [Bluefin](https://projectbluefin.io/), [Bazzite](https://bazzite.gg/), or Fedora Sway Atomic, featuring the [Niri](https://github.com/YaLTeR/niri) scrollable-tiling Wayland compositor. Bluefin and Bazzite variants use [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell); the Fedora Sway Atomic variant uses [Noctalia](https://github.com/noctalia-dev/noctalia-shell).

## Images

### Bluefin-based

| Image | Base | GPU Support |
|-------|------|-------------|
| `ghcr.io/btd987/bluefin-niri:stable` | bluefin-dx | AMD/Intel |
| `ghcr.io/btd987/bluefin-niri:stable-daily` | bluefin-dx | AMD/Intel |
| `ghcr.io/btd987/bluefin-niri-nvidia:stable` | bluefin-dx-nvidia-open | NVIDIA |
| `ghcr.io/btd987/bluefin-niri-nvidia:stable-daily` | bluefin-dx-nvidia-open | NVIDIA |

### Bazzite-based (gaming)

| Image | Base | GPU Support |
|-------|------|-------------|
| `ghcr.io/btd987/bazzite-niri:stable` | bazzite | AMD/Intel |
| `ghcr.io/btd987/bazzite-niri:stable-daily` | bazzite | AMD/Intel |
| `ghcr.io/btd987/bazzite-niri-nvidia:stable` | bazzite-nvidia | NVIDIA |
| `ghcr.io/btd987/bazzite-niri-nvidia:stable-daily` | bazzite-nvidia | NVIDIA |

### Fedora Sway Atomic-based

| Image | Base | GPU Support |
|-------|------|-------------|
| `ghcr.io/btd987/fedora-44-niri:stable` | Fedora Sway Atomic 44 | AMD/Intel |
| `ghcr.io/btd987/fedora-44-niri:stable-daily` | Fedora Sway Atomic 44 | AMD/Intel |

### Release Streams

- **stable**: Weekly builds (Tuesdays)
- **stable-daily**: Daily builds for fresher base images where available

## Installation

### Rebase from existing Fedora Atomic

```bash
# Bluefin - AMD/Intel GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bluefin-niri:stable

# Bluefin - NVIDIA GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bluefin-niri-nvidia:stable

# Bazzite - AMD/Intel GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bazzite-niri:stable

# Bazzite - NVIDIA GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/bazzite-niri-nvidia:stable

# Fedora Sway Atomic - AMD/Intel GPU
rpm-ostree rebase ostree-unverified-registry:ghcr.io/btd987/fedora-44-niri:stable
```

### Fresh Install

Use a Fedora Atomic ISO and rebase after first boot. For `fedora-44-niri`, start from Fedora Sway Atomic when possible.

## What's Included

### Compositor & Shell
- **Niri** - Scrollable-tiling Wayland compositor
- **DankMaterialShell (DMS)** - Material Design desktop shell for Bluefin/Bazzite variants
- **Noctalia** - Quickshell-based desktop shell for the Fedora Sway Atomic variant
- **Quickshell** - Shell runtime
- **xwayland-satellite** - X11 compatibility layer

### Utilities
- **kitty** - GPU-accelerated terminal
- **kanshi** - Display configuration daemon
- **GNOME Software** - Software center for Flatpak installs on the Fedora Sway Atomic variant
- **Homebrew** - Linuxbrew package manager on the Fedora Sway Atomic variant
- **Steam** - Gaming client on the Fedora Sway Atomic variant
- **gamescope** - Gaming compositor
- **khal** - Calendar application on Bluefin/Bazzite variants

### Configuration
- ZSH set as default shell for new users
- DMS and kanshi services auto-enabled on Bluefin/Bazzite variants
- Noctalia autostart configured through Niri on the Fedora Sway Atomic variant
- Flathub configured for Flatpak installs on the Fedora Sway Atomic variant
- Fedora Sway-style wlroots/GTK portals configured for `fedora-44-niri`

## Usage

After rebooting, select "Niri" from the session menu at the login screen. Bluefin and Bazzite use GDM; `fedora-44-niri` uses SDDM and keeps Sway available as a fallback session.

### ujust Recipes

Bluefin and Bazzite variants include uBlue `ujust` recipes:

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
# Bluefin - AMD/Intel
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx --build-arg VARIANT=bluefin-niri -t bluefin-niri:test .

# Bluefin - NVIDIA
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bluefin-dx-nvidia-open --build-arg VARIANT=bluefin-niri-nvidia -t bluefin-niri-nvidia:test .

# Bazzite - AMD/Intel
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite --build-arg VARIANT=bazzite-niri -t bazzite-niri:test .

# Bazzite - NVIDIA
podman build --build-arg BASE_IMAGE=ghcr.io/ublue-os/bazzite-nvidia --build-arg VARIANT=bazzite-niri-nvidia -t bazzite-niri-nvidia:test .

# Fedora Sway Atomic 44 - AMD/Intel
podman build --build-arg BASE_IMAGE=quay.io/fedora/fedora-sway-atomic --build-arg TAG=44 --build-arg VARIANT=fedora-44-niri -t fedora-44-niri:test .
```

## Credits

- [Universal Blue](https://universal-blue.org/) - For the amazing ublue-os project
- [Project Bluefin](https://projectbluefin.io/) - Base image (Bluefin variants)
- [Bazzite](https://bazzite.gg/) - Base image (gaming variants)
- [Fedora Sway Atomic](https://fedoraproject.org/atomic-desktops/sway/) - Base image (Fedora variant)
- [Niri](https://github.com/YaLTeR/niri) - Compositor
- [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell) - Desktop shell
- [Noctalia](https://github.com/noctalia-dev/noctalia-shell) - Desktop shell for the Fedora variant
