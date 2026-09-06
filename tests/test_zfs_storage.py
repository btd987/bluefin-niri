#!/usr/bin/python3
"""Root-container tests with executable stubs, never host pool commands.

podman run --rm --network=none -v "$PWD:/src:ro" --security-opt label=disable \
  --entrypoint python3 localhost/fedora-niri:proof /src/tests/test_zfs_storage.py
"""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


RUNNER = '''
import os, runpy, sys
from pathlib import Path
storage = runpy.run_path(sys.argv[1])['storage']
storage.CONFIG = Path(os.environ['CONFIG_DIR'])
storage.ENV = dict(os.environ)
sys.argv = ['storage', *sys.argv[2:]]
flock = storage.fcntl.flock
def notified_flock(fd, operation):
    print('locking', flush=True)
    flock(fd, operation)
storage.fcntl.flock = notified_flock
storage.main()
'''


def stub():
    state = Path(os.environ['STATE'])
    data = json.loads(state.read_text())
    args = [Path(sys.argv[0]).name, *sys.argv[1:]]
    with Path(os.environ['CALLS']).open('a') as out:
        out.write(json.dumps(args) + '\n')
    result = ''
    if args[:2] == ['zpool', 'list']:
        result = data['pools']
    elif args[:2] == ['zpool', 'get']:
        result = '1'
    elif args[:2] == ['zpool', 'import']:
        assert args == ['zpool', 'import', '-N', '-o', 'cachefile=none', '1']
        data['pools'] = 'tank\t1'
    elif args[:2] == ['zfs', 'get']:
        result = data.get(args[-1], data['tank/home'])[args[-2]]
    elif args[:2] == ['zfs', 'list']:
        result = 'tank/home\t2\t/var/mnt/storage-test\tno\t-'
    elif args[0] == 'findmnt':
        result = json.dumps({'filesystems': data['mounts']})
    elif args[:2] == ['zfs', 'load-key']:
        assert args[:3] == ['zfs', 'load-key', '-L'] and args[-1] == 'tank/home'
        if args[3] == 'prompt':
            assert sys.stdin.buffer.read() == b'secret\n'
        else:
            assert args[3].startswith('file:///proc/self/fd/')
            assert Path(args[3][7:]).read_bytes() == b'secret\n'
        if data.get('fail_key'):
            print('secret', file=sys.stderr)
            sys.exit(1)
        data['tank/home']['keystatus'] = 'available'
    elif args[:2] == ['zfs', 'mount']:
        assert args == ['zfs', 'mount', 'tank/home']
        data['tank/home']['mounted'] = 'yes'
        data['mounts'] = [dict(target=data['tank/home']['mountpoint'], source='tank/home', fstype='zfs')]
    elif args[0] == 'systemd-ask-password':
        result = 'secret'
    elif args[0] == 'systemctl':
        if data.get('fail_enable') and args[1] == 'enable':
            sys.exit(1)
        if data.get('start_service') and args[1] == 'enable':
            mode, ident = args[-1].removeprefix('fedora-zfs-storage-').removesuffix('.service').split('@')
            subprocess.run(['/usr/bin/python3', '-c', RUNNER, str(Path(__file__).resolve()),
                            'run', ident, mode], check=True, capture_output=True, timeout=10)
            return  # Do not overwrite the runtime process's state changes.
    else:
        raise AssertionError(args)
    state.write_text(json.dumps(data))
    if result:
        print(result)


ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader('storage', str(ROOT / 'fedora_files/usr/libexec/fedora-zfs-storage'))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
storage = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(storage)


