#!/usr/bin/env python3
"""Run the statistical reproduction and package verification in sequence."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def remove_macos_metadata(root: Path) -> int:
    """Remove metadata artifacts that macOS may create on external volumes."""
    targets: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        if path.name.startswith("._") or path.name in {".DS_Store", "__MACOSX"}:
            targets.append(path)

    for path in sorted(targets, key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    return len(targets)


def main(bootstrap_repetitions: int, threads: int) -> None:
    reproduce_command = [
        sys.executable,
        str(PACKAGE_ROOT / "scripts" / "reproduce.py"),
        "--bootstrap-reps",
        str(bootstrap_repetitions),
        "--threads",
        str(threads),
    ]
    subprocess.run(reproduce_command, cwd=PACKAGE_ROOT, check=True)
    removed_before_validation = remove_macos_metadata(PACKAGE_ROOT)
    if removed_before_validation:
        print(
            f"Removed {removed_before_validation} macOS metadata artifact(s) "
            "before validation.",
            flush=True,
        )
    subprocess.run(
        [sys.executable, str(PACKAGE_ROOT / "scripts" / "verify_package.py")],
        cwd=PACKAGE_ROOT,
        check=True,
    )
    removed_after_validation = remove_macos_metadata(PACKAGE_ROOT)
    if removed_after_validation:
        print(
            f"Removed {removed_after_validation} macOS metadata artifact(s) "
            "after validation.",
            flush=True,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-reps", type=int, default=500)
    parser.add_argument("--threads", type=int, default=-1)
    arguments = parser.parse_args()
    if arguments.bootstrap_reps < 1:
        parser.error("--bootstrap-reps must be positive")
    return arguments


if __name__ == "__main__":
    args = parse_args()
    main(args.bootstrap_reps, args.threads)
