"""Execute the Containerfile testing gates with mocked commands, never host writes."""
import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "Containerfile.fedora").read_text()
SCRIPTS = re.findall(r"^RUN /usr/bin/bash -euo pipefail <<'EOF'\n(.*?)\nEOF$",
                     TEXT, re.MULTILINE | re.DOTALL)
MOCKS = r'''
# Keep cleanup glob assertions independent of files on the test host.
set -f
record() { printf '%s\n' "$*" >&2; [[ "$*" != "$FAIL_AT" ]] || return 42; }
test() {
    record test "$@" || return
    case "$*" in
        '-x /usr/bin/niriusd') return 0 ;;
        '! -e /usr/share/zfs/zfs-signing-cert.der') [[ ${CERT_PRESENT:-0} == 0 ]] ;;
        '! -L /usr/share/zfs/zfs-signing-cert.der') [[ ${CERT_SYMLINK:-0} == 0 ]] ;;
        *) builtin test "$@" ;;
    esac
}
rpm() {
    record rpm "$@" || return
    if [[ $* == '--verify zfs' ]]; then
        [[ ${BAD_ZFS:-0} == 0 && ( ${DAMAGED_ZFS:-0} == 0 || ! -v editors_installed ) ]]
        return
    fi
    if [[ -v installed ]]; then printf '%s\n' "$AFTER_KERNEL";
    else printf '%s\n' "$KERNEL"; fi
}
openssl() { record openssl "$@" || return; printf '%s\n' "$SERIAL"; }
bash() {
    record bash "$@" || return
    if [[ $1 == /tmp/build.sh ]]; then
        [[ $VARIANT == fedora-niri ]] || return 1
        installed=1
    elif [[ $1 == /tmp/install-fedora-tools.sh || $1 == /tmp/install-fedora-editors.sh || $1 == /tmp/install-fedora-cli.sh || $1 == /tmp/install-sanoid.sh || $1 == /tmp/install-fedora-fonts.sh ]]; then
        installed=1
        if [[ $1 == /tmp/install-fedora-editors.sh ]]; then editors_installed=1; fi
    else
        if [[ $ZFS_BUILD_MODE == unsigned-testing ]]; then
            [[ "$*" == '/tmp/validate-zfs.sh 2.4.4 --unsigned-testing' ]] || return 1
        else
            [[ "$*" == '/tmp/validate-zfs.sh 2.4.4 12:34:AB:CD' ]] || return 1
        fi
    fi
}
depmod() { record depmod "$@"; }
dnf5() { record dnf5 "$@"; }
rm() { record rm "$@"; }
bootc() { record bootc "$@"; }
mktemp() { record mktemp "$@" || return; printf '%s\n' /tmp/fedora-smoke; }
sha256sum() {
    record sha256sum "$@" || return
    if [[ $* == '--check --strict -' ]]; then
        local hashes
        IFS= read -r hashes
        [[ $hashes == 'original daemon and service hashes' && ${CHANGED_ZFS:-0} == 0 ]]
    else
        [[ $* == '/sbin/zed /usr/lib/systemd/system/zfs-zed.service' && ! -v editors_installed ]] || return 1
        printf '%s\n' 'original daemon and service hashes'
    fi
}
zeditor() {
    record zeditor "$@" || return
    [[ $* == --version && $ZED_ALLOW_ROOT == true && $HOME == /tmp/fedora-smoke &&
       $XDG_CONFIG_HOME == "$HOME/config" && $XDG_CACHE_HOME == "$HOME/cache" &&
       $XDG_DATA_HOME == "$HOME/data" && $XDG_STATE_HOME == "$HOME/state" ]]
}
devpod() { record devpod "$@" || return; [[ $* == version && $HOME == /tmp/fedora-smoke ]]; }
starship() { record starship "$@" || return; [[ $* == --version && $HOME == /tmp/fedora-smoke ]]; }
yazi() { record yazi "$@" || return; [[ $* == --version && $HOME == /tmp/fedora-smoke ]]; }
ya() { record ya "$@" || return; [[ $* == --version && $HOME == /tmp/fedora-smoke ]]; }
lazygit() { record lazygit "$@" || return; [[ $* == --version && $HOME == /tmp/fedora-smoke ]]; }
nirius() { record nirius "$@" || return; [[ $* == --version && $HOME == /tmp/fedora-smoke ]]; }
'''


