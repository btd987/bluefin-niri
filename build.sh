#!/usr/bin/bash
set -ouex pipefail

is_fedora_variant() {
    [[ "${VARIANT}" == fedora-* ]]
}

install_staged_system_files() {
    if [[ -d /tmp/system_files ]]; then
        cp -a /tmp/system_files/. /
    fi
}

# Secure COPR installation helper
# Enables COPR temporarily, disables it, then installs with isolated repo
copr_install_isolated() {
    local copr_name="$1"
    local repo_id
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

ensure_real_opt() {
    # Fedora Atomic symlinks /opt -> /var/opt, which breaks RPMs that install to /opt
    # (cpio mkdir fails because the symlink exists). Replace with a real directory.
    if [[ -L /opt ]]; then
        rm /opt
        mkdir -p /opt
        # Migrate any existing content from /var/opt
        cp -a /var/opt/. /opt/ 2>/dev/null || true
    fi
}

install_vpn_packages() {
    ensure_real_opt

    # Install Mullvad VPN + Browser from Mullvad repo (isolated)
    dnf5 config-manager addrepo --from-repofile=https://repository.mullvad.net/rpm/stable/mullvad.repo
    dnf5 install -y \
        mullvad-vpn \
        mullvad-browser
    dnf5 config-manager setopt mullvad-stable.enabled=0

    # Install Proton VPN (CLI + GUI) from Proton repo (isolated)
    cat > /etc/yum.repos.d/protonvpn-stable.repo << 'EOF'
[protonvpn-fedora-stable]
name=ProtonVPN Fedora Stable
baseurl=https://repo.protonvpn.com/fedora-$releasever-stable/
enabled=1
gpgcheck=1
gpgkey=https://repo.protonvpn.com/fedora-$releasever-stable/public_key.asc
EOF
    # noscripts: proton-vpn-daemon %posttrans tries to contact systemd over D-Bus,
    # which isn't available during container builds
    dnf5 install -y --setopt=tsflags=noscripts \
        proton-vpn-gnome-desktop \
        proton-vpn-cli
    dnf5 config-manager setopt protonvpn-fedora-stable.enabled=0
}

configure_default_niri_session() {
    # Set Niri as default session for new users via AccountsService template.
    mkdir -p /usr/share/accountsservice/user-templates
    cat > /usr/share/accountsservice/user-templates/standard << 'EOF'
[User]
Session=niri
SystemAccount=false
EOF
}

configure_sddm_niri_session() {
    # SDDM preselects the last session from its state file.
    mkdir -p /var/lib/sddm
    cat > /var/lib/sddm/state.conf << 'EOF'
[Last]
Session=niri.desktop
EOF
    chown sddm:sddm /var/lib/sddm/state.conf 2>/dev/null || true
}

configure_os_release() {
    local niri_variant="$1"
    local niri_variant_id="$2"
    local os_release="/usr/lib/os-release"
    local build_date

    build_date=$(date -u +%Y%m%dT%H%M%SZ)

    # Append Niri to PRETTY_NAME (e.g., "Bluefin-dx 42" -> "Bluefin-dx 42 Niri")
    sed -i "s/^PRETTY_NAME=\"\(.*\)\"/PRETTY_NAME=\"\1 ${niri_variant}\"/" "$os_release"

    # Set variant fields
    sed -i "/^VARIANT=/d" "$os_release"
    sed -i "/^VARIANT_ID=/d" "$os_release"
    echo "VARIANT=\"${niri_variant}\"" >> "$os_release"
    echo "VARIANT_ID=\"${niri_variant_id}\"" >> "$os_release"

    # Add build timestamp
    sed -i "/^BUILD_ID=/d" "$os_release"
    echo "BUILD_ID=\"${build_date}\"" >> "$os_release"
}

configure_fedora_niri_noctalia() {
    mkdir -p /etc/niri
    install -Dm0644 /usr/share/doc/niri/default-config.kdl /etc/niri/config.kdl

    # Noctalia is started by Niri, which is the upstream-recommended method.
    sed -i 's|^spawn-at-startup "waybar"$|spawn-at-startup "qs" "-c" "noctalia-shell"|' /etc/niri/config.kdl
    sed -i 's|Mod+T hotkey-overlay-title="Open a Terminal: alacritty" { spawn "alacritty"; }|Mod+T hotkey-overlay-title="Open a Terminal: kitty" { spawn "kitty"; }|' /etc/niri/config.kdl

    sed -i '/^binds {/a\
    Mod+Space { spawn-sh "qs -c noctalia-shell ipc call launcher toggle"; }\
    Mod+S { spawn-sh "qs -c noctalia-shell ipc call controlCenter toggle"; }
' /etc/niri/config.kdl
    sed -i 's|Mod+Comma  { consume-window-into-column; }|Mod+Comma { spawn-sh "qs -c noctalia-shell ipc call settings toggle"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioRaiseVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1+ -l 1.0"; }|XF86AudioRaiseVolume allow-when-locked=true { spawn "qs" "-c" "noctalia-shell" "ipc" "call" "volume" "increase"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioLowerVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1-"; }|XF86AudioLowerVolume allow-when-locked=true { spawn "qs" "-c" "noctalia-shell" "ipc" "call" "volume" "decrease"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioMute        allow-when-locked=true { spawn-sh "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"; }|XF86AudioMute        allow-when-locked=true { spawn "qs" "-c" "noctalia-shell" "ipc" "call" "volume" "muteOutput"; }|' /etc/niri/config.kdl
    sed -i 's|XF86MonBrightnessUp allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "+10%"; }|XF86MonBrightnessUp allow-when-locked=true { spawn "qs" "-c" "noctalia-shell" "ipc" "call" "brightness" "increase"; }|' /etc/niri/config.kdl
    sed -i 's|XF86MonBrightnessDown allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "10%-"; }|XF86MonBrightnessDown allow-when-locked=true { spawn "qs" "-c" "noctalia-shell" "ipc" "call" "brightness" "decrease"; }|' /etc/niri/config.kdl

    cat >> /etc/niri/config.kdl << 'EOF'

// Noctalia integration.
window-rule {
    geometry-corner-radius 20
    clip-to-geometry true
}

debug {
    honor-xdg-activation-with-invalid-serial
}

layer-rule {
    match namespace="^noctalia-overview*"
    place-within-backdrop true
}
EOF

    niri validate

    # Use Fedora Sway's wlroots/GTK portal preference for the Niri session.
    cp /usr/share/xdg-desktop-portal/wlroots-portals.conf /usr/share/xdg-desktop-portal/niri-portals.conf
}

install_fedora_niri_noctalia() {
    echo "Installing Fedora 44 Niri compositor + Noctalia shell..."

    # Install Noctalia from Terra, then disable Terra so future transactions use Fedora by default.
    dnf5 install -y --nogpgcheck --repofrompath 'terra,https://repos.fyralabs.com/terra$releasever' terra-release
    dnf5 install -y \
        noctalia-shell
    sed -i 's/^enabled=1/enabled=0/' /etc/yum.repos.d/terra.repo
    sed -i 's/^enabled_metadata=1/enabled_metadata=0/' /etc/yum.repos.d/terra.repo

    # Install Fedora packages.
    dnf5 install -y \
        niri \
        xwayland-satellite \
        kitty \
        kanshi \
        gamescope \
        grim \
        slurp \
        libvirt-daemon-kvm \
        qemu-kvm \
        virt-manager \
        virt-install \
        virt-viewer \
        swtpm \
        swtpm-tools \
        edk2-ovmf \
        guestfs-tools \
        libvirt-nss \
        libvirt-daemon-config-network \
        virt-top \
        spice-gtk-tools \
        libguestfs-tools-c \
        partclone \
        libappindicator-gtk3 \
        zsh \
        gnome-keyring \
        gnome-keyring-pam \
        pinentry-gnome3 \
        xdg-desktop-portal-wlr \
        xdg-desktop-portal-gtk \
        git \
        ImageMagick \
        python3 \
        wl-clipboard \
        wlr-randr \
        wget

    install_vpn_packages

    # Enable libvirtd for VM support.
    systemctl enable libvirtd.service

    # Enable Mullvad VPN daemon.
    systemctl enable mullvad-daemon.service

    # Polkit rule: allow libvirt group to manage VMs without password.
    mkdir -p /etc/polkit-1/rules.d
    cat > /etc/polkit-1/rules.d/50-libvirt.rules << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.libvirt.unix.manage" &&
        subject.isInGroup("libvirt")) {
        return polkit.Result.YES;
    }
});
EOF

    # Set zsh as default shell for new users.
    sed -i 's|SHELL=/bin/bash|SHELL=/bin/zsh|' /etc/default/useradd

    configure_fedora_niri_noctalia
    configure_default_niri_session
    configure_sddm_niri_session
    configure_os_release "Niri Noctalia" "niri-noctalia"

    echo "Fedora 44 Niri + Noctalia installation complete"
}

