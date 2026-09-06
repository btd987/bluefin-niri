"""Offline installer tests: empty PATH, mocked writes, real temporary cleanup."""

from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-fedora-editors.sh"
INSTALLER = SCRIPT.read_text()
MOCKS = r'''
record() {
    local count=0
    [[ ! -f "$workdir/count" ]] || IFS= read -r count < "$workdir/count"
    count=$((count + 1))
    printf '%s\n' "$count" > "$workdir/count"
    printf '%s\n' "$*"
    [[ "$count" != "$FAIL_AT" ]] || return 42
}
uname() { printf '%s\n' "$ARCH"; }
mktemp() { /usr/bin/mktemp -d "$TMPDIR/editors.XXXXXXXX"; }
rm() {
    [[ "$*" == "-rf -- $TMPDIR/"* ]] || return 99
    /usr/bin/rm "$@"
}
curl() { record curl "$@"; }
sha256sum() {
    local checksum
    IFS= read -r checksum
    record sha256sum "$@" "$checksum"
}
tar() { record tar "$@"; }
sed() { record sed "$@" >&2; }
cp() { record cp "$@"; }
install() {
    record install "$@"
    if [[ "$*" == *'/usr/bin/zeditor' ]]; then
        while IFS= read -r line; do printf 'wrapper: %s\n' "$line"; done < "$2"
    fi
}
'''


class FedoraEditorsTests(unittest.TestCase):
    def run_installer(self, fail_at=0, arch="x86_64", real_checksum=False):
        with tempfile.TemporaryDirectory() as directory:
            # The sole platform probe is mocked separately; no container is needed
            # to exercise control flow. Empty PATH prevents unmocked commands from
            # reaching the host. All real writes are confined to this temp directory.
            script = INSTALLER.replace(
                "[[ -f /run/.containerenv || -f /.dockerenv ]]", "true"
            )
            mocks = MOCKS
            if real_checksum:
                mocks += r'''
curl() {
    record curl "$@"
    while [[ "$1" != --output ]]; do shift; done
    printf 'corrupted artifact\n' > "$2"
}
sha256sum() { /usr/bin/sha256sum "$@"; }
'''
            result = subprocess.run(
                ["/usr/bin/bash", "--noprofile", "--norc", "-c", mocks + script],
                env={"PATH": directory, "TMPDIR": directory,
                     "ARCH": arch, "FAIL_AT": str(fail_at)},
                capture_output=True, text=True,
            )
            self.assertEqual(list(Path(directory).iterdir()), [], "Temporary files leaked")
            return result

    def test_pinned_verified_install_and_system_integration(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stdout.splitlines()
        self.assertEqual([line.split()[0] for line in calls[:5]],
                         ["curl", "sha256sum", "curl", "sha256sum", "tar"])
        self.assertIn("/v1.18.1/zed-linux-x86_64.tar.gz", calls[0])
        self.assertIn("/v0.6.15/devpod-linux-amd64", calls[2])
        for index in (0, 2):
            self.assertIn("--fail --location --proto =https --proto-redir =https", calls[index])
        for index, checksum in ((1, "eea62268d8ec5fd3587df06fa76e072c104cca5e0b0b0abecbc28ae5b87c0bad"),
                                (3, "cc50bce09229d5a6d448ac1d4494327f4b8f7a20321e5fcee3bfec1aef0d20c5")):
            self.assertIn(f"sha256sum --check --strict - {checksum}  ", calls[index])
        self.assertIn("--no-same-owner", calls[4])
        self.assertTrue(calls[4].endswith(" zed.app"))
        self.assertIn("install -dm0755 /usr/lib/zed", calls)
        self.assertRegex(result.stdout, r"cp -R .*/zed.app/\. /usr/lib/zed/")
        self.assertIn('wrapper: exec /usr/lib/zed/bin/zed "$@"', calls)
        self.assertIn('wrapper: export ZED_UPDATE_EXPLANATION="Zed is image-managed.', result.stdout)
        self.assertIn("Exec=/usr/bin/zeditor|", result.stderr)
        self.assertIn("TryExec=/usr/bin/zeditor|", result.stderr)
        self.assertRegex(result.stdout, r"install -Dm0755 .*/zeditor /usr/bin/zeditor\n")
        self.assertNotRegex(result.stdout + result.stderr, r"/usr/(?:s?bin)/zed(?:\s|\||$)")
        self.assertNotIn("ln ", INSTALLER)
        self.assertIn("Icon=/usr/share/icons/hicolor/512x512/apps/zed.png", result.stderr)
        self.assertRegex(result.stdout, r"install -Dm0644 .* /usr/share/applications/dev.zed.Zed.desktop")
        for size in (512, 1024):
            self.assertIn(f" /usr/share/icons/hicolor/{size}x{size}/apps/zed.png", result.stdout)
        self.assertRegex(calls[-1], r"install -Dm0755 .*/devpod /usr/bin/devpod$")

    def test_every_command_failure_stops_and_cleans_up(self):
        # sed records on stderr because its stdout is the generated desktop file.
        for step in range(1, 14):
            with self.subTest(step=step):
                result = self.run_installer(fail_at=step)
                self.assertEqual(result.returncode, 42, result.stderr)
                calls = [line for line in (result.stdout + result.stderr).splitlines()
                         if not line.startswith("wrapper:")]
                self.assertEqual(len(calls), step)
                if step <= 6:
                    self.assertNotIn("install ", result.stdout)

    def test_real_checksum_rejects_corrupted_download(self):
        result = self.run_installer(real_checksum=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout)
        self.assertNotIn("tar ", result.stdout)
        self.assertNotIn("install ", result.stdout)

    def test_unsupported_architecture_rejected_before_download(self):
        result = self.run_installer(arch="aarch64")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("require x86_64", result.stderr)

    def test_shell_syntax_and_container_guard(self):
        result = subprocess.run(["/usr/bin/bash", "-n", str(SCRIPT)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[ -f /run/.containerenv || -f /.dockerenv ]]", INSTALLER)


if __name__ == "__main__":
    unittest.main()