class FedoraBuildTests(unittest.TestCase):
    def run_gate(self, layer=0, **changes):
        env = dict(os.environ, KERNEL="7.1.13-200.fc44.x86_64",
                   AFTER_KERNEL="7.1.13-200.fc44.x86_64", SERIAL="serial=1234ABCD",
                   FAIL_AT="", ZFS_BUILD_MODE="unsigned-testing")
        env.update(changes)
        # Replace only the container marker probe; every mutating command is mocked.
        script = SCRIPTS[layer].replace('test -f /run/.containerenv || test -f /.dockerenv',
                                '[[ ${CONTAINER:-1} == 1 ]]')
        return subprocess.run(["bash", "--noprofile", "--norc", "-euo", "pipefail",
                               "-c", MOCKS + script], env=env,
                              capture_output=True, text=True)

    def test_success_and_order(self):
        self.assertEqual(len(SCRIPTS), 2)
        for layer, installers in enumerate((['/tmp/build.sh'], [
                '/tmp/install-fedora-tools.sh', '/tmp/install-fedora-editors.sh',
                '/tmp/install-fedora-cli.sh', '/tmp/install-sanoid.sh',
                '/tmp/install-fedora-fonts.sh'])):
            with self.subTest(layer=layer):
                result = self.run_gate(layer)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = result.stderr.splitlines()
                ordered = [f"bash {installer}" for installer in installers] + [
                    "test 7.1.13-200.fc44.x86_64 = 7.1.13-200.fc44.x86_64",
                    "depmod -a 7.1.13-200.fc44.x86_64",
                    "bash /tmp/validate-zfs.sh 2.4.4 --unsigned-testing",
                ]
                if layer == 1:
                    ordered += ["zeditor --version", "devpod version", "starship --version",
                                "yazi --version", "ya --version", "lazygit --version",
                                "nirius --version", "test -x /usr/bin/niriusd"]
                ordered += ["dnf5 clean all", "bootc container lint"]
                positions = [calls.index(call) for call in ordered]
                self.assertEqual(positions, sorted(positions))
                self.assertEqual(calls[-1], "bootc container lint")
                self.assertTrue(any(c.startswith(f"rm -rf {installers[0]}") for c in calls))
                if layer == 1:
                    self.assertEqual(calls.count("rpm --verify zfs"), 2)
                    self.assertLess(calls.index("rpm --verify zfs"), calls.index("bash /tmp/install-fedora-tools.sh"))
                    self.assertLess(calls.index("sha256sum /sbin/zed /usr/lib/systemd/system/zfs-zed.service"),
                                    calls.index("bash /tmp/install-fedora-editors.sh"))
                    check = calls.index("sha256sum --check --strict -")
                    self.assertLess(calls.index("bash /tmp/install-sanoid.sh"), check)
                    self.assertLess(calls.index("bash /tmp/install-fedora-fonts.sh"), check)
                    removal = calls.index("dnf5 -y remove kernel-devel")
                    self.assertLess(calls.index("bash /tmp/install-fedora-fonts.sh"), removal)
                    self.assertLess(removal, check)
                    self.assertEqual(calls[check + 1], "rpm --verify zfs")
                    self.assertTrue(any('/tmp/install-sanoid.sh' in c for c in calls if c.startswith('rm -rf ')))
                    self.assertTrue(any('/tmp/install-fedora-fonts.sh' in c for c in calls if c.startswith('rm -rf ')))
                    self.assertIn("rm -rf /var/log/dnf*", calls)
                    self.assertLess(calls.index("rm -rf -- /tmp/fedora-smoke"),
                                    calls.index("bootc container lint"))

    def test_explicit_modes_never_fall_back(self):
        for layer in range(len(SCRIPTS)):
            with self.subTest(layer=layer):
                unsigned = self.run_gate(layer, SERIAL="invalid")
                self.assertEqual(unsigned.returncode, 0, unsigned.stderr)
                self.assertNotIn("openssl", unsigned.stderr)
                signed = self.run_gate(layer, ZFS_BUILD_MODE="signed")
                self.assertEqual(signed.returncode, 0, signed.stderr)
                self.assertIn("bash /tmp/validate-zfs.sh 2.4.4 12:34:AB:CD", signed.stderr)
                self.assertNotIn("--unsigned-testing", signed.stderr)
                cert_failure = self.run_gate(
                    layer, ZFS_BUILD_MODE="signed",
                    FAIL_AT="openssl x509 -inform DER -in /usr/share/zfs/zfs-signing-cert.der -noout -serial",
                )
                self.assertNotEqual(cert_failure.returncode, 0)
                self.assertNotIn("bash /tmp/", cert_failure.stderr)
                for changes in ({"ZFS_BUILD_MODE": ""}, {"ZFS_BUILD_MODE": "unsigned"},
                                {"ZFS_BUILD_MODE": "--unsigned-testing"},
                                {"ZFS_BUILD_MODE": "unknown"}, {"CERT_PRESENT": "1"},
                                {"CERT_SYMLINK": "1"}):
                    with self.subTest(changes=changes):
                        result = self.run_gate(layer, **changes)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn("bash /tmp/", result.stderr)
                        self.assertNotIn("bootc container lint", result.stderr)

    def test_validator_rejects_unknown_flags_before_querying_host(self):
        for flag in ("--unsigned", "--unsigned-testing=1", "--unknown", ""):
            with self.subTest(flag=flag):
                result = subprocess.run(
                    ["bash", str(ROOT / "scripts/validate-zfs.sh"), "2.4.4", flag],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid signing key ID", result.stderr)

    def test_zfs_corruption_fails_closed(self):
        for changes in ({"BAD_ZFS": "1"}, {"DAMAGED_ZFS": "1"}, {"CHANGED_ZFS": "1"}):
            with self.subTest(changes=changes):
                result = self.run_gate(1, **changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("zeditor --version", result.stderr)
                self.assertNotIn("bootc container lint", result.stderr)
                if "BAD_ZFS" in changes:
                    self.assertNotIn("bash /tmp/install-fedora-editors.sh", result.stderr)

    def test_invalid_inputs_and_kernel_changes_fail_closed(self):
        for changes in ({"CONTAINER": "0"}, {"KERNEL": ""},
                        {"KERNEL": "../host"}, {"KERNEL": "a\nb"},
                        {"ZFS_BUILD_MODE": "signed", "SERIAL": "serial=XYZ"},
                        {"ZFS_BUILD_MODE": "signed", "SERIAL": "serial=123"},
                        {"AFTER_KERNEL": "7.1.14-200.fc44.x86_64"}):
            for layer in range(len(SCRIPTS)):
                with self.subTest(layer=layer, changes=changes):
                    result = self.run_gate(layer, **changes)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("bootc container lint", result.stderr)

    def test_each_command_failure_stops_build(self):
        for layer in range(len(SCRIPTS)):
            calls = self.run_gate(layer).stderr.splitlines()
            cleanup = "rm -rf -- /tmp/fedora-smoke"
            for call in set(calls):
                with self.subTest(layer=layer, call=call):
                    result = self.run_gate(layer, FAIL_AT=call)
                    self.assertNotEqual(result.returncode, 0)
                    expected = calls[:calls.index(call) + 1]
                    # An EXIT trap may clean temporary config, but no later build
                    # command (including the later layer's lint) may execute.
                    if layer == 1 and calls.index("mktemp -d") < calls.index(call) < calls.index("bootc container lint"):
                        expected += [cleanup]
                    self.assertEqual(result.stderr.splitlines(), expected)

    def test_explicit_copy_allowlist_and_syntax(self):
        self.assertIn("ARG BASE_IMAGE=localhost/zfs-runtime:unsigned-testing\n", TEXT)
        self.assertIn("ARG NIRIUS_IMAGE=localhost/nirius-artifact:testing\n", TEXT)
        self.assertIn("ARG ZFS_BUILD_MODE=unsigned-testing\n", TEXT)
        self.assertEqual(re.findall(r"^FROM (.+)$", TEXT, re.MULTILINE),
                         ["${NIRIUS_IMAGE} AS nirius-artifact", "${BASE_IMAGE}"])
        self.assertEqual([line for line in TEXT.splitlines() if line.startswith("COPY")], [
            "COPY build.sh /tmp/build.sh", "COPY system_files /tmp/system_files",
            "COPY fedora_files /tmp/fedora_files",
            "COPY scripts/validate-zfs.sh /tmp/validate-zfs.sh",
            "COPY --from=nirius-artifact /nirius /niriusd /usr/bin/",
            "COPY --from=nirius-artifact /provenance.txt /usr/share/niri-system/nirius-provenance.txt",
            "COPY scripts/install-fedora-tools.sh scripts/install-fedora-editors.sh scripts/install-fedora-cli.sh scripts/install-sanoid.sh scripts/install-fedora-fonts.sh scripts/validate-zfs.sh /tmp/",
        ])
        self.assertLess(TEXT.index("\nEOF"), TEXT.index("COPY scripts/install-fedora-tools.sh"))
        self.assertNotIn("type=secret", TEXT)
        for script in SCRIPTS:
            subprocess.run(["bash", "-n"], input=script, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
