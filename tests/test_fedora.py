"""Fedora testing checks using extracted shell functions and mocks only."""

import os
from pathlib import Path
import re
import subprocess
import unittest


BUILD = (Path(__file__).resolve().parents[1] / "build.sh").read_text()
FOUNDATION = re.search(
    r"^install_fedora_niri_foundation\(\) \{\n.*?^\}", BUILD, re.M | re.S
).group()
DISPATCH = BUILD[BUILD.index('case "${VARIANT}" in'):]
MOCKS = r'''
record() {
    printf '%s\n' "$*"
    [[ "$*" != "$FAIL_AT" ]] || return 42
}
rpm() {
    if [[ "$*" == '-q kernel-core --qf '* ]]; then
        [[ "$FAIL_AT" != kernel-query ]] || return 42
        printf '%s\n' "$IMAGE_KERNEL"
    else
        record rpm "$@"
    fi
}
dnf5() { record dnf5 "$@"; }
systemctl() { record systemctl "$@"; }
cp() { record cp "$@"; }
install() { record install "$@"; }
mkdir() { record mkdir "$@"; }
test() { record test "$@"; }
install_mise() { record mise; }
install_ublue_niri_noctalia() {
    record shared
    if [[ -n "$REPLACEMENT_KERNEL" ]]; then IMAGE_KERNEL="$REPLACEMENT_KERNEL"; fi
}
'''


