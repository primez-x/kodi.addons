#!/usr/bin/env python3
"""Build a static Kodi add-on repository for GitHub Pages."""

from __future__ import annotations

import fnmatch
import hashlib
import html
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "addons.json"
OUTPUT_DIR = ROOT / os.environ.get("KODI_OUTPUT_DIR", "public")

DEFAULT_EXCLUDES = (
    ".git",
    ".git/*",
    ".github",
    ".github/*",
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


def download_archive(repository: str, ref: str, target: Path) -> None:
    quoted_ref = urllib.parse.quote(ref, safe="")
    url = f"https://api.github.com/repos/{repository}/zipball/{quoted_ref}"
    target.write_bytes(github_request(url))


def fetch_published_addon_versions(config: dict) -> dict[str, str]:
    url = with_trailing_slash(config["base_url"]) + "addons.xml"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "primez-kodi-repository-builder",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to fetch published add-on versions: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch published add-on versions: {exc.reason}") from exc

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RuntimeError(f"Published addons.xml at {url} is not valid XML: {exc}") from exc

    versions: dict[str, str] = {}
    for addon in root.findall("addon"):
        addon_id = addon.attrib.get("id")
        version = addon.attrib.get("version")
        if addon_id and version:
            versions[addon_id] = version
    return versions


def fetch_published_source_manifest(config: dict) -> dict[str, dict]:
    url = with_trailing_slash(config["base_url"]) + "source-manifest.json"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "primez-kodi-repository-builder",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to fetch published source manifest: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch published source manifest: {exc.reason}") from exc

    try:
        manifest = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Published source-manifest.json at {url} is not valid JSON: {exc}") from exc

    sources: dict[str, dict] = {}
    for entry in manifest.get("addons", []):
        addon_id = entry.get("id")
        if addon_id:
            sources[addon_id] = entry
    return sources


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

    for candidate in ("icon.png", "fanart.jpg", "fanart.png", "changelog.txt"):
        if (source_root / candidate).is_file():
            paths.add(candidate)

    assets = addon_xml_root.find("extension[@point='xbmc.addon.metadata']/assets")
    if assets is not None:
        for asset in assets:
            if asset.text and asset.text.strip():
                paths.add(asset.text.strip())

    for changelog in source_root.glob("changelog*.txt"):
        if changelog.is_file():
            paths.add(changelog.name)

    for path in sorted(paths):
        copy_repository_asset(source_root, addon_id, output_dir, path)

    changelog = source_root / "changelog.txt"
    if changelog.is_file():
        versioned = output_dir / addon_id / f"changelog-{version}.txt"
        versioned.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(changelog, versioned)


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
    published_versions: dict[str, str] | None = None
    published_sources: dict[str, dict] | None = None

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

    with tempfile.TemporaryDirectory(prefix="kodi-addons-") as temp_name:
        temp_dir = Path(temp_name)
        for addon_config in manifest["addons"]:
            repository = addon_config["repository"]
            ref = source_ref_for(addon_config)
            source_sha = resolve_source_sha(repository, ref)
            archive_path = temp_dir / f"{repository.replace('/', '__')}.zip"
            extract_dir = temp_dir / repository.replace("/", "__")
            extract_dir.mkdir()

            print(f"Packaging {repository}@{ref} ({source_sha})")
            download_archive(repository, source_sha, archive_path)
            safe_extract(archive_path, extract_dir)
            addon_root = find_addon_root(extract_dir)
            addon_id, version, addon_xml_root = parse_addon(addon_root / "addon.xml")
            if is_source_publish(addon_config):
                if published_versions is None:
                    published_versions = fetch_published_addon_versions(manifest["repository"])
                if published_sources is None:
                    published_sources = fetch_published_source_manifest(manifest["repository"])
                enforce_source_version_bump(
                    addon_id,
                    version,
                    addon_config,
                    published_versions,
                    published_sources,
                    source_sha,
                )

            exclude_patterns = list(DEFAULT_EXCLUDES)
            exclude_patterns.extend(addon_config.get("exclude", []))
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
