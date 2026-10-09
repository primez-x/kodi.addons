"""Tests for the publish selection logic in tools/build_repository.py.

Run with: python3 -m unittest discover -s tests
"""

import importlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

PASSING_TEST = ["python3", "-c", "import sys; sys.exit(0)"]
FAILING_TEST = ["python3", "-c", "import sys; print('boom'); sys.exit(1)"]


def addon_zip(addon_id, version, failing=False):
    """A GitHub zipball of an add-on whose test passes or fails."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"owner-repo-abc/addon.xml",
            f'<addon id="{addon_id}" name="{addon_id}" version="{version}" provider-name="x">'
            '<extension point="xbmc.addon.metadata"><platform>all</platform></extension>'
            "</addon>",
        )
        archive.writestr("owner-repo-abc/marker.txt", "fail" if failing else "pass")
    return buffer.getvalue()


class BuildRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "public"
        with mock.patch.dict(os.environ, {"KODI_OUTPUT_DIR": str(self.output)}):
            sys.modules.pop("build_repository", None)
            self.builder = importlib.import_module("build_repository")
        self.builder.OUTPUT_DIR = self.output
        # repository -> {sha: (version, failing)}
        self.commits = {}
        self.heads = {}
        self.published = {}
        self.published_versions = {}
        self.tests_run = []
        self.env = {}

        builder = self.builder
        builder.resolve_source_sha = lambda repository, ref: (
            ref if ref in self.commits[repository] else self.heads[repository]
        )

        def download(repository, sha, target):
            version, failing = self.commits[repository][sha]
            target.write_bytes(addon_zip(repository.split("/")[1], version, failing))

        builder.download_archive = download
        builder.fetch_published_addon_versions = lambda config: dict(self.published_versions)
        builder.fetch_published_source_manifest = lambda config: {
            entry["id"]: entry for entry in self.published.values()
        }
        real_run_tests = builder.run_addon_tests

        def run_tests(addon_root, addon_config, label):
            self.tests_run.append(label)
            failing = (addon_root / "marker.txt").read_text() == "fail"
            config = dict(addon_config, tests=[FAILING_TEST if failing else PASSING_TEST])
            real_run_tests(addon_root, config, label)

        builder.run_addon_tests = run_tests

    def add(self, repository, sha, version, failing=False, head=True):
        self.commits.setdefault(repository, {})[sha] = (version, failing)
        if head:
            self.heads[repository] = sha

    def publish_state(self, repository, sha):
        version = self.commits[repository][sha][0]
        addon_id = repository.split("/")[1]
        self.published[repository] = {
            "id": addon_id,
            "repository": repository,
            "sha": sha,
            "version": version,
        }
        self.published_versions[addon_id] = version

    def build(self, repositories, source=None):
        manifest = {
            "repository": {
                "id": "repository.test",
                "name": "Test",
                "version": "1.0.0",
                "base_url": "https://example.invalid/",
            },
            "addons": [
                {"repository": repository, "ref": "main", "tests": [PASSING_TEST]}
                for repository in repositories
            ],
        }
        self.builder.load_manifest = lambda: manifest
        env = {}
        if source:
            env = {"KODI_SOURCE_REPOSITORY": source[0], "KODI_SOURCE_SHA": source[1]}
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("KODI_SOURCE_REPOSITORY", "KODI_SOURCE_SHA"):
                if key not in env:
                    os.environ.pop(key, None)
            self.builder.build()
        manifest_out = json.loads((self.output / "source-manifest.json").read_text())
        return {entry["repository"]: entry for entry in manifest_out["addons"]}

    def test_source_publish_with_failing_tests_fails_the_run(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1", failing=True)

        with self.assertRaisesRegex(RuntimeError, "Tests failed for o/a@a2"):
            self.build(["o/a"], source=("o/a", "a2"))

    def test_source_publish_without_version_bump_fails_the_run(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.0")

        with self.assertRaisesRegex(RuntimeError, "version must increase"):
            self.build(["o/a"], source=("o/a", "a2"))

    def test_other_addon_without_version_bump_keeps_its_published_commit(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1")
        self.add("o/b", "b1", "2.0.0")
        self.publish_state("o/b", "b1")
        self.add("o/b", "b2", "2.0.0")  # pushed without a bump

        built = self.build(["o/a", "o/b"], source=("o/a", "a2"))

        self.assertEqual(built["o/a"]["sha"], "a2")
        self.assertEqual(built["o/b"]["sha"], "b1")

    def test_other_addon_with_failing_tests_keeps_its_published_commit(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1")
        self.add("o/b", "b1", "2.0.0")
        self.publish_state("o/b", "b1")
        self.add("o/b", "b2", "2.0.1", failing=True)

        built = self.build(["o/a", "o/b"], source=("o/a", "a2"))

        self.assertEqual(built["o/b"]["sha"], "b1")
        self.assertEqual(built["o/b"]["version"], "2.0.0")

    def test_other_addon_with_a_bumped_passing_head_is_picked_up(self):
        # E.g. its own publish run was dropped from GitHub's queue
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1")
        self.add("o/b", "b1", "2.0.0")
        self.publish_state("o/b", "b1")
        self.add("o/b", "b2", "2.0.1")

        built = self.build(["o/a", "o/b"], source=("o/a", "a2"))

        self.assertEqual(built["o/b"]["sha"], "b2")

    def test_already_published_commits_are_not_tested_again(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/b", "b1", "2.0.0")
        self.publish_state("o/b", "b1")

        self.build(["o/a", "o/b"])

        self.assertEqual(self.tests_run, [])

    def test_local_build_without_published_state_builds_heads(self):
        def unavailable(config):
            raise RuntimeError("offline")

        self.builder.fetch_published_addon_versions = unavailable
        self.add("o/a", "a1", "1.0.0")

        built = self.build(["o/a"])

        self.assertEqual(built["o/a"]["sha"], "a1")


class RunAddonTestsTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("build_repository", None)
        self.builder = importlib.import_module("build_repository")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_commands_run_in_the_addon_root_with_extra_env(self):
        script = (
            "import os, sys; "
            "sys.exit(0 if os.environ['EXTRA'] == 'yes' and os.path.exists('here') else 1)"
        )
        (self.root / "here").write_text("")
        self.builder.run_addon_tests(
            self.root,
            {"tests": [["python3", "-c", script]], "test_env": {"EXTRA": "yes"}},
            "label",
        )

    def test_publish_token_is_not_passed_to_tests(self):
        script = "import os, sys; sys.exit(1 if 'GITHUB_TOKEN' in os.environ else 0)"
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "secret"}):
            self.builder.run_addon_tests(
                self.root, {"tests": [["python3", "-c", script]]}, "label")

    def test_failure_reports_the_output_tail(self):
        with self.assertRaisesRegex(RuntimeError, "exit 3"):
            self.builder.run_addon_tests(
                self.root,
                {"tests": [["python3", "-c", "import sys; sys.exit(3)"]]},
                "label",
            )


if __name__ == "__main__":
    unittest.main()
