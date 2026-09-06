"""Proof-builder tests use fake RPMs and commands, never host RPM or signing keys."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-zfs-rpms.sh"
KERNEL = "7.1.13-200.fc44.x86_64"
STUB = r'''
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
data = json.loads((root / "data.json").read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
kernel = data["kernel"]
if name == data.get("fail"):
    sys.exit(42)
if name == "openssl":
    if "-ext" in args:
        print("X509v3 Subject Key Identifier:\n    AB:CD")
    elif "-serial" in args:
        print("serial=1234")
    elif "-outform" in args or "-pubkey" in args:
        if "-pubin" in args:
            sys.stdin.read()
        print("public key")
elif name == "rpm":
    if "kernel-core" in args:
        print(kernel)
    elif "--whatprovides" in args:
        print(data.get("devel", kernel))
    elif "--requires" in args:
        print(data.get("requires", "kernel-uname-r = " + kernel))
    elif "--provides" in args:
        print(data.get("provides", "zfs-kmod = 2.4.4-1.fc44"))
    else:
        field = args[args.index("--qf") + 1]
        print({"%{NAME}": Path(args[-1]).stem, "%{VERSION}": "2.4.4",
               "%{ARCH}": "x86_64"}[field])
elif name == "make":
    ksrc = root / "usr/src/kernels" / kernel
    assert (ksrc / "certs/signing_key.pem").is_symlink() == (data["mode"] == "signed")
    assert not (root / "lib/modules" / kernel / "build").exists()
    for package in ["zfs", "libnvpair3", "libuutil3", "libzfs7", "libzpool7",
                    "kmod-zfs-" + kernel, "zfs-dkms", "zfs-test", "libzfs7-devel"]:
        if package != data.get("omit"):
            Path(package + ".rpm").touch()
elif name == "cpio":
    dest = Path.cwd() / "lib/modules" / kernel / "extra/zfs"
    dest.mkdir(parents=True)
    for module in ["spl", "zfs"]:
        (dest / (module + ".ko")).touch()
elif name == "modinfo":
    unsigned = data["mode"] == "unsigned-testing"
    print({"vermagic": kernel + " SMP", "signer": data.get("signer", "" if unsigned else "key"),
           "sig_key": data.get("sig_key", "" if unsigned else "12:34"),
           "sig_hashalgo": data.get("sig_hashalgo", "" if unsigned else "sha256")}[args[1]])
elif name not in ["dnf5", "rpm2cpio", "configure"]:
    raise RuntimeError((name, args))
'''


class ZFSBuildTests(unittest.TestCase):
    def run_build(self, changes=None, missing=None, mode="signed"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = {"kernel": KERNEL, "mode": mode, **(changes or {})}
            (root / "data.json").write_text(json.dumps(data))
            (root / "bin").mkdir()
            for command in ("openssl", "rpm", "dnf5", "make", "rpm2cpio", "cpio", "modinfo"):
                path = root / "bin" / command
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o755)
            for secret in ("zfs_signing_key", "zfs_signing_cert"):
                path = root / "run/secrets" / secret
                path.parent.mkdir(parents=True, exist_ok=True)
                if secret != missing and (mode != "unsigned-testing" or data.get("secrets")):
                    path.write_text("test placeholder, not a key")
            (root / ".dockerenv").touch()
            ksrc = root / "usr/src/kernels" / KERNEL
            (ksrc / "scripts").mkdir(parents=True)
            (ksrc / "Makefile").touch()
            sign = ksrc / "scripts/sign-file"
            sign.touch()
            sign.chmod(0o755)
            link = root / "lib/modules" / KERNEL / "build"
            link.parent.mkdir(parents=True)
            link.symlink_to(ksrc)
            source = root / "build/zfs-2.4.4"
            source.mkdir(parents=True)
            configure = source / "configure"
            configure.write_text("#!/bin/sh\nexit 0\n")
            configure.chmod(0o755)
            text = SCRIPT.read_text()
            # Redirect every builder-owned absolute path into the disposable tree.
            for path in ("/run/", "/.dockerenv", "/usr/src/", "/lib/modules/", "/build/", "/out"):
                text = re.sub(r"(?<![\w/-])" + re.escape(path), str(root) + path, text)
            result = subprocess.run(["bash", "-c", text], text=True, capture_output=True,
                                    env={**os.environ, "PATH": f"{root / 'bin'}:/usr/bin:/bin", "ZFS_BUILD_MODE": mode})
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()] if (root / "calls").exists() else []
            outputs = sorted(p.name for p in (root / "out").glob("*"))
            if "build-mode" in outputs:
                self.assertEqual((root / "out/build-mode").read_text(), mode + "\n")
            self.assertTrue(link.is_symlink(), result.stderr)
            self.assertFalse((ksrc / "certs/signing_key.pem").is_symlink())
            return result, calls, outputs

    def test_success_allowlist_and_exact_devel(self):
        result, calls, outputs = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(["dnf5", "-y", "install", f"kernel-devel-uname-r = {KERNEL}"], calls)
        self.assertIn(["rpm", "-q", "--whatprovides", "kernel-devel-uname-r", "--qf", r"%{VERSION}-%{RELEASE}.%{ARCH}\n"], calls)
        self.assertEqual(outputs, sorted(["PROOF.txt", "build-mode", "kernel-uname-r", "zfs-signing-cert.der"] +
                         [p + ".rpm" for p in ("zfs", "libnvpair3", "libuutil3", "libzfs7", "libzpool7", "kmod-zfs-" + KERNEL)]))
        make = next(c for c in calls if c[0] == "make")
        self.assertEqual(make[1:3], ["rpm-utils", "rpm-kmod"])
        self.assertIn("CONFIG_MODULE_COMPRESS_ALL=", make)
        kmod_defines = next(arg for arg in make if arg.startswith("RPM_DEFINE_KMOD="))
        self.assertIn('--define "debug_package %{nil}"', kmod_defines)

    def test_required_secrets_fail_before_transactions(self):
        for secret in ("zfs_signing_key", "zfs_signing_cert"):
            with self.subTest(secret=secret):
                result, calls, _ = self.run_build(missing=secret)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(calls)

    def test_unsigned_testing(self):
        result, calls, outputs = self.run_build(mode="unsigned-testing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build-mode", outputs)
        self.assertNotIn("zfs-signing-cert.der", outputs)
        self.assertEqual(len([p for p in outputs if p.endswith(".rpm")]), 6)
        self.assertFalse(any(c[0] == "openssl" for c in calls))
        for changes in ({"sig_key": "12:34"}, {"signer": "test key"},
                        {"sig_hashalgo": "sha256"}, {"secrets": True}, {"fail": "modinfo"},
                        {"devel": "wrong"}, {"omit": "zfs"}):
            with self.subTest(changes=changes):
                result, _, _ = self.run_build(changes, mode="unsigned-testing")
                self.assertNotEqual(result.returncode, 0)

    def test_invalid_mode(self):
        for mode in ("", "unsigned", "typo"):
            result, calls, _ = self.run_build(mode=mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_kernel_guards(self):
        for kernel in ("", KERNEL + "\n" + KERNEL, "../../bad"):
            with self.subTest(kernel=kernel):
                result, calls, _ = self.run_build({"kernel": kernel})
                self.assertIn("exactly one", result.stderr)
                self.assertFalse(any(c[0] == "dnf5" for c in calls))
        result, calls, _ = self.run_build({"devel": "wrong"})
        self.assertIn("exact kernel-devel", result.stderr)
        self.assertFalse(any(c[0] == "make" for c in calls))

    def test_package_and_signature_guards(self):
        for change, error in [({"requires": "kernel-uname-r >= " + KERNEL}, "exact kernel"),
                              ({"provides": "fake-zfs = 2.4.4"}, "real zfs-kmod"),
                              ({"sig_key": "DE:AD"}, "signing key mismatch"),
                              ({"omit": "libzfs7"}, "missing runtime RPM")]:
            with self.subTest(change=change):
                result, _, _ = self.run_build(change)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)

    def test_command_failures(self):
        for command in ("openssl", "rpm", "dnf5", "make", "rpm2cpio", "modinfo"):
            with self.subTest(command=command):
                result, _, _ = self.run_build({"fail": command})
                self.assertNotEqual(result.returncode, 0)

    def test_syntax_and_container_contract(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        container = (ROOT / "Containerfile.zfs").read_text()
        source, builder = container.split("FROM zfs-prerequisites AS zfs-builder")
        self.assertIn("AS zfs-source", source)
        self.assertNotIn("type=secret", source)
        self.assertIn("sha256:cc0e99fb83e3cf2bd34b073535cfa656dc817dfd29911a1c47546bb013e1c845", source)
        self.assertIn("2a3c70d55a37cc71618a95a60e81ad66530201eb118d37741dc92efcf848c8b1", source)
        self.assertIn("sha256sum --check --strict", source)
        self.assertIn("--proto-redir '=https'", source)
        prerequisites = source.split("AS zfs-prerequisites", 1)[1]
        self.assertNotIn("--exclude='kernel*'", prerequisites)
        self.assertIn('kernel-devel-uname-r = $kernel', prerequisites)
        self.assertIn('Module.symvers', prerequisites)
        for secret in ("zfs_signing_key", "zfs_signing_cert"):
            self.assertIn(f"type=secret,id={secret}", builder)
        self.assertIn("ARG ZFS_BUILD_MODE=signed", builder)
        self.assertIn("FROM scratch AS zfs-rpms", builder)
        script = SCRIPT.read_text()
        self.assertIn("./configure --with-config=all --with-spec=generic", script)
        self.assertIn('--with-linux="$ksrc" --with-linux-obj="$ksrc"', script)
        self.assertNotRegex(script, r"\buname\s+-r\b|\bgenrsa\b|\bgenpkey\b")
        self.assertIn('ln -s "$key"', script)


if __name__ == "__main__":
    unittest.main()
