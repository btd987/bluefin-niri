"""Offline control-flow tests; real release verification uses the source stage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify-zfs-source.sh"
FINGERPRINT = "4F3BA9AB6D1F8D683DC2DFB56AD860EED4598027"
STUB = r'''
import json
import os
from pathlib import Path
import sys

name, args = Path(sys.argv[0]).name, sys.argv[1:]
home = Path(os.environ["GNUPGHOME"])
assert home != Path(os.environ["PERSONAL_HOME"])
assert home.stat().st_mode & 0o777 == 0o700
with Path(os.environ["CALLS"]).open("a") as log:
    log.write(json.dumps([name, args, str(home)]) + "\n")
if name == "curl":
    assert args[args.index("--proto") + 1] == "=https"
    assert args[args.index("--proto-redir") + 1] == "=https"
    assert "--fail" in args
    if os.environ.get("FAIL") == "download":
        sys.exit(22)
    Path(args[args.index("--output") + 1]).touch()
else:
    assert "--batch" in args and "--no-options" in args
    if "--show-keys" in args:
        if os.environ.get("FAIL") == "show":
            sys.exit(2)
        for fingerprint in os.environ["FINGERPRINTS"].split(","):
            print("pub:::::::::")
            print("fpr:::::::::" + fingerprint + ":")
        print("sub:::::::::")
        print("fpr:::::::::SUBKEY:")
    elif "--import" in args:
        if os.environ.get("FAIL") == "import":
            sys.exit(2)
    elif "--verify" in args:
        assert "--no-auto-key-retrieve" in args
        assert args[-1] == "zfs-2.4.4.tar.gz"
        if os.environ.get("FAIL") == "signature":
            sys.exit(1)
    else:
        raise AssertionError(args)
'''


class ZFSSourceTests(unittest.TestCase):
    def verify(self, fingerprints=FINGERPRINT, fail=""):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            personal = root / "personal"
            personal.mkdir()
            (personal / "sentinel").write_text("unchanged")
            for command in ("curl", "gpg"):
                path = root / command
                path.write_text(f"#!{sys.executable}\n" + STUB)
                path.chmod(0o755)
            result = subprocess.run(
                ["bash", str(SCRIPT)], cwd=root, capture_output=True, text=True,
                env={**os.environ, "PATH": f"{root}:/usr/bin:/bin",
                     "GNUPGHOME": str(personal), "PERSONAL_HOME": str(personal),
                     "CALLS": str(root / "calls"), "FINGERPRINTS": fingerprints,
                     "FAIL": fail, "TMPDIR": str(root)},
            )
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            self.assertEqual(list(personal.iterdir()), [personal / "sentinel"])
            self.assertEqual((personal / "sentinel").read_text(), "unchanged")
            for _, _, home in calls:
                self.assertFalse(Path(home).exists(), "temporary keyring was not removed")
            return result, calls

    def test_pinned_key_and_signature(self):
        result, calls = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--verify", calls[-1][1])
        self.assertIn("search=0x" + FINGERPRINT, " ".join(calls[0][1]))
        self.assertIn("zfs-2.4.4.tar.gz.asc", " ".join(calls[1][1]))

    def test_wrong_missing_or_additional_key(self):
        for fingerprints in ("", "0" * 40, FINGERPRINT + "," + "0" * 40):
            with self.subTest(fingerprints=fingerprints):
                result, calls = self.verify(fingerprints)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("fingerprint mismatch", result.stderr)
                self.assertFalse(any("--import" in args or "--verify" in args
                                     for _, args, _ in calls))

    def test_fail_closed(self):
        for failure in ("download", "show", "import", "signature"):
            with self.subTest(failure=failure):
                result, _ = self.verify(fail=failure)
                self.assertNotEqual(result.returncode, 0)

    def test_source_stage_contract(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        source = (ROOT / "Containerfile.zfs").read_text().split("FROM zfs-source AS")[0]
        self.assertIn("gnupg2", source)
        self.assertIn("COPY scripts/verify-zfs-source.sh", source)
        self.assertLess(source.index("sha256sum --check --strict"),
                        source.index("bash /build/verify-zfs-source.sh &&"))
        self.assertLess(source.index("bash /build/verify-zfs-source.sh &&"),
                        source.index("tar -xzf"))


if __name__ == "__main__":
    unittest.main()
