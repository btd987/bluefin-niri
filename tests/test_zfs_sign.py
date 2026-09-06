"""Signing helper executes with redirected paths and mocked crypto, no secrets."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_zfs_runtime import FINGERPRINT, KERNEL, NAMES, ROOT, STUB


SCRIPT = ROOT / "scripts/sign-zfs-rpms.sh"


class ZFSSigningTests(unittest.TestCase):
    def run_sign(self, changes=None, fingerprint=FINGERPRINT, packages=None):
        data = {"kernel": KERNEL, **(changes or {})}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.json").write_text(json.dumps(data))
            for directory in ("bin", "run/secrets", "run/zfs-signing", "run/zfs-rpms"):
                (root / directory).mkdir(parents=True)
            (root / ".dockerenv").touch()
            for command in ("rpm", "rpmsign", "gpg", "gpgconf", "stat"):
                path = root / "bin" / command
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o755)
            if not data.get("missing_key"):
                (root / "run/secrets/zfs_rpm_signing_key").write_text("NOT A KEY: fixture only")
            artifacts = root / "run/zfs-rpms"
            (artifacts / "kernel-uname-r").write_text(data.get("artifact_kernel", KERNEL))
            (artifacts / "zfs-signing-cert.der").write_text("public cert fixture")
            if data.get("symlink_cert"):
                (artifacts / "zfs-signing-cert.der").unlink()
                (artifacts / "zfs-signing-cert.der").symlink_to(root / "run/secrets/zfs_rpm_signing_key")
            for name in NAMES if packages is None else packages:
                (artifacts / (name + ".rpm")).touch()
            text = re.sub(r"(?<![\w/-])(/run/|/\.dockerenv|/out\b)",
                          lambda match: str(root) + match[0], SCRIPT.read_text())
            result = subprocess.run(["bash", "-c", text], capture_output=True, text=True,
                                    env={**os.environ, "PATH": f"{root / 'bin'}:/usr/bin:/bin",
                                         "ZFS_RPM_SIGNING_FINGERPRINT": fingerprint})
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()] if (root / "calls").exists() else []
            self.assertEqual(list((root / "run/zfs-signing").iterdir()), [])
            outputs = sorted(p.name for p in (root / "out").glob("*"))
            return result, calls, outputs

    def test_signs_only_allowlist_and_exports_public_metadata(self):
        result, calls, outputs = self.run_sign()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, sorted([n + ".rpm" for n in NAMES] +
                                        ["kernel-uname-r", "zfs-signing-cert.der", "zfs-rpm-signing-key.asc"]))
        sign = next(c for c in calls if c[0] == "rpmsign")
        self.assertIn("_openpgp_sign_id " + FINGERPRINT + "!", sign)
        self.assertIn("--resign", sign)
        self.assertEqual(sum("--checksig" in c for c in calls), 6)
        self.assertTrue(all("--dbpath" in c for c in calls if c[0] == "rpm" and "--import" in c))

    def test_fail_closed_before_signing(self):
        cases = [{"missing_key": True}, {"filesystem": "ext4"}, {"gpg_import_status": 2},
                 {"fingerprints": []}, {"fingerprints": ["B" * 40]},
                 {"fingerprints": [FINGERPRINT, "B" * 40]}, {"artifact_kernel": "../bad"},
                 {"names": {"libzfs7": "zfs"}}, {"evra": "wrong"}, {"symlink_cert": True}]
        for changes in cases:
            with self.subTest(changes=changes):
                result, calls, _ = self.run_sign(changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] == "rpmsign" for c in calls))
        for fingerprint in ("", "a" * 40, "A" * 16, FINGERPRINT + "\n"):
            result, calls, _ = self.run_sign(fingerprint=fingerprint)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])
        for packages in (NAMES[:-1], NAMES + ["extra"], NAMES[:-1] + ["zfs-dkms"]):
            result, calls, _ = self.run_sign(packages=packages)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(c[0] == "rpmsign" for c in calls))

    def test_signing_and_signature_failures(self):
        for changes in ({"sign_status": 2}, {"signature_status": 1}, {"import_status": 1},
                        {"signature": "    Payload SHA256 digest: OK"},
                        {"signature": "    Header RSA Signature: NOKEY"},
                        {"signature": "    Header RSA Signature: BAD"}):
            with self.subTest(changes=changes):
                result, _, _ = self.run_sign(changes)
                self.assertNotEqual(result.returncode, 0)

    def test_container_secret_isolation(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        text = (ROOT / "Containerfile.zfs-sign").read_text()
        self.assertIn("--mount=type=secret,id=zfs_rpm_signing_key,required=true", text)
        self.assertIn("--mount=type=tmpfs,target=/run/zfs-signing", text)
        self.assertIn("install rpm-sign gnupg2", text)
        self.assertEqual(text.split("FROM scratch AS zfs-signed-rpms\n")[1],
                         "COPY --from=zfs-signer /out/ /\n")
        self.assertNotIn("--export-secret", SCRIPT.read_text())


if __name__ == "__main__":
    unittest.main()
