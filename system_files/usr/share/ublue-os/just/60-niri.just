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
