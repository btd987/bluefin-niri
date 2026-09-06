"""Offline build-contract checks and optional real exported-artifact validation.

Set NIRIUS_ARTIFACT_DIR to an exported artifact root to check binary hashes.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "82478b606e560f82f59c8f580da0a9eb88448c08b69996cba55029aa03cabfbe"
BASE = "quay.io/fedora/fedora-bootc:44@sha256:d6481b291e960abb02a346294dcac2818df8dfe2b1bc51d1ae8fa53a15718756"


class NiriusTests(unittest.TestCase):
    def test_source_and_locked_build_contract(self):
        script = ROOT / "scripts/build-nirius.sh"
        subprocess.run(["bash", "-n", str(script)], check=True)
        text = script.read_text()
        self.assertIn("set -euo pipefail", text)
        self.assertIn("readonly version=0.9.0", text)
        self.assertIn(f"readonly source_sha256={SOURCE_SHA256}", text)
        self.assertIn("https://static.crates.io/crates/nirius/nirius-${version}.crate", text)
        self.assertIn("--fail --location --proto '=https' --proto-redir '=https'", text)
        steps = ["sha256sum --check --strict", "tar -xzf", "[[ ! -s Cargo.lock ]]",
                 "exit 1", "cargo build --locked --release --bin nirius --bin niriusd",
                 "install -Dm755 target/release/nirius /out/nirius",
                 "install -Dm755 target/release/niriusd /out/niriusd"]
        positions = [text.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("sha256sum nirius niriusd", text)
        self.assertIn("sha256sum Cargo.lock", text)
        self.assertIn(f"builder_base={BASE}", text)
        self.assertNotRegex(text, r"(?m)^\s*(strip|systemctl)\b")

    def test_artifact_stage_contract(self):
        text = (ROOT / "Containerfile.nirius").read_text()
        stages = re.findall(r"^FROM (.+)$", text, re.MULTILINE)
        self.assertEqual(stages, [f"{BASE} AS builder", "scratch AS artifact"])
        builder, artifact = text.split("FROM scratch AS artifact\n")
        self.assertIn("install rust cargo gcc curl tar gzip", builder)
        self.assertIn("RUN bash /build/build-nirius.sh", builder)
        self.assertEqual(artifact.strip(), "COPY --from=builder /out/ /")

    @unittest.skipUnless(os.environ.get("NIRIUS_ARTIFACT_DIR"), "no real artifact export supplied")
    def test_exported_artifact_hashes(self):
        artifact = Path(os.environ["NIRIUS_ARTIFACT_DIR"])
        self.assertEqual({p.name for p in artifact.iterdir()},
                         {"nirius", "niriusd", "provenance.txt"})
        manifest = (artifact / "provenance.txt").read_text()
        self.assertIn(f"source_sha256={SOURCE_SHA256}\n", manifest)
        self.assertIn("version=0.9.0\n", manifest)
        self.assertIn(f"builder_base={BASE}\n", manifest)
        hashes = manifest.split("[artifact-sha256]\n")[1].splitlines()
        self.assertEqual(len(hashes), 2)
        for line, name in zip(hashes, ("nirius", "niriusd")):
            binary = artifact / name
            self.assertEqual(line, f"{hashlib.sha256(binary.read_bytes()).hexdigest()}  {name}")
            self.assertTrue(binary.stat().st_mode & 0o111)
            self.assertEqual(binary.read_bytes()[:4], b"\x7fELF")


if __name__ == "__main__":
    unittest.main()
