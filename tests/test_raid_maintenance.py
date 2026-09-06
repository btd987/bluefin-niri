import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'system_files/usr/bin/setup-raid-maintenance'
UUID = '01234567:89abcdef:01234567:89abcdef'


class RaidMaintenanceTests(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader('raid_maintenance', str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.helper = importlib.util.module_from_spec(spec)
        loader.exec_module(self.helper)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.helper.CONFIG = self.base / 'selection.json'
        self.helper.LOCK = self.base / 'maintenance.lock'
        self.helper.SYS_BLOCK = self.base / 'sys/class/block'
        self.md = self.helper.SYS_BLOCK / 'md0/md'
        self.md.mkdir(parents=True)
        (self.md.parent / 'dev').write_text('9:0\n')
        self.action = self.md / 'sync_action'
        self.action.write_text('idle\n')
        (self.md / 'array_state').write_text('clean\n')
        self.saved = {'device': '/dev/md0', 'uuid': UUID}
        self.calls = []
        self.output = io.StringIO()
        self.enter = contextlib.ExitStack()
        self.addCleanup(self.enter.close)
        self.enter.enter_context(contextlib.redirect_stdout(self.output))
        resolve = Path.resolve
        self.enter.enter_context(patch.object(Path, 'resolve', lambda path, **kw:
            Path('/dev/md0') if str(path) in ('/dev/md0', '/dev/md/selected') else resolve(path, **kw)))
        real_stat = os.stat
        self.device_stat = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(9, 0))
        self.enter.enter_context(patch.object(os, 'stat', side_effect=lambda path, *a, **kw:
            self.device_stat if str(path) == '/dev/md0' else real_stat(path, *a, **kw)))
        self.enter.enter_context(patch.object(self.helper, 'command', side_effect=self.command))
        self.enter.enter_context(patch.object(self.helper.time, 'sleep', side_effect=self.finish))

    def command(self, *args):
        self.calls.append(args)
        if args[0] == 'mdadm':
            self.assertEqual(args, ('mdadm', '--detail', '--export', '/dev/md0'))
            return 'MD_UUID=' + UUID + '\nMD_LEVEL=raid6\n'
        if args[0] == 'lsblk':
            return '/dev/md0 raid6\n'
        self.assertEqual(args[0], 'systemctl')
        return ''

    def finish(self, seconds):
        self.assertEqual(seconds, 10)
        self.assertEqual(self.action.read_text(), 'check\n')
        with self.helper.LOCK.open('r+') as lock:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.action.write_text('idle\n')

    def configure(self):
        self.helper.CONFIG.write_text(json.dumps(self.saved))
        self.helper.CONFIG.chmod(0o600)

    def enroll(self, answer='yes'):
        with patch('builtins.input', side_effect=['/dev/md/selected', answer]):
            self.helper.enroll()

    def test_enrollment_records_uuid_and_enables_only_own_timer(self):
        self.enroll()
        self.assertEqual(json.loads(self.helper.CONFIG.read_text()), self.saved)
        self.assertEqual(self.helper.CONFIG.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.calls[-2:], [('systemctl', 'daemon-reload'),
                         ('systemctl', 'enable', '--now', 'raid-maintenance.timer')])
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_cancel_and_rerun_do_not_write_or_enable(self):
        with self.assertRaisesRegex(ValueError, 'Cancelled'):
            self.enroll('no')
        self.assertFalse(self.helper.CONFIG.exists())
        self.assertFalse(any(c[0] == 'systemctl' for c in self.calls))
        self.configure()
        before = self.helper.CONFIG.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.enroll()
        self.assertEqual(self.helper.CONFIG.read_bytes(), before)

    def test_check_holds_lock_until_kernel_idle(self):
        self.configure()
        self.helper.check()
        self.assertEqual(self.action.read_text(), 'idle\n')
        self.assertGreaterEqual(sum(c[0] == 'mdadm' for c in self.calls), 3)
        self.assertIn('Requested check', self.output.getvalue())

    def test_busy_and_readonly_arrays_skip(self):
        self.configure()
        for action, state in [('check', 'active'), ('repair', 'active'),
                              ('resync', 'active'), ('recover', 'active'),
                              ('idle', 'readonly'), ('idle', 'read-auto'), ('idle', 'inactive')]:
            with self.subTest(action=action, state=state):
                self.action.write_text(action)
                (self.md / 'array_state').write_text(state)
                self.helper.check()
                self.assertEqual(self.action.read_text(), action)

    def test_shared_lock_skips_before_probing_storage(self):
        with self.helper.LOCK.open('w') as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.helper.check()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_uuid_mismatch_refuses(self):
        self.saved['uuid'] = 'ffffffff:ffffffff:ffffffff:ffffffff'
        self.configure()
        with self.assertRaisesRegex(ValueError, 'UUID'):
            self.helper.check()
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_identity_change_immediately_before_write_refuses(self):
        self.configure()
        with patch.object(self.helper, 'command', side_effect=[
                'MD_UUID=' + UUID, 'MD_UUID=ffffffff:ffffffff:ffffffff:ffffffff']):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                self.helper.check()
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_busy_immediately_before_write_skips(self):
        self.configure()
        original = self.helper.identity
        calls = 0

        def identity(device):
            nonlocal calls
            result = original(device)
            calls += 1
            if calls == 2:
                self.action.write_text('recover\n')
            return result

        with patch.object(self.helper, 'identity', side_effect=identity):
            self.helper.check()
        self.assertEqual(self.action.read_text(), 'recover\n')

    def test_sys_class_symlink_and_only_selected_array_touched(self):
        self.configure()
        block = self.md.parent
        target = self.base / 'devices/md0'
        target.parent.mkdir()
        block.rename(target)
        block.symlink_to(target, target_is_directory=True)
        other = self.helper.SYS_BLOCK / 'md1/md'
        other.mkdir(parents=True)
        (other / 'sync_action').write_text('idle\n')
        self.helper.check()
        self.assertEqual((other / 'sync_action').read_text(), 'idle\n')

    def test_readonly_configuration_location_never_enables_timer(self):
        with patch.object(os, 'open', side_effect=OSError(30, 'Read-only file system')):
            with self.assertRaises(OSError):
                self.enroll()
        self.assertFalse(any(c[0] == 'systemctl' for c in self.calls))
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_nonblock_and_sysfs_identity_mismatch_refuse(self):
        self.configure()
        self.device_stat.st_mode = stat.S_IFREG | 0o600
        with self.assertRaisesRegex(ValueError, 'not a block'):
            self.helper.check()
        self.device_stat.st_mode = stat.S_IFBLK | 0o600
        (self.md.parent / 'dev').write_text('9:1')
        with self.assertRaisesRegex(ValueError, 'sysfs identity'):
            self.helper.check()
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_arbitrary_path_and_missing_md_control_refuse(self):
        for device in (str(self.base), '/etc/passwd'):
            with self.assertRaisesRegex(ValueError, 'existing /dev/mdN'):
                self.helper.identity(device)
        self.configure()
        self.action.unlink()
        with self.assertRaises(FileNotFoundError):
            self.helper.check()

    def test_mdadm_failure_or_invalid_export_never_writes(self):
        self.configure()
        for export in ('', 'MD_UUID=bad', 'MD_UUID=' + UUID + '\nMD_UUID=' + UUID):
            with patch.object(self.helper, 'command', return_value=export):
                with self.assertRaises(ValueError):
                    self.helper.check()
        with patch.object(self.helper, 'command', side_effect=subprocess.CalledProcessError(1, 'mdadm')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.helper.check()
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_readonly_sysfs_failure_does_not_remount(self):
        self.configure()
        with patch.object(Path, 'write_text', side_effect=OSError(30, 'Read-only file system')):
            with self.assertRaises(OSError):
                self.helper.check()
        self.assertTrue(all(c[0] == 'mdadm' for c in self.calls))
        self.assertEqual(self.action.read_text(), 'idle\n')

    def test_unsafe_config_and_symlink_lock_refuse(self):
        self.configure()
        self.helper.CONFIG.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.helper.check()
        self.helper.LOCK.unlink()
        self.helper.LOCK.symlink_to(self.helper.CONFIG)
        with self.assertRaises(OSError):
            self.helper.check()

    def test_units_are_monthly_root_and_not_kernel_readonly(self):
        units = PROJECT / 'system_files/usr/lib/systemd/system'
        service = (units / 'raid-maintenance.service').read_text()
        timer = (units / 'raid-maintenance.timer').read_text()
        self.assertIn('User=root', service)
        self.assertIn('ExecStart=/usr/bin/setup-raid-maintenance --run', service)
        self.assertIn('TimeoutStartSec=infinity', service)
        self.assertNotIn('ProtectKernelTunables=true', service)
        self.assertIn('OnCalendar=monthly', timer)
        self.assertIn('ConditionPathExists=/etc/raid-maintenance.json', timer)
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze unavailable')
    def test_systemd_unit_syntax(self):
        units = PROJECT / 'system_files/usr/lib/systemd/system'
        paths = []
        for name in ('raid-maintenance.service', 'raid-maintenance.timer'):
            target = self.base / name
            target.write_text((units / name).read_text().replace(
                '/usr/bin/setup-raid-maintenance --run', '/bin/true'))
            paths.append(str(target))
        result = subprocess.run(['systemd-analyze', 'verify', *paths],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
