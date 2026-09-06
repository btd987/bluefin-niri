"""Execute custom storage recipes with isolated, non-privileged command stubs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
JUST = shutil.which("just")


@unittest.skipUnless(JUST, "just is required")
class CustomCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        (self.bin / 'sh').symlink_to('/bin/sh')
        self.log = self.directory / "calls.jsonl"
        self.justfile = self.directory / "justfile"
        self.text = (ROOT / "system_files/usr/share/niri-system/justfile").read_text()
        # Relocate only the existence probe/helper path; never install a host helper.
        self.helper = self.directory / "fedora-zfs"
        self.justfile.write_text(self.text.replace("/usr/libexec/fedora-zfs", str(self.helper)))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("JUST_")}
        self.env.update(PATH=str(self.bin), CALL_LOG=str(self.log), TMPDIR=str(self.directory))
        for command in ("sudo", "lsblk", "findmnt"):
            self.stub(command)

    def stub(self, name, status=0, stdout=""):
        path = self.bin / name
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['CALL_LOG'], 'a') as stream:\n"
            "    stream.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + '\\n')\n"
            f"print({stdout!r}, end='')\n"
            f"sys.exit({status})\n"
        )
        path.chmod(0o755)

    def run_recipe(self, *args, input=""):
        return subprocess.run(
            [JUST, "--justfile", str(self.justfile), "--", *args],
            cwd=self.directory, env=self.env, text=True, capture_output=True, input=input,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_backup_argument_boundaries_and_no_shell_evaluation(self):
        for args in ((), ("home",), ("--reuse", "home"), ("--help",),
                     ("two words", "", "'\"; touch INJECTED; #", "$(touch INJECTED)",
                      "`touch INJECTED`", "*", "line\nbreak")):
            with self.subTest(args=args):
                result = self.run_recipe("setup-backup", *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls()[-1], ["sudo", "setup-backup", *args])
                self.assertFalse((self.directory / "INJECTED").exists())

    def test_backup_status_validates_before_sudo(self):
        for name in ("", "--all", "UPPER", "a/b", "a.service", "a@b", "a" * 33,
                     "$(touch INJECTED)", "a\nb"):
            with self.subTest(name=name):
                self.assertNotEqual(self.run_recipe("backup-status", name).returncode, 0)
                self.assertEqual(self.calls(), [])
        for name in ("home", "a" + "1" * 31):
            result = self.run_recipe("backup-status", name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls()[-1], ["sudo", "systemctl", "--system", "--no-pager",
                                               "status", f"backup@{name}.timer", f"backup@{name}.service"])

    def test_storage_without_zfs(self):
        result = self.run_recipe("storage-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["lsblk", "-f"], ["findmnt", "-r"]])

    def test_storage_with_zfs_and_failure_continues_read_only(self):
        self.stub("zpool", 7)
        self.stub("zfs")
        result = self.run_recipe("storage-status")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.calls(), [["lsblk", "-f"], ["findmnt", "-r"],
                                       ["zpool", "status"],
                                       ["zfs", "list", "-o", "name,type,used,available,mountpoint"]])

    def test_zfs_missing_is_clear_and_does_not_elevate(self):
        result = self.run_recipe("configure-zfs")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fedora-only", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_zfs_isolated_python_and_literal_name(self):
        self.helper.touch()
        for args, name in (((), "default"), (("data-snapshots",), "data-snapshots"),
                           (("$(touch INJECTED)",), "$(touch INJECTED)")):
            result = self.run_recipe("configure-zfs", *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls()[-1], ["sudo", "python3", "-I", str(self.helper), "enroll", name])
            self.assertFalse((self.directory / "INJECTED").exists())

    def test_privileged_command_failure_propagates(self):
        self.stub("sudo", 23)
        self.helper.touch()
        for args in (("setup-backup",), ("backup-status", "home"), ("configure-zfs",)):
            self.assertEqual(self.run_recipe(*args).returncode, 23)

    def test_raid_uses_isolated_python(self):
        result = self.run_recipe('setup-raid-maintenance')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [['sudo', 'python3', '-I', '/usr/bin/setup-raid-maintenance']])

    def test_storage_helper_missing_and_literal_enrollment(self):
        for args in (('zfs-storage-enroll', 'data'), ('zfs-storage-status',)):
            result = self.run_recipe(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Fedora-only', result.stderr)
            self.assertEqual(self.calls(), [])
        helper = Path(str(self.helper) + '-storage')
        helper.touch()
        for name in ('data', 'two words', '$(touch INJECTED)', "'\"; touch INJECTED; #"):
            result = self.run_recipe('zfs-storage-enroll', name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls()[-1], ['sudo', 'python3', '-I', str(helper), 'enroll', name])
            self.assertFalse((self.directory / 'INJECTED').exists())
        self.stub('python3')
        result = self.run_recipe('zfs-storage-status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1], ['python3', '-I', str(helper), 'status'])
        self.stub('python3', 23)
        self.assertEqual(self.run_recipe('zfs-storage-status').returncode, 23)


if __name__ == "__main__":
    unittest.main()
