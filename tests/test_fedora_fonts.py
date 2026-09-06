"""Offline control-flow tests plus opt-in, isolated real upstream artifact proof.

IOSEVKA_ARCHIVE=/tmp/opencode/Iosevka-v3.5.1.tar.xz python -m unittest discover \
    -s tests -p test_fedora_fonts.py -v
"""

import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from xml.sax.saxutils import escape


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-fedora-fonts.sh"
INSTALLER = SCRIPT.read_text()
SHA256 = "3b94ea1dc3955756762f977b7677bca671947dd56bc755a6f8465a8e83b5f257"
STYLES = {"Regular": "Regular", "Bold": "Bold", "Italic": "Italic",
          "BoldItalic": "Bold Italic"}
MOCKS = r'''
record() { printf '%s\n' "$*" >&2; [[ "$1" != "$FAIL" ]] || return 42; }
mktemp() { /usr/bin/mktemp -d "$TMPDIR/fonts.XXXXXXXX"; }
rm() { [[ "$*" == "-rf -- $TMPDIR/"* ]] && /usr/bin/rm "$@"; }
curl() { record curl "$@"; }
sha256sum() { local line; IFS= read -r line; record sha256sum "$@" "$line"; }
tar() {
    record tar "$@" || return
    [[ "$LICENSE" == missing ]] || printf '%s' "$LICENSE" > "$workdir/LICENSE.md"
}
fc-scan() { record fc-scan "$@" || return; printf '%s' "$FAMILY"; }
install() { record install "$@"; }
fc-cache() { record fc-cache "$@"; }
'''


class FedoraFontsTests(unittest.TestCase):
    def run_installer(self, fail="", family="Iosevka Nerd Font", license="OFL",
                      container=True, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            script = INSTALLER.replace(
                "[[ -f /run/.containerenv || -f /.dockerenv ]]",
                "true" if container else "false",
            )
            mocks = MOCKS
            if corrupt:
                mocks += r'''
curl() { printf 'corrupt\n' > "$workdir/Iosevka.tar.xz"; }
sha256sum() { /usr/bin/sha256sum "$@"; }
'''
            result = subprocess.run(
                ["/usr/bin/bash", "--noprofile", "--norc", "-c", mocks + script],
                env={"PATH": directory, "TMPDIR": directory, "FAIL": fail,
                     "FAMILY": family, "LICENSE": license},
                capture_output=True, text=True,
            )
            self.assertEqual(list(Path(directory).iterdir()), [], "Temporary files leaked")
            return result

    def test_exact_verified_set_and_system_cache(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stderr.splitlines()
        self.assertIn("/v3.5.1/Iosevka.tar.xz", calls[0])
        self.assertIn("--proto =https --proto-redir =https", calls[0])
        self.assertIn(f"sha256sum --check --strict - {SHA256}  ", calls[1])
        self.assertIn("--no-same-owner", calls[2])
        self.assertEqual(calls[2].split()[-5:],
                         [f"IosevkaNerdFont-{s}.ttf" for s in STYLES] + ["LICENSE.md"])
        self.assertEqual([c.split()[0] for c in calls[3:7]], ["fc-scan"] * 4)
        installs = [c for c in calls if c.startswith("install ")]
        self.assertEqual(len(installs), 5)
        for call, style in zip(installs, STYLES):
            self.assertTrue(call.endswith(f" /usr/share/fonts/niri-iosevka/IosevkaNerdFont-{style}.ttf"))
        self.assertTrue(installs[-1].endswith(" /usr/share/licenses/niri-iosevka/LICENSE.md"))
        self.assertEqual(calls[-1], "fc-cache --system-only --force /usr/share/fonts/niri-iosevka")

    def test_rejects_wrong_metadata_or_missing_license_before_install(self):
        for options in ({"family": "Iosevka Nerd Font Mono"}, {"family": ""},
                        {"license": "missing"}, {"license": ""}):
            with self.subTest(options=options):
                result = self.run_installer(**options)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("install ", result.stderr)

    def test_command_failures_stop_and_cleanup(self):
        for command in ("curl", "sha256sum", "tar", "fc-scan", "install", "fc-cache"):
            with self.subTest(command=command):
                result = self.run_installer(fail=command)
                self.assertNotEqual(result.returncode, 0)
                if command in ("curl", "sha256sum", "tar", "fc-scan"):
                    self.assertNotIn("install ", result.stderr)

    def test_corruption_and_host_guard(self):
        result = self.run_installer(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout)
        self.assertNotIn("tar ", result.stderr)
        result = self.run_installer(container=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "Container required\n")
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    @unittest.skipUnless(os.environ.get("IOSEVKA_ARCHIVE"), "Set IOSEVKA_ARCHIVE for real font proof")
    def test_real_archive_metadata_glyphs_and_isolated_matching(self):
        archive = Path(os.environ["IOSEVKA_ARCHIVE"])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), SHA256)
        with tempfile.TemporaryDirectory(dir=archive.parent) as directory:
            root = Path(directory)
            fonts = root / "fonts"
            fonts.mkdir()
            names = [f"IosevkaNerdFont-{s}.ttf" for s in STYLES] + ["LICENSE.md"]
            with tarfile.open(archive) as bundle:
                for name in names:
                    member = bundle.getmember(name)
                    self.assertTrue(member.isfile())
                    (fonts / name).write_bytes(bundle.extractfile(member).read())
            self.assertIn("SIL Open Font License", (fonts / "LICENSE.md").read_text())
            config = root / "fonts.conf"
            config.write_text(f'<fontconfig><dir>{escape(str(fonts))}</dir>'
                              f'<cachedir>{escape(str(root / "cache"))}</cachedir></fontconfig>')
            env = {**os.environ, "FONTCONFIG_FILE": str(config), "HOME": directory,
                   "XDG_CACHE_HOME": str(root / "cache")}

            def fc(*args):
                return subprocess.check_output(args, env=env, text=True).strip()

            for suffix, style in STYLES.items():
                font = fonts / f"IosevkaNerdFont-{suffix}.ttf"
                self.assertEqual(fc("fc-scan", "--format", "%{family[0]}|%{style[0]}", str(font)),
                                 f"Iosevka Nerd Font|{style}")
                charset = fc("fc-query", "--format", "%{charset}", str(font))
                ranges = [token.split("-") for token in charset.split()]
                for codepoint in (0x41, 0xE0B0, 0xF120):
                    self.assertTrue(any(int(r[0], 16) <= codepoint <= int(r[-1], 16)
                                        for r in ranges), hex(codepoint))
                    self.assertEqual(fc("fc-match", "--format", "%{file}",
                                        f"Iosevka Nerd Font:style={style}:charset={codepoint:x}"),
                                     str(font))


if __name__ == "__main__":
    unittest.main()
