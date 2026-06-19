import os
from pathlib import Path

def test_no_trailing_whitespace():
    # Directories to scan
    project_root = Path(__file__).resolve().parent.parent
    targets = [
        project_root / "sto_crm",
        project_root / "tests"
    ]

    # Extensions to check
    extensions = {".py", ".js", ".css", ".html"}

    # Exclusions
    exclude_dirs = {".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".git"}

    offending_files = []

    for target_dir in targets:
        if not target_dir.exists():
            continue

        for root, dirs, files in os.walk(target_dir):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix in extensions:
                    # Exclude node_modules or venv just in case it leaks in
                    if any(part in file_path.parts for part in exclude_dirs):
                        continue

                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            lines = f.readlines()
                    except Exception as e:
                        print(f"Skipping {file_path} due to error {e}")
                        continue

                    for line_idx, line in enumerate(lines):
                        stripped_nl = line.rstrip("\r\n")
                        if stripped_nl != stripped_nl.rstrip(" \t"):
                            offending_files.append(
                                f"{file_path.relative_to(project_root)}:line {line_idx + 1}"
                            )
                            break

    assert not offending_files, f"Found trailing whitespace in the following files:\n" + "\n".join(offending_files)
