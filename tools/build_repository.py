#!/usr/bin/env python3
"""Build a static Kodi add-on repository for GitHub Pages."""

from __future__ import annotations

import fnmatch
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

import publish_check

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "addons.json"
OUTPUT_DIR = ROOT / os.environ.get("KODI_OUTPUT_DIR", "public")
TEST_TIMEOUT_SECONDS = int(os.environ.get("KODI_TEST_TIMEOUT", "900"))

DEFAULT_EXCLUDES = (
    ".git",
    ".git/*",
    ".github",
    ".github/*",
    ".claude",
    ".claude/*",
    ".DS_Store",
    ".codacy.yaml",
    ".gitattributes",
    ".gitignore",
    ".idea",
    ".idea/*",
    ".mypy_cache",
    ".mypy_cache/*",
    ".pytest_cache",
    ".pytest_cache/*",
    ".ruff_cache",
    ".ruff_cache/*",
    ".vscode",
    ".vscode/*",
    "__pycache__",
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
    "docs",
    "docs/*",
    "README",
    "README.*",
    "Readme.*",
    "test_*.py",
    "tests",
    "tests/*",
    "node_modules",
    "node_modules/*",
    "pyproject.toml",
    ".githooks",
    ".githooks/*",
    ".primez-publish.json",
    "CLAUDE.md",
    "AGENTS.md",
    "*.md",
    "CONTRIBUTING",
    "CONTRIBUTING.*",
    ".pylintrc",
    "pylintrc",
    ".flake8",
    "setup.cfg",
    "tox.ini",
    "Makefile",
    "requirements*.txt",
    "codecov.yml",
    ".editorconfig",
    ".pre-commit-config.yaml",
)


def load_manifest() -> dict:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def with_trailing_slash(value: str) -> str:
    return value if value.endswith("/") else value + "/"


def github_request(url: str) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "primez-kodi-repository-builder",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub request failed for {url}: HTTP {exc.code}: {body}") from exc


def resolve_source_sha(repository: str, ref: str) -> str:
    quoted_ref = urllib.parse.quote(ref, safe="")
    url = f"https://api.github.com/repos/{repository}/commits/{quoted_ref}"
    data = json.loads(github_request(url).decode("utf-8"))
    sha = data.get("sha")
    if not sha:
        raise RuntimeError(f"Failed to resolve {repository}@{ref} to a commit SHA")
    return sha


