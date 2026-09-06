"""Runtime helper tests redirect all writes and mock all system commands."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-zfs-rpms.sh"
KERNEL = "7.1.13-200.fc44.x86_64"
NAMES = ["zfs", "libnvpair3", "libuutil3", "libzfs7", "libzpool7", "kmod-zfs-" + KERNEL]
EVRA = "0:2.4.4-1.fc44.x86_64"
FINGERPRINT = "A" * 40
STUB = r'''
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
data = json.loads((root / "data.json").read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if [name, *args] == data.get("fail") or (data.get("fail_install") and name == "dnf5" and "install" in args):
    sys.exit(42)
if name == "rpm":
    if "--import" in args:
        sys.exit(data.get("import_status", 0))
    elif "--checksig" in args:
        print(data.get("signature", "    Header OpenPGP V4 RSA/SHA512 signature, key ID aaaaaaaa: OK\n    Payload SHA256 digest: OK"))
        sys.exit(data.get("signature_status", 0))
    elif "kernel-core" in args:
        print(data.get("after_kernel" if (root / "installed").exists() else "kernel", data["kernel"]))
    elif "--requires" in args:
        print(data.get("requires", "kernel-uname-r = " + data["kernel"]))
    elif "--provides" in args:
        print(data.get("provides", "zfs-kmod = 2.4.4-1.fc44"))
    elif args[args.index("--qf") + 1] == "%{NAME}":
        print(data.get("names", {}).get(Path(args[-1]).stem, Path(args[-1]).stem))
    else:
        print(data.get("evra" if "-qp" in args else "installed_evra", "0:2.4.4-1.fc44.x86_64"))
elif name == "openssl":
    print(data.get("serial", "serial=1234ABCD"))
elif name == "gpg":
    if "--list-keys" in args or "--list-secret-keys" in args:
        kind = "sec" if "--list-secret-keys" in args else "pub"
        for fingerprint in data.get("fingerprints", ["A" * 40]):
            print(kind + ":-:3072:1:AAAAAAAAAAAAAAAA:0:0:::::scSC:")
            print("fpr:::::::::" + fingerprint + ":")
    elif "--export" in args:
        print("public key fixture")
    else:
        sys.exit(data.get("gpg_import_status", 0))
elif name == "stat":
    print(data.get("filesystem", "tmpfs"))
elif name == "rpmsign":
    sys.exit(data.get("sign_status", 0))
elif name == "gpgconf":
    assert args == ["--kill", "all"]
elif name == "dnf5":
    if "install" in args:
        preset = root / "usr/lib/systemd/system-preset/00-zfs-unpublished.preset"
        lines = preset.read_text().splitlines()
        assert "disable zfs-import-cache.service" in lines
        assert "disable zfs-import-scan.service" in lines
        assert "disable zfs-import.target" in lines
        assert "disable zfs-mount.service" in lines
        assert "disable zfs-share.service" in lines
        assert "disable zfs-zed.service" in lines
        assert all(line.startswith("disable zfs") for line in lines)
        (root / "installed").touch()
elif name == "systemctl":
    assert args == ["--root=/", "list-unit-files", "--no-legend", "--no-pager", "zfs*"]
    print(data.get("units", "zfs.target disabled disabled\nzfs-import.service masked disabled\nzfs-scrub@.service static -"))
elif name == "validate-zfs":
    assert args == ["2.4.4", "--unsigned-testing" if data["mode"] == "unsigned-testing" else "12:34:AB:CD"]
elif name == "bootc":
    assert args == ["container", "lint"]
    for path in data["residue"]:
        assert not (root / path).exists(), path
    assert (root / "var/lib/pcp/keep").exists()
elif name != "depmod":
    raise RuntimeError((name, args))
'''


class ZFSRuntimeTests(unittest.TestCase):
    def run_install(self, changes=None, packages=None, container=True, mode="unsigned-proof", fingerprint=""):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            residue = ["tmp/zfs-runtime", "var/cache/libdnf5", "var/lib/dnf", "var/lib/dnf5",
                       "run/dnf", "run/selinux-policy", "var/log/dnf5.log",
                       "var/log/dnf.rpm.log.1", "var/cache/ldconfig/aux-cache"]
            data = {"kernel": KERNEL, "residue": residue, "mode": mode, **(changes or {})}
            (root / "data.json").write_text(json.dumps(data))
            (root / "bin").mkdir()
            for command in ("rpm", "openssl", "dnf5", "systemctl", "depmod", "bootc", "validate-zfs", "gpg", "gpgconf"):
                path = root / "bin" / command
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o755)
            if container:
                (root / ".dockerenv").touch()
            for path in [*residue, "var/lib/pcp/keep"]:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                if path == "tmp/zfs-runtime":
                    target.mkdir()
                else:
                    target.write_text("transaction fixture")
            (root / "tmp/zfs-runtime/validate-zfs.sh").write_text('exec validate-zfs "$@"\n')
            artifacts = root / "run/zfs-rpms"
            artifacts.mkdir(parents=True)
            (artifacts / "kernel-uname-r").write_text(data.get("artifact_kernel", KERNEL))
            if not data.get("missing_marker"):
                (artifacts / "build-mode").write_text(data.get("marker", "unsigned-testing" if mode == "unsigned-testing" else "signed") + "\n")
            if mode != "unsigned-testing" or data.get("certificate"):
                (artifacts / "zfs-signing-cert.der").write_text("public certificate fixture")
            if (mode != "unsigned-testing" or data.get("public_key")) and not data.get("missing_key"):
                (artifacts / "zfs-rpm-signing-key.asc").write_text("public key fixture")
            for name in packages if packages is not None else NAMES:
                (artifacts / (name + ".rpm")).touch()
            text = SCRIPT.read_text()
            # No test-only production switch. Redirect every filesystem root,
            # including cleanup destinations; systemctl itself is always mocked.
            text = re.sub(r"(?<![\w/-])(/run/|/\.dockerenv|/usr/|/tmp/|/var/)",
                          lambda match: str(root) + match[0], text)
            result = subprocess.run(["bash", "-c", text], capture_output=True, text=True,
                                    env={**os.environ, "PATH": f"{root / 'bin'}:/usr/bin:/bin",
                                         "ZFS_RPM_TRUST_MODE": mode,
                                         "ZFS_RPM_SIGNING_FINGERPRINT": fingerprint})
            self.assertEqual(list((root / "tmp").glob("zfs-rpm-trust.*")), [])
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()] if (root / "calls").exists() else []
            cert = (root / "usr/share/zfs/zfs-signing-cert.der").exists()
            return result, calls, cert

    def test_success_order_trust_and_cleanup(self):
        result, calls, cert = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(cert)
        transaction = next(c for c in calls if c[0] == "dnf5" and "install" in c)
        self.assertEqual(transaction[1:6], ["-y", "--setopt=gpgcheck=1", "--setopt=localpkg_gpgcheck=0", "--exclude=kernel*", "install"])
        self.assertEqual(len(transaction[6:]), 6)
        commands = [c[0] for c in calls]
        self.assertLess(commands.index("dnf5"), commands.index("systemctl"))
        self.assertLess(commands.index("systemctl"), commands.index("depmod"))
        self.assertLess(commands.index("depmod"), commands.index("validate-zfs"))
        self.assertEqual(calls[-2:], [["dnf5", "clean", "all"], ["bootc", "container", "lint"]])
        self.assertIn(["depmod", "-a", KERNEL], calls)

    def test_verified_trust(self):
        result, calls, _ = self.run_install(mode="verified", fingerprint=FINGERPRINT)
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = [c for c in calls if "--checksig" in c]
        self.assertEqual(len(checks), 6)
        self.assertTrue(all("--dbpath" in c for c in checks))
        imports = [c for c in calls if c[0] == "rpm" and "--import" in c]
        self.assertEqual(len(imports), 2)
        self.assertIn("--dbpath", imports[0])
        self.assertNotIn("--dbpath", imports[1])
        self.assertLess(calls.index(checks[-1]), calls.index(imports[1]))
        transaction = next(c for c in calls if c[0] == "dnf5" and "install" in c)
        self.assertIn("--setopt=localpkg_gpgcheck=1", transaction)

    def test_unsigned_testing(self):
        result, calls, cert = self.run_install(mode="unsigned-testing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(cert)
        self.assertFalse(any(c[0] in ("openssl", "gpg", "gpgconf") for c in calls))
        self.assertIn(["validate-zfs", "2.4.4", "--unsigned-testing"], calls)
        transaction = next(c for c in calls if c[0] == "dnf5" and "install" in c)
        self.assertIn("--setopt=gpgcheck=1", transaction)
        self.assertIn("--setopt=localpkg_gpgcheck=0", transaction)
        self.assertEqual(len(transaction[transaction.index("install") + 1:]), 6)
        for changes in ({"missing_marker": True}, {"marker": "signed"}, {"marker": "typo"},
                        {"marker": ""}, {"certificate": True}, {"public_key": True}):
            with self.subTest(changes=changes):
                result, calls, _ = self.run_install(changes, mode="unsigned-testing")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_verified_rejects_untrusted_before_install(self):
        cases = [{"missing_key": True}, {"fingerprints": []}, {"fingerprints": ["B" * 40]},
                 {"fingerprints": [FINGERPRINT, "B" * 40]}, {"gpg_import_status": 2},
                 {"import_status": 1}, {"signature_status": 1},
                 {"signature": "    Header SHA256 digest: OK\n    Payload SHA256 digest: OK"},
                 {"signature": "    Header RSA/SHA256 Signature, key ID aaaaaaaa: NOKEY"},
                 {"signature": "    Header RSA/SHA256 Signature, key ID aaaaaaaa: BAD"},
                 {"signature": "    Header RSA/SHA256 Signature, key ID aaaaaaaa: OK\n    Payload SHA256 digest: BAD"}]
        for changes in cases:
            with self.subTest(changes=changes):
                result, calls, _ = self.run_install(changes, mode="verified", fingerprint=FINGERPRINT)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] == "dnf5" for c in calls))
                self.assertFalse(any(c[:2] == ["rpm", "--import"] for c in calls))
        for mode, fingerprint in (("verified", ""), ("verified", "A" * 16),
                                  ("verified", "a" * 40), ("unsigned-proof", FINGERPRINT),
                                  ("unsigned-testing", FINGERPRINT), ("", ""), ("typo", "")):
            result, calls, _ = self.run_install(mode=mode, fingerprint=fingerprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_reject_before_install(self):
        cases = [{"kernel": ""}, {"kernel": KERNEL + "\n" + KERNEL},
                 {"kernel": "../../host"}, {"artifact_kernel": "wrong"},
                 {"serial": "serial=not-hex"}, {"requires": "kernel-uname-r >= " + KERNEL},
                 {"provides": "dummy-zfs-kmod = 2.4.4-1.fc44"},
                 {"names": {"libzfs7": "zfs"}}]
        cases += [{"evra": value} for value in ("1:2.4.4-1.fc44.x86_64", "0:2.4.5-1.fc44.x86_64",
                  "0:2.4.4-2.fc44.x86_64", "0:2.4.4-1.fc44.aarch64", EVRA + "\n" + EVRA)]
        for changes in cases:
            with self.subTest(changes=changes):
                result, calls, _ = self.run_install(changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] == "dnf5" for c in calls))
        for packages in (NAMES[:-1], NAMES + ["zfs-devel"], NAMES[:-1] + ["zfs-dkms"]):
            result, calls, _ = self.run_install(packages=packages)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(c[0] == "dnf5" for c in calls))
        result, calls, _ = self.run_install(container=False)
        self.assertIn("container required", result.stderr)
        self.assertEqual(calls, [])

    def test_post_transaction_guards(self):
        cases = [{"after_kernel": "wrong"}, {"installed_evra": "wrong"}, {"units": ""}]
        cases += [{"units": f"zfs-mount.service {state} disabled"} for state in
                  ("enabled", "enabled-runtime", "linked", "linked-runtime", "alias")]
        for changes in cases:
            with self.subTest(changes=changes):
                result, calls, _ = self.run_install(changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] == "depmod" for c in calls))

    def test_command_failures(self):
        result, calls, _ = self.run_install({"fail_install": True})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c[0] == "systemctl" for c in calls))
        result, calls, _ = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Unique queries plus every mutating/verification command must fail closed.
        for call in {tuple(c) for c in calls if c[0] != "dnf5" or "install" not in c}:
            if any("/run/zfs-rpms/" in arg for arg in call):
                continue  # Temporary artifact paths differ on the next run.
            with self.subTest(call=call):
                result, _, _ = self.run_install({"fail": list(call)})
                self.assertNotEqual(result.returncode, 0)

    def test_container_contract_and_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        source = (ROOT / "Containerfile.zfs").read_text()
        base = source.splitlines()[3].split(" AS ")[0]
        for filename, stage in (("Containerfile.zfs", "zfs-builder,source=/out"),
                                ("Containerfile.zfs-runtime", "zfs-rpm-artifacts,source=/")):
            text = (ROOT / filename).read_text()
            runtime = text.split(base + " AS zfs-runtime\n")[1]
            self.assertIn(f"from={stage},target=/run/zfs-rpms", runtime)
            self.assertNotIn("type=secret", runtime)
            self.assertIn("bash /tmp/zfs-runtime/install-zfs-rpms.sh", runtime)
        script = SCRIPT.read_text()
        self.assertNotRegex(script, r"\b(zpool|modprobe|insmod|genrsa|genpkey)\s")
        self.assertNotIn("--nogpgcheck", script)
        self.assertNotIn("--setopt=gpgcheck=0", script)
        self.assertNotRegex(script, r"systemctl[^\n]*\b(start|enable|mask|unmask)\b")


@unittest.skipUnless(all(os.environ.get(name) for name in
                        ("ZFS_SIGNED_TEST_IMAGE", "ZFS_UNSIGNED_TEST_IMAGE", "ZFS_TEST_FINGERPRINT")),
                     "requires disposable signed/unsigned artifact images and a test fingerprint")
class ZFSRealTrustTests(unittest.TestCase):
    def test_real_rpm_rejections(self):
        # All mutation and key imports occur in throwaway containers, never on
        # the host. No private key is needed; use only disposable proof images.
        image = os.environ["ZFS_SIGNED_TEST_IMAGE"]
        fingerprint = os.environ["ZFS_TEST_FINGERPRINT"]
        base = (ROOT / "Containerfile.zfs-runtime").read_text().split("FROM ")[2].split()[0]
        cases = [
            ("", "", "expected full uppercase"),
            ("B" * 40 if fingerprint != "B" * 40 else "A" * 40, "", "fingerprint mismatch"),
            (fingerprint, "rm /run/zfs-rpms/zfs-rpm-signing-key.asc", "RPM public key required"),
            (fingerprint, "cp /unsigned/*.rpm /run/zfs-rpms/", "RPM has no trusted signature"),
            (fingerprint, "truncate -s 1024 /run/zfs-rpms/*.rpm", "RPM signature verification failed"),
        ]
        for expected, mutation, error in cases:
            with self.subTest(error=error):
                shell = "mkdir /run/zfs-rpms && cp /proof/* /run/zfs-rpms/ && "
                if mutation:
                    shell += mutation + " && "
                shell += "bash -s"
                result = subprocess.run([
                    "podman", "run", "--rm", "-i", "--network=none",
                    "--mount", f"type=image,src={image},target=/proof",
                    "--mount", f"type=image,src={os.environ['ZFS_UNSIGNED_TEST_IMAGE']},target=/unsigned",
                    "--env", "ZFS_RPM_TRUST_MODE=verified",
                    "--env", f"ZFS_RPM_SIGNING_FINGERPRINT={expected}",
                    base, "bash", "-euc", shell,
                ], input=SCRIPT.read_text(), capture_output=True, text=True, timeout=120)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)


if __name__ == "__main__":
    unittest.main()
