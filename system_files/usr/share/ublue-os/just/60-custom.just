# Niri compositor and DMS shell recipes

# Switch to Niri session
[group('Desktop')]
niri-session:
    @echo "Log out and select 'Niri' from the session menu in GDM"

# Reload Niri configuration
[group('Desktop')]
niri-reload:
    niri msg action reload-config-or-panic

# Show Niri version info
[group('Desktop')]
niri-version:
    @niri --version
    @echo ""
    @rpm -q dms || echo "DMS not installed"

# Initialize snapper for btrfs snapshots (run once after install)
# Note: On Fedora Atomic, only /var/home is a btrfs subvolume.
# System rollback is handled by bootc/ostree, not btrfs snapshots.
[group('System')]
setup-snapshots:
    #!/usr/bin/bash
    set -euo pipefail
    if [[ $EUID -ne 0 ]]; then
        echo "Run with sudo: sudo ujust setup-snapshots"
        exit 1
    fi
    echo "Setting up snapper for /var/home snapshots..."
    snapper -c home create-config /var/home 2>/dev/null || echo "Config already exists"
    echo ""
    echo "Snapper configured! Timeline snapshots will run automatically."
    echo "Note: System rollback uses 'bootc rollback', not btrfs snapshots."
    echo "Use 'btrfs-assistant' for GUI or 'ujust list-snapshots' to view."

# List all btrfs snapshots
[group('System')]
list-snapshots:
    @snapper -c home list 2>/dev/null || echo "No config (run: sudo ujust setup-snapshots)"

# Create manual snapshot with description
[group('System')]
snapshot desc="manual":
    sudo snapper -c home create -d "{{desc}}"
    @echo "Created snapshot: {{desc}}"

# Open btrfs-assistant GUI
[group('System')]
btrfs-assistant:
    @btrfs-assistant

# Configure snapshots for dev machine (15-minute intervals)
[group('System')]
configure-snapshots-dev:
    #!/usr/bin/bash
    set -euo pipefail
    if [[ $EUID -ne 0 ]]; then
        echo "Run with sudo: sudo ujust configure-snapshots-dev"
        exit 1
    fi
    echo "Configuring snapshots for dev machine (15-minute intervals)..."
    # Configure retention: 24 timeline (6hrs), 7 daily, 4 weekly
    if [[ -f "/etc/snapper/configs/home" ]]; then
        sed -i 's/^TIMELINE_LIMIT_HOURLY=.*/TIMELINE_LIMIT_HOURLY="24"/' "/etc/snapper/configs/home"
        sed -i 's/^TIMELINE_LIMIT_DAILY=.*/TIMELINE_LIMIT_DAILY="7"/' "/etc/snapper/configs/home"
        sed -i 's/^TIMELINE_LIMIT_WEEKLY=.*/TIMELINE_LIMIT_WEEKLY="4"/' "/etc/snapper/configs/home"
        sed -i 's/^TIMELINE_LIMIT_MONTHLY=.*/TIMELINE_LIMIT_MONTHLY="0"/' "/etc/snapper/configs/home"
        sed -i 's/^TIMELINE_LIMIT_YEARLY=.*/TIMELINE_LIMIT_YEARLY="0"/' "/etc/snapper/configs/home"
        echo "Configured: 24 timeline, 7 daily, 4 weekly"
    else
        echo "Config not found - run 'sudo ujust setup-snapshots' first"
        exit 1
    fi
    # Override timer to run every 15 minutes
    mkdir -p /etc/systemd/system/snapper-timeline.timer.d
    printf '%s\n' '[Timer]' 'OnCalendar=' 'OnCalendar=*:0/15' > /etc/systemd/system/snapper-timeline.timer.d/dev-machine.conf
    systemctl daemon-reload
    systemctl restart snapper-timeline.timer
    echo ""
    echo "Done! Snapshots will run every 15 minutes."
    echo "Retention: 24 timeline (~6hrs), 7 daily, 4 weekly"

# Download latest virtio-win drivers ISO for Windows VMs
[group('Virtualization')]
download-virtio-win:
    #!/usr/bin/bash
    set -euo pipefail
    ISO_DIR="${HOME}/.local/share/libvirt/images"
    mkdir -p "$ISO_DIR"
    LATEST_URL="https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
    echo "Downloading latest virtio-win ISO..."
    curl -L -o "$ISO_DIR/virtio-win.iso" "$LATEST_URL"
    echo ""
    echo "Downloaded to: $ISO_DIR/virtio-win.iso"
    echo "Attach this ISO to Windows VMs to install virtio drivers."

