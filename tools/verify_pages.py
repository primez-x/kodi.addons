#!/usr/bin/env python3
"""Verify that GitHub Pages serves the source manifest from the current build."""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def manifest_sources(manifest: dict) -> dict[str, tuple[str, str, str]]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("addons"), list):
        raise ValueError("Source manifest must contain an addons list")
    sources = {}
    for entry in manifest["addons"]:
        fields = ("id", "repository", "sha", "version")
        if not isinstance(entry, dict) or any(
                not isinstance(entry.get(field), str) or not entry[field] for field in fields):
            raise ValueError("Source manifest has an invalid add-on entry")
        addon_id = entry["id"]
        if addon_id in sources:
            raise ValueError(f"Source manifest has duplicate add-on {addon_id}")
        sources[addon_id] = (entry["repository"], entry["sha"], entry["version"])
    if not sources:
        raise ValueError("Source manifest has no add-ons")
    return sources


def verify_pages(expected: dict, base_url: str, attempts: int = 8) -> None:
    sources = manifest_sources(expected)
    url = base_url.rstrip("/") + "/source-manifest.json"
    last_error = ""
    for attempt in range(attempts):
        request = urllib.request.Request(
            url + "?" + urllib.parse.urlencode({"verify": time.time_ns()}),
            headers={"Cache-Control": "no-cache", "User-Agent": "primez-pages-verifier"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                live = manifest_sources(json.load(response))
            mismatches = sorted(addon_id for addon_id in sources.keys() | live.keys()
                                if sources.get(addon_id) != live.get(addon_id))
            if not mismatches:
                print(f"Verified Pages source SHAs and versions for {len(sources)} add-ons")
                return
            last_error = "Source SHA/version mismatch: " + ", ".join(mismatches)
        except (OSError, ValueError) as exc:
            last_error = str(exc)
        print(f"Pages verification attempt {attempt + 1}/{attempts}: {last_error}")
        if attempt + 1 < attempts:
            time.sleep(min(5 * 2 ** attempt, 30))
    raise RuntimeError(f"Pages verification failed for {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        verify_pages(json.loads(args.manifest.read_text(encoding="utf-8")), args.base_url)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
