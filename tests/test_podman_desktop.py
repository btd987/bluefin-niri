"""Exercise opt-in enrollment with mocked Flatpak and no host operations."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


RECIPE_FILE = (
    Path(__file__).resolve().parents[1]
    / "system_files/usr/share/niri-system/justfile"
)
RECIPE = textwrap.dedent(
    RECIPE_FILE.read_text().split("setup-podman-desktop:\n", 1)[1].split("\n\n", 1)[0]
)
INSTALL = [
    "install", "--system",
    "https://dl.flathub.org/repo/appstream/io.podman_desktop.PodmanDesktop.flatpakref",
]
MOCK = r'''
flatpak() {
    printf '%s\n' "$@" >> "$CALLS"
    printf '%s\n' "$FLATPAK_OUTPUT" >&2
    return "$FLATPAK_STATUS"
}
'''


class PodmanDesktopTests(unittest.TestCase):
    def run_recipe(self, *, available=True, status=0, output=""):
        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory) / "calls"
            # An empty PATH prevents fallback to real Flatpak or other host tools.
            env = dict(
                os.environ, PATH=directory, BASH_ENV="", CALLS=str(calls),
                FLATPAK_STATUS=str(status), FLATPAK_OUTPUT=output,
            )
            result = subprocess.run(
                ["/usr/bin/bash", "--noprofile", "--norc", "-c",
                 (MOCK if available else "") + RECIPE],
                input="", text=True, capture_output=True, env=env,
            )
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_exact_interactive_system_install(self):
        result, calls = self.run_recipe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, INSTALL)

    def test_missing_flatpak(self):
        result, calls = self.run_recipe(available=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [])
        self.assertIn("flatpak is required", result.stderr)

    def test_native_failure_and_cancellation_are_preserved(self):
        for status, output in ((23, "Installation failed"), (1, "Installation cancelled")):
            with self.subTest(status=status):
                result, calls = self.run_recipe(status=status, output=output)
                self.assertEqual(result.returncode, status)
                self.assertEqual(calls, INSTALL)
                self.assertIn(output, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_repeated_enrollment_delegates_to_flatpak(self):
        # Flatpak owns already-installed handling; the recipe does not reinstall
        # forcibly, probe remotes, or mask its output/status.
        for output in ("Installation complete", "Already installed"):
            result, calls = self.run_recipe(output=output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, INSTALL)
            self.assertIn(output, result.stderr)


if __name__ == "__main__":
    unittest.main()
