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
CANDIDATE = (Path(__file__).resolve().parents[1] / ".github/workflows/fedora-candidate.yml").read_text()
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
        for job in (block(WORKFLOW, "  validate:"), block(CANDIDATE, "  candidate:")):
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
        self.assertLess(CANDIDATE.index("      - name: Run standard unit tests"),
                        CANDIDATE.index("      - name: Require supplied signing inputs"))

    def test_candidate_is_separate_and_nonpublishing(self):
        self.assertEqual(re.findall(r"^  (\w+):", block(CANDIDATE, "on:"), re.M),
                         ["workflow_dispatch"])
        self.assertEqual(re.findall(r"^  (\w+):", block(CANDIDATE, "jobs:"), re.M),
                         ["candidate"])
        job = block(CANDIDATE, "  candidate:")
        self.assertIn("    if: github.ref == 'refs/heads/main'\n", job)
        self.assertIn("    environment: fedora-production-validation\n", job)
        for text, header in ((CANDIDATE, "permissions:"), (job, "    permissions:")):
            self.assertEqual(block(text, header).strip(), "contents: read")
        self.assertIn("          persist-credentials: false", job)
        for forbidden in ("packages: write", "upload-artifact@", "login@", "podman push",
                          "podman save", "skopeo copy", "type: boolean", "continue-on-error:",
                          "localhost/zfs-rpms-test-proof", "/tmp/opencode", "openssl req"):
            self.assertNotIn(forbidden, CANDIDATE)
        for name in ("signing_key_secret", "signing_cert_secret", "rpm_signing_key_secret"):
            self.assertIn("        required: true", block(CANDIDATE, f"      {name}:"))
            self.assertIn("${{ secrets[inputs." + name + "] }}", CANDIDATE)
        self.assertIn("        required: true", block(CANDIDATE, "      rpm_signing_fingerprint_variable:"))
        self.assertIn("${{ vars[inputs.rpm_signing_fingerprint_variable] }}", job)
        self.assertIn("podman build --no-cache -f Containerfile.zfs-sign", job)
        self.assertIn("podman build --no-cache -f Containerfile.zfs-runtime", job)
        self.assertEqual(re.findall(r"podman build (?:--no-cache )?-f (\S+)", job), [
            "Containerfile.zfs", "Containerfile.zfs-sign", "Containerfile.zfs-runtime", "Containerfile.nirius",
            "Containerfile.fedora",
        ])
        for argument in ("--target zfs-rpms", "ZFS_RPM_IMAGE=localhost/zfs-rpms:candidate",
                         "ZFS_RPM_IMAGE=localhost/zfs-signed-rpms:candidate",
                         "ZFS_RPM_TRUST_MODE=verified",
                         "ZFS_RPM_SIGNING_FINGERPRINT=$RPM_SIGNING_FINGERPRINT",
                         "id=zfs_rpm_signing_key,src=$signing/rpm-key.asc",
                         "BASE_IMAGE=localhost/zfs-runtime:candidate",
                         "NIRIUS_IMAGE=localhost/nirius-artifact:candidate",
                         "id=zfs_signing_key,src=$signing/key.pem",
                         "id=zfs_signing_cert,src=$signing/cert.der"):
            self.assertIn(argument, job)
        self.assertIn("protected credentials/enrollment and booted verification remain release gates.", job)

    def test_candidate_missing_signing_inputs_fail_closed(self):
        for name in ("Require supplied signing inputs", "Build unpublished Fedora candidate"):
            step = block(CANDIDATE, f"      - name: {name}")
            shell = textwrap.dedent(block(step, "        run: |"))
            valid = dict(SIGNING_KEY="fixture", SIGNING_CERT="Zml4dHVyZQ==",
                         RPM_SIGNING_KEY="fixture", RPM_SIGNING_FINGERPRINT="A" * 40)
            cases = [{**valid, key: ""} for key in valid]
            cases += [{**valid, "RPM_SIGNING_FINGERPRINT": value} for value in ("A" * 16, "a" * 40)]
            for inputs in cases:
                with self.subTest(step=name, inputs=inputs):
                    result, _ = run(shell, **inputs)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("unbound variable", result.stderr)

    def test_candidate_build_sequence_with_mocked_builds(self):
        step = block(CANDIDATE, "      - name: Build unpublished Fedora candidate")
        shell = textwrap.dedent(block(step, "        run: |"))
        mock = '''
openssl() { return 0; }
podman() {
  [[ -s "$signing/key.pem" && -s "$signing/cert.der" && -s "$signing/rpm-key.asc" ]] || return 98
  [[ ! -v SIGNING_KEY && ! -v SIGNING_CERT && ! -v RPM_SIGNING_KEY ]] || return 99
  printf '%s\\n' "$*"
  [[ "$*" != *"$FAIL_BUILD"* ]]
}
'''
        for failure in ("no-failure", "Containerfile.zfs --target", "Containerfile.zfs-sign", "Containerfile.fedora"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                summary = Path(tmp) / "summary"
                result, _ = run(mock + shell, SIGNING_KEY="fixture", SIGNING_CERT="Zml4dHVyZQ==",
                                RPM_SIGNING_KEY="fixture", RPM_SIGNING_FINGERPRINT="A" * 40,
                                RUNNER_TEMP=tmp, GITHUB_STEP_SUMMARY=str(summary), FAIL_BUILD=failure)
                self.assertEqual(result.returncode == 0, failure == "no-failure", result.stderr)
                self.assertEqual(summary.exists(), failure == "no-failure")
                self.assertEqual(list(Path(tmp).glob("fedora-signing.*")), [])
                if failure == "no-failure":
                    self.assertEqual(len(result.stdout.splitlines()), 5)
                elif failure == "Containerfile.zfs --target":
                    self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_shell_syntax(self):
        scripts = re.findall(r"^        run: \|\n((?:          .*\n|\n)+)", WORKFLOW + CANDIDATE, re.M)
        self.assertGreaterEqual(len(scripts), 5)
        for shell in scripts:
            with self.subTest(script=shell.splitlines()[0]):
                result = subprocess.run(["bash", "-n"], input=textwrap.dedent(shell), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