@unittest.skipUnless(os.geteuid() == 0 and Path('/run/.containerenv').exists(), 'requires disposable root Podman container')
class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/etc')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for tool in ('zfs', 'zpool', 'findmnt', 'systemctl', 'systemd-ask-password'):
            executable = self.bin / tool
            executable.write_text('#!/usr/bin/python3\nimport runpy\nm = runpy.run_path(' + repr(str(Path(__file__).resolve())) + ')\nm["stub"]()\n')
            executable.chmod(0o700)
        self.state = self.base / 'state'
        self.calls = self.base / 'calls'
        self.mp = Path('/var/mnt/storage-test')
        self.mp.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.mp.rmdir)
        self.data = {'pools': 'tank\t1', 'mounts': [], 'tank/home': dict(
            type='filesystem', guid='2', mountpoint=str(self.mp), canmount='on', mounted='no',
            encryptionroot='-', keystatus='available', keyformat='passphrase')}
        self.job = dict(dataset='tank/home', guid='2', pool_guid='1', mountpoint=str(self.mp),
                        mode='data', encryptionroot='-', root_guid='-', unlock='none', keyfile='')
        self.save()
        for attr, value in [('CONFIG', self.base / 'config'), ('ENV', {
                'PATH': str(self.bin), 'STATE': str(self.state), 'CALLS': str(self.calls),
                'CONFIG_DIR': str(self.base / 'config')})]:
            ctx = patch.object(storage, attr, value)
            ctx.start()
            self.addCleanup(ctx.stop)

    def save(self):
        self.state.write_text(json.dumps(self.data))

    def logged(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def main(self, args, answers=()):
        with patch.object(sys, 'argv', ['storage', *args]), patch('builtins.input', side_effect=answers):
            storage.main()

    def encrypted(self, mode):
        self.job.update(encryptionroot='tank/home', root_guid='2', unlock=mode)
        self.data['tank/home'].update(encryptionroot='tank/home', keystatus='unavailable')
        if mode == 'keyfile':
            key = self.base / 'key'
            key.write_bytes(b'secret\n')
            key.chmod(0o600)
            self.job['keyfile'] = str(key)
        self.save()

    def test_import_selected_and_mount(self):
        self.data['pools'] = ''
        self.save()
        storage.mount(self.job)
        self.assertIn(['zpool', 'import', '-N', '-o', 'cachefile=none', '1'], self.logged())
        self.assertIn(['zfs', 'mount', 'tank/home'], self.logged())

    def test_collisions(self):
        for pools in ('tank\t9', 'other\t1', 'tank\t1\nother\t1'):
            self.data['pools'] = pools
            self.save()
            with self.assertRaises(ValueError):
                storage.mount(self.job)
        self.assertFalse(any(c[1] in ('import', 'mount') for c in self.logged()))

    def test_unsafe_properties_and_identity(self):
        for key, value in [('guid', '9'), ('type', 'volume'), ('canmount', 'off'),
                           ('mountpoint', '/etc'), ('encryptionroot', 'tank')]:
            with self.subTest(key=key):
                old = self.data['tank/home'][key]
                self.data['tank/home'][key] = value
                self.save()
                with self.assertRaises(ValueError):
                    storage.mount(self.job)
                self.data['tank/home'][key] = old
        self.assertFalse(any(c[:2] == ['zfs', 'mount'] for c in self.logged()))

    def test_nonempty_and_foreign_mount(self):
        file = self.mp / 'live'
        file.touch()
        try:
            with self.assertRaises(ValueError):
                storage.mount(self.job)
        finally:
            file.unlink()
        self.data['mounts'] = [dict(target=str(self.mp), source='/dev/sda', fstype='ext4')]
        self.save()
        with self.assertRaises(ValueError):
            storage.mount(self.job)

    def test_child_root_password_and_keyfile(self):
        for mode in ('ask', 'keyfile'):
            self.encrypted(mode)
            self.data['tank/home']['mounted'] = 'no'
            self.data['mounts'] = []
            self.save()
            storage.mount(self.job)
        self.assertEqual(sum(c[:2] == ['zfs', 'load-key'] for c in self.logged()), 2)
        self.assertNotIn('secret', self.calls.read_text())

    def test_key_failure_never_mounts(self):
        self.encrypted('ask')
        self.data['fail_key'] = True
        self.save()
        with self.assertRaises(subprocess.CalledProcessError):
            storage.mount(self.job)
        self.assertFalse(any(c[:2] == ['zfs', 'mount'] for c in self.logged()))

    def test_encryption_root_drift_and_raw_prompt_refused(self):
        self.encrypted('ask')
        for key, value in [('keyformat', 'raw'), ('encryptionroot', 'tank'), ('guid', '7')]:
            old = self.data['tank/home'][key]
            self.data['tank/home'][key] = value
            self.save()
            with self.assertRaises(ValueError):
                storage.mount(self.job)
            self.data['tank/home'][key] = old
        self.assertFalse(any(c[:2] == ['zfs', 'load-key'] for c in self.logged()))

    def test_duplicate_and_wrong_template(self):
        self.main(['enroll', 'test'], ['tank/home', f'ENROLL data {self.mp}'])
        with self.assertRaises(ValueError):
            self.main(['enroll', 'other'], ['tank/home'])
        with self.assertRaises(ValueError):
            self.main(['run', 'test', 'home'])

    def test_key_permissions_symlink_and_parent(self):
        self.encrypted('keyfile')
        key = Path(self.job['keyfile'])
        for mode in (0o644, 0o000, 0o660):
            key.chmod(mode)
            with self.assertRaises(ValueError):
                storage.validate(self.job)
        key.chmod(0o600)
        link = self.base / 'link'
        link.symlink_to(key)
        with self.assertRaises(ValueError):
            storage.validate({**self.job, 'keyfile': str(link)})
        self.base.chmod(0o777)
        with self.assertRaises(ValueError):
            storage.validate(self.job)
        self.base.chmod(0o700)

    def test_enroll_cancel_partial_and_loaded_validation(self):
        self.main(['enroll', 'test'], ['tank/home', 'cancel'])
        self.assertEqual(list(storage.CONFIG.iterdir()), [])
        self.data['fail_enable'] = True
        self.save()
        with self.assertRaises(subprocess.CalledProcessError):
            self.main(['enroll', 'test'], ['tank/home', f'ENROLL data {self.mp}'])
        config = storage.CONFIG / 'test.json'
        before = config.read_bytes()
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.main(['enroll', 'test'])
        self.assertEqual(config.read_bytes(), before)
        config.write_text(json.dumps({**self.job, 'dataset': 'tank/home;id'}))
        with self.assertRaises(ValueError):
            self.main(['run', 'test', 'data'])

    def test_home_requires_existing_mount(self):
        job = {**self.job, 'mountpoint': '/var/home', 'mode': 'home'}
        Path('/var/home').mkdir(exist_ok=True)
        self.data['tank/home']['mountpoint'] = '/var/home'
        self.save()
        with self.assertRaises(ValueError):
            storage.inspect(job, enrolling=True)
        self.data['tank/home']['mounted'] = 'yes'
        self.data['mounts'] = [dict(target='/var/home', source='tank/home', fstype='zfs')]
        self.save()
        self.assertTrue(storage.inspect(job, enrolling=True))

    def test_lock(self):
        storage.CONFIG.mkdir(mode=0o700)
        with patch('builtins.input', side_effect=AssertionError('must not prompt')):
            fd = os.open(storage.CONFIG, os.O_RDONLY | os.O_DIRECTORY)
            try:
                storage.fcntl.flock(fd, storage.fcntl.LOCK_EX)
                with self.assertRaises(BlockingIOError):
                    self.main(['enroll', 'locked'])
            finally:
                os.close(fd)

    def test_enrollment_starts_runtime_after_unlock(self):
        self.encrypted('keyfile')
        self.data['start_service'] = True
        self.save()
        self.main(['enroll', 'test'], ['tank/home', 'keyfile', self.job['keyfile'],
                                     f'ENROLL data {self.mp}'])
        self.assertEqual(json.loads((storage.CONFIG / 'test.json').read_text()), self.job)
        self.assertIn(['zfs', 'mount', 'tank/home'], self.logged())
        self.assertEqual(json.loads(self.state.read_text())['tank/home']['mounted'], 'yes')

    def test_runtime_waits_and_reads_configuration_under_lock(self):
        storage.CONFIG.mkdir(mode=0o700)
        self.encrypted('keyfile')
        for mode in ('data', 'home'):
            with self.subTest(mode=mode):
                mp = str(self.mp) if mode == 'data' else '/var/home'
                Path(mp).mkdir(exist_ok=True)
                self.job.update(mode=mode, mountpoint=mp)
                self.data['tank/home'].update(mountpoint=mp, mounted='no', keystatus='unavailable')
                self.data['mounts'] = []
                self.save()
                self.calls.unlink(missing_ok=True)
                fd = os.open(storage.CONFIG, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    config = storage.CONFIG / 'test.json'
                    config.write_text('{')
                    config.chmod(0o600)
                    with subprocess.Popen(
                            ['/usr/bin/python3', '-c', RUNNER, str(Path(__file__).resolve()),
                             'run', 'test', mode], env=storage.ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
                        try:
                            self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'runtime did not reach lock')
                            self.assertEqual(child.stdout.readline().strip(), 'locking')
                            with self.assertRaises(subprocess.TimeoutExpired):
                                child.wait(timeout=0.3)
                            self.assertEqual(self.logged(), [])
                            config.write_text(json.dumps(self.job))
                            fcntl.flock(fd, fcntl.LOCK_UN)
                            _, stderr = child.communicate(timeout=10)
                            self.assertEqual(child.returncode, 0, stderr)
                        finally:
                            if child.poll() is None:
                                child.kill()
                                child.communicate()
                finally:
                    os.close(fd)
                self.assertIn(['zfs', 'mount', 'tank/home'], self.logged())

    def test_status_readonly(self):
        self.main(['status'])
        self.assertEqual([c[:2] for c in self.logged()],
                         [['zpool', 'list'], ['zfs', 'list'], ['findmnt', '-t']])

    def test_units_verify_and_requirement(self):
        units = ROOT / 'fedora_files/usr/lib/systemd/system'
        paths = [units / f'fedora-zfs-storage-{mode}@.service' for mode in ('home', 'data')]
        subprocess.run(['systemd-analyze', 'verify', *map(str, paths)], check=True, capture_output=True)
        home = paths[0].read_text()
        self.assertIn('Before=systemd-user-sessions.service', home)
        self.assertIn('RequiredBy=systemd-user-sessions.service', home)
        for path in paths:
            self.assertNotIn('ExecStop', path.read_text())
        root = self.base / 'unit-root'
        dest = root / 'etc/systemd/system'
        dest.mkdir(parents=True)
        (dest / paths[0].name).write_text(home)
        subprocess.run(['/usr/bin/systemctl', '--root=' + str(root), 'enable',
                        'fedora-zfs-storage-home@test.service'], check=True, capture_output=True)
        self.assertTrue((dest / 'systemd-user-sessions.service.requires/fedora-zfs-storage-home@test.service').is_symlink())


if __name__ == '__stub__':
    stub()
elif __name__ == '__main__':
    unittest.main()
