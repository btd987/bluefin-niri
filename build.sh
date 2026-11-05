#!/usr/bin/bash
set -ouex pipefail

install_staged_system_files() {
    if [[ -d /tmp/system_files ]]; then
        cp -a /tmp/system_files/. /
        install -Dm0755 /tmp/system_files/usr/bin/setup-backup /usr/bin/setup-backup
        install -Dm0755 /tmp/system_files/usr/bin/setup-home-backup /usr/bin/setup-home-backup
        install -Dm0755 /tmp/system_files/usr/bin/setup-raid-maintenance /usr/bin/setup-raid-maintenance
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
    if [[ "$copr_name" == duxlabs/dms ]]; then
        # The upstream repo file also enables a broad companion repository.
        # Quickshell and matugen come from Fedora instead.
        dnf5 config-manager setopt coprdep:copr.fedorainfracloud.org:duxlabs:dux-repo.enabled=0
    fi
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

configure_niri_dms() {
    mkdir -p /etc/niri
    install -Dm0644 /usr/share/doc/niri/default-config.kdl /etc/niri/config.kdl

    # Start DMS only in Niri; do not also enable its user service.
    sed -i 's|^spawn-at-startup "waybar"$|spawn-at-startup "dms" "run"|' /etc/niri/config.kdl
    sed -i 's|This line starts waybar, a commonly used bar for Wayland compositors.|This line starts the DMS desktop shell.|' /etc/niri/config.kdl
    sed -i 's|Mod+T hotkey-overlay-title="Open a Terminal: alacritty" { spawn "alacritty"; }|Mod+T hotkey-overlay-title="Open a Terminal: kitty" { spawn "kitty"; }|' /etc/niri/config.kdl

    sed -i '/^binds {/a\
    Mod+Space { spawn "dms" "ipc" "call" "spotlight" "toggle"; }\
    Mod+S { spawn "dms" "ipc" "call" "control-center" "toggle"; }
' /etc/niri/config.kdl
    sed -i 's|Mod+D hotkey-overlay-title="Run an Application: fuzzel" { spawn "fuzzel"; }|Mod+D hotkey-overlay-title="Run an Application: DMS" { spawn "dms" "ipc" "call" "spotlight" "toggle"; }|' /etc/niri/config.kdl
    sed -i 's|Super+Alt+L hotkey-overlay-title="Lock the Screen: swaylock" { spawn "swaylock"; }|Mod+Alt+L hotkey-overlay-title="Lock the Screen: DMS" { spawn "dms" "ipc" "call" "lock" "lock"; }|' /etc/niri/config.kdl
    sed -i 's|Mod+Comma  { consume-window-into-column; }|Mod+Comma { spawn "dms" "ipc" "call" "settings" "toggle"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioRaiseVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1+ -l 1.0"; }|XF86AudioRaiseVolume allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "increment" "5"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioLowerVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1-"; }|XF86AudioLowerVolume allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "decrement" "5"; }|' /etc/niri/config.kdl
    sed -i 's|XF86AudioMute        allow-when-locked=true { spawn-sh "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"; }|XF86AudioMute        allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "mute"; }|' /etc/niri/config.kdl
    sed -i 's|XF86MonBrightnessUp allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "+10%"; }|XF86MonBrightnessUp allow-when-locked=true { spawn "dms" "ipc" "call" "brightness" "increment" "10"; }|' /etc/niri/config.kdl
    sed -i 's|XF86MonBrightnessDown allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "10%-"; }|XF86MonBrightnessDown allow-when-locked=true { spawn "dms" "ipc" "call" "brightness" "decrement" "10"; }|' /etc/niri/config.kdl

    # Fail rather than silently shipping incomplete integration if Niri defaults change.
    local expected
    for expected in \
        'spawn-at-startup "dms" "run"' \
        '    Mod+T hotkey-overlay-title="Open a Terminal: kitty" { spawn "kitty"; }' \
        '    Mod+Space { spawn "dms" "ipc" "call" "spotlight" "toggle"; }' \
        '    Mod+D hotkey-overlay-title="Run an Application: DMS" { spawn "dms" "ipc" "call" "spotlight" "toggle"; }' \
        '    Mod+S { spawn "dms" "ipc" "call" "control-center" "toggle"; }' \
        '    Mod+Comma { spawn "dms" "ipc" "call" "settings" "toggle"; }' \
        '    Mod+Alt+L hotkey-overlay-title="Lock the Screen: DMS" { spawn "dms" "ipc" "call" "lock" "lock"; }' \
        '    XF86AudioRaiseVolume allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "increment" "5"; }' \
        '    XF86AudioLowerVolume allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "decrement" "5"; }' \
        '    XF86AudioMute        allow-when-locked=true { spawn "dms" "ipc" "call" "audio" "mute"; }' \
        '    XF86MonBrightnessUp allow-when-locked=true { spawn "dms" "ipc" "call" "brightness" "increment" "10"; }' \
        '    XF86MonBrightnessDown allow-when-locked=true { spawn "dms" "ipc" "call" "brightness" "decrement" "10"; }'; do
        if [[ $(grep -Fxc "$expected" /etc/niri/config.kdl) -ne 1 ]]; then
            echo "Missing or duplicated Niri default: $expected" >&2
            return 1
        fi
    done
    if [[ $(grep -Ec '^[[:space:]]*spawn-at-startup[[:space:]]+"dms"' /etc/niri/config.kdl) -ne 1 ]]; then
        echo "Expected exactly one DMS startup in Niri defaults" >&2
        return 1
    fi
    # Conservative line checks: unfamiliar upstream layouts require manual review.
    if grep -E '^[[:space:]]*(spawn(-sh)?(-at-startup)?|[^/[:space:]][^{]*\{[[:space:]]*spawn(-sh)?)[[:space:]]+"(waybar|fuzzel|swaylock|alacritty|noctalia|noctalia-shell|qs|quickshell)("|[[:space:]])' /etc/niri/config.kdl; then
        echo "Obsolete shell command in Niri defaults" >&2
        return 1
    fi
    niri validate --config /etc/niri/config.kdl
}

install_bazzite_openrazer() (
    set -euo pipefail
    case "${VARIANT}" in
        bazzite-niri|bazzite-niri-nvidia) ;;
        *) return 0 ;;
    esac

    local kernel version module vermagic path package
    kernel=$(rpm -q kernel-core --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n')
    version=$(rpm -q openrazer --qf '%{VERSION}\n')
    if [[ -z "$kernel" || "$kernel" == *$'\n'* || -z "$version" || "$version" == *$'\n'* ]]; then
        echo "ERROR: Expected one inherited Bazzite kernel and OpenRazer package" >&2
        exit 1
    fi

    local tmp_dir
    tmp_dir=$(mktemp -d)
    trap 'rm -rf -- "$tmp_dir"' EXIT
    for module in razerkbd razermouse razerkraken razeraccessory; do
        vermagic=$(modinfo -k "$kernel" -F vermagic "$module")
        if [[ "${vermagic%% *}" != "$kernel" || $(modinfo -k "$kernel" -F version "$module") != "$version" ]]; then
            echo "ERROR: Inherited OpenRazer module $module does not match kernel/package" >&2
            exit 1
        fi
        path=$(modinfo -k "$kernel" -F filename "$module")
        sha256sum "$path" >> "$tmp_dir/modules.sha256"
    done

    # Only the GUI comes from upstream OBS: its daemon would pull in DKMS,
    # conflicting with Bazzite's prebuilt modules. Keep this repo disabled.
    cat > "$tmp_dir/niri-polychromatic.repo" << 'EOF'
[niri-polychromatic]
name=Polychromatic (OpenRazer upstream)
baseurl=https://download.opensuse.org/repositories/hardware:/razer/Fedora_$releasever/
enabled=0
includepkgs=polychromatic
gpgcheck=1
gpgkey=https://download.opensuse.org/repositories/hardware:/razer/Fedora_$releasever/repodata/repomd.xml.key
EOF
    dnf5 config-manager addrepo --from-repofile="$tmp_dir/niri-polychromatic.repo"
    # Match the upstream driver version, not Terra's packaging release: the
    # daemon needs the same-release common udev files (openrazer), whose RPM
    # revision can advance before Bazzite's base. Never replace kernel modules.
    dnf5 install -y --repo=fedora --repo=updates --repo=terra --repo=niri-polychromatic \
        --setopt=terra.includepkgs=openrazer,openrazer-daemon,python3-openrazer \
        --setopt=terra.gpgcheck=1 --setopt=terra.skip_if_unavailable=False --setopt=install_weak_deps=False \
        --exclude='kernel*' --exclude='kmod-openrazer*' --exclude='*openrazer*kmod*' --exclude='akmod*' --exclude='dkms*' \
        "openrazer-$version" "openrazer-daemon-$version" "python3-openrazer-$version" polychromatic

    test "$(rpm -q kernel-core --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n')" = "$kernel"
    for package in openrazer openrazer-daemon python3-openrazer; do
        test "$(rpm -q "$package" --qf '%{VERSION}\n')" = "$version"
    done
    sha256sum --check --strict "$tmp_dir/modules.sha256"
    rpm -q openrazer-daemon python3-openrazer polychromatic
    python3 -c 'import openrazer; import openrazer_daemon'
    test -x /usr/bin/polychromatic-controller
    test -f /usr/share/applications/polychromatic.desktop
    test -f /usr/lib/udev/rules.d/99-razer.rules
    test -x /usr/lib/udev/razer_mount
    test -f /usr/lib/systemd/user/openrazer-daemon.service
    test -f /usr/share/dbus-1/services/org.razer.service
    getent group plugdev
    # D-Bus activation starts the packaged user service on demand; no second
    # Niri startup command or system-wide daemon is needed.
)

