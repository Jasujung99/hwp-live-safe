"""Inspect the built wheel without installing it."""

from __future__ import annotations

import email.parser
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    version = project["version"]
    wheels = sorted((ROOT / "dist").glob(f"hwp_live_safe-{version}-*.whl"))
    sdists = sorted((ROOT / "dist").glob(f"hwp_live_safe-{version}.tar.gz"))
    if len(wheels) != 1:
        print(f"Expected one wheel for {version}, found {len(wheels)}", file=sys.stderr)
        return 1
    if len(sdists) != 1:
        print(f"Expected one source distribution for {version}, found {len(sdists)}", file=sys.stderr)
        return 1

    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        required = {
            "hwp_live/server.py",
            "hwp_live/hwp_com_worker.ps1",
        }
        missing = sorted(required - names)
        if missing:
            print(f"Wheel is missing: {', '.join(missing)}", file=sys.stderr)
            return 1

        entry_names = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(entry_names) != 1 or len(metadata_names) != 1:
            print("Wheel has unexpected dist-info metadata layout", file=sys.stderr)
            return 1

        entry_points = archive.read(entry_names[0]).decode("utf-8")
        if "hwp-live-safe = hwp_live.server:main" not in entry_points:
            print("Wheel does not expose the hwp-live-safe entry point", file=sys.stderr)
            return 1

        metadata = email.parser.Parser().parsestr(
            archive.read(metadata_names[0]).decode("utf-8")
        )
        if metadata["Name"] != "hwp-live-safe" or metadata["Version"] != version:
            print("Wheel name/version does not match pyproject.toml", file=sys.stderr)
            return 1

    with tarfile.open(sdists[0], "r:gz") as archive:
        source_names = {
            PurePosixPath(member.name).relative_to(PurePosixPath(member.name).parts[0]).as_posix()
            for member in archive.getmembers()
            if len(PurePosixPath(member.name).parts) > 1
        }
        forbidden_source = {
            ".codex/config.toml",
            ".mcp.json",
            "profile.local.json",
        }
        leaked = sorted(forbidden_source & source_names)
        leaked.extend(
            name
            for name in source_names
            if name.startswith("profiles/") and name != "profiles/profile.example.json"
        )
        if leaked:
            print(f"Source distribution contains local data: {', '.join(leaked)}", file=sys.stderr)
            return 1
        for required_source in {"LICENSE", "README.md", "profiles/profile.example.json"}:
            if required_source not in source_names:
                print(f"Source distribution is missing: {required_source}", file=sys.stderr)
                return 1

    print(f"Package artifact check passed: {wheel.name} and {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