install_ublue_niri_dms() {
    echo "Installing Niri compositor + DMS shell..."

    install_staged_system_files

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

    install_vpn_packages

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
        slurp \
        libvirt-daemon-kvm \
        qemu-kvm \
        virt-manager \
        virt-install \
        virt-viewer \
        swtpm \
        swtpm-tools \
        edk2-ovmf \
        guestfs-tools \
        libvirt-nss \
        libvirt-daemon-config-network \
        virt-top \
        spice-gtk-tools \
        libguestfs-tools-c \
        partclone \
        libappindicator-gtk3 \
        zsh \
        xdg-desktop-portal-gnome \
        gnome-keyring \
        gnome-keyring-pam \
        pinentry-gnome3

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

    # Enable libvirtd for VM support
    systemctl enable libvirtd.service

    # Enable thinkfan for ThinkPad fan control
    systemctl enable thinkfan.service

    # Enable Mullvad VPN daemon
    systemctl enable mullvad-daemon.service

    # Polkit rule: allow libvirt group to manage VMs without password
    mkdir -p /etc/polkit-1/rules.d
    cat > /etc/polkit-1/rules.d/50-libvirt.rules << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.libvirt.unix.manage" &&
        subject.isInGroup("libvirt")) {
        return polkit.Result.YES;
    }
});
EOF

    # Set zsh as default shell for new users
    sed -i 's|SHELL=/bin/bash|SHELL=/bin/zsh|' /etc/default/useradd

    # Enable DMS and kanshi services by default for all users via systemd preset
    # Disable xwaylandvideobridge (Bazzite ships it for KDE, but it creates a visible
    # white window on Niri since Niri handles screen sharing via portals natively)
    mkdir -p /usr/lib/systemd/user-preset
    cat > /usr/lib/systemd/user-preset/80-bluefin-niri.preset << 'EOF'
enable dms.service
enable kanshi.service
disable app-org.kde.xwaylandvideobridge@autostart.service
EOF

    # Portal configuration for Niri
    # Uses GNOME portal (works well with Niri) + GTK fallback
    mkdir -p /usr/share/xdg-desktop-portal
    cat > /usr/share/xdg-desktop-portal/niri-portals.conf << 'EOF'
[preferred]
default=gnome;gtk
EOF

    configure_default_niri_session

    if [[ "${VARIANT}" == *"nvidia"* ]]; then
        configure_os_release "Niri NVIDIA" "niri-nvidia"
    else
        configure_os_release "Niri" "niri"
    fi

    echo "Niri + DMS installation complete"
}

if is_fedora_variant; then
    install_fedora_niri_noctalia
else
    install_ublue_niri_dms
fi
