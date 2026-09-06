"""Installer contract plus an actual nonmutating upstream parse in the proof container."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SanoidTests(unittest.TestCase):
    def test_installer_contract(self):
        path = ROOT / 'scripts/install-sanoid.sh'
        subprocess.run(['bash', '-n', str(path)], check=True)
        text = path.read_text()
        self.assertIn('https://codeload.github.com/jimsalterjrs/sanoid/tar.gz/refs/tags/v2.3.0', text)
        self.assertIn('1d8735a271a34ec87ea46313a66f6f20bd38b583886924574d3c1f72ea173620', text)
        self.assertLess(text.index('sha256sum -c'), text.index('tar --extract'))
        self.assertIn('--repo=fedora --repo=updates', text)
        self.assertNotIn('systemctl', text)
        self.assertNotIn('/etc/sanoid', text)
        for module in ('Config-IniFiles', 'Capture-Tiny', 'Data-Dumper', 'File-Path',
                       'File-Copy', 'Getopt-Long', 'Pod-Usage', 'Time-Local', 'Sys-Hostname'):
            self.assertIn('perl-' + module, text)

    @unittest.skipUnless(shutil.which('sanoid'), 'Actual upstream parse requires the disposable proof container')
    def test_upstream_parse_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = (ROOT / 'fedora_files/usr/share/fedora-zfs/sanoid.conf.in').read_text()
            config = root / 'sanoid.conf'
            config.write_text(template.format(source='tank/data', hourly=24, daily=7, weekly=4))
            shutil.copy('/usr/share/sanoid/sanoid.defaults.conf', root)
            # Reject every storage invocation. --readonly alone parses config,
            # without selecting a snapshot/prune action or needing a live pool.
            for name in ('zfs', 'zpool'):
                stub = root / name
                stub.write_text('#!/bin/sh\nprintf "unexpected storage call\\n" >&2\nexit 99\n')
                stub.chmod(0o755)
            args = ['sanoid', '--readonly', '--configdir=' + tmp,
                    '--cache-dir=' + tmp + '/cache', '--run-dir=' + tmp + '/run']
            env = {**os.environ, 'PATH': tmp + ':' + os.environ['PATH']}
            result = subprocess.run(args, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('unexpected storage call', result.stderr)
            config.write_text(config.read_text() + '\ninvalid_setting = yes\n')
            result = subprocess.run(args, env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("don't understand the setting", result.stderr)


if __name__ == '__main__':
    unittest.main()
