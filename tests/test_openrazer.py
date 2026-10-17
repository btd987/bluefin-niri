"""Exercise Bazzite-only installation and fail-closed inherited driver checks."""

import configparser
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "build.sh").read_text()
INSTALLER = re.search(r"^install_bazzite_openrazer\(\) \(\n.*?^\)", BUILD, re.M | re.S).group()
MOCKS = r'''
rpm() {
    [[ "$CASE" != missing-package || "$2" != openrazer ]] || return 1
    case "$2:$4" in
        kernel-core:*)
            if [[ "$CASE" == multiple-kernels ]]; then printf 'other\n'; fi
            printf 'test-kernel\n' ;;
        openrazer:*|openrazer-daemon:*|python3-openrazer:*) printf '3.12.4\n' ;;
    esac
}
modinfo() {
    [[ "$CASE" != missing-module || "$5" != razermouse ]] || return 1
    case "$4" in
        vermagic)
            if [[ "$CASE" == wrong-kernel ]]; then printf 'other SMP\n'; else printf 'test-kernel SMP\n'; fi ;;
        version)
            if [[ "$CASE" == wrong-version ]]; then printf '0.0\n'; else printf '3.12.4\n'; fi ;;
        filename) printf '%s/%s.ko\n' "$TEST_ROOT" "$5" ;;
    esac
}
dnf5() {
    printf '%s\n' "$*" >> "$TEST_ROOT/calls"
    if [[ "$1" == config-manager ]]; then
        cp "${3#--from-repofile=}" "$TEST_ROOT/repo"
    else
        [[ "$CASE" != transaction-failure ]] || return 42
        if [[ "$CASE" == changed-module ]]; then printf changed > "$TEST_ROOT/razerkbd.ko"; fi
    fi
}
python3() { printf 'imports checked\n'; }
getent() { [[ "$*" == 'group plugdev' ]]; }
'''


class OpenRazerTests(unittest.TestCase):
    def run_installer(self, variant="bazzite-niri", case=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            for module in ("razerkbd", "razermouse", "razerkraken", "razeraccessory"):
                (root / f"{module}.ko").write_text("inherited signed module")
            for name in ("bin/polychromatic-controller", "share/applications/polychromatic.desktop",
                         "lib/udev/rules.d/99-razer.rules", "lib/udev/razer_mount",
                         "lib/systemd/user/openrazer-daemon.service", "share/dbus-1/services/org.razer.service"):
                path = root / "usr" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(mode=0o755)
            installer = INSTALLER.replace("/usr/", f"{root}/usr/")
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", MOCKS + installer + "\ninstall_bazzite_openrazer\n"],
                env=dict(os.environ, TEST_ROOT=directory, TMPDIR=str(root / "tmp"),
                         VARIANT=variant, CASE=case), capture_output=True, text=True,
            )
            self.assertEqual(list((root / "tmp").iterdir()), [], "Temporary files leaked")
            calls = (root / "calls").read_text() if (root / "calls").exists() else ""
            repo = (root / "repo").read_text() if (root / "repo").exists() else ""
            return result, calls, repo

    def test_both_bazzite_variants_use_matching_userspace_and_scoped_repos(self):
        for variant in ("bazzite-niri", "bazzite-niri-nvidia"):
            with self.subTest(variant=variant):
                result, calls, repo = self.run_installer(variant)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("openrazer-3.12.4 openrazer-daemon-3.12.4 python3-openrazer-3.12.4 polychromatic", calls)
                self.assertIn("--repo=fedora --repo=updates --repo=terra --repo=niri-polychromatic", calls)
                self.assertIn("--setopt=terra.includepkgs=openrazer,openrazer-daemon,python3-openrazer", calls)
                self.assertIn("--setopt=terra.gpgcheck=1", calls)
                for exclusion in ("kernel*", "kmod-openrazer*", "akmod*", "dkms*"):
                    self.assertIn(f"--exclude={exclusion}", calls)
                config = configparser.ConfigParser()
                config.read_string(repo)
                self.assertEqual(config.sections(), ["niri-polychromatic"])
                self.assertEqual(config["niri-polychromatic"]["includepkgs"], "polychromatic")
                self.assertEqual(config["niri-polychromatic"]["enabled"], "0")
                self.assertEqual(config["niri-polychromatic"]["gpgcheck"], "1")

    def test_other_variants_do_nothing_even_without_inherited_packages(self):
        for variant in ("bluefin-niri", "fedora-niri", "", "unknown"):
            result, calls, repo = self.run_installer(variant, "missing-package")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((calls, repo), ("", ""))

    def test_missing_or_mismatched_inheritance_stops_before_transaction(self):
        for case in ("missing-package", "multiple-kernels", "missing-module", "wrong-kernel", "wrong-version"):
            with self.subTest(case=case):
                result, calls, repo = self.run_installer(case=case)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((calls, repo), ("", ""))

    def test_transaction_failure_is_not_hidden(self):
        result, _, _ = self.run_installer(case="transaction-failure")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertNotIn("imports checked", result.stdout)

    def test_module_replacement_rejected(self):
        result, _, _ = self.run_installer(case="changed-module")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout)
        self.assertNotIn("imports checked", result.stdout)

    def test_shared_build_calls_guarded_installer(self):
        self.assertEqual(BUILD.count("\n    install_bazzite_openrazer\n"), 1)
        shared = BUILD.split("install_ublue_niri_noctalia() {", 1)[1].split("install_mise()", 1)[0]
        self.assertIn("\n    install_bazzite_openrazer\n", shared)


if __name__ == "__main__":
    unittest.main()
