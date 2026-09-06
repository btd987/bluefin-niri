"""Exercise opt-in enrollment with isolated commands and relocated timer files."""

import shutil
import sys
import unittest

import test_custom_commands as custom


@unittest.skipUnless(custom.JUST, "just is required")
class DevEnrollmentTests(unittest.TestCase):
    stub = custom.CustomCommandTests.stub
    run_recipe = custom.CustomCommandTests.run_recipe
    calls = custom.CustomCommandTests.calls

    def setUp(self):
        custom.CustomCommandTests.setUp(self)
        self.override = self.directory / "timer.d/dev-machine.conf"
        self.justfile.write_text(
            self.text.replace("$EUID", "$TEST_EUID").replace(
                "/etc/systemd/system/snapper-timeline.timer.d/dev-machine.conf",
                str(self.override),
            )
        )
        self.env["TEST_EUID"] = "0"
        for name in ("grep", "mkdir", "just"):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / "python3").symlink_to(sys.executable)
        self.stub("snapper", stdout="SUBVOLUME,/var/home\nTIMELINE_CREATE,no\n")
        self.stub("systemctl")
        self.stub("podman")
        self.stub("devpod", stdout="{}")

    def test_timer_decline_and_eof_are_read_only(self):
        for answer in ("", "n\n", "yes\n"):
            result = self.run_recipe("enable-snapshot-timers", input=answer)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(call[0] == "snapper" and "get-config" in call for call in self.calls()))

    def test_timer_activation(self):
        result = self.run_recipe("enable-snapshot-timers", input="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-2:], [
            ["snapper", "-c", "home", "set-config", "TIMELINE_CREATE=yes"],
            ["systemctl", "--system", "enable", "--now", "snapper-timeline.timer", "snapper-cleanup.timer"],
        ])
        self.assertIn("ALL eligible", result.stdout)

    def test_validation_and_privileges_fail_closed(self):
        for recipe in ("enable-snapshot-timers", "configure-snapshot-schedule"):
            self.env["TEST_EUID"] = "1000"
            self.assertNotEqual(self.run_recipe(recipe, input="y\n").returncode, 0)
            self.assertEqual(self.calls(), [])
        self.env["TEST_EUID"] = "0"
        self.stub("snapper", stdout="SUBVOLUME,/wrong\n")
        for recipe in ("enable-snapshot-timers", "configure-snapshot-schedule"):
            self.assertNotEqual(self.run_recipe(recipe, input="y\n").returncode, 0)
        self.assertFalse(self.override.exists())
        self.assertFalse(any(call[0] == "systemctl" for call in self.calls()))

    def test_schedule_decline_and_activation_decline(self):
        result = self.run_recipe("configure-snapshot-schedule", input="n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.override.exists())
        result = self.run_recipe("configure-snapshots-dev", input="y\nn\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.override.read_text(), "[Timer]\nOnCalendar=\nOnCalendar=*:0/15\n")
        self.assertEqual([c for c in self.calls() if c[0] == "systemctl"],
                         [["systemctl", "--system", "daemon-reload"]])
        before = self.calls()
        result = self.run_recipe("configure-snapshot-schedule", input="y\ny\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls()[len(before):][0][0], "snapper")
        self.assertEqual(len(self.calls()), len(before) + 1)

    def test_schedule_explicit_activation(self):
        result = self.run_recipe("configure-snapshot-schedule", input="y\ny\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1], ["systemctl", "--system", "enable", "--now",
                                           "snapper-timeline.timer", "snapper-cleanup.timer"])

    def test_timer_failure_propagates(self):
        self.stub("systemctl", status=23)
        result = self.run_recipe("enable-snapshot-timers", input="y\n")
        self.assertEqual(result.returncode, 23, result.stderr)

    def test_snapper_failure_prevents_activation(self):
        self.stub("snapper", status=24)
        result = self.run_recipe("enable-snapshot-timers", input="y\n")
        self.assertEqual(result.returncode, 24, result.stderr)
        self.assertFalse(any(c[0] == "systemctl" for c in self.calls()))

    def test_devpod_opt_in_and_exact_arguments(self):
        self.env["TEST_EUID"] = "1000"
        result = self.run_recipe("setup-devpod-podman", input="n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["devpod", "provider", "list", "--output", "json"], ["podman", "info"]])
        result = self.run_recipe("setup-devpod-podman", input="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-2:], [
            ["devpod", "provider", "add", "docker", "--name", "podman",
             "--option", "DOCKER_PATH=podman", "--use=false"],
            ["devpod", "provider", "set-options", "podman", "--option", "DOCKER_PATH=podman"],
        ])
        self.assertIn("initialized; default selection unchanged", result.stdout)

    def test_devpod_eof_and_nonconfirmation_do_not_add(self):
        self.env["TEST_EUID"] = "1000"
        for answer in ("", "yes\n"):
            result = self.run_recipe("setup-devpod-podman", input=answer)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[2] in ("add", "set-options") for c in self.calls() if c[0] == "devpod"))

    def test_devpod_podman_failure_prevents_add(self):
        self.env["TEST_EUID"] = "1000"
        self.stub("podman", status=24)
        result = self.run_recipe("setup-devpod-podman", input="y\n")
        self.assertEqual(result.returncode, 24, result.stderr)
        self.assertEqual(self.calls(), [["devpod", "provider", "list", "--output", "json"], ["podman", "info"]])

    def test_devpod_add_and_initialization_failures(self):
        self.env["TEST_EUID"] = "1000"
        for failure in ("add", "set-options"):
            with self.subTest(failure=failure):
                self.stub("devpod", stdout="{}")
                path = self.bin / "devpod"
                path.write_text(path.read_text().replace(
                    "sys.exit(0)", f"sys.exit(23 if sys.argv[2] == {failure!r} else 0)"))
                before = len(self.calls())
                result = self.run_recipe("setup-devpod-podman", input="y\n")
                self.assertEqual(result.returncode, 23, result.stderr)
                calls = self.calls()[before:]
                self.assertEqual([c[2] for c in calls if c[0] == "devpod"],
                                 ["list", "add"] if failure == "add" else ["list", "add", "set-options"])
                self.assertNotIn("initialized; default selection unchanged", result.stdout)
                if failure == "set-options":
                    self.assertIn("provider added but initialization failed", result.stderr)
                    self.assertIn("Review before explicitly retrying", result.stderr)

    def test_devpod_existing_and_invalid_inventory_never_add(self):
        self.env["TEST_EUID"] = "1000"
        for output, status in (("{\"podman\": {}}", 0), ("not json", 1), ("[]", 1)):
            self.stub("devpod", stdout=output)
            result = self.run_recipe("setup-devpod-podman", input="y\n")
            self.assertEqual(result.returncode == 0, status == 0, result.stderr)
            if status == 0:
                self.assertIn("no options or defaults changed", result.stdout)
                self.assertIn("review the existing provider first", result.stdout)
        self.assertTrue(all(c == ["devpod", "provider", "list", "--output", "json"] for c in self.calls()))

    def test_devpod_root_missing_dependency_and_query_failure(self):
        self.assertNotEqual(self.run_recipe("setup-devpod-podman", input="y\n").returncode, 0)
        self.assertEqual(self.calls(), [])
        self.env["TEST_EUID"] = "1000"
        (self.bin / "podman").unlink()
        self.assertNotEqual(self.run_recipe("setup-devpod-podman", input="y\n").returncode, 0)
        self.assertEqual(self.calls(), [])
        self.stub("podman")
        self.stub("devpod", status=23)
        self.assertEqual(self.run_recipe("setup-devpod-podman", input="y\n").returncode, 23)


if __name__ == "__main__":
    unittest.main()
