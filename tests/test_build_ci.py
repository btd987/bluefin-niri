"""Workflow regression checks using stdlib unittest, bash and jq (no image builds).

Run: python3 -m unittest discover -s tests -p test_build_ci.py -v
Extraction intentionally follows build.yml's indentation, not general YAML syntax.
Use actionlint separately to validate YAML and GitHub Actions expressions.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


def block(text, header):
    lines = text.splitlines()
    start = lines.index(header) + 1
    indent = len(header) - len(header.lstrip())
    end = start
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    return "\n".join(lines[start:end])


WORKFLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/build.yml").read_text()
BUILD = block(WORKFLOW, "  build:")
PUBLISH = block(WORKFLOW, "  publish:")


def script(name):
    step = block(BUILD, f"      - name: {name}")
    return textwrap.dedent(block(step, "        run: |"))


def run(script, **env):
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output"
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            env={**os.environ, "GITHUB_OUTPUT": str(output), **env},
            text=True, capture_output=True,
        )
        return result, output.read_text() if output.exists() else ""


class BuildCITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("bash", "jq"):
            if not shutil.which(tool):
                raise RuntimeError(f"Workflow tests require {tool} on PATH")

    def test_permissions_and_dependencies(self):
        self.assertIn("  pull_request:\n", WORKFLOW)
        self.assertNotIn("pull_request_target:", WORKFLOW)
        self.assertEqual(block(WORKFLOW, "permissions:").strip(), "contents: read")
        for job in (BUILD, block(WORKFLOW, "  validate:")):
            self.assertEqual(block(job, "    permissions:").strip(), "contents: read")
            self.assertNotIn("secrets.", job)
            self.assertNotIn("login@", job)
            self.assertIn("          persist-credentials: false", job)
        self.assertEqual(block(PUBLISH, "    permissions:").strip(), "packages: write")
        self.assertIn("    needs: validate\n", BUILD)
        self.assertIn("    needs: build\n", PUBLISH)
        self.assertNotIn("checkout@", PUBLISH)
        self.assertIn("BASE_REF=${{ steps.base_version.outputs.base_ref }}", BUILD)

    def test_publish_gates(self):
        gate = re.search(r"^    if: (.+)$", PUBLISH, re.M).group(1)
        for name in ("Export release image", "Upload release image"):
            step = block(BUILD, f"      - name: {name}")
            self.assertIn(f"        if: {gate}\n", step)
        expression = gate.replace("github.ref", '"$REF"').replace("github.event_name", '"$EVENT"')
        for event in ("pull_request", "push", "schedule", "workflow_dispatch", "pull_request_target"):
            for ref in ("refs/heads/main", "refs/heads/feature", "refs/tags/main", "refs/pull/12/merge"):
                with self.subTest(event=event, ref=ref):
                    result, _ = run(f"[[ {expression} ]]", REF=ref, EVENT=event)
                    self.assertIn(result.returncode, (0, 1), result.stderr)
                    expected = ref == "refs/heads/main" and event in ("schedule", "workflow_dispatch")
                    self.assertEqual(result.returncode == 0, expected)

    def test_matrix_and_channels(self):
        matrix = re.findall(
            r"- base_image: (\S+)\n +image_name: (\S+)\n +base_tag_stable: (\S+)\n +base_tag_daily: (\S+)",
            BUILD,
        )
        self.assertEqual(matrix, [
            ("ghcr.io/ublue-os/bluefin-dx", "bluefin-niri", "stable", "stable-daily"),
            ("ghcr.io/ublue-os/bluefin-dx-nvidia-open", "bluefin-niri-nvidia", "stable", "stable-daily"),
            ("ghcr.io/ublue-os/bazzite", "bazzite-niri", "stable", "latest"),
            ("ghcr.io/ublue-os/bazzite-nvidia", "bazzite-niri-nvidia", "stable", "latest"),
        ])
        names = re.search(r"image_name: \[(.+)\]", PUBLISH).group(1).split(", ")
        self.assertEqual(names, [row[1] for row in matrix])
        for _, name, stable, daily in matrix:
            for event, schedule, channel, expected in (
                ("pull_request", "", "", "stable-daily"),
                ("push", "", "", "stable-daily"),
                ("schedule", "0 5 * * TUE", "", "stable"),
                ("schedule", "0 12 * * *", "", "stable-daily"),
                ("workflow_dispatch", "", "stable", "stable"),
                ("workflow_dispatch", "", "stable-daily", "stable-daily"),
            ):
                with self.subTest(image=name, event=event, channel=expected):
                    shell = script("Determine channel")
                    for key, value in {
                        "github.event_name": event, "github.event.schedule": schedule,
                        "inputs.channel": channel, "matrix.base_tag_stable": stable,
                        "matrix.base_tag_daily": daily,
                    }.items():
                        shell = shell.replace("${{ " + key + " }}", value)
                    result, output = run(shell)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    base = stable if expected == "stable" else daily
                    self.assertEqual(output, f"channel={expected}\nbase_tag={base}\n")

    def test_digest_and_version(self):
        digest = "sha256:" + "a" * 64
        valid_tag = {"Digest": digest}
        valid_version = {"Labels": {"org.opencontainers.image.version": "44.20260905"}}
        # Replace only registry I/O; execute the workflow's actual shell and jq.
        mock = '''
skopeo() {
  printf '%s\\n' "$*" >&2
  case "$2" in
    docker://example/base:stable)
      [[ "$FAIL_AT" != tag ]] || return 1
      printf '%s' "$TAG_JSON" ;;
    "docker://example/base@$EXPECTED_DIGEST")
      [[ "$FAIL_AT" != digest ]] || return 1
      printf '%s' "$VERSION_JSON" ;;
    *) return 99 ;;
  esac
}
'''
        cases = [(valid_tag, valid_version, "", True)]
        for value in (None, "", "null", " ", 42, "sha256:abc", "sha256:" + "g" * 64,
                      digest + "\n", digest + "\r", digest + "\nINJECT=1"):
            cases.append(({"Digest": value}, valid_version, "", False))
        for value in (None, "", "null", "  ", 42, [], {}, "\t", "44\n", "44\r", "44\nINJECT=1", "44\x00"):
            cases.append((valid_tag, {"Labels": {"org.opencontainers.image.version": value}}, "", False))
        cases.extend([
            ({}, valid_version, "", False),
            (valid_tag, {}, "", False),
            (valid_tag, {"Labels": {}}, "", False),
            (valid_tag, valid_version, "tag", False),
            (valid_tag, valid_version, "digest", False),
        ])
        for tag, version, fail, valid in cases:
            with self.subTest(tag=tag, version=version, fail=fail):
                result, output = run(
                    mock + script("Resolve base digest and version"),
                    BASE_IMAGE="example/base", BASE_TAG="stable", EXPECTED_DIGEST=digest,
                    TAG_JSON=json.dumps(tag), VERSION_JSON=json.dumps(version), FAIL_AT=fail,
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                if valid:
                    self.assertEqual(output, f"base_ref=example/base@{digest}\nversion=44.20260905\n")
                    self.assertEqual(result.stderr.splitlines(), [
                        "inspect docker://example/base:stable", f"inspect docker://example/base@{digest}",
                    ])
                else:
                    self.assertEqual(output, "")
                    if tag != valid_tag or fail == "tag":
                        self.assertEqual(result.stderr.splitlines(), ["inspect docker://example/base:stable"])

    def test_shell_syntax(self):
        scripts = re.findall(r"^        run: \|\n((?:          .*\n|\n)+)", WORKFLOW, re.M)
        self.assertGreaterEqual(len(scripts), 5)
        for shell in scripts:
            with self.subTest(script=shell.splitlines()[0]):
                result = subprocess.run(["bash", "-n"], input=textwrap.dedent(shell), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
