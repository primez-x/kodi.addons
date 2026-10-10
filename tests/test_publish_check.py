"""Tests for tools/publish_check.py (the per-repository publish rules)."""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


class PrePushTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("publish_check", None)
        self.check = importlib.import_module("publish_check")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.cwd)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.write_config()
        self.base = self.commit("1.0.0", "v1.0.0\n- First")

    def git(self, *args):
        return subprocess.run(["git"] + list(args), check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).stdout.decode().strip()

    def write_config(self, tests=None):
        (self.repo / ".primez-publish.json").write_text(json.dumps({
            "branch": "main",
            "tests": tests or [["python3", "-c", "import sys; sys.exit(0)"]],
        }))

    def commit(self, version, news):
        (self.repo / "addon.xml").write_text(
            f'<addon id="a" name="a" version="{version}" provider-name="x">'
            '<extension point="xbmc.addon.metadata">'
            f"<news>{news}</news></extension></addon>")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", version)
        return self.git("rev-parse", "HEAD")

    def push(self, sha, remote_sha=None, branch="main"):
        remote_sha = remote_sha or self.base
        line = f"refs/heads/{branch} {sha} refs/heads/{branch} {remote_sha}"
        with mock.patch("sys.stdin", __import__("io").StringIO(line + "\n")):
            return self.check.main(["publish_check.py", "pre-push", "origin", "url"])

    def test_bumped_release_with_news_passes(self):
        self.assertEqual(self.push(self.commit("1.0.1", "v1.0.1\n- Fix")), 0)

    def test_missing_version_bump_is_rejected(self):
        self.assertEqual(self.push(self.commit("1.0.0", "v1.0.0\n- Sneaky")), 1)

    def test_version_going_backwards_is_rejected(self):
        self.assertEqual(self.push(self.commit("0.9.9", "v0.9.9\n- Old")), 1)

    def test_news_must_name_the_new_version(self):
        self.assertEqual(self.push(self.commit("1.0.1", "v1.0.0\n- First")), 1)
        # A longer version that merely starts with it does not count
        self.assertEqual(self.push(self.commit("1.0.2", "v1.0.21\n- Typo")), 1)

    def test_news_formats_used_by_the_addons_pass(self):
        for version, news in (("1.0.1", "version 1.0.1 (beta only):"),
                              ("1.0.2", "\nv1.0.2 (2026-10-09)\n- Dated")):
            sha = self.commit(version, news)
            self.assertEqual(self.push(sha), 0, news)
            self.base = sha

    def test_failing_tests_are_rejected(self):
        self.write_config([["python3", "-c", "import sys; sys.exit(1)"]])
        self.assertEqual(self.push(self.commit("1.0.1", "v1.0.1\n- Fix")), 1)

    def test_tests_run_on_the_pushed_commit_not_the_worktree(self):
        self.write_config([["python3", "-c",
                            "import os, sys; sys.exit(0 if os.path.exists('tracked') else 1)"]])
        (self.repo / "tracked").write_text("")
        sha = self.commit("1.0.1", "v1.0.1\n- Fix")
        os.remove(self.repo / "tracked")  # gone from the worktree only
        self.assertEqual(self.push(sha), 0)

    def test_other_branches_are_not_checked(self):
        sha = self.commit("1.0.0", "v1.0.0\n- Work in progress")
        self.assertEqual(self.push(sha, branch="claude/feature"), 0)

    def test_first_push_of_the_branch_has_nothing_to_compare(self):
        sha = self.commit("1.0.1", "v1.0.1\n- Fix")
        self.assertEqual(self.push(sha, remote_sha="0" * 40), 0)


if __name__ == "__main__":
    unittest.main()
