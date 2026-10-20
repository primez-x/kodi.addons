"""Tests for the publish selection logic in tools/build_repository.py.

Test output must not add, replace, or remove package files. Preserve source
databases and keep one test workspace across commands for each add-on.

Run with: python3 -m unittest discover -s tests
"""

import hashlib
import importlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

PASSING_TEST = ["python3", "-c", "import sys; sys.exit(0)"]
FAILING_TEST = ["python3", "-c", "import sys; print('boom'); sys.exit(1)"]


def addon_zip(addon_id, version, failing=False, news=None, publish_config=None, files=None):
    """A GitHub zipball of an add-on whose test passes or fails."""
    news = f"v{version}\n- Changes" if news is None else news
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"owner-repo-abc/addon.xml",
            f'<addon id="{addon_id}" name="{addon_id}" version="{version}" provider-name="x">'
            '<extension point="xbmc.addon.metadata"><platform>all</platform>'
            f"<news>{news}</news></extension>"
            "</addon>",
        )
        archive.writestr("owner-repo-abc/marker.txt", "fail" if failing else "pass")
        if publish_config is not None:
            archive.writestr("owner-repo-abc/.primez-publish.json", json.dumps(publish_config))
        for name, content in (files or {}).items():
            archive.writestr(f"owner-repo-abc/{name}", content)
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
        # repository -> {sha: (version, failing, extra zip arguments)}
        self.commits = {}
        self.heads = {}
        self.published = {}
        self.published_versions = {}
        self.tests_run = []
        self.env = {}
        self.commit_messages = {}

        builder = self.builder
        builder.resolve_source_sha = lambda repository, ref: (
            ref if ref in self.commits[repository] else self.heads[repository]
        )
        self.fetch_commit_message = builder.fetch_source_commit_message
        builder.fetch_source_commit_message = lambda repository, sha: (
            self.commit_messages.get((repository, sha), "")
        )

        def download(repository, sha, target):
            version, failing, extra = self.commits[repository][sha]
            target.write_bytes(addon_zip(repository.split("/")[1], version, failing, **extra))

        builder.download_archive = download
        builder.fetch_published_addon_versions = lambda config: dict(self.published_versions)
        builder.fetch_published_source_manifest = lambda config: {
            entry["id"]: entry for entry in self.published.values()
        }
        real_run_tests = builder.run_addon_tests
        self.original_test_runner = real_run_tests
        self.test_configs = []

        def run_tests(addon_root, addon_config, label):
            self.tests_run.append(label)
            self.test_configs.append(addon_config)
            failing = (addon_root / "marker.txt").read_text() == "fail"
            config = dict(addon_config, tests=[FAILING_TEST if failing else PASSING_TEST])
            real_run_tests(addon_root, config, label)

        builder.run_addon_tests = run_tests

    def test_archives_are_downloaded_once_per_repository_and_sha(self):
        self.add("o/a", "a1", "1.0.0")
        download = self.builder.download_archive
        calls = []

        def counted(repository, sha, target):
            calls.append((repository, sha))
            download(repository, sha, target)

        self.builder.download_archive = counted
        self.build(["o/a", "o/a"])
        self.assertEqual(calls, [("o/a", "a1")])

    def test_archive_prefetch_overlaps_without_changing_package_order(self):
        repositories = [f"o/a{index}" for index in range(6)]
        for repository in repositories:
            self.add(repository, "same-sha", "1.0.0")
        download = self.builder.download_archive
        lock = threading.Lock()
        overlap = threading.Event()
        active = peak = 0

        def concurrent(repository, sha, target):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active >= 2:
                    overlap.set()
            try:
                if not overlap.wait(2):
                    raise RuntimeError("Archives were fetched serially")
                download(repository, sha, target)
            finally:
                with lock:
                    active -= 1

        self.builder.download_archive = concurrent
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            built = self.build(repositories)
        self.assertGreaterEqual(peak, 2)
        self.assertLessEqual(peak, 4)
        self.assertEqual(list(built), repositories)
        package_lines = [line.split("@")[0] for line in output.getvalue().splitlines()
                         if line.startswith("Packaging ")]
        self.assertEqual(package_lines, [f"Packaging {name}" for name in repositories])

    def test_prefetch_failure_reports_the_source_in_manifest_order(self):
        self.add("o/a", "a1", "1.0.0")
        self.add("o/b", "b1", "1.0.0")
        download = self.builder.download_archive

        def failed(repository, sha, target):
            if repository == "o/b":
                raise RuntimeError("o/b archive unavailable")
            download(repository, sha, target)

        self.builder.download_archive = failed
        with self.assertRaisesRegex(RuntimeError, "o/b archive unavailable"):
            self.build(["o/a", "o/b"])
        self.assertTrue((self.output / "a" / "a-1.0.0.zip").exists())

    def test_shipped_files_use_streamed_digests_and_keep_excludes(self):
        root = Path(self.temp.name) / "source"
        root.mkdir()
        content = b"a" * (2 * 1024 * 1024 + 3)
        (root / "asset.bin").write_bytes(content)
        (root / "README.md").write_text("excluded")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("Whole-file read")):
            files = self.builder.shipped_files(root, list(self.builder.DEFAULT_EXCLUDES))
        self.assertEqual(files, {"asset.bin": hashlib.sha256(content).hexdigest()})
        (root / "asset.bin").write_bytes(content[:-1] + b"b")
        self.assertNotEqual(files, self.builder.shipped_files(root, list(self.builder.DEFAULT_EXCLUDES)))

    def test_shared_service_drift_reports_missing_or_changed_copies(self):
        master = Path(self.temp.name) / "tools" / "service_common"
        master.mkdir(parents=True)
        (master / "utils.py").write_text("canonical\n")
        addon = Path(self.temp.name) / "addon"
        (addon / "resources" / "lib").mkdir(parents=True)
        with mock.patch.object(self.builder, "ROOT", Path(self.temp.name)), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            self.builder.warn_shared_service_drift(addon, "service.upnext")
            self.assertIn("utils.py", output.getvalue())
            (addon / "resources" / "lib" / "utils.py").write_text("changed\n")
            output.truncate(0)
            output.seek(0)
            self.builder.warn_shared_service_drift(addon, "service.nexttrack")
            self.assertIn("utils.py", output.getvalue())
            (addon / "resources" / "lib" / "utils.py").write_text("canonical\n")
            output.truncate(0)
            output.seek(0)
            self.builder.warn_shared_service_drift(addon, "service.upnext")
            self.builder.warn_shared_service_drift(addon, "plugin.video.example")
            self.assertEqual(output.getvalue(), "")

    def add(self, repository, sha, version, failing=False, head=True, **extra):
        self.commits.setdefault(repository, {})[sha] = (version, failing, extra)
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

    def build(self, repositories, source=None, configs=None):
        manifest = {
            "repository": {
                "id": "repository.test",
                "name": "Test",
                "version": "1.0.0",
                "base_url": "https://example.invalid/",
            },
            "addons": [
                dict({"repository": repository, "ref": "main", "tests": [PASSING_TEST]},
                     **(configs or {}).get(repository, {}))
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

    def rollback_state(self, **target_options):
        repository = "primez-x/plugin.audio.spotifykodiconnect"
        previous = "f2f58eecd078d8feee20f5d58ba532822b84af84"
        target = "185b6069a13d63cab770318fa4d50a77962099c5"
        self.add(repository, previous, "1.10.3")
        self.publish_state(repository, previous)
        self.add(repository, target, "1.4.2", head=False, **target_options)
        rollback = {
            "repository": repository,
            "id": "plugin.audio.spotifykodiconnect",
            "from_sha": previous,
            "from_version": "1.10.3",
            "to_sha": target,
            "to_version": "1.4.2",
        }
        return repository, target, {repository: {"ref": target, "version_rollback": rollback}}

    def test_exact_rollback_builds_target_package_and_allows_idempotent_retry(self):
        repository, target, configs = self.rollback_state()
        for index, source in enumerate((None, (repository, target)), start=1):
            self.publish_state(repository, configs[repository]["version_rollback"]["from_sha"])
            with self.subTest(source=source):
                built = self.build([repository], source=source, configs=configs)
                entry = built[repository]
                self.assertEqual(entry["sha"], target)
                self.assertEqual(entry["version"], "1.4.2")
                self.assertEqual(entry["resolved_ref"], target)
                addon = ET.parse(self.output / "addons.xml").find("./addon[@id='plugin.audio.spotifykodiconnect']")
                self.assertEqual(addon.get("version"), "1.4.2")
                package = self.output / "plugin.audio.spotifykodiconnect/plugin.audio.spotifykodiconnect-1.4.2.zip"
                with zipfile.ZipFile(package) as archive:
                    xml = archive.read("plugin.audio.spotifykodiconnect/addon.xml")
                    self.assertEqual(ET.fromstring(xml).get("version"), "1.4.2")
                self.assertEqual(len(self.tests_run), index)
                self.publish_state(repository, target)
                self.build([repository], source=source, configs=configs)
                self.assertEqual(len(self.tests_run), index)

    def test_rollback_denies_every_missing_or_mismatched_declaration_field(self):
        repository, target, configs = self.rollback_state()
        rollback = configs[repository]["version_rollback"]
        for field, wrong in {
            "repository": "other/plugin.audio.spotifykodiconnect",
            "id": "other.addon",
            "from_sha": "a" * 40,
            "from_version": "1.10.2",
            "to_sha": "b" * 40,
            "to_version": "1.4.1",
        }.items():
            for value in (None, wrong):
                declaration = dict(rollback)
                if value is None:
                    declaration.pop(field)
                else:
                    declaration[field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(RuntimeError, "rollback"):
                    self.build([repository], configs={repository: dict(configs[repository],
                                                                      version_rollback=declaration)})

    def test_rollback_denies_missing_or_inconsistent_published_state(self):
        repository, target, configs = self.rollback_state()
        addon_id = "plugin.audio.spotifykodiconnect"
        original = dict(self.published[repository])
        for field, value in (("id", "other.addon"), ("repository", "other/repository"),
                             ("sha", "a" * 40), ("version", "1.10.2"),
                             ("sha", None), ("version", None)):
            self.published[repository] = dict(original, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaisesRegex(RuntimeError, "rollback"):
                self.build([repository], configs=configs)
        self.published[repository] = original
        for versions, sources in (({}, self.published), (self.published_versions, {}),
                                  ({addon_id: "1.10.2"}, self.published)):
            with self.subTest(versions=versions, sources=sources), \
                    mock.patch.object(self.builder, "fetch_published_addon_versions", return_value=versions), \
                    mock.patch.object(self.builder, "fetch_published_source_manifest",
                                      return_value={entry["id"]: entry for entry in sources.values()}):
                with self.assertRaisesRegex(RuntimeError, "rollback"):
                    self.build([repository], configs=configs)
        self.builder.fetch_published_addon_versions = mock.Mock(side_effect=RuntimeError("offline"))
        with self.assertRaisesRegex(RuntimeError, "offline"):
            self.build([repository], configs=configs)

    def test_active_rollback_denies_stale_webhooks_before_and_after_publication(self):
        repository, target, configs = self.rollback_state()
        previous = configs[repository]["version_rollback"]["from_sha"]
        for published_sha in (previous, target):
            self.publish_state(repository, published_sha)
            for stale, version in ((previous, "1.10.3"), ("c" * 40, "1.5.0"), ("b" * 40, "1.4.2")):
                if stale != previous:
                    self.add(repository, stale, version, head=False)
                with self.subTest(published=published_sha, stale=stale), \
                        self.assertRaisesRegex(RuntimeError, "rollback"):
                    self.build([repository], source=(repository, stale), configs=configs)

    def test_rollback_retains_news_tests_and_source_isolation(self):
        repository, target, configs = self.rollback_state(news="v1.10.3\nWrong release")
        with self.assertRaisesRegex(RuntimeError, "news"):
            self.build([repository], configs=configs)
        self.add(repository, target, "1.4.2", failing=True)
        with self.assertRaisesRegex(RuntimeError, "Tests failed"):
            self.build([repository], configs=configs)
        self.add(repository, target, "1.4.2", publish_config={"tests": [["python3", "-c",
            "from pathlib import Path; import os; assert 'GITHUB_TOKEN' not in os.environ; "
            "Path('marker.txt').write_text('changed'); Path('generated.bin').touch()"]]})
        self.builder.run_addon_tests = self.original_test_runner
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
            self.build([repository], configs=configs)
        package = self.output / "plugin.audio.spotifykodiconnect/plugin.audio.spotifykodiconnect-1.4.2.zip"
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(archive.read("plugin.audio.spotifykodiconnect/marker.txt"), b"pass")
            self.assertNotIn("plugin.audio.spotifykodiconnect/generated.bin", archive.namelist())
            self.assertNotIn("plugin.audio.spotifykodiconnect/.primez-publish.json", archive.namelist())
        self.add(repository, target, "1.4.2", files={"../../outside": "unsafe"})
        with self.assertRaisesRegex(RuntimeError, "Unsafe archive path"):
            self.build([repository], configs=configs)

    def test_consumed_rollback_uses_normal_guards_after_declaration_removal(self):
        repository, target, configs = self.rollback_state()
        with self.assertRaisesRegex(RuntimeError, "backwards"):
            self.build([repository], source=(repository, target))
        self.build([repository], configs=configs)
        self.publish_state(repository, target)
        self.add(repository, "d" * 40, "1.4.3")
        self.assertEqual(self.build([repository])[repository]["version"], "1.4.3")
        self.add(repository, "e" * 40, "1.4.5")
        with self.assertRaisesRegex(RuntimeError, "not one step above"):
            self.build([repository], source=(repository, "e" * 40))

    def test_source_publish_with_failing_tests_fails_the_run(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1", failing=True)

        with self.assertRaisesRegex(RuntimeError, "Tests failed for o/a@a2"):
            self.build(["o/a"], source=("o/a", "a2"))

    def test_same_version_fallback_preserves_published_metadata(self):
        self.add("o/a", "a1", "1.0.0", news="v1.0.0\nPublished news")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.0", news="v1.0.0\nRejected news")
        self.assertEqual(self.build(["o/a"])["o/a"]["sha"], "a1")
        addon = ET.parse(self.output / "addons.xml").find("./addon[@id='a']")
        self.assertEqual([line.strip() for line in addon.find("./extension/news").text.splitlines()],
                         ["v1.0.0", "Published news"])

    def test_background_metadata_network_failure_keeps_published_commit(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.3")
        self.builder.fetch_source_commit_message = self.fetch_commit_message
        with mock.patch.object(self.builder, "github_request", side_effect=urllib.error.URLError("offline")):
            self.assertEqual(self.build(["o/a"])["o/a"]["sha"], "a1")

    def test_commit_metadata_requires_exact_sha_and_message(self):
        for metadata in ({"sha": "other", "commit": {"message": "Version-Jump: upstream"}},
                         {"sha": "a2", "commit": {"message": []}}, []):
            with self.subTest(metadata=metadata), mock.patch.object(
                    self.builder, "github_request", return_value=json.dumps(metadata).encode()):
                with self.assertRaisesRegex(RuntimeError, "Invalid commit metadata"):
                    self.fetch_commit_message("o/a", "a2")

    def test_source_publish_rejects_a_skipped_version(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.3")
        with self.assertRaisesRegex(RuntimeError, "not one step above"):
            self.build(["o/a"], source=("o/a", "a2"))
        self.assertEqual(self.tests_run, [])

    def test_other_addon_with_a_skipped_version_keeps_the_published_commit(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.3")
        self.assertEqual(self.build(["o/a"])["o/a"]["sha"], "a1")
        self.assertEqual(self.tests_run, [])

    def test_source_publish_accepts_a_declared_version_jump(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "2.3.0")
        self.commit_messages[("o/a", "a2")] = "Adopt upstream\n\nVersion-Jump: adopt upstream 2.3.0\n"
        self.assertEqual(self.build(["o/a"], source=("o/a", "a2"))["o/a"]["sha"], "a2")

    def test_source_publish_rejects_a_component_count_change(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.0.1")
        with self.assertRaisesRegex(RuntimeError, "not one step above"):
            self.build(["o/a"], source=("o/a", "a2"))

    def test_source_publish_without_version_bump_keeps_the_published_package(self):
        # A same-version commit is never shipped: the hook and CI decide whether
        # it was a legitimate non-release (No-Release) or a missing bump.
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.0", files={"resources/lib/code.py": "changed"})

        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            entries = self.build(["o/a"], source=("o/a", "a2"))
        self.assertEqual("a1", entries["o/a"]["sha"])
        self.assertIn("WARNING", out.getvalue())

    def test_source_publish_that_lowers_the_version_still_fails(self):
        self.add("o/a", "a1", "1.0.1")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.0")

        with self.assertRaises(RuntimeError):
            self.build(["o/a"], source=("o/a", "a2"))

    def test_source_publish_of_non_shipped_changes_keeps_the_published_package(self):
        # Docs, CLAUDE.md, tests or CI only: not a release, so no version step
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.0", files={
            "CLAUDE.md": "notes", "AGENTS.md": "notes", "tests/test_x.py": "", "docs/x.md": "",
            "Makefile": "", "tox.ini": "", "requirements.txt": "", "notes/design.md": "",
        })

        entries = self.build(["o/a"], source=("o/a", "a2"))
        # same package; the manifest follows the branch, which may no longer
        # contain a1 (e.g. after a history rewrite)
        self.assertEqual("a2", entries["o/a"]["sha"])
        self.assertEqual("1.0.0", entries["o/a"]["version"])
        self.assertEqual([], self.tests_run)

    def test_agent_notes_are_not_packaged(self):
        self.add("o/a", "a1", "1.0.0", files={"CLAUDE.md": "notes", "AGENTS.md": "notes"})
        self.build(["o/a"])
        with zipfile.ZipFile(self.output / "a" / "a-1.0.0.zip") as archive:
            names = archive.namelist()
        self.assertNotIn("a/CLAUDE.md", names)
        self.assertNotIn("a/AGENTS.md", names)

    def test_test_output_cannot_change_either_source_package(self):
        for name in ("a", "b"):
            self.add("o/" + name, name + "0", "1.0.0")
            self.publish_state("o/" + name, name + "0")
            self.add("o/" + name, name + "1", "1.0.1", files={
                "resources/code.py": "source code",
                "resources/icon.png": b"source image",
                "resources/catalogue.db": b"source database",
            })
        mutate = (
            "from pathlib import Path; "
            "Path('offline_badges.db').touch(); "
            "Path('generated.bin').write_bytes(b'test output'); "
            "Path('resources/code.py').write_text('test mutation'); "
            "Path('resources/icon.png').unlink()"
        )
        verify_workspace = (
            "from pathlib import Path; "
            "assert Path('offline_badges.db').exists(); "
            "assert Path('resources/code.py').read_text() == 'test mutation'"
        )

        def run_tests(addon_root, addon_config, label):
            self.tests_run.append(label)
            self.original_test_runner(addon_root, {
                "tests": [["python3", "-c", mutate], ["python3", "-c", verify_workspace]],
            }, label)

        self.builder.run_addon_tests = run_tests
        self.build(["o/a", "o/b"], source=("o/a", "a1"))
        self.assertEqual(2, len(self.tests_run))
        for name in ("a", "b"):
            with self.subTest(addon=name), zipfile.ZipFile(self.output / name / (name + "-1.0.1.zip")) as archive:
                self.assertNotIn(name + "/offline_badges.db", archive.namelist())
                self.assertNotIn(name + "/generated.bin", archive.namelist())
                self.assertEqual(b"source code", archive.read(name + "/resources/code.py"))
                self.assertEqual(b"source image", archive.read(name + "/resources/icon.png"))
                self.assertEqual(b"source database", archive.read(name + "/resources/catalogue.db"))

    def test_publish_check_treats_the_same_paths_as_not_shipped(self):
        sys.modules.pop("publish_check", None)
        publish_check = importlib.import_module("publish_check")
        self.assertEqual(set(self.builder.DEFAULT_EXCLUDES), set(publish_check.NON_SHIPPED_PATTERNS))

    def test_source_publish_without_a_news_entry_fails_the_run(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1", news="v1.0.0\n- Old entry")

        with self.assertRaisesRegex(RuntimeError, "news"):
            self.build(["o/a"], source=("o/a", "a2"))

    def test_the_addon_repository_config_provides_its_tests(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1", publish_config={
            "branch": "main", "tests": [["python3", "-m", "own"]], "test_env": {"X": "1"}})

        self.build(["o/a"], source=("o/a", "a2"))

        self.assertEqual(self.test_configs[0]["tests"], [["python3", "-m", "own"]])
        self.assertEqual(self.test_configs[0]["test_env"], {"X": "1"})

    def test_hook_files_are_not_packaged(self):
        self.add("o/a", "a1", "1.0.0", publish_config={"branch": "main"})

        self.build(["o/a"])

        with zipfile.ZipFile(self.output / "a" / "a-1.0.0.zip") as archive:
            self.assertNotIn("a/.primez-publish.json", archive.namelist())

    def test_other_addon_without_version_bump_keeps_its_published_commit(self):
        self.add("o/a", "a1", "1.0.0")
        self.publish_state("o/a", "a1")
        self.add("o/a", "a2", "1.0.1")
        self.add("o/b", "b1", "2.0.0")
        self.publish_state("o/b", "b1")
        # a shipped change pushed without a bump
        self.add("o/b", "b2", "2.0.0", files={"resources/lib/code.py": "changed"})

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

    def test_changelog_is_generated_from_news(self):
        source = Path(self.temp.name) / "source"
        source.mkdir()
        (source / "changelog.txt").write_text("version 1.0.0:\n- stale\n")
        news = "v1.2.0\n- New thing\n\nv1.1.0\n- Old thing"
        root = ET.fromstring(
            '<addon id="a" version="1.2.0"><extension point="xbmc.addon.metadata">'
            f"<news>\n        {news}\n        </news></extension></addon>"
        )

        self.builder.copy_repository_assets(source, "a", "1.2.0", root, self.output)

        self.assertEqual((self.output / "a" / "changelog-1.2.0.txt").read_text(), news + "\n")
        self.assertFalse((self.output / "a" / "changelog.txt").exists())

    def test_no_changelog_without_news(self):
        source = Path(self.temp.name) / "source"
        source.mkdir()
        root = ET.fromstring('<addon id="a" version="1.2.0"><extension point="xbmc.addon.metadata"/></addon>')

        self.builder.copy_repository_assets(source, "a", "1.2.0", root, self.output)

        self.assertFalse((self.output / "a" / "changelog-1.2.0.txt").exists())


class WebhookBranchTests(unittest.TestCase):
    def test_worker_defaults_match_all_maintained_manifest_branches(self):
        manifest = json.loads((ROOT / "addons.json").read_text())
        source = (ROOT / "webhook/cloudflare-worker/src/index.js").read_text()
        declaration = re.search(r"\bconst\s+DEFAULT_ALLOWED_REPOS\s*=\s*", source)
        self.assertIsNotNone(declaration, "Worker default repository map is missing")
        # Keep the Worker map in JSON object syntax; decode the whole map.
        defaults, _ = json.JSONDecoder().raw_decode(source[declaration.end():])
        owner = manifest["repository"]["provider_name"]
        branches = {entry["repository"]: entry["ref"] for entry in manifest["addons"]
                    if entry["repository"].startswith(owner + "/")}
        self.assertEqual(defaults, branches)


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