# Add current user to libvirt group for passwordless VM management
[group('Virtualization')]
setup-libvirt:
    #!/usr/bin/bash
    set -euo pipefail
    if groups | grep -q libvirt; then
        echo "Already in libvirt group!"
    else
        sudo usermod -aG libvirt "$USER"
        echo "Added $USER to libvirt group."
        echo "Log out and back in for changes to take effect."
    fi

# Start libvirt default network
[group('Virtualization')]
virt-network-start:
    sudo virsh net-start default 2>/dev/null || echo "Network already running"
    sudo virsh net-autostart default
    @echo "Default network is running and set to autostart."

# Show VM status
[group('Virtualization')]
virt-status:
    @echo "=== Running VMs ==="
    @virsh list 2>/dev/null || echo "libvirtd not running or no permission"
    @echo ""
    @echo "=== Networks ==="
    @virsh net-list --all 2>/dev/null || true
    @echo ""
    @echo "=== Storage Pools ==="
    @virsh pool-list --all 2>/dev/null || true

# Monitor VMs with virt-top
[group('Virtualization')]
virt-monitor:
    virt-top

# Open virt-manager GUI
[group('Virtualization')]
virt-manager:
    @virt-manager

# Download official Windows ISO from Microsoft
[group('Virtualization')]
download-windows-iso:
    #!/usr/bin/bash
    set -euo pipefail

    ISO_DIR="${HOME}/.local/share/libvirt/images"
    mkdir -p "$ISO_DIR"

    UA="Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

    echo "=== Microsoft Windows ISO Downloader ==="
    echo ""
    echo "Downloads evaluation ISOs directly from Microsoft."
    echo ""
    echo "  1) Windows 11 Enterprise LTSC  (90-day evaluation)"
    echo "  2) Windows Server 2025         (180-day evaluation)"
    echo ""
    read -rp "Choice [1]: " win_ver
    win_ver=${win_ver:-1}

    case $win_ver in
        1)
            EVAL_URL="https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise"
            WIN_NAME="Win11_Enterprise_LTSC"
            FILTER_LTSC=true
            ;;
        2)
            EVAL_URL="https://www.microsoft.com/en-us/evalcenter/download-windows-server-2025"
            WIN_NAME="WinServer2025"
            FILTER_LTSC=false
            ;;
        *)
            echo "Invalid choice"; exit 1
            ;;
    esac

    echo ""
    echo "Fetching download links for ${WIN_NAME}..."

    # Use strings to filter out binary data from the page
    EVAL_PAGE=$(curl -sL -A "$UA" "$EVAL_URL" 2>/dev/null | strings)

    # Extract ISO links - different pages use different formats
    if [[ "${FILTER_LTSC}" == "true" ]]; then
        # Windows 11 Enterprise LTSC: use aria-label pattern, filter for LTSC only
        mapfile -t ISO_ENTRIES < <(echo "$EVAL_PAGE" | \
            grep -oP 'aria-label="[^"]*LTSC[^"]*64-bit \([^)]+\)"[^>]*href="https://go\.microsoft\.com/fwlink[^"]+' | \
            sed 's/aria-label="[^"]*64-bit (\([^)]*\))".*href="/\1 /; s/"$//')
    else
        # Try Server format first: "ISO 64-bit (en-US)" ... href="..."
        mapfile -t ISO_ENTRIES < <(echo "$EVAL_PAGE" | \
            grep -oP 'ISO 64-bit \([^)]+\)" target="_self" href="https://go\.microsoft\.com/fwlink[^"]+' | \
            sed 's/ISO 64-bit (\([^)]*\)).*href="/\1 /; s/"$//')
    fi

    # Fallback: try aria-label pattern (non-LTSC)
    if [[ ${#ISO_ENTRIES[@]} -eq 0 ]]; then
        mapfile -t ISO_ENTRIES < <(echo "$EVAL_PAGE" | \
            grep -oP 'aria-label="[^"]*ISO[^"]*64-bit \([^)]+\)"[^>]*href="https://go\.microsoft\.com/fwlink[^"]+' | \
            grep -v "LTSC" | \
            sed 's/aria-label="[^"]*64-bit (\([^)]*\))".*href="/\1 /; s/"$//')
    fi

    if [[ ${#ISO_ENTRIES[@]} -eq 0 ]]; then
        echo "Could not extract download links. Opening browser..."
        xdg-open "$EVAL_URL" 2>/dev/null || echo "Open: $EVAL_URL"
        exit 1
    fi

    echo ""
    echo "Available languages:"
    for i in "${!ISO_ENTRIES[@]}"; do
        # Format is "en-US https://..." - extract first field
        LANG=$(echo "${ISO_ENTRIES[$i]}" | cut -d' ' -f1)
        echo "  $((i+1))) $LANG"
    done
    echo ""
    read -rp "Choice [1]: " lang_choice
    lang_choice=${lang_choice:-1}

    IDX=$((lang_choice - 1))
    if [[ $IDX -lt 0 || $IDX -ge ${#ISO_ENTRIES[@]} ]]; then
        echo "Invalid choice"; exit 1
    fi

    SELECTED="${ISO_ENTRIES[$IDX]}"
    # Format is "en-US https://..."
    LANG_CODE=$(echo "$SELECTED" | cut -d' ' -f1)
    FWLINK=$(echo "$SELECTED" | cut -d' ' -f2)

    echo ""
    echo "Resolving download URL..."
    ISO_URL=$(curl -sI -L -o /dev/null -w '%{url_effective}' "$FWLINK" 2>/dev/null)

    if [[ -z "$ISO_URL" || "$ISO_URL" != *".iso"* ]]; then
        echo "Could not resolve download URL. Opening browser..."
        xdg-open "$EVAL_URL" 2>/dev/null
        exit 1
    fi

    FILENAME="${WIN_NAME}_${LANG_CODE}.iso"
    FILEPATH="$ISO_DIR/$FILENAME"

    echo ""
    echo "Downloading: $WIN_NAME ($LANG_CODE)"
    echo "URL: $ISO_URL"
    echo "Saving to: $FILEPATH"
    echo ""
    echo "This may take a while (4-6 GB)..."
    echo ""

    curl -L -o "$FILEPATH" --progress-bar "$ISO_URL"

    echo ""
    echo "Download complete!"
    echo "  ISO: $FILEPATH"
    echo ""
    echo "Next steps:"
    echo "  1. Download virtio drivers: ujust download-virtio-win"
    echo "  2. Open virt-manager: ujust virt-manager"
    echo "  3. Create new VM, attach this ISO"
    echo "  4. For Windows 11: enable TPM + UEFI in VM settings"

# Check GPU passthrough readiness and show IOMMU groups
[group('Virtualization')]
vfio-check:
    #!/usr/bin/bash
    set -euo pipefail

    echo "=== GPU Passthrough Readiness Check ==="
    echo ""

    # Check CPU vendor
    if grep -q "GenuineIntel" /proc/cpuinfo; then
        CPU_VENDOR="intel"
        IOMMU_PARAM="intel_iommu=on"
    elif grep -q "AuthenticAMD" /proc/cpuinfo; then
        CPU_VENDOR="amd"
        IOMMU_PARAM="amd_iommu=on"
    else
        echo "Unknown CPU vendor"
        exit 1
    fi
    echo "CPU: $CPU_VENDOR"

    # Check if IOMMU is enabled
    if dmesg 2>/dev/null | grep -qi "IOMMU enabled\|DMAR.*IOMMU\|AMD-Vi.*enabled"; then
        echo "IOMMU: Enabled ✓"
        IOMMU_ENABLED=true
    elif [[ -d /sys/class/iommu ]]; then
        if ls /sys/class/iommu/ 2>/dev/null | grep -q .; then
            echo "IOMMU: Enabled ✓"
            IOMMU_ENABLED=true
        else
            echo "IOMMU: Not enabled ✗"
            IOMMU_ENABLED=false
        fi
    else
        echo "IOMMU: Not enabled ✗"
        IOMMU_ENABLED=false
    fi

    # Check for VT-d/AMD-Vi in BIOS
    if [[ "$IOMMU_ENABLED" == "false" ]]; then
        echo ""
        echo "To enable IOMMU:"
        echo "  1. Enable VT-d (Intel) or AMD-Vi (AMD) in BIOS"
        echo "  2. Add kernel parameter: $IOMMU_PARAM"
        echo "  3. Run: ujust vfio-kargs"
        echo ""
    fi

    echo ""
    echo "=== IOMMU Groups ==="
    echo ""

    if [[ ! -d /sys/kernel/iommu_groups ]]; then
        echo "IOMMU groups not available. Enable IOMMU first."
        exit 1
    fi

    # List IOMMU groups with devices
    for g in $(ls /sys/kernel/iommu_groups/ | sort -n); do
        echo "Group $g:"
        for d in /sys/kernel/iommu_groups/$g/devices/*; do
            if [[ -e "$d" ]]; then
                DEV=$(basename "$d")
                DESC=$(lspci -nns "$DEV" 2>/dev/null || echo "$DEV")
                echo "  $DESC"
            fi
        done
    done

    echo ""
    echo "=== GPUs Detected ==="
    echo ""
    lspci -nn | grep -E "VGA|3D|Display" || echo "No GPUs found"

    echo ""
    echo "Next: Run 'ujust vfio-setup' to configure passthrough for a GPU"

# Generate kernel args for VFIO passthrough
[group('Virtualization')]
vfio-kargs:
    #!/usr/bin/bash
    set -euo pipefail

    echo "=== VFIO Kernel Arguments Generator ==="
    echo ""

    # Detect CPU vendor
    if grep -q "GenuineIntel" /proc/cpuinfo; then
        IOMMU_PARAM="intel_iommu=on"
    else
        IOMMU_PARAM="amd_iommu=on"
    fi

    echo "Required kernel arguments for GPU passthrough:"
    echo ""
    echo "  $IOMMU_PARAM iommu=pt"
    echo ""
    echo "To apply on Fedora Atomic:"
    echo ""
    echo "  rpm-ostree kargs --append=$IOMMU_PARAM --append=iommu=pt"
    echo ""
    echo "Then reboot and run 'ujust vfio-check' to verify."

# Configure VFIO for GPU passthrough
[group('Virtualization')]
vfio-setup:
    #!/usr/bin/bash
    set -euo pipefail

    echo "=== VFIO GPU Passthrough Setup ==="
    echo ""

    # Check IOMMU first
    if [[ ! -d /sys/kernel/iommu_groups ]] || ! ls /sys/kernel/iommu_groups/ 2>/dev/null | grep -q .; then
        echo "IOMMU not enabled. Run 'ujust vfio-kargs' first."
        exit 1
    fi

    # List available GPUs
    echo "Available GPUs:"
    echo ""
    GPU_LIST=$(lspci -nn | grep -E "VGA|3D|Display")
    echo "$GPU_LIST" | nl
    echo ""

    GPU_COUNT=$(echo "$GPU_LIST" | wc -l)
    if [[ $GPU_COUNT -lt 2 ]]; then
        echo "Warning: Only one GPU detected. Passing it through will leave"
        echo "the host without display output (headless)."
        echo ""
        read -rp "Continue anyway? [y/N]: " confirm
        [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
    fi

    echo ""
    read -rp "Enter GPU number to passthrough: " gpu_num

    GPU_LINE=$(echo "$GPU_LIST" | sed -n "${gpu_num}p")
    if [[ -z "$GPU_LINE" ]]; then
        echo "Invalid selection"
        exit 1
    fi

    # Extract PCI IDs (vendor:device)
    GPU_PCI_ID=$(echo "$GPU_LINE" | grep -oP '\[\K[0-9a-f]{4}:[0-9a-f]{4}(?=\])' | head -1)
    GPU_BUS_ID=$(echo "$GPU_LINE" | grep -oP '^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]')

    echo ""
    echo "Selected GPU:"
    echo "  $GPU_LINE"
    echo ""
    echo "PCI ID: $GPU_PCI_ID"
    echo "Bus ID: $GPU_BUS_ID"

    # Find associated audio device (usually same bus, function 1)
    AUDIO_BUS="${GPU_BUS_ID%.*}.1"
    AUDIO_LINE=$(lspci -nn | grep "^$AUDIO_BUS" | grep -i audio || true)
    AUDIO_PCI_ID=""

    if [[ -n "$AUDIO_LINE" ]]; then
        AUDIO_PCI_ID=$(echo "$AUDIO_LINE" | grep -oP '\[\K[0-9a-f]{4}:[0-9a-f]{4}(?=\])' | head -1)
        echo ""
        echo "Associated audio device found:"
        echo "  $AUDIO_LINE"
        echo "  PCI ID: $AUDIO_PCI_ID"
    fi

    echo ""
    echo "=== Configuration ==="
    echo ""

    # Build vfio-pci IDs
    VFIO_IDS="$GPU_PCI_ID"
    [[ -n "$AUDIO_PCI_ID" ]] && VFIO_IDS="$VFIO_IDS,$AUDIO_PCI_ID"

    echo "Add to kernel arguments:"
    echo ""
    echo "  vfio-pci.ids=$VFIO_IDS"
    echo ""
    echo "Full command:"
    echo ""
    echo "  rpm-ostree kargs --append=vfio-pci.ids=$VFIO_IDS"
    echo ""

    read -rp "Apply kernel args now? [y/N]: " apply
    if [[ "$apply" =~ ^[Yy]$ ]]; then
        rpm-ostree kargs --append="vfio-pci.ids=$VFIO_IDS"
        echo ""
        echo "Kernel args applied. Reboot to activate."
        echo "After reboot, the GPU will be bound to vfio-pci driver."
    else
        echo ""
        echo "Run the command above manually when ready."
    fi
