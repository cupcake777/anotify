#!/usr/bin/env python3
"""Check Tauri bundle artifact sizes.

Used by CI after packaging so oversized installers are visible immediately
instead of being discovered only after download.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

DEFAULT_LIMITS_MB = {
    ".msi": 20.0,
    ".exe": 20.0,
    ".dmg": 25.0,
    ".deb": 20.0,
    ".rpm": 25.0,
    ".appimage": 95.0,
    ".zip": 30.0,
}

BUNDLE_EXTS = tuple(DEFAULT_LIMITS_MB)


def mb(size: int) -> float:
    return size / 1024 / 1024


def parse_limits(values: list[str]) -> dict[str, float]:
    limits = dict(DEFAULT_LIMITS_MB)
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --limit {value!r}; expected .ext=MB")
        ext, raw = value.split("=", 1)
        ext = ext.lower()
        if not ext.startswith("."):
            ext = "." + ext
        limits[ext] = float(raw)
    return limits


def find_artifacts(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in BUNDLE_EXTS else []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in BUNDLE_EXTS
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Bundle directory or artifact file")
    parser.add_argument(
        "--limit",
        action="append",
        default=[],
        help="Override size limit, e.g. --limit appimage=95 --limit deb=20",
    )
    args = parser.parse_args()

    limits = parse_limits(args.limit)
    artifacts: list[Path] = []
    for raw in args.paths:
        artifacts.extend(find_artifacts(Path(raw)))

    if not artifacts:
        print("No bundle artifacts found.")
        return 1

    rows: list[tuple[Path, int, float, float, str]] = []
    failed = False
    for path in artifacts:
        size = path.stat().st_size
        ext = path.suffix.lower()
        limit = limits.get(ext, 0.0)
        status = "ok" if mb(size) <= limit else "too-large"
        if status != "ok":
            failed = True
        rows.append((path, size, mb(size), limit, status))

    print("Bundle size check:")
    for path, _size, size_mb, limit, status in rows:
        print(f"  {status:9s} {size_mb:8.2f} MiB <= {limit:6.2f} MiB  {path}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("\n### Bundle size check\n\n")
            fh.write("| Status | Size | Limit | Artifact |\n")
            fh.write("|---|---:|---:|---|\n")
            for path, _size, size_mb, limit, status in rows:
                fh.write(f"| {status} | {size_mb:.2f} MiB | {limit:.2f} MiB | `{path}` |\n")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
