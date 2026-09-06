"""Run the image-only tools installer with no live package or service changes."""

import os
from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-fedora-tools.sh"
PACKAGES = (
    "helix syncthing chezmoi git git-delta git-lfs gnupg2 openssh-clients "
    "pinentry pinentry-gnome3 fzf zoxide atuin direnv eza bat glow podman-compose jq"
).split()
CLIS = (
    "hx syncthing chezmoi git delta git-lfs gpg gpg-agent gpgconf pinentry "
    "pinentry-gnome3 fzf zoxide atuin direnv eza bat podman-compose jq"
).split()
MOCKS = r'''
record() { printf '%s\n' "$*"; }
install() {
    record install "$@"
    while IFS= read -r line; do record preset "$line"; done
}
dnf5() { record dnf5 "$@"; return "$DNF_STATUS"; }
rpm() { record rpm "$@"; }
systemctl() { printf '%s\n' "$UNIT_STATE"; }
command() { record command "$@"; }
'''


class FedoraToolsTests(unittest.TestCase):
    def run_installer(self, dnf_status=0, state="syncthing.service disabled disabled",
                      cli_status=0):
        # Replace only the container guard so these unit tests also run on a host.
        script = SCRIPT.read_text().replace(
            "[[ -f /run/.containerenv || -f /.dockerenv ]]", "true"
        )
        mocks = MOCKS + "\n".join(
            f'{cli}() {{ record {cli} "$@"; return "$CLI_STATUS"; }}'
            for cli in CLIS + ["ssh", "glow"]
        )
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", mocks + "\n" + script],
            env=dict(os.environ, DNF_STATUS=str(dnf_status), UNIT_STATE=state,
                     CLI_STATUS=str(cli_status)),
            capture_output=True, text=True,
        )

    def test_single_fedora_transaction_and_version_checks(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stdout.splitlines()
        self.assertEqual(calls[:4], [
            "install -Dm644 /dev/stdin /usr/lib/systemd/user-preset/00-fedora-tools.preset",
            "preset disable syncthing.service",
            "install -Dm644 /dev/stdin /usr/lib/systemd/system-preset/00-fedora-tools.preset",
            "preset disable syncthing@.service",
        ])
        self.assertNotIn("Deferred (unavailable in Fedora repos): starship yazi lazygit", calls)
        self.assertEqual([c for c in calls if c.startswith("dnf5 ")], [
            "dnf5 -y --repo=fedora --repo=updates --setopt=install_weak_deps=False install "
            + " ".join(PACKAGES)
        ])
        self.assertIn("rpm -q " + " ".join(PACKAGES), calls)
        self.assertEqual(calls[6:], [f"{cli} --version" for cli in CLIS]
                         + ["ssh -V", "command -v ssh-agent ssh-keygen", "glow --version"])

    def test_dnf_failure_stops_verification(self):
        result = self.run_installer(dnf_status=42)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertTrue(result.stdout.splitlines()[-1].startswith("dnf5 "))

    def test_cli_failure_is_fatal(self):
        result = self.run_installer(cli_status=43)
        self.assertEqual(result.returncode, 43, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "hx --version")

    def test_syncthing_must_be_disabled_with_disabled_preset(self):
        for state in ("syncthing.service enabled disabled",
                      "syncthing.service disabled enabled", ""):
            with self.subTest(state=state):
                result = self.run_installer(state=state)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unexpected Syncthing user unit state", result.stderr)


if __name__ == "__main__":
    unittest.main()
