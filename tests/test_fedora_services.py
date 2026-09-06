"""Fedora-only service policy; never start services or update the host."""

import configparser
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "fedora_files"
SYSTEMD = OVERLAY / "usr/lib/systemd"


def unit(scope, name):
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read(SYSTEMD / scope / name)
    return config


class FedoraServiceTests(unittest.TestCase):
    def test_auth_session_lifecycle(self):
        agent = unit("user", "niri-polkit-agent.service")
        for key in ("PartOf", "After", "Requisite"):
            self.assertEqual(agent["Unit"][key], "graphical-session.target")
        self.assertEqual(agent["Install"]["WantedBy"], "niri.service")
        self.assertEqual(agent["Service"]["ExecStart"],
                         "/usr/libexec/polkit-mate-authentication-agent-1")
        self.assertEqual(agent["Service"]["Restart"], "on-failure")
        self.assertEqual(
            (SYSTEMD / "user-preset/80-fedora-niri.preset").read_text(),
            "enable niri-polkit-agent.service\n",
        )
        self.assertFalse(list(OVERLAY.rglob("*.desktop")))

    def test_auth_desktop_condition(self):
        condition = unit("user", "niri-polkit-agent.service")["Service"]["ExecCondition"]
        # Simulate systemd's literal-dollar unescaping, not service execution.
        command = shlex.split(condition.replace("$$", "$"))
        for desktop, expected in (("niri", 0), ("other:niri", 0),
                                  ("niri:other", 0), ("other:niri:extra", 0),
                                  ("MATE", 1), ("GNOME", 1), ("", 1),
                                  ("notniri", 1), ("niri-other", 1), (None, 1)):
            with self.subTest(desktop=desktop):
                env = dict(os.environ)
                env.pop("XDG_CURRENT_DESKTOP", None)
                if desktop is not None:
                    env["XDG_CURRENT_DESKTOP"] = desktop
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_updates_stage_os_and_update_only_system_flatpaks(self):
        for name, command in (
            ("os", "/usr/bin/bootc upgrade"),
            ("flatpak", "/usr/bin/flatpak update --system --noninteractive"),
        ):
            service = unit("system", f"fedora-niri-{name}-update.service")
            self.assertEqual(dict(service["Service"]),
                             {"Type": "oneshot", "ExecStart": command})
            self.assertEqual(service["Unit"]["Wants"], "network-online.target")
            self.assertEqual(service["Unit"]["After"], "network-online.target")
        self.assertEqual(
            unit("system", "fedora-niri-os-update.service")["Unit"]["ConditionPathExists"],
            "/run/ostree-booted",
        )
        for path in SYSTEMD.rglob("*.service"):
            service = unit(path.parent.name, path.name)
            for key, value in service["Service"].items():
                if key.startswith("Exec"):
                    self.assertNotRegex(value, r"--apply|--soft-reboot|reboot|shutdown|uninstall|--force-remove")
            for section in service.sections():
                self.assertFalse({"FailureAction", "SuccessAction", "StartLimitAction"}
                                 & set(service[section]))

    def test_timer_schedule_and_presets(self):
        for name in ("os", "flatpak"):
            timer = unit("system", f"fedora-niri-{name}-update.timer")
            self.assertEqual(dict(timer["Timer"]), {
                "OnCalendar": "*-*-* 00/6:00:00",
                "RandomizedDelaySec": "1h",
                "Persistent": "true",
            })
            self.assertEqual(timer["Install"]["WantedBy"], "timers.target")
        presets = (SYSTEMD / "system-preset/80-fedora-niri.preset").read_text()
        self.assertEqual([line for line in presets.splitlines() if not line.startswith("#")], [
            "disable bootc-fetch-apply-updates.timer",
            "enable fedora-niri-os-update.timer",
            "enable fedora-niri-flatpak-update.timer",
        ])

    def test_overlay_is_not_in_shared_staging(self):
        for path in OVERLAY.rglob("*"):
            if path.is_file():
                self.assertFalse((ROOT / "system_files" / path.relative_to(OVERLAY)).exists())

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze unavailable")
    def test_systemd_verify_offline(self):
        # A private unit search path avoids host unit dependencies and user-bus access.
        # Only unavailable executables are replaced, in temporary copies, with true.
        with tempfile.TemporaryDirectory(prefix="fedora-services-") as directory:
            temp = Path(directory)
            names = []
            for path in sorted(SYSTEMD.glob("*/*.service")) + sorted(SYSTEMD.glob("*/*.timer")):
                text = path.read_text()
                for executable in ("/usr/libexec/polkit-mate-authentication-agent-1",
                                   "/usr/bin/bootc", "/usr/bin/flatpak"):
                    if not os.access(executable, os.X_OK):
                        text = text.replace(f"ExecStart={executable}", "ExecStart=/bin/true")
                (temp / path.name).write_text(text)
                names.append(str(temp / path.name))
            for target in ("graphical-session.target", "network-online.target",
                           "timers.target", "sysinit.target", "basic.target",
                           "shutdown.target"):
                (temp / target).write_text("[Unit]\nDescription=Offline verification target\n")
            (temp / "niri.service").write_text(
                "[Unit]\nBindsTo=graphical-session.target\nBefore=graphical-session.target\n"
                "Wants=niri-polkit-agent.service\n[Service]\nType=notify\nExecStart=/bin/true\n"
            )
            result = subprocess.run(
                ["systemd-analyze", "verify", "--man=no", *names, str(temp / "niri.service")],
                env=dict(os.environ, SYSTEMD_UNIT_PATH=str(temp)),
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
