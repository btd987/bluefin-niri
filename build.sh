#!/usr/bin/bash
set -ouex pipefail

install_staged_system_files() {
    if [[ -d /tmp/system_files ]]; then
        cp -a /tmp/system_files/. /
    fi
}

# Allow only the requested packages and known vendor dependencies from each COPR.
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
    local include_packages
    include_packages=$(IFS=,; echo "${packages[*]}")
    if [[ "$copr_name" == lukenukem/asus-linux ]]; then
        # Current RPM name providing the requested rog-control-center command.
        include_packages+=",asusctl-rog-gui"
    fi

    echo "Installing ${packages[*]} from COPR $copr_name (isolated)"

    dnf5 -y copr enable "$copr_name"
    dnf5 -y copr disable "$copr_name"
    dnf5 config-manager setopt "${repo_id}.includepkgs=${include_packages}"
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
    dnf5 config-manager setopt mullvad-stable.includepkgs=mullvad-vpn,mullvad-browser
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
includepkgs=proton-vpn-gnome-desktop,proton-vpn-cli,proton-vpn-gtk-app,proton-vpn-daemon,python3-proton-core,python3-proton-keyring-linux,python3-proton-vpn-api-core
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

install_gamescope_if_missing() {
    if rpm -q gamescope >/dev/null 2>&1 || rpm -q terra-gamescope >/dev/null 2>&1; then
        echo "Gamescope is already installed; skipping Fedora gamescope package"
        return
    fi

    dnf5 install -y gamescope
}

