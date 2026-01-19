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
[group('System')]
setup-snapshots:
    #!/usr/bin/bash
    set -euo pipefail
    if [[ $EUID -ne 0 ]]; then
        echo "Run with sudo: sudo ujust setup-snapshots"
        exit 1
    fi
    echo "Setting up snapper for btrfs snapshots..."
    echo "Creating config for /var..."
    snapper -c var create-config /var 2>/dev/null || echo "/var config already exists"
    echo "Creating config for /var/home..."
    snapper -c home create-config /var/home 2>/dev/null || echo "/var/home config already exists"
    echo ""
    echo "Snapper configured! Timeline snapshots will run automatically."
    echo "Use 'btrfs-assistant' for GUI management or 'ujust list-snapshots' to view."

# List all btrfs snapshots
[group('System')]
list-snapshots:
    @echo "=== /var snapshots ==="
    @snapper -c var list 2>/dev/null || echo "No /var config (run: sudo ujust setup-snapshots)"
    @echo ""
    @echo "=== /var/home snapshots ==="
    @snapper -c home list 2>/dev/null || echo "No /var/home config (run: sudo ujust setup-snapshots)"

# Create manual snapshot with description
[group('System')]
snapshot desc="manual":
    sudo snapper -c var create -d "{{desc}}"
    sudo snapper -c home create -d "{{desc}}"
    @echo "Created snapshots: {{desc}}"

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
    for config in var home; do
        if [[ -f "/etc/snapper/configs/$config" ]]; then
            sed -i 's/^TIMELINE_LIMIT_HOURLY=.*/TIMELINE_LIMIT_HOURLY="24"/' "/etc/snapper/configs/$config"
            sed -i 's/^TIMELINE_LIMIT_DAILY=.*/TIMELINE_LIMIT_DAILY="7"/' "/etc/snapper/configs/$config"
            sed -i 's/^TIMELINE_LIMIT_WEEKLY=.*/TIMELINE_LIMIT_WEEKLY="4"/' "/etc/snapper/configs/$config"
            sed -i 's/^TIMELINE_LIMIT_MONTHLY=.*/TIMELINE_LIMIT_MONTHLY="0"/' "/etc/snapper/configs/$config"
            sed -i 's/^TIMELINE_LIMIT_YEARLY=.*/TIMELINE_LIMIT_YEARLY="0"/' "/etc/snapper/configs/$config"
            echo "Configured $config: 24 timeline, 7 daily, 4 weekly"
        else
            echo "Config $config not found - run 'sudo ujust setup-snapshots' first"
        fi
    done
    # Override timer to run every 15 minutes
    mkdir -p /etc/systemd/system/snapper-timeline.timer.d
    cat > /etc/systemd/system/snapper-timeline.timer.d/dev-machine.conf << 'TIMEREOF'
[Timer]
OnCalendar=
OnCalendar=*:0/15
TIMEREOF
    systemctl daemon-reload
    systemctl restart snapper-timeline.timer
    echo ""
    echo "Done! Snapshots will run every 15 minutes."
    echo "Retention: 24 timeline (~6hrs), 7 daily, 4 weekly"
