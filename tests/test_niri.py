"""Isolated build.sh checks; NIRI_TEST_IMAGE enables full packaged-config validation."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


BUILD = (Path(__file__).resolve().parents[1] / "build.sh").read_text()
FUNCTION = re.search(
    r"^configure_niri_noctalia\(\) \{\n.*?^\}(?=\n\n\w+\(\))", BUILD, re.M | re.S
).group()
# Unmodified relevant lines from niri-26.04-1.fc44 default-config.kdl.
UPSTREAM = '''spawn-at-startup "waybar"
binds {
    Mod+T hotkey-overlay-title="Open a Terminal: alacritty" { spawn "alacritty"; }
    Mod+D hotkey-overlay-title="Run an Application: fuzzel" { spawn "fuzzel"; }
    Super+Alt+L hotkey-overlay-title="Lock the Screen: swaylock" { spawn "swaylock"; }
    Mod+Comma  { consume-window-into-column; }
    XF86AudioRaiseVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1+ -l 1.0"; }
    XF86AudioLowerVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1-"; }
    XF86AudioMute        allow-when-locked=true { spawn-sh "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"; }
    XF86MonBrightnessUp allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "+10%"; }
    XF86MonBrightnessDown allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "10%-"; }
}
'''
LAUNCHER = '    Mod+Space { spawn "noctalia" "msg" "panel-toggle" "launcher"; }'
OBSOLETE = ("waybar", "fuzzel", "swaylock", "alacritty", "dms", "qs", "quickshell")


class NiriTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = os.environ.get("NIRI_TEST_IMAGE", "")
        cls.upstream = UPSTREAM
        if cls.image:
            cls.upstream = subprocess.run(
                ["podman", "run", "--rm", "--network=none", "--entrypoint",
                 "/usr/bin/cat", cls.image, "/usr/share/doc/niri/default-config.kdl"],
                check=True, capture_output=True, text=True,
            ).stdout

    def configure(self, source):
        with tempfile.TemporaryDirectory(prefix="niri-test-") as directory:
            root = Path(directory)
            (root / "upstream.kdl").write_text(source)
            function = FUNCTION.replace(
                "/usr/share/doc/niri/default-config.kdl", '"$TEST_ROOT/upstream.kdl"'
            ).replace("/etc/niri", '"$TEST_ROOT/etc/niri"')
            self.assertNotIn("/usr/share/doc/", function)
            self.assertNotIn(" /etc/", function)
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", r'''
niri() {
    [[ "$1" == validate && "$2" == --config && "$3" == "$TEST_ROOT/etc/niri/config.kdl" ]]
    if [[ -n "$NIRI_TEST_IMAGE" ]]; then
        podman run --rm --network=none --security-opt label=disable \
            -v "$TEST_ROOT:$TEST_ROOT:ro" --entrypoint /usr/bin/niri \
            "$NIRI_TEST_IMAGE" "$@"
    fi
    printf 'validated\n'
}
''' + function + "\nconfigure_niri_noctalia\n"],
                env=dict(os.environ, TEST_ROOT=directory, NIRI_TEST_IMAGE=self.image),
                capture_output=True, text=True,
            )
            config = root / "etc/niri/config.kdl"
            self.assertTrue(config.exists(), result.stderr)
            return result, config.read_text()

    def test_upstream(self):
        result, config = self.configure(self.upstream)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validated", result.stdout)
        self.assertEqual(config.splitlines().count('spawn-at-startup "noctalia"'), 1)
        self.assertEqual(config.splitlines().count(LAUNCHER), 1)
        for command in ("launcher", "control-center", "settings-toggle", "lock",
                        "volume-up", "volume-down", "volume-mute",
                        "brightness-up", "brightness-down"):
            self.assertIn(f'"{command}";', config)

    def test_mod_d_whitespace_drift_despite_valid_mod_space(self):
        source = self.upstream.replace("Mod+D hotkey", "Mod+D  hotkey")
        self.assertNotEqual(source, self.upstream)
        result, config = self.configure(source)
        self.assertEqual(result.returncode, 1)
        self.assertIn(LAUNCHER, config)
        self.assertIn("Missing or duplicated Niri default:     Mod+D", result.stderr)
        self.assertNotIn("validated", result.stdout)

    def test_duplicate_startup(self):
        result, _ = self.configure(self.upstream + 'spawn-at-startup "noctalia"\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Missing or duplicated Niri default: spawn-at-startup "noctalia"', result.stderr)
        self.assertNotIn("validated", result.stdout)

    def test_obsolete_extra_startups_and_bindings(self):
        for command in OBSOLETE:
            for line in (f'    spawn-at-startup "{command}"',
                         f'    spawn-sh-at-startup "{command} --old"',
                         f'    Mod+F12 {{ spawn "{command}"; }}',
                         f'    Mod+F12 {{ spawn-sh "{command} --old"; }}'):
                with self.subTest(line=line):
                    source = (self.upstream.replace("binds {", "binds {\n" + line)
                              if "Mod+" in line else self.upstream + line + "\n")
                    result, _ = self.configure(source)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("Obsolete shell command in Niri defaults", result.stderr)
                    self.assertNotIn("validated", result.stdout)

    def test_comments_ignored(self):
        source = self.upstream + '\n// spawn-at-startup "noctalia"\n'
        for command in OBSOLETE:
            source += f'    // spawn-sh-at-startup "{command} --old"\n'
            source = source.replace(
                "binds {", f'binds {{\n    // Mod+F12 {{ spawn "{command}"; }}', 1
            )
        result, _ = self.configure(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validated", result.stdout)

    def test_indented_duplicate_startup_rejected(self):
        result, _ = self.configure(self.upstream + '    spawn-at-startup "noctalia"\n')
        self.assertEqual(result.returncode, 1)

    def test_multiline_obsolete_binding_rejected(self):
        source = self.upstream.replace(
            "binds {", 'binds {\n    Mod+F12 {\n        spawn "dms";\n    }', 1
        )
        result, _ = self.configure(source)
        self.assertEqual(result.returncode, 1)

    def test_unfamiliar_block_comment_fails_closed(self):
        # These build-time checks deliberately do not implement a KDL parser.
        result, _ = self.configure(self.upstream + '\n/*\nspawn-at-startup "dms"\n*/\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn("Obsolete shell command in Niri defaults", result.stderr)


if __name__ == "__main__":
    unittest.main()
