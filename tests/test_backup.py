import contextlib
import fnmatch
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
except ImportError:
    yaml = None

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'system_files/usr/bin/setup-backup'


@unittest.skipIf(yaml is None, 'requires python3-pyyaml; use image/system Python')
class BackupTests(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader('backup', str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.wizard = importlib.util.module_from_spec(spec)
        loader.exec_module(self.wizard)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        (self.source / 'important.txt').write_text('restore me exactly\n')
        self.target = self.base / 'target'
        self.target.mkdir()
        self.wizard.ROOT = self.base / 'configs'
        self.wizard.UNITS = self.base / 'units'
        self.wizard.UNITS.mkdir()
        self.identity = {'target': str(self.target), 'source': '/dev/test-only', 'uuid': 'test-only'}
        self.calls = []
        self.wizard.RAID_LOCK = self.base / 'raid.lock'
        self.wizard.SYS_BLOCK = self.base / 'sys-block'
        self.wizard.SYS_BLOCK.mkdir()
        real_fstat = os.fstat
        def root_stat(fd):
            values = list(real_fstat(fd))
            values[4] = 0
            return os.stat_result(values)
        mock = patch.object(self.wizard.os, 'fstat', side_effect=root_stat)
        mock.start()
        self.addCleanup(mock.stop)

    def answers(self, kind='local', action='initialize'):
        destination = [str(self.target), 'repo'] if kind == 'local' else ['ssh://backup@example.org/backup/repo']
        return [str(self.source), '', 'yes', kind, *destination, action,
                'daily', '7', '4', '12', 'monthly', 'yes',
                *(['yes'] if action == 'initialize' else []), 'yes', 'no']

    def fake_run(self, *args, **kwargs):
        self.calls.append(args)
        if args[0] == 'findmnt':
            return json.dumps({'filesystems': [{'target': str(self.base), 'source': '/dev/source-test', 'uuid': 'source-test'}]})
        return ''

    def enroll(self, answers=None, runner=None, secret='test-secret', reuse=False):
        output = io.StringIO()
        with patch('builtins.input', side_effect=answers or self.answers()), \
                patch.object(self.wizard.getpass, 'getpass', side_effect=[secret, secret]), \
                patch.object(self.wizard.sys.stdin, 'isatty', return_value=True), \
                patch.object(self.wizard, 'mount_identity', return_value=self.identity), \
                patch.object(self.wizard, 'run', side_effect=runner or self.fake_run), \
                contextlib.redirect_stdout(output):
            self.wizard.enroll('documents', reuse=reuse)
        self.assertNotIn(secret, output.getvalue())

    def test_local_enrollment_order_permissions_and_scope(self):
        self.enroll()
        directory = self.wizard.ROOT / 'documents'
        config = yaml.safe_load((directory / 'config.yaml').read_text())
        self.assertEqual(config['source_directories'], [str(self.source)])
        self.assertEqual(config['keep_daily'], 7)
        self.assertTrue(config['one_file_system'])
        self.assertIn('pp:' + str(self.target / 'repo'), config['exclude_patterns'])
        self.assertIn('sh:**/.snapshots', config['exclude_patterns'])
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        for file in directory.iterdir():
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        actions = [call[3] for call in self.calls if call[0] == 'borgmatic']
        self.assertEqual(actions, ['config', 'repo-create', 'repo-info'])
        self.assertEqual(self.calls[-1], ('systemctl', 'enable', '--now', 'backup@documents.timer'))
        self.assertNotIn('test-secret', repr(self.calls))

    def test_ssh_reuse_never_initializes(self):
        self.enroll(self.answers('ssh', 'reuse'))
        self.assertFalse(any('repo-create' in call for call in self.calls))
        meta = json.loads((self.wizard.ROOT / 'documents/enrollment.json').read_text())
        self.assertIsNone(meta['mount'])

    def test_rerun_refuses_and_explicit_reuse_preserves_all_bytes(self):
        self.enroll()
        before = {p: p.read_bytes() for p in (self.wizard.ROOT / 'documents').iterdir()}
        with self.assertRaisesRegex(ValueError, 'exists'):
            self.enroll()
        self.calls.clear()
        self.enroll(['yes', 'yes', 'no'], reuse=True)
        self.assertFalse(any('repo-create' in call for call in self.calls))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_validation_and_repository_failures_never_enable(self):
        for action in ('config', 'repo-create', 'repo-info'):
            with self.subTest(action=action):
                self.wizard.ROOT = self.base / action
                self.calls.clear()
                def fail(*args, **kwargs):
                    result = self.fake_run(*args, **kwargs)
                    if action in args:
                        raise subprocess.CalledProcessError(2, args)
                    return result
                with self.assertRaises(subprocess.CalledProcessError):
                    self.enroll(runner=fail)
                self.assertFalse(any(call[0] == 'systemctl' for call in self.calls))

    def test_cancellation_at_each_confirmation(self):
        for index in (12, 13, 14):
            with self.subTest(index=index):
                self.wizard.ROOT = self.base / ('cancel' + str(index))
                self.calls.clear()
                answers = self.answers()
                answers[index] = 'no'
                with self.assertRaisesRegex(ValueError, 'Cancelled'):
                    self.enroll(answers)
                self.assertFalse(any(call[0] == 'systemctl' for call in self.calls))
                if index == 12:
                    self.assertFalse(self.wizard.ROOT.exists())
                if index <= 13:
                    self.assertFalse(any('repo-create' in call for call in self.calls))

    def test_invalid_names(self):
        for name in ('../home', '-bad', 'a/b', 'Upper', '', 'a' * 33, 'a\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.wizard.name_check(name)

    def test_invalid_inputs_do_not_write(self):
        for index, value in ((0, '/nonexistent-source-test'), (2, 'maybe'),
                             (6, 'destroy'), (7, 'every second'), (8, '0'), (11, 'never')):
            answers = self.answers()
            answers[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.enroll(answers)
            self.assertFalse(self.wizard.ROOT.exists())

    def test_reject_ssh_credentials_and_shell_syntax(self):
        for url in ('ssh://user:password@host/repo', 'ssh://host/repo;touch',
                    'host:repo', 'ssh://host/repo?password=secret',
                    'ssh://-option/repo', 'ssh://-option@host/repo', 'ssh://host:99999/repo'):
            answers = self.answers('ssh')
            answers[4] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.enroll(answers)
            self.assertFalse(self.wizard.ROOT.exists())

    def test_mount_missing_or_changed_fails_closed(self):
        with self.assertRaises(ValueError):
            self.wizard.mount_identity(str(self.target))
        with patch.object(self.wizard, 'mount_identity', return_value={**self.identity, 'uuid': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                self.wizard.local_check({'mount': self.identity, 'repository': str(self.target / 'repo')})

    def test_symlink_destination_and_existing_init_refused(self):
        (self.target / 'repo').symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.enroll()
        (self.target / 'repo').unlink()
        (self.target / 'repo').mkdir()
        with self.assertRaisesRegex(ValueError, 'nonexistent'):
            self.enroll()
        self.assertFalse(self.wizard.ROOT.exists())

    def test_secret_mismatch_and_nonterminal_refused(self):
        with patch.object(self.wizard.getpass, 'getpass', side_effect=['one', 'two']), \
                patch('builtins.input', side_effect=self.answers()), \
                patch.object(self.wizard, 'run', side_effect=self.fake_run), \
                patch.object(self.wizard.sys.stdin, 'isatty', return_value=True), \
                patch.object(self.wizard, 'mount_identity', return_value=self.identity), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'match'):
                self.wizard.enroll('documents')
        self.assertFalse(self.wizard.ROOT.exists())
        with patch('builtins.input', side_effect=self.answers()), \
                patch.object(self.wizard, 'run', side_effect=self.fake_run), \
                patch.object(self.wizard.sys.stdin, 'isatty', return_value=False), \
                patch.object(self.wizard, 'mount_identity', return_value=self.identity), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'terminal'):
                self.wizard.enroll('documents')

    def test_command_environment_is_noninteractive_and_no_borg_overrides(self):
        with patch.dict(os.environ, {'BORG_PASSPHRASE': 'not-used',
                                    'BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK': 'yes',
                                    'HOME': '/untrusted', 'XDG_CONFIG_HOME': '/untrusted/config',
                                    'XDG_CACHE_HOME': '/untrusted/cache', 'PYTHONPATH': '/untrusted',
                                    'LD_PRELOAD': '/untrusted/loader.so', 'BASH_ENV': '/untrusted/shell',
                                    'SSH_AUTH_SOCK': '/untrusted/agent'}), \
                patch.object(self.wizard.subprocess, 'run') as command:
            self.wizard.run('borgmatic', 'repo-info')
        env = command.call_args.kwargs['env']
        self.assertNotIn('BORG_PASSPHRASE', env)
        self.assertNotIn('BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK', env)
        self.assertIn('StrictHostKeyChecking=yes', env['BORG_RSH'])
        self.assertEqual(env, {'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C', 'HOME': '/root',
                               'BORG_RSH': 'ssh -oBatchMode=yes -oStrictHostKeyChecking=yes'})
        self.assertEqual(command.call_args.kwargs['stdin'], subprocess.DEVNULL)

    def test_conflicting_timer_not_overwritten(self):
        override = self.wizard.UNITS / 'backup@documents.timer.d'
        override.mkdir()
        file = override / 'schedule.conf'
        file.write_text('custom schedule')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.enroll()
        self.assertEqual(file.read_text(), 'custom schedule')
        self.assertFalse(any(call[0] == 'systemctl' for call in self.calls))

    def test_symlink_timer_override_refused(self):
        override = self.wizard.UNITS / 'backup@documents.timer.d'
        override.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            self.enroll()
        self.assertEqual(list(self.source.iterdir()), [self.source / 'important.txt'])
        self.assertFalse(any(call[0] == 'systemctl' for call in self.calls))

    def test_reuse_validates_policy_without_rewriting(self):
        self.enroll()
        self.calls.clear()
        file = self.wizard.ROOT / 'documents/config.yaml'
        config = yaml.safe_load(file.read_text())
        for change in ({'match_archives': 'sh:documents-*'}, {'exclude_patterns': []},
                       {'repositories': [{'path': 'ssh://host/other'}]},
                       {'source_directories': []}, {'source_directories': ['/nonexistent-source-test']}):
            file.write_text(yaml.safe_dump({**config, **change}))
            before = file.read_bytes()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.enroll(['yes'], reuse=True)
            self.assertEqual(file.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_activation_failure_can_be_retried_without_reinitialization(self):
        def fail(*args, **kwargs):
            result = self.fake_run(*args, **kwargs)
            if 'enable' in args:
                raise subprocess.CalledProcessError(1, args)
            return result
        with self.assertRaises(subprocess.CalledProcessError):
            self.enroll(runner=fail)
        before = {p: p.read_bytes() for p in (self.wizard.ROOT / 'documents').iterdir()}
        self.calls.clear()
        self.enroll(['yes', 'yes', 'no'], reuse=True)
        self.assertFalse(any('repo-create' in call for call in self.calls))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_runtime_checks_mount_before_borg_and_locks(self):
        self.enroll()
        for mounted in (True, False):
            self.calls.clear()
            with patch.object(self.wizard.fcntl, 'flock') as lock, \
                    patch.object(self.wizard, 'mount_identity', side_effect=None if mounted else ValueError('unmounted'),
                                 return_value=self.identity), \
                    patch.object(self.wizard, 'run', side_effect=self.fake_run):
                if mounted:
                    self.wizard.run_backup(self.wizard.ROOT / 'documents')
                    self.assertEqual(self.calls[-2:], [
                        ('borgmatic', '--config', str(self.wizard.ROOT / 'documents/config.yaml'), 'create'),
                        ('borgmatic', '--config', str(self.wizard.ROOT / 'documents/config.yaml'), 'prune', 'compact', 'check')])
                    self.assertEqual(lock.call_args.args[1], self.wizard.fcntl.LOCK_EX | self.wizard.fcntl.LOCK_NB)
                else:
                    with self.assertRaisesRegex(ValueError, 'unmounted'):
                        self.wizard.run_backup(self.wizard.ROOT / 'documents')
                    self.assertFalse(any(call[0] == 'borgmatic' for call in self.calls))

    def test_retention_does_not_match_other_backup_names(self):
        self.enroll()
        config = yaml.safe_load((self.wizard.ROOT / 'documents/config.yaml').read_text())
        pattern = config['match_archives'].removeprefix('sh:')
        timestamp = '2026-09-06T12:34:56.123456'
        self.assertTrue(fnmatch.fnmatchcase('documents-' + timestamp, pattern))
        for name in ('documents-other', 'documents-2026', 'other'):
            self.assertFalse(fnmatch.fnmatchcase(name + '-' + timestamp, pattern))

    def test_unsafe_root_and_enrollment_paths_refused(self):
        self.wizard.ROOT.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.enroll()
        self.assertEqual(list(self.source.iterdir()), [self.source / 'important.txt'])
        self.wizard.ROOT.unlink()
        self.wizard.ROOT.mkdir(mode=0o777)
        self.wizard.ROOT.chmod(0o777)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.enroll()
        self.wizard.ROOT.chmod(0o700)
        (self.wizard.ROOT / 'documents').symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.enroll(['yes'], reuse=True)
        self.assertEqual(self.calls, [])

    def test_reuse_rejects_unsafe_files_before_commands(self):
        self.enroll()
        self.calls.clear()
        for filename in ('passphrase', 'config.yaml', 'enrollment.json'):
            file = self.wizard.ROOT / 'documents' / filename
            file.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.enroll(['yes'], reuse=True)
            file.chmod(0o600)
            contents = file.read_bytes()
            file.unlink()
            file.symlink_to(self.source / 'important.txt')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.enroll(['yes'], reuse=True)
            file.unlink()
            self.wizard.write_new(file, contents.decode())
        with patch.object(self.wizard.os, 'geteuid', return_value=os.geteuid() + 1):
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.wizard.secure(file)
        self.assertEqual(self.calls, [])

    def test_excluded_sources_refused_and_overlapping_sources_preserved(self):
        repo = self.target / 'repo'
        repo.mkdir()
        snapshots = self.source / '.snapshots'
        snapshots.mkdir()
        for source in (repo, snapshots):
            answers = self.answers(action='reuse')
            answers[0] = str(source)
            with self.assertRaisesRegex(ValueError, 'excluded'):
                self.enroll(answers)
            self.assertFalse(self.wizard.ROOT.exists())
        answers = self.answers(action='reuse')
        answers[:1] = [str(self.base), str(self.source), str(self.source)]
        self.enroll(answers)
        config = yaml.safe_load((self.wizard.ROOT / 'documents/config.yaml').read_text())
        self.assertEqual(config['source_directories'], [str(self.base), str(self.source)])
        self.assertIn('pp:' + str(repo), config['exclude_patterns'])
        self.assertTrue(snapshots.is_dir())

    def test_initial_backup_does_not_wait_while_enrollment_holds_lock(self):
        answers = self.answers()
        answers[-1] = 'yes'
        self.enroll(answers)
        self.assertEqual(self.calls[-1], ('systemctl', 'start', '--no-block', 'backup@documents.service'))

    def test_failed_creation_never_prunes(self):
        self.enroll()
        self.calls.clear()
        def fail(*args, **kwargs):
            result = self.fake_run(*args, **kwargs)
            if 'create' in args:
                raise subprocess.CalledProcessError(1, args)
            return result
        with patch.object(self.wizard, 'mount_identity', return_value=self.identity), \
                patch.object(self.wizard, 'run', side_effect=fail), self.assertRaises(subprocess.CalledProcessError):
            self.wizard.run_backup(self.wizard.ROOT / 'documents')
        self.assertFalse(any('prune' in call or 'compact' in call for call in self.calls))

    def test_raid_busy_or_unknown_skips_all_borg_work(self):
        md = self.wizard.SYS_BLOCK / 'md127/md'
        md.mkdir(parents=True)
        action = md / 'sync_action'
        for state in ('check', 'repair', 'resync', 'recover', 'reshape', 'frozen', '', None):
            if state is None:
                action.unlink()
            else:
                action.write_text(state)
            with self.subTest(state=state), patch.object(self.wizard, 'run', side_effect=self.fake_run), \
                    patch.object(self.wizard, 'validate') as validate:
                self.wizard.run_backup(self.wizard.ROOT / 'documents')
                validate.assert_not_called()
                self.assertFalse(any(call[0] == 'borgmatic' for call in self.calls))

    def test_raid_jobs_and_failed_query_skip_retention(self):
        for result in ('1 mdcheck_start.service start running\n',
                       '2 mdcheck_continue.service start waiting\n',
                       '3 home-backup-raid-check.service start running\n',
                       '4 raid-maintenance.service start waiting\n', 'unexpected',
                       subprocess.CalledProcessError(1, 'systemctl')):
            with self.subTest(result=result), patch.object(self.wizard, 'run') as run, \
                    patch.object(self.wizard, 'validate') as validate:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                self.wizard.run_backup(self.wizard.ROOT / 'documents')
                validate.assert_not_called()
                self.assertEqual(run.call_count, 1)

    def test_shared_lock_contention_and_full_operation_lifetime(self):
        lockpath = self.wizard.RAID_LOCK
        lockpath.touch(mode=0o600)
        with lockpath.open('r+') as competing, patch.object(self.wizard, 'validate'), \
                patch.object(self.wizard, 'run') as run:
            self.wizard.fcntl.flock(competing, self.wizard.fcntl.LOCK_EX)
            self.wizard.run_backup(self.wizard.ROOT / 'documents')
            run.assert_not_called()
            self.wizard.fcntl.flock(competing, self.wizard.fcntl.LOCK_UN)
            def assert_locked(*args, **kwargs):
                with self.assertRaises(BlockingIOError):
                    self.wizard.fcntl.flock(competing, self.wizard.fcntl.LOCK_EX | self.wizard.fcntl.LOCK_NB)
                return 'No jobs running.\n' if args[0] == 'systemctl' else ''
            run.side_effect = assert_locked
            self.wizard.run_backup(self.wizard.ROOT / 'documents')
            self.assertEqual(run.call_args.args[-3:], ('prune', 'compact', 'check'))
            self.wizard.fcntl.flock(competing, self.wizard.fcntl.LOCK_EX | self.wizard.fcntl.LOCK_NB)
        self.assertTrue(lockpath.exists())

    def test_unsafe_shared_lock_refused_before_commands(self):
        lock = self.wizard.RAID_LOCK
        with patch.object(self.wizard, 'run') as run:
            lock.symlink_to(self.source / 'important.txt')
            with self.assertRaises(OSError):
                self.wizard.run_backup(self.wizard.ROOT / 'documents')
            lock.unlink()
            lock.touch(mode=0o600)
            for mode in (0o666, 0o644):
                lock.chmod(mode)
                with self.assertRaisesRegex(ValueError, 'Unsafe RAID'):
                    self.wizard.run_backup(self.wizard.ROOT / 'documents')
            lock.chmod(0o600)
            info = list(lock.stat())
            info[4] = 12345
            with patch.object(self.wizard.os, 'fstat', return_value=os.stat_result(info)):
                with self.assertRaisesRegex(ValueError, 'Unsafe RAID'):
                    self.wizard.run_backup(self.wizard.ROOT / 'documents')
            os.link(lock, self.base / 'hardlink')
            with self.assertRaisesRegex(ValueError, 'Unsafe RAID'):
                self.wizard.run_backup(self.wizard.ROOT / 'documents')
            run.assert_not_called()

    def test_source_unmounted_but_directory_exists_fails_closed(self):
        self.enroll()
        self.calls.clear()
        with patch.object(self.wizard, 'source_identity', return_value={
                'target': '/', 'source': '/dev/other', 'uuid': 'other'}):
            with self.assertRaisesRegex(ValueError, 'Source filesystem identity changed'):
                self.enroll(['yes'], reuse=True)
        self.assertTrue(self.source.is_dir())
        self.assertEqual(self.calls, [])

    def test_no_echo_fallback_and_exclusive_secret_write(self):
        with patch.object(self.wizard.getpass, 'getpass', side_effect=self.wizard.getpass.GetPassWarning('no terminal')), \
                patch('builtins.input', side_effect=self.answers()), \
                patch.object(self.wizard, 'run', side_effect=self.fake_run), \
                patch.object(self.wizard.sys.stdin, 'isatty', return_value=True), \
                patch.object(self.wizard, 'mount_identity', return_value=self.identity), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(self.wizard.getpass.GetPassWarning):
                self.wizard.enroll('documents')
        self.assertFalse(self.wizard.ROOT.exists())
        path = self.base / 'existing-secret'
        path.write_text('preserve')
        with self.assertRaises(FileExistsError):
            self.wizard.write_new(path, 'overwrite')
        self.assertEqual(path.read_text(), 'preserve')

    def test_legacy_storage_and_snapshots_untouched(self):
        wrapper = (PROJECT / 'system_files/usr/bin/setup-home-backup').read_text()
        self.assertIn('exec /usr/bin/setup-backup "$@"', wrapper)
        for forbidden in ('cryptsetup', "run('mdadm'", '/etc/fstab', '/etc/crypttab', 'snapper-timeline', 'disable --now'):
            self.assertNotIn(forbidden, wrapper)
            self.assertNotIn(forbidden, SCRIPT.read_text())
        legacy = (PROJECT / 'system_files/usr/bin/home-borgmatic').read_text()
        self.assertIn('/etc/borgmatic.d/home.yaml', legacy)
        self.assertIn('flock -n 9', legacy)

    def test_named_run_routes_through_shared_coordination(self):
        fd = os.open(self.base / 'named.lock', os.O_CREAT | os.O_WRONLY, 0o600)
        with patch.object(self.wizard.sys, 'argv', ['setup-backup', '--run', 'documents']), \
                patch.object(self.wizard.os, 'geteuid', return_value=0), \
                patch.object(self.wizard.os, 'umask'), \
                patch.object(self.wizard.os, 'open', return_value=fd), \
                patch.object(self.wizard, 'run_backup') as coordinated:
            self.wizard.main()
        coordinated.assert_called_once_with(self.wizard.ROOT / 'documents')

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze unavailable')
    def test_units_offline(self):
        units = self.base / 'offline-units'
        units.mkdir()
        for suffix in ('service', 'timer'):
            text = (PROJECT / ('system_files/usr/lib/systemd/system/backup@.' + suffix)).read_text()
            text = text.replace('/usr/bin/setup-backup', '/bin/true')
            (units / ('backup@.' + suffix)).write_text(text)
        for target in ('network-online', 'local-fs', 'sysinit', 'basic', 'shutdown', 'timers'):
            (units / (target + '.target')).write_text('[Unit]\nDescription=Offline test target\n')
        result = subprocess.run(['systemd-analyze', 'verify', '--man=no', str(units / 'backup@documents.timer')],
                                env={**os.environ, 'SYSTEMD_UNIT_PATH': str(units)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        preset = PROJECT / 'system_files/usr/lib/systemd/system-preset/80-niri-backup.preset'
        self.assertEqual(preset.read_text(), 'disable backup@*.timer\n')

    @unittest.skipUnless(os.environ.get('BACKUP_REAL_CONTAINER') == '1', 'run only in disposable container')
    def test_actual_borgmatic_backup_restore(self):
        home = self.base / 'home'
        home.mkdir()
        environment = patch.dict(self.wizard.ENV, {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
                                               'XDG_CACHE_HOME': str(home / '.cache'), 'XDG_STATE_HOME': str(home / '.state')})
        environment.start()
        self.addCleanup(environment.stop)
        real_run = self.wizard.run
        def isolated_run(*args, **kwargs):
            if args[0] == 'systemctl':
                return self.fake_run(*args, **kwargs)
            return real_run(*args, **kwargs)
        self.enroll(runner=isolated_run)
        config = str(self.wizard.ROOT / 'documents/config.yaml')
        real_run('borgmatic', '--config', config)
        real_run('borgmatic', '--config', config, 'check', '--force')
        restore = self.base / 'restore'
        restore.mkdir()
        old = os.getcwd()
        try:
            os.chdir(restore)
            real_run('borgmatic', '--config', config, 'extract', '--archive', 'latest')
        finally:
            os.chdir(old)
        restored = restore / str(self.source).lstrip('/') / 'important.txt'
        self.assertEqual(restored.read_bytes(), (self.source / 'important.txt').read_bytes())


if __name__ == '__main__':
    unittest.main()
