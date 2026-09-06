"""Exercise mise repository isolation without network access or live installs."""

import configparser
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "build.sh").read_text()
INSTALLER = re.search(
    r"^install_mise\(\) \(\n.*?^\)", BUILD, re.M | re.S
).group()
FINGERPRINT = "24853EC9F655CE80B48E6C3A8B81C9D17413A06D"
MOCKS = r'''
record() {
    printf '%s\n' "$*" >> "$CALLS"
    [[ "$*" != "$FAIL_AT" && "$1 ${2:-}" != "$FAIL_AT" ]] || return 42
}
dnf5() {
    record dnf5 "$@" || return $?
    if [[ "$1" == config-manager ]]; then
        command cp "${3#--from-repofile=}" "$REPO"
    fi
}
curl() { record curl; }
gpg() {
    record gpg || return $?
    printf 'pub::::::::::\nfpr:::::::::%s:\nsub::::::::::\nfpr:::::::::SUBKEY:\n' "$KEY"
}
install() { record install; }
rpm() { record rpm "$@"; }
mise() { record mise "$@"; }
'''


class MiseTests(unittest.TestCase):
    def run_installer(self, fail_at="", key=FINGERPRINT):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tmp = root / "tmp"
            tmp.mkdir()
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c",
                 MOCKS + INSTALLER + '\ninstall_mise\n'],
                env=dict(os.environ, TMPDIR=str(tmp), FAIL_AT=fail_at, KEY=key,
                         CALLS=str(root / "calls"), REPO=str(root / "mise.repo")),
                capture_output=True, text=True,
            )
            self.assertEqual(list(tmp.iterdir()), [], "Temporary files leaked")
            calls = (root / "calls").read_text().splitlines()
            repo = (root / "mise.repo").read_text() if (root / "mise.repo").exists() else ""
            return result, calls, repo

    def test_verified_key_and_isolated_rpm_transaction(self):
        result, calls, repo = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[:4], [
            "dnf5 install -y --repo=fedora --repo=updates dnf5-plugins gnupg2 curl ca-certificates",
            "curl", "gpg", "install",
        ])
        self.assertRegex(calls[4], r"^dnf5 config-manager addrepo --from-repofile=.*mise.repo$")
        self.assertEqual(calls[5:], [
            "dnf5 install -y --repo=fedora --repo=updates --repo=mise-repo mise",
            "rpm -q mise", "mise --version",
        ])
        self.assertIn("--fail --location --proto '=https' --proto-redir '=https'", INSTALLER)
        self.assertIn('--output "$tmp_dir/mise-key.pub" https://mise.jdx.dev/gpg-key.pub', INSTALLER)
        self.assertIn('gpg --batch --homedir "$tmp_dir" --show-keys --with-colons', INSTALLER)
        self.assertIn('install -Dm0644 "$tmp_dir/mise-key.pub" /etc/pki/rpm-gpg/RPM-GPG-KEY-mise', INSTALLER)
        config = configparser.ConfigParser()
        config.read_string(repo)
        self.assertEqual(config.sections(), ["mise-repo"])
        self.assertEqual(dict(config["mise-repo"]), {
            "name": "mise repo", "baseurl": "https://mise.jdx.dev/rpm",
            "enabled": "0", "includepkgs": "mise", "gpgcheck": "1",
            "repo_gpgcheck": "1", "gpgkey": "file:///etc/pki/rpm-gpg/RPM-GPG-KEY-mise",
        })

    def test_failures_stop_installation_and_clean_up(self):
        _, calls, _ = self.run_installer()
        for index, call in enumerate(calls):
            if call.startswith("dnf5 config-manager"):
                call = "dnf5 config-manager"
            with self.subTest(call=call):
                result, failed_calls, _ = self.run_installer(fail_at=call)
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertEqual(len(failed_calls), index + 1)
                self.assertTrue(failed_calls[-1].startswith(call))

    def test_wrong_missing_or_additional_primary_key_rejected(self):
        for key in ("0" * 40, "", FINGERPRINT + ":\npub::::::::::\nfpr:::::::::" + "0" * 40):
            with self.subTest(key=key):
                result, calls, repo = self.run_installer(key=key)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("fingerprint mismatch", result.stderr)
                self.assertEqual(len(calls), 3)
                self.assertEqual(repo, "")

    def test_only_fedora_foundation_calls_installer_after_plugins(self):
        self.assertEqual(BUILD.count("\n    install_mise\n"), 1)
        foundation = re.search(
            r"^install_fedora_niri_foundation\(\) \{\n.*?^\}", BUILD, re.M | re.S
        ).group()
        self.assertLess(foundation.index("dnf5-plugins"), foundation.index("\n    install_mise\n"))

    def test_pinned_binary_updater_removed(self):
        for path in ("scripts/update-mise.py", "tests/test_mise_update.py", ".github/workflows/update-mise.yml"):
            self.assertFalse((ROOT / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
