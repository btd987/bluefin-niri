"""All storage, service, privilege and SSH interactions are mocked."""
import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader('fedora_zfs', str(ROOT / 'fedora_files/usr/libexec/fedora-zfs'))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
zfs = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(zfs)


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.job = dict(kind='replication', source='tank/data', target='backup/data', remote='', schedule='daily')
        self.calls = []
        self.overrides = {}

    def command(self, args):
        self.calls.append(args)
        if args[0] == 'ssh':
            args = shlex.split(args[-1])
        if tuple(args) in self.overrides:
            return self.overrides[tuple(args)]
        if args[:2] == ['zpool', 'get']:
            return '1' if args[-1] == 'tank' else '2'
        if args[0] == 'zfs':
            if args[1] == 'list':
                if 'type' in args:
                    return 'filesystem'
                if 'snapshot' in args:
                    return 'backup/data@seed\t123'
                return 'backup/data'
            return {'readonly': 'on', 'mounted': 'no', 'receive_resume_token': '-',
                    'guid': '123', 'written@seed': '0'}[args[-2]]
        if args[:2] == ['zpool', 'list']:
            return 'ONLINE'
        return ''

    def test_invalid_names_hosts_cycles_and_retention(self):
        for key, values in {
            'source': ['-x', 'tank/a;id', 'tank/a b', 'tank/../a', 'tank/a\nx', 'tank/a@s'],
            'target': ['tank/data', 'tank/data/child', 'tank', 'backup'],
            'remote': ['-oProxyCommand=id', 'root@host;id', 'root@host:22', 'a@$(id)',
                       'a@host\nx', 'a@host/xx', 'a b@host'],
            'schedule': ['*:0/1', 'daily\nExecStart=id'],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    zfs.validate({**self.job, key: value})
        for value in (-1, 10001, True, '2'):
            with self.assertRaises(ValueError):
                zfs.validate(dict(kind='snapshots', source='tank/data', schedule='hourly',
                                  hourly=value, daily=0, weekly=0))

    def test_destination_fail_closed(self):
        with patch.object(zfs, 'command', self.command):
            zfs.preflight(self.job)
        cases = [(['zpool', 'get', '-H', '-o', 'value', 'guid', 'backup'], '1'),
                 (['zfs', 'list', '-H', '-r', '-o', 'name', 'backup/data'], 'backup/data\nbackup/data/child')]
        for prop, value in [('readonly', 'off'), ('mounted', 'yes'), ('receive_resume_token', 'token'),
                            ('written@seed', '1')]:
            cases.append((['zfs', 'get', '-H', *(['-p'] if prop.startswith('written') else []),
                           '-o', 'value', prop, 'backup/data'], value))
        cases.append((['zfs', 'get', '-H', '-o', 'value', 'guid', 'tank/data@seed'], '999'))
        cases.append((['zfs', 'list', '-H', '-p', '-d', '1', '-t', 'snapshot',
                       '-o', 'name,guid', '-s', 'createtxg', 'backup/data'], ''))
        cases.append((['zfs', 'list', '-H', '-o', 'type', 'backup/data'], 'volume'))
        for args, output in cases:
            self.overrides = {tuple(args): output}
            with self.subTest(args=args), patch.object(zfs, 'command', self.command), self.assertRaises(ValueError):
                zfs.preflight(self.job)
        self.assertFalse(any(c[0] == 'syncoid' for c in self.calls))

    def test_remote_queries_preserve_shell_argument_boundaries(self):
        job = {**self.job, 'remote': 'backup@server.example'}
        args = ['zfs', 'get', '-H', '-o', 'value', 'written@seed', 'backup/data']
        with patch.object(zfs, 'command', self.command):
            zfs.preflight(job)
        remote = [call for call in self.calls if call[0] == 'ssh']
        self.assertTrue(remote)
        for call in remote:
            self.assertEqual(call[:-1], ['ssh', *zfs.SSH, job['remote']])
        with patch.object(zfs, 'command') as command:
            zfs.query(job, args + ['shell metacharacters; $not_expanded'], True)
        self.assertEqual(shlex.split(command.call_args.args[0][-1]),
                         args + ['shell metacharacters; $not_expanded'])

    def test_cancel_no_writes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(zfs, 'JOBS', Path(tmp) / 'jobs'), \
                patch.object(zfs, 'UNITS', Path(tmp) / 'units'), patch.object(zfs, 'command', self.command), \
                patch('builtins.input', side_effect=['replication', 'tank/data', 'daily', 'backup/data', '', 'no']):
            zfs.enroll('backup')
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertFalse(any(c[0] == 'systemctl' for c in self.calls))

    def test_enroll_permissions_rerun_and_syncoid_arguments(self):
        for remote in ('', 'backup@server.example'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                units = root / 'units'
                units.mkdir()
                with patch.object(zfs, 'JOBS', root / 'config/jobs'), patch.object(zfs, 'UNITS', units), \
                        patch.object(zfs, 'SHARE', ROOT / 'fedora_files/usr/share/fedora-zfs'), \
                        patch.object(zfs, 'command', self.command), patch.object(zfs.os, 'geteuid', return_value=0), \
                        patch.object(zfs, 'secure') as secure, \
                        patch('builtins.input', side_effect=['replication', 'tank/data', 'daily', 'backup/data', remote, 'ENROLL']):
                    zfs.enroll('backup')
                    folder = root / 'config/jobs/backup'
                    self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
                    self.assertEqual((folder / 'job.json').stat().st_mode & 0o777, 0o600)
                    self.assertIn('OnCalendar=daily', (units / 'fedora-zfs-backup.timer').read_text())
                    with self.assertRaises(ValueError):
                        zfs.enroll('backup')
                    zfs.run('backup')
                    secure.assert_any_call(folder / 'job.json')
                args = self.calls[-1]
                self.assertEqual(args[0], 'syncoid')
                for option in ('--no-rollback', '--no-resume', '--no-sync-snap', '--no-stream',
                               '--no-privilege-elevation', '--recvoptions=u o readonly=on'):
                    self.assertIn(option, args)
                self.assertNotIn('--force-delete', args)
                self.assertEqual(args[-2:], ['tank/data', (remote + ':' if remote else '') + 'backup/data'])
                if remote:
                    self.assertIn('--sshoption=StrictHostKeyChecking=yes', args)
                    self.assertIn('--sshconfig=/dev/null', args)

    def test_permissions_and_privilege(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'job'
            path.write_text('{}')
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                zfs.secure(path)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                zfs.secure(link)
        with patch.object(zfs.os, 'geteuid', return_value=1000), \
                patch.object(zfs.sys, 'argv', ['fedora-zfs', 'enroll', 'job']), self.assertRaises(ValueError):
            zfs.main()

    def test_duplicate_and_cross_job_cycles(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(zfs, 'JOBS', Path(tmp) / 'jobs'), \
                patch.object(zfs, 'UNITS', Path(tmp) / 'units'), patch.object(zfs, 'secure'):
            folder = zfs.JOBS / 'first'
            folder.mkdir(parents=True)
            (folder / 'job.json').write_text(json.dumps(self.job))
            for job in (self.job, {**self.job, 'source': 'backup/data', 'target': 'third/data'},
                        {**self.job, 'source': 'third/data', 'target': 'tank/data'},
                        {**self.job, 'source': 'third/data', 'target': 'backup/data/child'}):
                with self.subTest(job=job), self.assertRaises(ValueError):
                    zfs.conflicts('second', job)

    def test_snapshot_and_scrub_execution(self):
        jobs = [dict(kind='scrub', source='tank', schedule='weekly'),
                dict(kind='snapshots', source='tank/data', schedule='hourly', hourly=24, daily=7, weekly=4)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(zfs, 'JOBS', Path(tmp)), \
                patch.object(zfs, 'secure'), patch.object(zfs, 'command', self.command):
            folder = Path(tmp) / 'job'
            folder.mkdir()
            for job in jobs:
                (folder / 'job.json').write_text(json.dumps(job))
                zfs.run('job')
                if job['kind'] == 'scrub':
                    self.assertEqual(self.calls[-1], ['zpool', 'scrub', 'tank'])
                else:
                    self.assertEqual(self.calls[-1], ['sanoid', '--cron', '--configdir=' + str(folder),
                                                     '--cache-dir=/var/cache/fedora-zfs/job',
                                                     '--run-dir=/run/fedora-zfs/job'])

    def test_preflight_failure_never_activates(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(zfs, 'JOBS', Path(tmp) / 'jobs'), \
                patch.object(zfs, 'UNITS', Path(tmp) / 'units'), patch.object(zfs, 'command', side_effect=OSError('unavailable')), \
                patch('builtins.input', side_effect=['scrub', 'tank', 'weekly']), self.assertRaises(OSError):
            zfs.enroll('job')
        self.assertFalse(self.calls)

    def test_activation_failure_preserves_recoverable_enrollment(self):
        def command(args):
            if args[:2] == ['systemctl', 'enable']:
                raise subprocess.CalledProcessError(1, args)
            return self.command(args)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            units = root / 'units'
            units.mkdir()
            with patch.object(zfs, 'JOBS', root / 'config/jobs'), patch.object(zfs, 'UNITS', units), \
                    patch.object(zfs, 'SHARE', ROOT / 'fedora_files/usr/share/fedora-zfs'), \
                    patch.object(zfs, 'command', command), patch.object(zfs, 'secure'), \
                    patch('builtins.input', side_effect=['scrub', 'tank', 'weekly', 'ENROLL']):
                with self.assertRaises(subprocess.CalledProcessError):
                    zfs.enroll('scrub')
                files = [root / 'config/jobs/scrub/job.json', units / 'fedora-zfs-scrub.timer']
                before = [file.read_bytes() for file in files]
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    zfs.enroll('scrub')
                self.assertEqual([file.read_bytes() for file in files], before)

    def test_runtime_divergence_and_interrupted_receive_never_invoke_syncoid(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(zfs, 'JOBS', Path(tmp)), \
                patch.object(zfs, 'secure'), patch.object(zfs, 'command', self.command):
            folder = Path(tmp) / 'job'
            folder.mkdir()
            (folder / 'job.json').write_text(json.dumps(self.job))
            for prop, value in [('receive_resume_token', 'interrupted'), ('written@seed', '1')]:
                self.overrides = {('zfs', 'get', '-H', *(['-p'] if prop.startswith('written') else []),
                                   '-o', 'value', prop, 'backup/data'): value}
                with self.subTest(prop=prop), self.assertRaises(ValueError):
                    zfs.run('job')
            self.assertFalse(any(call[0] == 'syncoid' for call in self.calls))

    def test_snapshot_enrollment_parse_before_activation(self):
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            if str(path) == '/usr/share/sanoid/sanoid.defaults.conf':
                return 'upstream defaults fixture'
            return original_read(path, *args, **kwargs)
        for fail_parse in (False, True):
            self.calls.clear()
            def command(args):
                result = self.command(args)
                if fail_parse and args[0] == 'sanoid':
                    raise OSError('parse failed')
                return result
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                units = root / 'units'
                units.mkdir()
                with patch.object(zfs, 'JOBS', root / 'config/jobs'), patch.object(zfs, 'UNITS', units), \
                        patch.object(zfs, 'SHARE', ROOT / 'fedora_files/usr/share/fedora-zfs'), \
                        patch.object(zfs, 'command', command), patch.object(zfs, 'secure'), \
                        patch.object(Path, 'read_text', read), \
                        patch('builtins.input', side_effect=['snapshots', 'tank/data', 'hourly', '24', '7', '4', 'ENROLL']):
                    if fail_parse:
                        with self.assertRaises(OSError):
                            zfs.enroll('snapshots')
                        self.assertEqual(list(units.iterdir()), [])
                        self.assertFalse(any(c[0] == 'systemctl' for c in self.calls))
                    else:
                        zfs.enroll('snapshots')
                        config = root / 'config/jobs/snapshots/sanoid.conf'
                        self.assertIn('hourly = 24', config.read_text())
                        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                        parse = next(i for i, c in enumerate(self.calls) if c[0] == 'sanoid')
                        activate = next(i for i, c in enumerate(self.calls) if c[0] == 'systemctl')
                        self.assertLess(parse, activate)
                        self.assertIn('--readonly', self.calls[parse])

    def test_status_is_read_only(self):
        with patch.object(zfs.sys, 'argv', ['fedora-zfs', 'status']), patch.object(zfs, 'command', return_value='') as cmd:
            zfs.main()
        self.assertEqual([c.args[0][:2] for c in cmd.call_args_list],
                         [['lsblk', '-f'], ['findmnt', '-r'], ['zpool', 'status'], ['zfs', 'list']])


if __name__ == '__main__':
    unittest.main()
