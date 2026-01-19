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
