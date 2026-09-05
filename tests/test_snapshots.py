"""Run setup-snapshots with mocked Snapper, without root or host changes."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


RECIPE_FILE = (
    Path(__file__).resolve().parents[1]
    / "system_files/usr/share/ublue-os/just/60-custom.just"
)
RECIPE = textwrap.dedent(
    RECIPE_FILE.read_text().split("setup-snapshots:\n", 1)[1].split("\n\n", 1)[0]
)
LIST = "--csvout --no-headers list-configs --columns config"
GET = "--csvout --no-headers -c home get-config --columns key,value"
CREATE = "-c home create-config /var/home"
SUCCESS = "Snapper config 'home' is configured for /var/home."
MOCK = r'''
snapper() {
    printf '%s\n' "$*" >> "$CALLS"
    case "$*" in
        '--csvout --no-headers list-configs --columns config')
            if [[ $LIST_STATUS != 0 ]]; then
                echo 'list read failed' >&2
                return "$LIST_STATUS"
            fi
            printf '%s\n' "$CONFIGS"
            ;;
        '-c home create-config /var/home')
            if [[ $CREATE_STATUS != 0 ]]; then
                echo 'create failed' >&2
                return "$CREATE_STATUS"
            fi
            ;;
        '--csvout --no-headers -c home get-config --columns key,value')
            if [[ $GET_STATUS != 0 ]]; then
                echo 'config read failed' >&2
                return "$GET_STATUS"
            fi
            printf '%s\n' "SUBVOLUME,$TARGET" 'TIMELINE_CREATE,no'
            ;;
        *) echo "Unexpected Snapper command: $*" >&2; return 99 ;;
    esac
}
sudo() { echo 'Unexpected sudo invocation' >&2; exit 99; }
'''


class SnapshotTests(unittest.TestCase):
    def run_recipe(self, **overrides):
        env = dict(
            os.environ, CONFIGS="root\nhome", TARGET="/var/home",
            LIST_STATUS="0", CREATE_STATUS="0", GET_STATUS="0", TEST_EUID="0",
        )
        env.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory) / "calls"
            env["CALLS"] = str(calls)
            # Only substitute the root guard; all recipe commands run unchanged.
            result = subprocess.run(
                ["/usr/bin/bash", "--noprofile", "--norc"],
                input=MOCK + RECIPE.replace("$EUID", "$TEST_EUID"),
                text=True, capture_output=True, env=env,
            )
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_existing_valid_config_with_timeline_disabled(self):
        result, calls = self.run_recipe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [LIST, GET])
        self.assertIn(SUCCESS, result.stdout)
        self.assertNotIn("will run automatically", result.stdout)
        self.assertIn("require TIMELINE_CREATE=yes", result.stdout)

    def test_existing_wrong_target(self):
        result, calls = self.run_recipe(TARGET="/home")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [LIST, GET])
        self.assertIn("must target /var/home", result.stderr)
        self.assertNotIn(SUCCESS, result.stdout)

    def test_missing_config_created(self):
        for configs in ("", "root\nhome-backup"):
            with self.subTest(configs=configs):
                result, calls = self.run_recipe(CONFIGS=configs)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [LIST, CREATE, GET])
                self.assertIn(SUCCESS, result.stdout)

    def test_create_failure(self):
        result, calls = self.run_recipe(CONFIGS="root", CREATE_STATUS="23")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(calls, [LIST, CREATE])
        self.assertIn("create failed", result.stderr)
        self.assertNotIn(SUCCESS, result.stdout)
        self.assertNotIn("already exists", result.stdout)

    def test_read_failure(self):
        for overrides, expected_calls, error in (
            ({"LIST_STATUS": "24"}, [LIST], "list read failed"),
            ({"GET_STATUS": "24"}, [LIST, GET], "config read failed"),
            ({"CONFIGS": "", "GET_STATUS": "24"},
             [LIST, CREATE, GET], "config read failed"),
        ):
            with self.subTest(overrides=overrides):
                result, calls = self.run_recipe(**overrides)
                self.assertEqual(result.returncode, 24)
                self.assertEqual(calls, expected_calls)
                self.assertIn(error, result.stderr)
                self.assertNotIn(SUCCESS, result.stdout)

    def test_non_root(self):
        result, calls = self.run_recipe(TEST_EUID="1000")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [])
        self.assertIn("Run with sudo:", result.stdout)


if __name__ == "__main__":
    unittest.main()