install_ublue_niri_dms() {
    echo "Installing Niri compositor + DMS shell..."

    install_staged_system_files

    # Install Niri from COPR (yalter/niri)
    copr_install_isolated yalter/niri \
        niri \
        xwayland-satellite

    # Community Fedora package listed in Ghostty's upstream installation docs.
    copr_install_isolated scottames/ghostty ghostty
    rpm -q ghostty
    ghostty --version
    test -f /usr/share/applications/com.mitchellh.ghostty.desktop

    # Refresh Bazzite's inherited updater without changing its service wrapper.
    # uupd 1.5 fixes successful exit codes when an update module has failed.
    case "${VARIANT}" in
        bazzite-niri|bazzite-niri-nvidia)
            dnf5 install -y --repo=fedora --repo=updates \
                --repo=copr:copr.fedorainfracloud.org:ublue-os:packages \
                --setopt=copr:copr.fedorainfracloud.org:ublue-os:packages.includepkgs=uupd \
                --setopt=copr:copr.fedorainfracloud.org:ublue-os:packages.gpgcheck=1 \
                --setopt=copr:copr.fedorainfracloud.org:ublue-os:packages.skip_if_unavailable=False \
                'uupd >= 1.5.0'
            rpm -q uupd
            ;;
    esac

    # Stable DMS and its split CLI package from the upstream COPR.
    dnf5 install -y --repo=fedora --repo=updates quickshell matugen
    copr_install_isolated duxlabs/dms dms dms-cli

    install_vpn_packages

    # Install additional packages from Fedora repos
    dnf5 install -y \
        kitty \
        nautilus \
        kanshi \
        khal \
        thinkfan \
        snapper \
        btrfs-assistant \
        mdadm \
        borgbackup \
        borgmatic \
        python3-pyyaml \
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
        just \
        zsh \
        xdg-desktop-portal-gnome \
        gnome-keyring \
        gnome-keyring-pam \
        gvfs-fuse \
        gvfs-smb \
        pinentry-gnome3

    install_gamescope_if_missing

    install_bazzite_openrazer

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
    install -Dm0644 /tmp/system_files/usr/share/niri-system/defaults/50-libvirt.rules /etc/polkit-1/rules.d/50-libvirt.rules

    # Set zsh as default shell for new users
    sed -i 's|SHELL=/bin/bash|SHELL=/bin/zsh|' /etc/default/useradd

    # Enable kanshi via systemd preset; DMS starts only through Niri.
    # Disable xwaylandvideobridge (Bazzite ships it for KDE, but it creates a visible
    # white window on Niri since Niri handles screen sharing via portals natively)
    install -Dm0644 /tmp/system_files/usr/share/niri-system/defaults/80-bluefin-niri.preset /usr/lib/systemd/user-preset/80-bluefin-niri.preset

    # Override the package's XDG autostart entry, including for existing users.
    install -Dm0644 /tmp/system_files/usr/share/niri-system/defaults/org.kde.xwaylandvideobridge.desktop /etc/xdg/autostart/org.kde.xwaylandvideobridge.desktop

    # Portal configuration for Niri
    # Uses GNOME portal (works well with Niri) + GTK fallback
    install -Dm0644 /tmp/system_files/usr/share/niri-system/defaults/niri-portals.conf /usr/share/xdg-desktop-portal/niri-portals.conf

    configure_niri_dms
    # Set Niri as default session for new users via AccountsService template.
    install -Dm0644 /tmp/system_files/usr/share/niri-system/defaults/standard-user /usr/share/accountsservice/user-templates/standard

    rpm -q dms dms-cli quickshell
    # DMS rejects root; drop privileges without opening a PAM session in CI.
    setpriv --reuid=nobody --regid=nobody --clear-groups dms version

    if [[ "${VARIANT}" == *"nvidia"* ]]; then
        configure_os_release "Niri NVIDIA" "niri-nvidia"
    else
        configure_os_release "Niri" "niri"
    fi

    echo "Niri + DMS installation complete"
}

case "${VARIANT}" in
    ""|bluefin-niri|bazzite-niri|bazzite-niri-nvidia)
        install_ublue_niri_dms
        ;;
    *)
        echo "Unsupported image variant: ${VARIANT}" >&2
        exit 1
        ;;
esac
