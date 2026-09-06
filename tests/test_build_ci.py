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
CLEANUP = (Path(__file__).resolve().parents[1] / ".github/workflows/cleanup.yml").read_text()
TESTING = (Path(__file__).resolve().parents[1] / ".github/workflows/fedora-testing.yml").read_text()
FEDORA_BUILD = block(TESTING, "  build:")
FEDORA_PUBLISH = block(TESTING, "  publish:")
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
            ("ghcr.io/ublue-os/bazzite", "bazzite-niri", "stable", "latest"),
            ("ghcr.io/ublue-os/bazzite-nvidia", "bazzite-niri-nvidia", "stable", "latest"),
        ])
        names = re.search(r"image_name: \[(.+)\]", PUBLISH).group(1).split(", ")
        self.assertEqual(names, [row[1] for row in matrix])
        packages = block(CLEANUP, "        package:")
        self.assertEqual(re.findall(r"^ +\- (\S+)$", packages, re.M), names)
        for excluded in ("bluefin-niri-nvidia", "fedora-44-niri", "fedora-niri"):
            self.assertNotIn(excluded, WORKFLOW)
            self.assertNotIn(excluded, CLEANUP)
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

    def test_cleanup_retention(self):
        self.assertIn("tags.includes('stable') || tags.includes('stable-daily')", CLEANUP)
        self.assertIn("...stableDated.slice(5)", CLEANUP)
        self.assertIn("...dailyDated.slice(7)", CLEANUP)

    def test_full_standard_suite_with_dependencies_before_builds(self):
        for job in (block(WORKFLOW, "  validate:"), FEDORA_BUILD):
            install = block(job, "      - name: Install test dependencies")
            tests = block(job, "      - name: Run standard unit tests")
            self.assertIn("sudo apt-get update && sudo apt-get install -y python3-yaml", install)
            self.assertIn('cargo install --locked --version 1.57.0 just --root "$RUNNER_TEMP/just"', install)
            self.assertIn('echo "$RUNNER_TEMP/just/bin" >> "$GITHUB_PATH"', install)
            self.assertIn("command -v just", tests)
            self.assertIn("/usr/bin/python3 -c 'import yaml'", tests)
            self.assertIn("/usr/bin/python3 -m unittest discover -s tests -v", tests)
            self.assertNotIn(" -p ", tests)
            self.assertNotIn("continue-on-error", job)
            self.assertLess(job.index(install), job.index(tests))
            self.assertNotIn("BACKUP_REAL_CONTAINER", job)
            self.assertNotIn("NIRIUS_ARTIFACT_DIR", job)
            self.assertNotIn("NIRI_TEST_IMAGE", job)
        self.assertLess(TESTING.index("      - name: Run standard unit tests"),
                        TESTING.index("      - name: Build Fedora testing image"))

    def test_testing_permissions_and_triggers(self):
        self.assertTrue(TESTING.startswith("name: Fedora Niri Testing\n"))
        self.assertFalse((Path(__file__).resolve().parents[1] /
                          ".github/workflows/fedora-candidate.yml").exists())
        self.assertEqual(re.findall(r"^  (\w+):", block(TESTING, "on:"), re.M),
                         ["pull_request", "push", "schedule", "workflow_dispatch"])
        self.assertEqual(block(TESTING, "  push:").strip(), "branches:\n      - main")
        self.assertEqual(re.findall(r'cron: "([^"]+)"', TESTING), ["17 13 * * *"])
        self.assertNotIn('cron: "17 13 * * *"', WORKFLOW)
        self.assertEqual(re.findall(r"^  (\w+):", block(TESTING, "jobs:"), re.M),
                         ["build", "publish"])
        for text, header in ((TESTING, "permissions:"), (FEDORA_BUILD, "    permissions:")):
            self.assertEqual(block(text, header).strip(), "contents: read")
        self.assertEqual(block(FEDORA_PUBLISH, "    permissions:").strip(), "packages: write")
        self.assertEqual(TESTING.count("packages: write"), 1)
        self.assertIn("    needs: build\n", FEDORA_PUBLISH)
        self.assertIn("          persist-credentials: false", FEDORA_BUILD)
        self.assertNotIn("    if:", FEDORA_BUILD.split("    steps:")[0])
        for forbidden in ("secrets", "login@", "skopeo copy", "podman push"):
            self.assertNotIn(forbidden, FEDORA_BUILD)
        for forbidden in ("checkout@", "podman build", "podman run"):
            self.assertNotIn(forbidden, FEDORA_PUBLISH)
        self.assertEqual(re.findall(r"\$\{\{ secrets\.(\w+) \}\}", TESTING), ["GITHUB_TOKEN"])
        for forbidden in ("environment:", "inputs:", "inputs.", "secrets[", "reviewers",
                          "SIGNING_KEY", "SIGNING_CERT", "FINGERPRINT", "--secret", "--privileged",
                          "mktemp", "openssl", "type: boolean", "continue-on-error:",
                          "Containerfile.zfs-sign", "localhost/zfs-rpms-test-proof", "/tmp/opencode",
                          ":proof", ":candidate", "stable", "production-validation"):
            self.assertNotIn(forbidden, TESTING)

    def test_testing_publish_gates(self):
        gate = re.search(r"^    if: (.+)$", FEDORA_PUBLISH, re.M).group(1)
        for name in ("Export testing image", "Upload testing image"):
            self.assertIn(f"        if: {gate}\n", block(FEDORA_BUILD, f"      - name: {name}"))
        expression = (gate.replace("github.ref", '"$REF"')
                      .replace("github.event_name", '"$EVENT"').replace("github.repository", '"$REPO"'))
        for repo in ("btd987/bluefin-niri", "fork/bluefin-niri"):
            for event in ("pull_request", "push", "schedule", "workflow_dispatch", "pull_request_target"):
                for ref in ("refs/heads/main", "refs/heads/feature", "refs/tags/main", "refs/pull/12/merge"):
                    with self.subTest(repo=repo, event=event, ref=ref):
                        result, _ = run(f"[[ {expression} ]]", REPO=repo, REF=ref, EVENT=event)
                        self.assertIn(result.returncode, (0, 1), result.stderr)
                        expected = (repo == "btd987/bluefin-niri" and ref == "refs/heads/main"
                                    and event in ("schedule", "workflow_dispatch"))
                        self.assertEqual(result.returncode == 0, expected)

    def test_testing_build_sequence_with_mocked_builds(self):
        step = block(FEDORA_BUILD, "      - name: Build Fedora testing image")
        shell = textwrap.dedent(block(step, "        run: |"))
        mock = '''
podman() {
  printf '%s\\n' "$*"
  [[ "$*" != *"$FAIL_BUILD"* ]]
}
'''
        commands = [
            "build -f Containerfile.zfs --target zfs-rpms --build-arg ZFS_BUILD_MODE=unsigned-testing "
            "-t localhost/zfs-rpms:testing .",
            "build --no-cache -f Containerfile.zfs-runtime --build-arg ZFS_RPM_IMAGE=localhost/zfs-rpms:testing "
            "--build-arg ZFS_RPM_TRUST_MODE=unsigned-testing -t localhost/zfs-runtime:testing .",
            "build -f Containerfile.nirius -t localhost/nirius-artifact:testing .",
            "build -f Containerfile.fedora --build-arg BASE_IMAGE=localhost/zfs-runtime:testing "
            "--build-arg NIRIUS_IMAGE=localhost/nirius-artifact:testing "
            "--build-arg ZFS_BUILD_MODE=unsigned-testing -t localhost/fedora-niri:testing .",
        ]
        for index, failure in enumerate(commands + ["no-failure"]):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                summary = Path(tmp) / "summary"
                result, _ = run(mock + shell,
                                RUNNER_TEMP=tmp, GITHUB_STEP_SUMMARY=str(summary), FAIL_BUILD=failure)
                self.assertEqual(result.returncode == 0, failure == "no-failure", result.stderr)
                self.assertEqual(summary.exists(), failure == "no-failure")
                self.assertEqual(result.stdout.splitlines(), commands[:index + 1])
                if failure == "no-failure":
                    self.assertIn("Secure Boot disabled", summary.read_text())
                    self.assertIn("acceptance are not established", summary.read_text())

    def test_testing_artifact_and_publication_with_mocked_io(self):
        upload = block(FEDORA_BUILD, "      - name: Upload testing image")
        download = block(FEDORA_PUBLISH, "      - name: Download testing image")
        for step in (upload, download):
            self.assertIn("          name: fedora-niri-testing", step)
            self.assertIn("          path: ${{ runner.temp }}/release/", step)
        for setting in ("compression-level: 0", "retention-days: 1", "if-no-files-found: error"):
            self.assertIn(setting, upload)
        export = textwrap.dedent(block(block(FEDORA_BUILD, "      - name: Export testing image"), "        run: |"))
        push = textwrap.dedent(block(block(FEDORA_PUBLISH, "      - name: Push to GHCR"), "        run: |"))
        mock = '''
podman() { printf '%s\\n' "$*"; }
date() { [[ "$*" == '-u +%Y%m%d' ]] && printf '20260906'; }
skopeo() { printf '%s\\n' "$*"; }
'''
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = run(mock + export + "\n" + push, RUNNER_TEMP=tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(tmp) / "release/tags.txt").read_text(), "testing\ntesting-20260906\n")
            self.assertEqual(result.stdout.splitlines(), [
                f"save --format oci-archive --output {tmp}/release/image.tar localhost/fedora-niri:testing",
                f"copy oci-archive:{tmp}/release/image.tar docker://ghcr.io/btd987/fedora-niri:testing",
                f"copy oci-archive:{tmp}/release/image.tar docker://ghcr.io/btd987/fedora-niri:testing-20260906",
            ])
            for tag in ("stable", "latest", "testing-20260906/other", "testing-20260906\r"):
                with self.subTest(tag=tag):
                    (Path(tmp) / "release/tags.txt").write_text(tag + "\n")
                    result, _ = run(mock + push, RUNNER_TEMP=tmp)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")

    def test_shell_syntax(self):
        scripts = re.findall(r"^        run: \|\n((?:          .*\n|\n)+)", WORKFLOW + TESTING, re.M)
        self.assertGreaterEqual(len(scripts), 5)
        for shell in scripts:
            with self.subTest(script=shell.splitlines()[0]):
                result = subprocess.run(["bash", "-n"], input=textwrap.dedent(shell), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
