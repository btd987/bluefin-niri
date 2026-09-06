"""Check shared recipes and ujust imports without running system operations."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SHARE = Path(__file__).resolve().parents[1] / "system_files/usr/share"
COMMANDS = {
    "niri-session", "niri-reload", "niri-version", "setup-snapshots",
    "list-snapshots", "snapshot", "btrfs-assistant", "setup-home-backup",
    "home-backup-status", "configure-snapshots-dev", "download-virtio-win",
    "setup-libvirt", "virt-network-start", "virt-status", "virt-monitor",
    "virt-manager", "download-windows-iso", "vfio-check", "vfio-kargs",
    "vfio-setup", "setup-podman-desktop", "setup-backup", "backup-status",
    "storage-status", "configure-zfs", "enable-snapshot-timers",
    "configure-snapshot-schedule", "setup-devpod-podman",
    "setup-raid-maintenance", "zfs-storage-enroll", "zfs-storage-status",
}


@unittest.skipUnless(shutil.which("just"), "just is required")
class JustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.shared = self.directory / "usr/share/niri-system/justfile"
        self.compat = self.directory / "usr/share/ublue-os/just/60-custom.just"
        for source, target in (
            (SHARE / "niri-system/justfile", self.shared),
            (SHARE / "ublue-os/just/60-custom.just", self.compat),
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.root = self.compat.parent.parent / "justfile"
        # Match the installed ujust root's settings and optional custom import.
        self.root.write_text(
            "set allow-duplicate-recipes := true\n"
            "set ignore-comments := true\n"
            "_default:\n    @echo upstream-default\n"
            "upstream-command:\n    @echo upstream-command\n"
            "import? 'just/60-custom.just'\n"
        )
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("JUST_")}
        self.env["TMPDIR"] = str(self.directory)

    def just(self, justfile, *args, check=True):
        result = subprocess.run(
            ["just", "--justfile", str(justfile), *args],
            cwd=self.directory, env=self.env, text=True, capture_output=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_parse_and_public_inventory(self):
        for entry, extra in (
            (self.shared, set()), (self.compat, set()),
            (self.root, {"_default", "upstream-command"}),
        ):
            with self.subTest(entry=entry):
                data = json.loads(self.just(entry, "--dump", "--dump-format", "json").stdout)
                self.assertEqual(set(data["recipes"]), COMMANDS | extra | {"_validate-snapshot-config"})
                listing = self.just(entry, "--list").stdout
                for command in COMMANDS:
                    self.assertIn(command, listing)
                self.assertIn('snapshot desc="manual"', listing)
                for group in ("Desktop", "System", "Virtualization"):
                    self.assertIn(f"[{group}]", listing)

    def test_all_forwarded_recipe_bodies_and_parameters(self):
        for command in sorted(COMMANDS):
            with self.subTest(command=command):
                expected = self.just(self.shared, "--show", command).stdout
                for entry in (self.compat, self.root):
                    self.assertEqual(self.just(entry, "--show", command).stdout, expected)

    def test_all_forwarded_dry_runs(self):
        for command in sorted(COMMANDS):
            with self.subTest(command=command):
                args = ("home",) if command in ("backup-status", "zfs-storage-enroll") else ()
                expected = self.just(self.shared, "--dry-run", command, *args)
                for entry in (self.compat, self.root):
                    actual = self.just(entry, "--dry-run", command, *args)
                    self.assertEqual(actual.stdout, expected.stdout)
                    self.assertEqual(actual.stderr, expected.stderr)

    def test_snapshot_default_and_description_forwarding(self):
        for args, description in (((), "manual"), (("before update",), "before update")):
            for entry in (self.shared, self.compat, self.root):
                with self.subTest(entry=entry, args=args):
                    result = self.just(entry, "--dry-run", "snapshot", *args)
                    self.assertIn(f'sudo snapper -c home create -d "{description}"', result.stderr)

    def test_safe_execution_and_upstream_default(self):
        expected = self.just(self.shared, "niri-session").stdout
        self.assertIn("Log out and select 'Niri'", expected)
        self.assertEqual(self.just(self.compat, "niri-session").stdout, expected)
        self.assertEqual(self.just(self.root, "niri-session").stdout, expected)
        self.assertEqual(self.just(self.root).stdout, "upstream-default\n")
        self.assertEqual(self.just(self.root, "upstream-command").stdout, "upstream-command\n")

    def test_recipe_failure_propagates(self):
        # Replace only the external command, not the recipe, with a failing stub.
        bin_dir = self.directory / "bin"
        bin_dir.mkdir()
        niri = bin_dir / "niri"
        niri.write_text("#!/bin/sh\nexit 23\n")
        niri.chmod(0o755)
        self.env["PATH"] = str(bin_dir) + os.pathsep + self.env["PATH"]
        for entry in (self.shared, self.compat, self.root):
            result = self.just(entry, "niri-reload", check=False)
            self.assertEqual(result.returncode, 23, result.stderr)

    def test_project_local_just_unaffected(self):
        project = self.directory / "project"
        project.mkdir()
        (project / "justfile").write_text("default:\n    @echo project-local\n")
        result = subprocess.run(
            ["just"], cwd=project, env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "project-local\n")

    def test_no_ujust_dependency_or_duplicate_implementation(self):
        self.assertEqual(
            [line for line in self.compat.read_text().splitlines()
             if line and not line.startswith("#")],
            ["import '../../niri-system/justfile'"],
        )
        self.assertNotIn("ujust", self.shared.read_text())


if __name__ == "__main__":
    unittest.main()
