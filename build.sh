#!/usr/bin/bash
set -ouex pipefail

echo "Installing Niri compositor + DMS shell..."

# Secure COPR installation helper
# Enables COPR temporarily, disables it, then installs with isolated repo
copr_install_isolated() {
    local copr_name="$1"
    shift
    local packages=("$@")

    if [[ ${#packages[@]} -eq 0 ]]; then
        echo "ERROR: No packages specified for copr_install_isolated"
        return 1
    fi

    repo_id="copr:copr.fedorainfracloud.org:${copr_name//\//:}"

    echo "Installing ${packages[*]} from COPR $copr_name (isolated)"

    dnf5 -y copr enable "$copr_name"
    dnf5 -y copr disable "$copr_name"
    dnf5 -y install --enablerepo="$repo_id" "${packages[@]}"

    echo "Installed ${packages[*]} from $copr_name"
}

# Install Niri from COPR (yalter/niri)
copr_install_isolated yalter/niri \
    niri \
    xwayland-satellite

# Install Quickshell-git and DMS utilities from COPR (avengemedia/danklinux)
# quickshell-git has full feature support (Polkit, IdleMonitor, etc.)
copr_install_isolated avengemedia/danklinux \
    quickshell-git \
    matugen \
    danksearch

# Install DMS (DankMaterialShell) from COPR
copr_install_isolated avengemedia/dms \
    dms

# Install additional packages from Fedora repos
dnf5 install -y \
    kitty \
    kanshi \
    gamescope \
    khal \
    thinkfan \
    snapper \
    btrfs-assistant \
    grim \
    slurp

# Install asusctl for NVIDIA variant (ASUS ROG/TUF laptop support)
if [[ "${VARIANT}" == *"nvidia"* ]]; then
    echo "Installing asusctl for ASUS laptop support..."
    copr_install_isolated lukenukem/asus-linux \
        asusctl \
        rog-control-center
fi

# Enable snapper automatic snapshot timers
systemctl enable snapper-timeline.timer
systemctl enable snapper-cleanup.timer

# Set zsh as default shell for new users
sed -i 's|SHELL=/bin/bash|SHELL=/bin/zsh|' /etc/default/useradd

# Enable DMS and kanshi services by default for all users via systemd preset
mkdir -p /usr/lib/systemd/user-preset
cat > /usr/lib/systemd/user-preset/80-bluefin-niri.preset << 'EOF'
enable dms.service
enable kanshi.service
EOF

# Portal configuration for Niri
# Uses GNOME portal (works well with Niri) + GTK fallback
mkdir -p /usr/share/xdg-desktop-portal
cat > /usr/share/xdg-desktop-portal/niri-portals.conf << 'EOF'
[preferred]
default=gnome;gtk
EOF

# Set Niri as default session for new users via AccountsService template
mkdir -p /usr/share/accountsservice/user-templates
cat > /usr/share/accountsservice/user-templates/standard << 'EOF'
[User]
Session=niri
SystemAccount=false
EOF

# Customize os-release to identify this build
OS_RELEASE="/usr/lib/os-release"
BUILD_DATE=$(date -u +%Y%m%dT%H%M%SZ)

if [[ "${VARIANT}" == *"nvidia"* ]]; then
    NIRI_VARIANT="Niri NVIDIA"
    NIRI_VARIANT_ID="niri-nvidia"
else
    NIRI_VARIANT="Niri"
    NIRI_VARIANT_ID="niri"
fi

# Append Niri to PRETTY_NAME (e.g., "Bluefin-dx 42" -> "Bluefin-dx 42 Niri")
sed -i "s/^PRETTY_NAME=\"\(.*\)\"/PRETTY_NAME=\"\1 ${NIRI_VARIANT}\"/" "$OS_RELEASE"

# Set variant fields
sed -i "/^VARIANT=/d" "$OS_RELEASE"
sed -i "/^VARIANT_ID=/d" "$OS_RELEASE"
echo "VARIANT=\"${NIRI_VARIANT}\"" >> "$OS_RELEASE"
echo "VARIANT_ID=\"${NIRI_VARIANT_ID}\"" >> "$OS_RELEASE"

# Add build timestamp
sed -i "/^BUILD_ID=/d" "$OS_RELEASE"
echo "BUILD_ID=\"${BUILD_DATE}\"" >> "$OS_RELEASE"

echo "Niri + DMS installation complete"
