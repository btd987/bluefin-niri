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
    thinkfan

# Install asusctl for NVIDIA variant (ASUS ROG/TUF laptop support)
if [[ "${VARIANT}" == *"nvidia"* ]]; then
    echo "Installing asusctl for ASUS laptop support..."
    copr_install_isolated lukenukem/asus-linux \
        asusctl \
        rog-control-center
fi

# Set zsh as default shell for new users
sed -i 's|SHELL=/bin/bash|SHELL=/bin/zsh|' /etc/default/useradd

# Enable DMS and kanshi services for new users via systemd
mkdir -p /etc/skel/.config/systemd/user/graphical-session.target.wants
ln -sf /usr/lib/systemd/user/dms.service \
    /etc/skel/.config/systemd/user/graphical-session.target.wants/dms.service
ln -sf /usr/lib/systemd/user/kanshi.service \
    /etc/skel/.config/systemd/user/graphical-session.target.wants/kanshi.service

# Portal configuration for Niri
# Uses GNOME portal (works well with Niri) + GTK fallback
mkdir -p /usr/share/xdg-desktop-portal
cat > /usr/share/xdg-desktop-portal/niri-portals.conf << 'EOF'
[preferred]
default=gnome;gtk
EOF

echo "Niri + DMS installation complete"