def fetch_source_commit_message(repository: str, sha: str) -> str:
    quoted_sha = urllib.parse.quote(sha, safe="")
    url = f"https://api.github.com/repos/{repository}/commits/{quoted_sha}"
    try:
        data = json.loads(github_request(url).decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot fetch commit metadata for {repository}@{sha}: {exc}") from exc
    commit = data.get("commit") if isinstance(data, dict) else None
    message = commit.get("message") if isinstance(commit, dict) else None
    if not isinstance(message, str) or data.get("sha") != sha:
        raise RuntimeError(f"Invalid commit metadata for {repository}@{sha}")
    return message


def download_archive(repository: str, ref: str, target: Path) -> None:
    quoted_ref = urllib.parse.quote(ref, safe="")
    url = f"https://api.github.com/repos/{repository}/zipball/{quoted_ref}"
    target.write_bytes(github_request(url))


def fetch_published_file(config: dict, name: str, description: str) -> bytes | None:
    """Return the deployed file, or None before the first deploy.

    A unique query string bypasses the Pages CDN cache, which otherwise serves the
    previous deploy for up to ten minutes and would make the version guard compare
    against an old release.
    """
    url = with_trailing_slash(config["base_url"]) + name
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode({"build": time.time_ns()}),
        headers={
            "Cache-Control": "no-cache",
            "User-Agent": "primez-kodi-repository-builder",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to fetch published {description}: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch published {description}: {exc.reason}") from exc


def fetch_published_addon_versions(config: dict) -> dict[str, str]:
    body = fetch_published_file(config, "addons.xml", "add-on versions")
    if body is None:
        return {}
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RuntimeError(f"Published addons.xml is not valid XML: {exc}") from exc

    versions: dict[str, str] = {}
    for addon in root.findall("addon"):
        addon_id = addon.attrib.get("id")
        version = addon.attrib.get("version")
        if addon_id and version:
            versions[addon_id] = version
    return versions


def fetch_published_source_manifest(config: dict) -> dict[str, dict]:
    body = fetch_published_file(config, "source-manifest.json", "source manifest")
    if body is None:
        return {}
    try:
        manifest = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Published source-manifest.json is not valid JSON: {exc}") from exc

    sources: dict[str, dict] = {}
    for entry in manifest.get("addons", []):
        addon_id = entry.get("id")
        if addon_id:
            sources[addon_id] = entry
    return sources


def run_addon_tests(addon_root: Path, addon_config: dict, label: str) -> None:
    """Run configured tests in a source copy; raise RuntimeError on failure.

    ``tests`` in addons.json is a list of argv lists run from the add-on root.
    A leading "python3" runs with this interpreter. ``test_env`` adds
    environment variables (e.g. PYTHONPATH) for every command.
    """
    commands = addon_config.get("tests") or []
    if not commands:
        return
    env = dict(os.environ)
    env.update({key: str(value) for key, value in addon_config.get("test_env", {}).items()})
    # Tests must never see publish credentials
    env.pop("GITHUB_TOKEN", None)
    with tempfile.TemporaryDirectory(prefix="kodi-addon-tests-") as test_name:
        test_root = Path(test_name) / addon_root.name
        shutil.copytree(addon_root, test_root)
        for command in commands:
            argv = [sys.executable if index == 0 and part == "python3" else part
                    for index, part in enumerate(command)]
            print(f"Testing {label}: {' '.join(command)}")
            try:
                result = subprocess.run(
                    argv,
                    cwd=test_root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=TEST_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Tests for {label} timed out after {TEST_TIMEOUT_SECONDS}s: {' '.join(command)}"
                ) from exc
            except OSError as exc:
                raise RuntimeError(f"Could not run tests for {label}: {exc}") from exc
            if result.returncode != 0:
                tail = "\n".join(result.stdout.splitlines()[-60:])
                raise RuntimeError(
                    f"Tests failed for {label} (exit {result.returncode}): {' '.join(command)}\n{tail}"
                )


def is_source_publish(addon_config: dict) -> bool:
    return (
        os.environ.get("KODI_SOURCE_REPOSITORY") == addon_config["repository"]
        and bool(os.environ.get("KODI_SOURCE_SHA"))
    )


def parse_numeric_version(value: str) -> tuple[int, ...]:
    parts = value.strip().split(".")
    if not parts or any(not part.isdecimal() for part in parts):
        raise RuntimeError(
            f"Unsupported add-on version {value!r}: publish guard expects dot-separated numeric versions"
        )
    return tuple(int(part) for part in parts)


def compare_addon_versions(left: str, right: str) -> int:
    left_parts = parse_numeric_version(left)
    right_parts = parse_numeric_version(right)
    width = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (width - len(left_parts))
    padded_right = right_parts + (0,) * (width - len(right_parts))
    return (padded_left > padded_right) - (padded_left < padded_right)


def enforce_source_version_bump(
    addon_id: str,
    incoming_version: str,
    addon_config: dict,
    published_versions: dict[str, str],
    published_sources: dict[str, dict],
    incoming_sha: str,
) -> None:
    published_version = published_versions.get(addon_id)
    if not published_version:
        print(f"Version guard: {addon_id} is not currently published; allowing initial publish")
        return

    comparison = compare_addon_versions(incoming_version, published_version)
    repository = addon_config["repository"]
    if comparison > 0:
        print(f"Version guard: {addon_id} {incoming_version} > published {published_version}")
        return

    if comparison == 0:
        published_source = published_sources.get(addon_id, {})
        if published_source.get("repository") == repository and published_source.get("sha") == incoming_sha:
            print(
                f"Version guard: {addon_id} {incoming_version} is already published "
                f"from {repository}@{incoming_sha}; allowing idempotent rebuild"
            )
            return

        raise RuntimeError(
            f"{addon_id} version must increase for webhook publish from {repository}@{incoming_sha}. "
            f"Published version is {published_version}; incoming addon.xml version is "
            f"{incoming_version}. Bump addon.xml before publishing to this branch."
        )

    raise RuntimeError(
        f"{addon_id} version went backwards for webhook publish from {repository}@{incoming_sha}. "
        f"Published version is {published_version}; incoming addon.xml version is {incoming_version}."
    )


def safe_extract(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"Unsafe archive path: {member.filename}")
        archive.extractall(destination)


def find_addon_root(extracted_dir: Path) -> Path:
    roots = [path for path in extracted_dir.iterdir() if path.is_dir()]
    if len(roots) == 1 and (roots[0] / "addon.xml").is_file():
        return roots[0]

    matches = [path.parent for path in extracted_dir.rglob("addon.xml")]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one addon.xml in {extracted_dir}, found {len(matches)}")
    return matches[0]


def parse_addon(addon_xml: Path) -> tuple[str, str, ET.Element]:
    tree = ET.parse(addon_xml)
    root = tree.getroot()
    if root.tag != "addon":
        raise RuntimeError(f"{addon_xml} root element is not <addon>")

    addon_id = root.attrib.get("id")
    version = root.attrib.get("version")
    if not addon_id or not version:
        raise RuntimeError(f"{addon_xml} must include addon id and version")

    return addon_id, version, root


def should_exclude(relative_path: str, patterns: list[str]) -> bool:
    parts = relative_path.split("/")
    for part in parts:
        if part in {".git", ".github", "__pycache__"}:
            return True
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def shipped_files(source_root: Path, exclude_patterns: list[str]) -> dict[str, str]:
    """Stream SHA-256 digests of the files zip_addon would pack."""
    files = {}
    for file_path in sorted(source_root.rglob("*")):
        relative_path = file_path.relative_to(source_root).as_posix()
        if not file_path.is_file() or should_exclude(relative_path, exclude_patterns):
            continue
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files[relative_path] = digest.hexdigest()
    return files


def warn_shared_service_drift(addon_root: Path, addon_id: str) -> None:
    if addon_id not in ("service.upnext", "service.nexttrack"):
        return
    for master in sorted((ROOT / "tools" / "service_common").glob("*.py")):
        copy = addon_root / "resources" / "lib" / master.name
        if not copy.is_file() or copy.read_bytes() != master.read_bytes():
            print(
                f"WARNING: {addon_id}/resources/lib/{master.name} differs from the shared master; "
                "run tools/sync_service_common.py before the next release",
                file=sys.stderr,
            )


def zip_addon(source_root: Path, addon_id: str, version: str, output_dir: Path, exclude_patterns: list[str]) -> Path:
    addon_output_dir = output_dir / addon_id
    addon_output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = addon_output_dir / f"{addon_id}-{version}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in sorted(source_root.rglob("*")):
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(source_root).as_posix()
            if should_exclude(relative_path, exclude_patterns):
                continue
            archive.write(file_path, f"{addon_id}/{relative_path}")

    return zip_path


def copy_repository_asset(source_root: Path, addon_id: str, output_dir: Path, relative_path: str) -> bool:
    normalized = PurePosixPath(relative_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        return False

    source = source_root / Path(*normalized.parts)
    if not source.is_file():
        return False

    target = output_dir / addon_id / Path(*normalized.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def copy_repository_assets(source_root: Path, addon_id: str, version: str, addon_xml_root: ET.Element, output_dir: Path) -> None:
    paths: set[str] = set()

    for candidate in ("icon.png", "fanart.jpg", "fanart.png"):
        if (source_root / candidate).is_file():
            paths.add(candidate)

    assets = addon_xml_root.find("extension[@point='xbmc.addon.metadata']/assets")
    if assets is not None:
        for asset in assets:
            if asset.text and asset.text.strip():
                paths.add(asset.text.strip())

    for path in sorted(paths):
        copy_repository_asset(source_root, addon_id, output_dir, path)

    # The <news> history is the only release-notes source; Kodi reads the
    # changelog for a version from changelog-<version>.txt next to the zip.
    news = addon_xml_root.find("extension[@point='xbmc.addon.metadata']/news")
    if news is not None and news.text and news.text.strip():
        changelog = output_dir / addon_id / f"changelog-{version}.txt"
        changelog.parent.mkdir(parents=True, exist_ok=True)
        changelog.write_text(textwrap.dedent(news.text).strip() + "\n", encoding="utf-8")


def serialize_addon(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


def build_repository_addon_xml(config: dict) -> ET.Element:
    base_url = with_trailing_slash(config["base_url"])
    addon = ET.Element(
        "addon",
        {
            "id": config["id"],
            "name": config["name"],
            "version": config["version"],
            "provider-name": config.get("provider_name", "primez-x"),
        },
    )

    repository = ET.SubElement(addon, "extension", {"point": "xbmc.addon.repository", "name": config["name"]})
    directory = ET.SubElement(repository, "dir")
    ET.SubElement(directory, "info", {"compressed": "false"}).text = base_url + "addons.xml"
    ET.SubElement(directory, "checksum").text = base_url + "addons.xml.md5"
    ET.SubElement(directory, "datadir", {"zip": "true"}).text = base_url
    ET.SubElement(directory, "hashes").text = "false"

    metadata = ET.SubElement(addon, "extension", {"point": "xbmc.addon.metadata"})
    ET.SubElement(metadata, "summary", {"lang": "en"}).text = config.get("summary", config["name"])
    ET.SubElement(metadata, "description", {"lang": "en"}).text = config.get("description", config["name"])
    ET.SubElement(metadata, "platform").text = "all"
    return addon


def zip_repository_addon(repo_addon_xml: str, config: dict, output_dir: Path) -> Path:
    addon_id = config["id"]
    version = config["version"]
    addon_output_dir = output_dir / addon_id
    addon_output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = addon_output_dir / f"{addon_id}-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(f"{addon_id}/addon.xml", repo_addon_xml)
    return zip_path


def write_addons_xml(addon_xml_entries: list[str], output_dir: Path) -> None:
    body = "\n".join("\n".join("  " + line if line else line for line in entry.splitlines()) for entry in addon_xml_entries)
    addons_xml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<addons>\n{body}\n</addons>\n"
    (output_dir / "addons.xml").write_text(addons_xml, encoding="utf-8", newline="\n")
    digest = hashlib.md5(addons_xml.encode("utf-8")).hexdigest()
    (output_dir / "addons.xml.md5").write_text(digest, encoding="utf-8", newline="\n")


def write_index(packages: list[dict], output_dir: Path) -> None:
    rows = []
    for package in packages:
        label = f"{package['id']} {package['version']}"
        rows.append(f"<li><a href=\"{html.escape(package['path'])}\">{html.escape(label)}</a></li>")
    html_content = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Primez Kodi Add-ons</title>
</head>
<body>
  <h1>Primez Kodi Add-ons</h1>
  <p>Install the repository add-on, then use Kodi's add-on updater.</p>
  <ul>
    {rows}
  </ul>
</body>
</html>
""".format(rows="\n    ".join(rows))
    (output_dir / "index.html").write_text(html_content, encoding="utf-8", newline="\n")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")


def write_source_manifest(sources: list[dict], output_dir: Path) -> None:
    manifest = {
        "addons": sources,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (output_dir / "source-manifest.json").write_text(content, encoding="utf-8", newline="\n")


def source_publish_config(addon_root: Path, addon_config: dict) -> dict:
    """The add-on's own .primez-publish.json test settings win over addons.json."""
    config_path = addon_root / publish_check.CONFIG_FILE
    if not config_path.is_file():
        return addon_config
    try:
        source_config = json.loads(config_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RuntimeError(f"{publish_check.CONFIG_FILE} is not valid JSON: {exc}") from exc
    merged = dict(addon_config)
    for key in ("tests", "test_env"):
        if key in source_config:
            merged[key] = source_config[key]
    return merged


def check_candidate(
    addon_id: str,
    version: str,
    addon_root: Path,
    addon_config: dict,
    published_versions: dict[str, str],
    published_sources: dict[str, dict],
    source_sha: str,
    label: str,
) -> None:
    """Raise RuntimeError unless this not-yet-published commit may be published."""
    enforce_source_version_bump(
        addon_id,
        version,
        addon_config,
        published_versions,
        published_sources,
        source_sha,
    )
    try:
        _addon_id, _version, news = publish_check.addon_info(
            (addon_root / "addon.xml").read_bytes(), label)
        publish_check.check_news(version, news)
        previous = published_versions.get(addon_id)
        message = ""
        if previous and publish_check.parse_version(version) not in [
            publish_check.parse_version(candidate)
            for candidate in publish_check.next_versions(previous)
        ]:
            message = fetch_source_commit_message(addon_config["repository"], source_sha)
        publish_check.check_version_step(version, previous, source_sha, commit_message=message)
    except publish_check.CheckError as exc:
        raise RuntimeError(f"{label}: {exc}") from exc
    run_addon_tests(addon_root, source_publish_config(addon_root, addon_config), label)


def published_source_for(repository: str, published_sources: dict[str, dict]) -> dict | None:
    for entry in published_sources.values():
        if entry.get("repository") == repository and entry.get("sha"):
            return entry
    return None


def source_ref_for(addon_config: dict) -> str:
    event_repository = os.environ.get("KODI_SOURCE_REPOSITORY", "")
    event_sha = os.environ.get("KODI_SOURCE_SHA", "")
    if event_repository == addon_config["repository"] and event_sha:
        return event_sha
    return addon_config["ref"]


def build() -> None:
    manifest = load_manifest()
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    packages: list[dict] = []
    addon_xml_entries: list[str] = []
    source_entries: list[dict] = []

    repo_addon_root = build_repository_addon_xml(manifest["repository"])
    repo_addon_xml = serialize_addon(repo_addon_root)
    repo_zip = zip_repository_addon(repo_addon_xml, manifest["repository"], OUTPUT_DIR)
    packages.append(
        {
            "id": manifest["repository"]["id"],
            "version": manifest["repository"]["version"],
            "path": repo_zip.relative_to(OUTPUT_DIR).as_posix(),
        }
    )
    addon_xml_entries.append(repo_addon_xml)

    # The add-on that triggered a webhook publish must pass its version guard
    # and tests, or the run fails. Every other add-on is rebuilt from its
    # branch head only if that head passes the same checks; otherwise the
    # commit that is already published is kept. That way a commit without a
    # version bump (or with failing tests) never leaks out with another
    # add-on's publish, and a publish whose run GitHub dropped from the queue
    # is still picked up by the next one.
    try:
        published_versions = fetch_published_addon_versions(manifest["repository"])
        published_sources = fetch_published_source_manifest(manifest["repository"])
    except RuntimeError as exc:
        if os.environ.get("KODI_SOURCE_REPOSITORY"):
            raise
        print(f"WARNING: {exc}; building every add-on from its configured ref")
        published_versions, published_sources = {}, {}

    with tempfile.TemporaryDirectory(prefix="kodi-addons-") as temp_name, \
            ThreadPoolExecutor(max_workers=4) as executor:
        temp_dir = Path(temp_name)
        archives = {}

        def download_source(repository: str, sha: str, directory: Path) -> Path:
            directory.mkdir()
            archive_path = directory / "source.zip"
            extract_dir = directory / "source"
            download_archive(repository, sha, archive_path)
            safe_extract(archive_path, extract_dir)
            return find_addon_root(extract_dir)

        def prefetch(repository: str, sha: str):
            key = (repository, sha)
            if key not in archives:
                directory = temp_dir / str(len(archives))
                archives[key] = executor.submit(download_source, repository, sha, directory)
            return archives[key]

        sources = []
        for addon_config in manifest["addons"]:
            repository = addon_config["repository"]
            ref = source_ref_for(addon_config)
            source_sha = resolve_source_sha(repository, ref)
            sources.append((addon_config, ref, source_sha))
            prefetch(repository, source_sha)

        # Only archive fetch/extract runs in parallel. Checks, tests, logs and
        # output retain manifest order. Futures cache candidates and fallbacks.
        for addon_config, ref, source_sha in sources:
            repository = addon_config["repository"]
            strict = is_source_publish(addon_config)
            published = published_source_for(repository, published_sources)

            print(f"Packaging {repository}@{ref} ({source_sha})")
            addon_root = prefetch(repository, source_sha).result()
            addon_id, version, addon_xml_root = parse_addon(addon_root / "addon.xml")
            label = f"{repository}@{source_sha[:12]}"
            already_published = published is not None and published.get("sha") == source_sha
            exclude_patterns = list(DEFAULT_EXCLUDES)
            exclude_patterns.extend(addon_config.get("exclude", []))
            if (not already_published and published is not None
                    and published.get("version") == version):
                # Same version: not a release (non-shipped files only, or shipped
                # changes declared No-Release; the pre-push hook and CI enforce
                # which). Keep the published package without failing the run.
                published_root = prefetch(repository, published["sha"]).result()
                unchanged = shipped_files(published_root, exclude_patterns) == shipped_files(
                    addon_root, exclude_patterns)
                print(
                    f"{'' if unchanged else 'WARNING: '}{label}: same version {version} as the "
                    f"published {repository}@{published['sha'][:12]}"
                    f"{'; only files that are not shipped changed' if unchanged else ' with shipped changes'}"
                    "; not a release, keeping the published package"
                )
                # Identical shipped files make the same package, so record the
                # branch head: the published commit may no longer be on the
                # branch (e.g. after a history rewrite).
                if not unchanged:
                    source_sha = published["sha"]
                    ref = source_sha
                    addon_root = published_root
                    addon_id, version, addon_xml_root = parse_addon(addon_root / "addon.xml")
                already_published = True
            if not already_published and (strict or published is not None):
                try:
                    check_candidate(
                        addon_id,
                        version,
                        addon_root,
                        addon_config,
                        published_versions,
                        published_sources,
                        source_sha,
                        label,
                    )
                except RuntimeError as exc:
                    if strict or published is None:
                        raise
                    kept_sha = published["sha"]
                    print(
                        f"WARNING: not publishing {label}: {exc}\n"
                        f"Keeping the published {repository}@{kept_sha[:12]} "
                        f"({published.get('version')})"
                    )
                    source_sha = kept_sha
                    ref = kept_sha
                    addon_root = prefetch(repository, source_sha).result()
                    addon_id, version, addon_xml_root = parse_addon(addon_root / "addon.xml")

            warn_shared_service_drift(addon_root, addon_id)
            package_path = zip_addon(addon_root, addon_id, version, OUTPUT_DIR, exclude_patterns)
            copy_repository_assets(addon_root, addon_id, version, addon_xml_root, OUTPUT_DIR)
            source_entries.append(
                {
                    "id": addon_id,
                    "ref": addon_config["ref"],
                    "repository": repository,
                    "resolved_ref": ref,
                    "sha": source_sha,
                    "version": version,
                }
            )
            packages.append(
                {
                    "id": addon_id,
                    "version": version,
                    "path": package_path.relative_to(OUTPUT_DIR).as_posix(),
                }
            )
            addon_xml_entries.append(serialize_addon(addon_xml_root))

    write_addons_xml(addon_xml_entries, OUTPUT_DIR)
    write_source_manifest(source_entries, OUTPUT_DIR)
    write_index(packages, OUTPUT_DIR)

    print("Built Kodi repository:")
    for package in packages:
        print(f"- {package['id']} {package['version']} -> {package['path']}")


def main() -> int:
    try:
        build()
    except Exception as exc:  # noqa: BLE001 - keep workflow failures readable.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
