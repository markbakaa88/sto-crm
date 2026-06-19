#!/usr/bin/env python3
"""Cross-platform trailing whitespace validator.

Can check:
  - Staged files (ideal for pre-commit hooks) using: git diff --cached --name-only --diff-filter=d
  - All tracked files (ideal for CI, pytest, local full checks) using: git ls-files
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

VALID_EXTENSIONS = {
    ".py",
    ".js",
    ".css",
    ".html",
    ".json",
    ".yml",
    ".yaml",
    ".md",
}


def get_files(staged_only: bool) -> list[str]:
    """Retrieve list of files to check from Git."""
    root = Path(__file__).resolve().parent
    try:
        if staged_only:
            cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=d"]
        else:
            cmd = ["git", "ls-files"]
        res = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return files
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(
            f"Warning: Failed to run Git command ({e}). Falling back to full scan.",
            file=sys.stderr,
        )
        # Fallback to recursively scanning root directory if git is not available
        files = []
        exclude_dirs = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
            "release",
        }
        for path in root.rglob("*"):
            if path.is_file():
                # Check if any parent part of path is in excluded dirs
                parts = path.relative_to(root).parts
                if not any(part in exclude_dirs for part in parts):
                    files.append(str(path.relative_to(root).as_posix()))
        return files


def check_file(file_path: Path) -> list[tuple[int, str]]:
    """Check a single file for trailing whitespace.

    Returns a list of tuples containing (line_number, line_content).
    """
    errors: list[tuple[int, str]] = []
    try:
        # Read file as bytes to avoid encoding issues, then decode safely
        content = file_path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            # Skip checking binary files or unsupported encodings
            return errors

        lines = text.splitlines(keepends=False)
        for idx, line in enumerate(lines, start=1):
            # Check if line ends with space or tab
            if line and (line[-1] == " " or line[-1] == "\t"):
                errors.append((idx, line))
    except OSError as e:
        print(f"Error reading file {file_path}: {e}", file=sys.stderr)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate trailing whitespace.")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Only check staged files (useful for git pre-commit hooks).",
    )
    args = parser.parse_args()

    file_names = get_files(args.staged)
    root = Path(__file__).resolve().parent

    total_errors = 0
    checked_count = 0

    for name in file_names:
        file_path = root / name
        if not file_path.exists() or not file_path.is_file():
            continue

        if file_path.suffix.lower() not in VALID_EXTENSIONS:
            continue

        checked_count += 1
        errors = check_file(file_path)
        if errors:
            total_errors += len(errors)
            print(f"File: {name}")
            for line_num, line_content in errors:
                print(f"  Line {line_num}: {line_content!r}")

    if total_errors > 0:
        print(
            f"\nValidation failed! Found {total_errors} trailing whitespace error(s) in {checked_count} file(s)."
        )
        return 1

    print(
        f"Validation passed. Checked {checked_count} file(s), no trailing whitespace found."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
