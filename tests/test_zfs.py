"""Isolated metadata checks, never querying host packages or modules.

Run: python3 -m unittest discover -s tests -p test_zfs.py -v
These tests do not establish cryptographic signature validity or bootability.
"""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate-zfs.sh"
KERNEL = "6.19.8-200.fc44.x86_64"
VERSION = "2.4.1"
KEY = "AB:CD:12:34"
STUB = r'''
import json
from pathlib import Path
import sys

root = Path(__file__).parent
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
data = json.loads((root / "data.json").read_text())
call = [name, *args]
if call == data.get("fail"):
    sys.exit(42)
if name == "rpm" and args == ["-q", "--qf", "%{VERSION}-%{RELEASE}.%{ARCH}\\n", "kernel-core"]:
    value = data["kernel"]
elif name == "rpm" and args == ["-q", "--qf", "%{VERSION}\\n", "zfs"]:
    value = data["userspace"]
elif name == "rpm" and args == ["-qa", "--qf", "%{NAME}\\n"]:
    value = data["packages"]
elif name == "modinfo" and len(args) == 5 and args[:3] == ["-k", data["kernel"], "-F"]:
    value = data["modules"][args[4]][args[3]]
elif name == "modprobe" and args == ["--set-version", data["kernel"], "--show-depends", "zfs"]:
    value = data["dependencies"]
else:
    raise RuntimeError(f"Unexpected command: {call}")
print(value)
'''


class ZFSTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "kernel": KERNEL,
            "userspace": VERSION,
            "packages": "kernel-core\nzfs\nkmod-zfs",
            "modules": {
                module: {
                    "version": VERSION + "-1",
                    "vermagic": KERNEL + " SMP preempt mod_unload modversions ",
                    "filename": f"/lib/modules/{KERNEL}/extra/{module}.ko.xz",
                    "signer": "Build signing key",
                    "sig_key": KEY,
                    "sig_hashalgo": "sha256",
                }
                for module in ("spl", "zfs")
            },
            "dependencies": f"insmod /lib/modules/{KERNEL}/extra/spl.ko.xz\n"
                            f"insmod /lib/modules/{KERNEL}/extra/zfs.ko.xz",
        }

    def run_validator(self, args=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("rpm", "modinfo", "modprobe"):
                stub = root / name
                stub.write_text(f"#!{sys.executable}\n" + STUB)
                stub.chmod(0o755)
            (root / "data.json").write_text(json.dumps(self.data))
            result = subprocess.run(
                [shutil.which("bash"), str(SCRIPT),
                 *(args if args is not None else [VERSION, KEY])],
                cwd=root, env={"PATH": tmp, "LC_ALL": "C"},
                capture_output=True, text=True,
            )
            calls = root / "calls"
            return result, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    def assert_rejected(self, message):
        result, _ = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)

    def test_valid(self):
        for prefix in ("/lib", "/usr/lib"):
            with self.subTest(prefix=prefix):
                for module, fields in self.data["modules"].items():
                    fields["filename"] = f"{prefix}/modules/{KERNEL}/extra/{module}.ko.zst"
                result, calls = self.run_validator()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(KERNEL, result.stdout)
                self.assertEqual(len(calls), 16)
                self.assertEqual(calls[-1], ["modprobe", "--set-version", KERNEL, "--show-depends", "zfs"])
                self.assertEqual({tuple(call[1:3]) for call in calls if call[0] == "modinfo"}, {("-k", KERNEL)})

    def test_arguments(self):
        for args in ([], [VERSION], [VERSION, KEY, "extra"],
                     ["2.4", KEY], ["2.4.1-1", KEY], ["02.4.1", KEY],
                     ["2.4.1\n", KEY], [".*", KEY], [VERSION, ""],
                     [VERSION, "not-a-key"]):
            with self.subTest(args=args):
                result, calls = self.run_validator(args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_kernel_count_and_format(self):
        for kernel in ("", KERNEL + "\n" + KERNEL, KERNEL + "\n6.18.1-1.fc44.x86_64",
                       "../../host", "6.19.8", "6.19.8-../host.x86_64"):
            with self.subTest(kernel=kernel):
                self.data["kernel"] = kernel
                self.assert_rejected("exactly one installed kernel-core")

    def test_userspace_mismatch(self):
        for version in ("", "2.4.0", VERSION + "-1", VERSION + "\n" + VERSION):
            with self.subTest(version=version):
                self.data["userspace"] = version
                self.assert_rejected("userspace version mismatch")

    def test_forbidden_packages(self):
        for package in ("dkms", "zfs-dkms", "akmod-zfs"):
            with self.subTest(package=package):
                self.data["packages"] = "kernel-core\nzfs\n" + package
                self.assert_rejected("forbidden runtime package: " + package)
        self.data["packages"] = ""
        self.assert_rejected("empty installed package list")

    def test_bad_module_metadata(self):
        original = copy.deepcopy(self.data)
        invalid = {
            "version": ["", "2.4.10", "2.4.1evil", "2.3.0", VERSION + "\nother"],
            "vermagic": ["", "6.18.1-1.fc44.x86_64 SMP", KERNEL + "extra SMP"],
            "filename": ["", "(builtin)", "/tmp/zfs.ko", "/lib/modules/other/zfs.ko",
                         f"/lib/modules/{KERNEL}extra/zfs.ko", f"/lib/modules/{KERNEL}/../zfs.ko",
                         f"/usr/lib/modules/{KERNEL}/extra/../../zfs.ko", f"/lib/modules/{KERNEL}/"],
            "signer": ["", " \t", "key\nother"],
            "sig_key": ["", "00:11", KEY.lower()],
            "sig_hashalgo": ["", "sha512", "SHA256"],
        }
        for module in ("spl", "zfs"):
            for field, values in invalid.items():
                for value in values:
                    with self.subTest(module=module, field=field, value=value):
                        self.data = copy.deepcopy(original)
                        self.data["modules"][module][field] = value
                        self.assert_rejected(module + ":")

    def test_every_command_failure_including_missing_modules(self):
        result, calls = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in calls:
            with self.subTest(call=call):
                self.data["fail"] = call
                self.assert_rejected("ZFS validation failed:")

    def test_empty_dependencies(self):
        for dependencies in ("", " \t"):
            self.data["dependencies"] = dependencies
            self.assert_rejected("empty zfs dependency resolution")


if __name__ == "__main__":
    unittest.main()
