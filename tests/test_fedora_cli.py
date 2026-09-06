"""Offline CLI installer tests: mocked system writes, real temporary cleanup."""

from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-fedora-cli.sh"
INSTALLER = SCRIPT.read_text()
GUARD = "[[ -f /run/.containerenv || -f /.dockerenv ]]"
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
mktemp() { /usr/bin/mktemp -d "$TMPDIR/cli.XXXXXXXX"; }
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
unzip() { record unzip "$@"; }
install() { record install "$@"; }
'''


class FedoraCliTests(unittest.TestCase):
    def run_installer(self, fail_at=0, arch="x86_64", container=True, corrupt=""):
        with tempfile.TemporaryDirectory() as directory:
            # Empty PATH prevents unmocked commands from touching the host.
            script = INSTALLER.replace(GUARD, "true" if container else "false")
            mocks = MOCKS
            if corrupt:
                mocks += r'''
curl() {
    record curl "$@"
    while [[ "$1" != --output ]]; do shift; done
    printf 'corrupted artifact\n' > "$2"
}
sha256sum() {
    local checksum
    IFS= read -r checksum
    record sha256sum "$@" "$checksum"
    if [[ "$checksum" == *"/$CORRUPT" ]]; then
        printf '%s\n' "$checksum" | /usr/bin/sha256sum "$@"
    fi
}
'''
            result = subprocess.run(
                ["/usr/bin/bash", "--noprofile", "--norc", "-c", mocks + script],
                env={"PATH": directory, "TMPDIR": directory, "ARCH": arch,
                     "FAIL_AT": str(fail_at), "CORRUPT": corrupt},
                capture_output=True, text=True,
            )
            self.assertEqual(list(Path(directory).iterdir()), [], "Temporary files leaked")
            return result

    def test_pins_https_verification_and_selected_binaries(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stdout.splitlines()
        self.assertEqual([line.split()[0] for line in calls],
                         ["curl", "sha256sum"] * 3 + ["tar", "unzip", "tar"] + ["install"] * 4)
        pins = [
            ("starship/starship", "1.26.0", "starship-x86_64-unknown-linux-musl.tar.gz",
             "b7c232b0e8249d8e55a40beb79c5c43a7d370f3f9408bd215deb0170daeaadf3"),
            ("sxyazi/yazi", "26.9.1", "yazi-x86_64-unknown-linux-musl.zip",
             "9b9c39decccf8cb0ff53a7d637d38f8a79d93bbd0099f4ea9c619ef6bb392f5d"),
            ("jesseduffield/lazygit", "0.65.0", "lazygit_0.65.0_linux_x86_64.tar.gz",
             "44d8e7dd1484b4a66e191bd4ab25a71e8b4b3a65ab122f838e65677ef58c5506"),
        ]
        for index, (repo, version, artifact, checksum) in enumerate(pins):
            self.assertIn("--fail --location --proto =https --proto-redir =https", calls[index * 2])
            self.assertTrue(calls[index * 2].endswith(
                f"https://github.com/{repo}/releases/download/v{version}/{artifact}"))
            self.assertIn(f"sha256sum --check --strict - {checksum}  ", calls[index * 2 + 1])
        for index, binary in ((6, "starship"), (8, "lazygit")):
            self.assertIn("--extract --gzip --no-same-owner", calls[index])
            self.assertTrue(calls[index].endswith(f" {binary}"))
        self.assertRegex(calls[7], r"^unzip -q \S+/yazi.zip yazi-x86_64-unknown-linux-musl/yazi "
                         r"yazi-x86_64-unknown-linux-musl/ya -d \S+$")
        for call, binary in zip(calls[9:], ("starship", "yazi", "ya", "lazygit")):
            self.assertRegex(call, rf"^install -Dm0755 \S+/{binary} /usr/bin/{binary}$")

    def test_every_command_failure_stops_and_cleans_up(self):
        for step in range(1, 14):
            with self.subTest(step=step):
                result = self.run_installer(fail_at=step)
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertEqual(len(result.stdout.splitlines()), step)
                if step <= 6:
                    self.assertNotIn("tar ", result.stdout)
                    self.assertNotIn("unzip ", result.stdout)
                if step <= 9:
                    self.assertNotIn("install ", result.stdout)

    def test_real_checksum_rejects_each_corrupted_artifact(self):
        for artifact in ("starship.tar.gz", "yazi.zip", "lazygit.tar.gz"):
            with self.subTest(artifact=artifact):
                result = self.run_installer(corrupt=artifact)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAILED", result.stdout)
                for command in ("tar ", "unzip ", "install "):
                    self.assertNotIn(command, result.stdout)

    def test_platform_guards_reject_before_download(self):
        for options, error in (({"arch": "aarch64"}, "require x86_64"),
                               ({"container": False}, "Container required")):
            with self.subTest(options=options):
                result = self.run_installer(**options)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn(error, result.stderr)

    def test_shell_syntax_and_container_guard(self):
        result = subprocess.run(["/usr/bin/bash", "-n", str(SCRIPT)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(GUARD, INSTALLER)


if __name__ == "__main__":
    unittest.main()