enable_libvirt_service() {
    if [[ -e /usr/lib/systemd/system/libvirtd.service ]]; then
        systemctl enable libvirtd.service
    elif [[ -e /usr/lib/systemd/system/virtqemud.service ]]; then
        systemctl enable virtqemud.service
    else
        echo "No libvirt service unit found; skipping explicit libvirt enable"
    fi
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

configure_niri_noctalia() {
    mkdir -p /etc/niri
    install -Dm0644 /usr/share/doc/niri/default-config.kdl /etc/niri/config.kdl

    # Noctalia is started by Niri, which is the upstream-recommended method.
    sed -i 's|^spawn-at-startup "waybar"$|spawn-at-startup "noctalia"|' /etc/niri/config.kdl
    sed -i 's|This line starts waybar, a commonly used bar for Wayland compositors.|This line starts the native Noctalia desktop shell.|' /etc/niri/config.kdl
    sed -i 's|Mod+T hotkey-overlay-title="Open a Terminal: alacritty" { spawn "alacritty"; }|Mod+T hotkey-overlay-title="Open a Terminal: kitty" { spawn "kitty"; }|' /etc/niri/config.kdl

    sed -i '/^binds {/a\
    Mod+Space { spawn "noctalia" "msg" "panel-toggle" "launcher"; }\
    Mod+S { spawn "noctalia" "msg" "panel-toggle" "control-center"; }
' /etc/niri/config.kdl
    sed -i 's|Mod+D hotkey-overlay-title="Run an Application: fuzzel" { spawn "fuzzel"; }|Mod+D hotkey-overlay-title="Run an Application: Noctalia" { spawn "noctalia" "msg" "panel-toggle" "launcher"; }|' /etc/niri/config.kdl
    sed -i 's|Super+Alt+L hotkey-overlay-title="Lock the Screen: swaylock" { spawn "swaylock"; }|Mod+Alt+L hotkey-overlay-title="Lock the Screen: Noctalia" { spawn "noctalia" "msg" "session" "lock"; }|' /etc/niri/config.kdl
    sed -i 's|Mod+Comma  { consume-window-into-column; }|Mod+Comma { spawn "noctalia" "msg" "settings-toggle"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioRaiseVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1+ -l 1.0"; }|XF86AudioRaiseVolume allow-when-locked=true { spawn "noctalia" "msg" "volume-up"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioLowerVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1-"; }|XF86AudioLowerVolume allow-when-locked=true { spawn "noctalia" "msg" "volume-down"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioMute        allow-when-locked=true { spawn-sh "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"; }|XF86AudioMute        allow-when-locked=true { spawn "noctalia" "msg" "volume-mute"; }|' /etc/niri/config.kdl
    sed -i 's|XF86MonBrightnessUp allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "+10%"; }|XF86MonBrightnessUp allow-when-locked=true { spawn "noctalia" "msg" "brightness-up"; }|' /etc/niri/config.kdl
    sed -i 's|XF86MonBrightnessDown allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "10%-"; }|XF86MonBrightnessDown allow-when-locked=true { spawn "noctalia" "msg" "brightness-down"; }|' /etc/niri/config.kdl

    cat >> /etc/niri/config.kdl << 'EOF'

// Noctalia integration.
window-rule {
    match app-id=r#"^dev\.noctalia\.Noctalia$"#
    open-floating true
}

debug {
    honor-xdg-activation-with-invalid-serial
}

layer-rule {
    match namespace="^noctalia-backdrop"
    place-within-backdrop true
}
EOF

    # Fail rather than silently shipping incomplete integration if Niri defaults change.
    local expected
    for expected in \
        'spawn-at-startup "noctalia"' \
        '    Mod+T hotkey-overlay-title="Open a Terminal: kitty" { spawn "kitty"; }' \
        '    Mod+Space { spawn "noctalia" "msg" "panel-toggle" "launcher"; }' \
        '    Mod+D hotkey-overlay-title="Run an Application: Noctalia" { spawn "noctalia" "msg" "panel-toggle" "launcher"; }' \
        '    Mod+S { spawn "noctalia" "msg" "panel-toggle" "control-center"; }' \
        '    Mod+Comma { spawn "noctalia" "msg" "settings-toggle"; }' \
        '    Mod+Alt+L hotkey-overlay-title="Lock the Screen: Noctalia" { spawn "noctalia" "msg" "session" "lock"; }' \
        '    XF86AudioRaiseVolume allow-when-locked=true { spawn "noctalia" "msg" "volume-up"; }' \
        '    XF86AudioLowerVolume allow-when-locked=true { spawn "noctalia" "msg" "volume-down"; }' \
        '    XF86AudioMute        allow-when-locked=true { spawn "noctalia" "msg" "volume-mute"; }' \
        '    XF86MonBrightnessUp allow-when-locked=true { spawn "noctalia" "msg" "brightness-up"; }' \
        '    XF86MonBrightnessDown allow-when-locked=true { spawn "noctalia" "msg" "brightness-down"; }'; do
        if [[ $(grep -Fxc "$expected" /etc/niri/config.kdl) -ne 1 ]]; then
            echo "Missing or duplicated Niri default: $expected" >&2
            return 1
        fi
    done
    if [[ $(grep -Ec '^[[:space:]]*spawn-at-startup[[:space:]]+"noctalia"' /etc/niri/config.kdl) -ne 1 ]]; then
        echo "Expected exactly one Noctalia startup in Niri defaults" >&2
        return 1
    fi
    # Conservative line checks: unfamiliar upstream layouts require manual review.
    if grep -E '^[[:space:]]*(spawn(-sh)?(-at-startup)?|[^/[:space:]][^{]*\{[[:space:]]*spawn(-sh)?)[[:space:]]+"(waybar|fuzzel|swaylock|alacritty|dms|qs|quickshell)("|[[:space:]])' /etc/niri/config.kdl; then
        echo "Obsolete shell command in Niri defaults" >&2
        return 1
    fi
    niri validate --config /etc/niri/config.kdl
}

install_ublue_niri_noctalia() {
    echo "Installing Niri compositor + native Noctalia shell..."

    install_staged_system_files

    # Install Niri from COPR (yalter/niri)
    copr_install_isolated yalter/niri \
        niri \
        xwayland-satellite

    # Native v5 comes from Fedora, not the legacy Quickshell/Terra packages.
    dnf5 install -y --repo=fedora --repo=updates 'noctalia >= 5.0.0'

    install_vpn_packages

    # Install additional packages from Fedora repos
    dnf5 install -y \
        kitty \
        kanshi \
        khal \
        thinkfan \
        snapper \
        btrfs-assistant \
        mdadm \
        borgbackup \
        borgmatic \
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
        gvfs-fuse \
        gvfs-smb \
        pinentry-gnome3

    install_gamescope_if_missing

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

    # Enable libvirt for VM support
    enable_libvirt_service

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

    # Enable kanshi via systemd preset; Noctalia starts only through Niri.
    # Disable xwaylandvideobridge (Bazzite ships it for KDE, but it creates a visible
    # white window on Niri since Niri handles screen sharing via portals natively)
    mkdir -p /usr/lib/systemd/user-preset
    cat > /usr/lib/systemd/user-preset/80-bluefin-niri.preset << 'EOF'
enable kanshi.service
disable app-org.kde.xwaylandvideobridge@autostart.service
EOF

    # Override the package's XDG autostart entry, including for existing users.
    mkdir -p /etc/xdg/autostart
    cat > /etc/xdg/autostart/org.kde.xwaylandvideobridge.desktop << 'EOF'
[Desktop Entry]
Hidden=true
EOF

    # Portal configuration for Niri
    # Uses GNOME portal (works well with Niri) + GTK fallback
    mkdir -p /usr/share/xdg-desktop-portal
    cat > /usr/share/xdg-desktop-portal/niri-portals.conf << 'EOF'
[preferred]
default=gnome;gtk
EOF

    configure_niri_noctalia
    configure_default_niri_session

    rpm -q noctalia
    noctalia --version

    if [[ "${VARIANT}" == *"nvidia"* ]]; then
        configure_os_release "Niri NVIDIA" "niri-nvidia"
    else
        configure_os_release "Niri" "niri"
    fi

    echo "Niri + native Noctalia installation complete"
}

case "${VARIANT}" in
    ""|bluefin-niri|bluefin-niri-nvidia|bazzite-niri|bazzite-niri-nvidia)
        install_ublue_niri_noctalia
        ;;
    *)
        echo "Unsupported image variant: ${VARIANT}" >&2
        exit 1
        ;;
esac
