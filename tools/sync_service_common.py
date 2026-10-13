#!/usr/bin/env python3
"""Copy the shared Kodi service modules or check for source drift."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_IDS = ("service.upnext", "service.nexttrack")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report drift without changes")
    parser.add_argument("--addons-dir", type=Path, default=ROOT.parent / "kodi-addons-dev")
    args = parser.parse_args()
    drift = False
    for addon_id in ADDON_IDS:
        target = args.addons_dir / addon_id / "resources" / "lib"
        if not target.is_dir():
            parser.error(f"Missing add-on source directory: {target}")
        for master in sorted((ROOT / "tools" / "service_common").glob("*.py")):
            copy = target / master.name
            content = master.read_bytes()
            if copy.is_file() and copy.read_bytes() == content:
                continue
            drift = True
            if args.check:
                print(f"Shared source drift: {copy}")
            else:
                copy.write_bytes(content)
                print(f"Updated {copy}")
    return 1 if args.check and drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