class FedoraTests(unittest.TestCase):
    def run_shell(self, script, variant="fedora-niri", fail_at="",
                  kernel="7.1.13-200.fc44.x86_64", replacement_kernel=""):
        script = script.replace(
            '> /usr/lib/systemd/system-preset/00-fedora-niri-snapshots.preset',
            '> /dev/null',
        )
        script = script.replace(
            '> /usr/lib/systemd/system/thermald.service.d/10-intel-only.conf',
            '> /dev/null',
        )
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c",
             MOCKS + script],
            env=dict(os.environ, VARIANT=variant, FAIL_AT=fail_at,
                     IMAGE_KERNEL=kernel, REPLACEMENT_KERNEL=replacement_kernel),
            capture_output=True, text=True,
        )

    def test_shared_storage_dependencies_and_fedora_only_opt_in(self):
        shared = BUILD.split('install_ublue_niri_noctalia() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('        python3-pyyaml \\\n', shared)
        for timer in ('snapper-timeline.timer', 'snapper-cleanup.timer'):
            self.assertIn(f'systemctl enable {timer}', shared)
            self.assertNotIn(f'disable {timer}', shared)
            self.assertIn(f"'disable {timer}'", FOUNDATION)
        for name in ('setup-backup', 'setup-home-backup', 'setup-raid-maintenance'):
            self.assertIn(f'install -Dm0755 /tmp/system_files/usr/bin/{name} /usr/bin/{name}', BUILD)

    def test_foundation_order_and_desktop_packages(self):
        result = self.run_shell(FOUNDATION + "\ninstall_fedora_niri_foundation\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stdout.splitlines()
        self.assertEqual(calls[:2], [
            "rpm -q bootc rpm-ostree",
            "dnf5 install -y dnf5-plugins just",
        ])
        self.assertTrue(calls[2].startswith("dnf5 install -y "))
        packages = set(calls[2].split()[3:])
        self.assertTrue({
            "gdm", "accountsservice", "NetworkManager", "NetworkManager-wifi",
            "NetworkManager-bluetooth", "bluez", "pipewire", "pipewire-alsa",
            "pipewire-pulseaudio", "wireplumber", "alsa-sof-firmware",
            "upower", "power-profiles-daemon", "mesa-dri-drivers",
            "mesa-vulkan-drivers", "linux-firmware", "xdg-desktop-portal",
            "iwlegacy-firmware", "iwlwifi-dvm-firmware",
            "iwlwifi-mvm-firmware", "iwlwifi-mld-firmware",
            "xdg-desktop-portal-gtk", "xdg-utils", "shared-mime-info",
            "polkit", "mate-polkit", "at-spi2-core", "orca", "brightnessctl",
            "playerctl", "wl-clipboard", "podman", "flatpak", "sudo", "curl",
            "ca-certificates", "tar", "gzip", "coreutils",
        }.issubset(packages))
        self.assertNotIn("polkit-gnome", packages)
        self.assertTrue(calls[3].startswith(
            'dnf5 install -y --repo=fedora --repo=updates '
            '--exclude=kernel-core --exclude=kernel-modules --exclude=kernel-modules-core '
            'kernel-modules-extra-uname-r = 7.1.13-200.fc44.x86_64 '
        ))
        self.assertTrue({
            'alsa-ucm', 'alsa-utils', 'alsa-firmware', 'alsa-tools-firmware',
            'thermald', 'lm_sensors', 'intel-vsc-firmware', 'libcamera-tools',
            'libcamera-gstreamer', 'fprintd', 'fprintd-pam', 'libfprint',
            'pcsc-lite', 'pcsc-lite-ccid', 'opensc', 'gnupg2-scdaemon',
            'yubikey-manager', 'libertas-firmware', 'usb_modeswitch',
            'usb_modeswitch-data', 'ModemManager', 'NetworkManager-wwan',
        }.issubset(calls[3].split()))
        self.assertEqual(calls[4:], [
            "mise",
            "shared",
            "cp -a /tmp/fedora_files/. /",
            "install -Dm0755 /tmp/fedora_files/usr/libexec/fedora-zfs /usr/libexec/fedora-zfs",
            "install -Dm0755 /tmp/fedora_files/usr/libexec/fedora-zfs-storage /usr/libexec/fedora-zfs-storage",
            "test -x /usr/libexec/polkit-mate-authentication-agent-1",
            "test -x /usr/bin/bootc",
            "test -x /usr/bin/flatpak",
            "test -f /usr/lib/systemd/user/niri.service",
            "systemctl --global preset niri-polkit-agent.service",
            "systemctl preset bootc-fetch-apply-updates.timer fedora-niri-os-update.timer fedora-niri-flatpak-update.timer",
            "systemctl disable thinkfan.service",
            "mkdir -p /usr/lib/systemd/system-preset",
            "systemctl disable snapper-timeline.timer snapper-cleanup.timer",
            "mkdir -p /usr/lib/systemd/system/thermald.service.d",
            "systemctl enable thermald.service",
            "rpm -q kernel-modules-extra-7.1.13-200.fc44.x86_64",
            "systemctl enable NetworkManager.service bluetooth.service power-profiles-daemon.service",
            "systemctl enable gdm.service",
            "systemctl set-default graphical.target",
        ])

    def test_kernel_must_be_single_and_unchanged(self):
        script = FOUNDATION + '\ninstall_fedora_niri_foundation\n'
        for kernel in ('', '7.1.13-200.fc44.x86_64\n7.1.14-200.fc44.x86_64'):
            with self.subTest(kernel=kernel):
                result = self.run_shell(script, kernel=kernel)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('dnf5', result.stdout)
        result = self.run_shell(script, fail_at='kernel-query')
        self.assertEqual(result.returncode, 42)
        result = self.run_shell(script, replacement_kernel='7.1.14-200.fc44.x86_64')
        self.assertEqual(result.returncode, 1)
        self.assertIn('changed the image kernel', result.stderr)
        self.assertNotIn('systemctl enable gdm.service', result.stdout)

    def test_thermal_guard_and_no_automatic_authentication_or_tuning(self):
        guard = re.search(r"'ExecCondition=(.*?)'", FOUNDATION).group(1)
        self.assertEqual(guard, '/usr/bin/grep -qE "^vendor_id[[:space:]]*:[[:space:]]*GenuineIntel$" /proc/cpuinfo')
        for vendor, expected in (('GenuineIntel', 0), ('AuthenticAMD', 1), ('', 1)):
            result = subprocess.run(
                ['grep', '-qE', '^vendor_id[[:space:]]*:[[:space:]]*GenuineIntel$'],
                input=f'vendor_id\t: {vendor}\n', text=True,
            )
            self.assertEqual(result.returncode, expected)
        for forbidden in ('ExecStart=', '--ignore-cpuid-check', 'authselect ',
                          'fprintd-enroll', 'ykman ', 'sensors-detect',
                          'ryzen_smu', 'nvidia', 'cups', 'powerprofilesctl '):
            self.assertNotIn(forbidden, FOUNDATION)

    def test_foundation_stops_at_each_failure(self):
        script = FOUNDATION + "\ninstall_fedora_niri_foundation\n"
        success = self.run_shell(script)
        self.assertEqual(success.returncode, 0, success.stderr)
        calls = success.stdout.splitlines()
        for index, call in enumerate(calls):
            with self.subTest(call=call):
                result = self.run_shell(script, fail_at=call)
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertEqual(result.stdout.splitlines(), calls[:index + 1])

    def test_fedora_dispatch_uses_foundation(self):
        script = 'install_fedora_niri_foundation() { record foundation; }\n' + DISPATCH
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "foundation\n")

    def test_existing_dispatch_uses_only_shared_installer(self):
        script = 'install_fedora_niri_foundation() { record foundation; }\n' + DISPATCH
        for variant in ("", "bluefin-niri",
                        "bazzite-niri", "bazzite-niri-nvidia"):
            with self.subTest(variant=variant):
                result = self.run_shell(script, variant=variant)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "shared\n")

    def test_unknown_and_retired_variants_remain_rejected(self):
        for variant in ("unknown", "fedora-niri-proof", "fedora-44-niri", "fedora-niri-nvidia", "bluefin-niri-nvidia"):
            with self.subTest(variant=variant):
                result = self.run_shell(DISPATCH, variant=variant)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn(f"Unsupported image variant: {variant}", result.stderr)


if __name__ == "__main__":
    unittest.main()
