import os
import shutil
import subprocess
from pathlib import Path

from check_whitespace import VALID_EXTENSIONS, check_file, get_files


def install_git_hook(root: Path) -> None:
    """Automatically copy the pre-commit hook into Git hooks directory."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True
        )
        hooks_dir = Path(res.stdout.strip())
        if not hooks_dir.is_absolute():
            hooks_dir = root / hooks_dir

        if hooks_dir.exists() and hooks_dir.is_dir():
            target_hook = hooks_dir / "pre-commit"
            source_hook = root / "pre-commit-hook.sh"
            if source_hook.exists():
                shutil.copy2(source_hook, target_hook)
                # On non-Windows platforms, make the hook executable
                if os.name != "nt":
                    try:
                        target_hook.chmod(0o755)
                    except OSError:
                        pass
    except Exception:
        # Fail silently if not in a git repo or git CLI is missing
        pass


def test_no_trailing_whitespace():
    root = Path(__file__).resolve().parent.parent
    install_git_hook(root)

    file_names = get_files(staged_only=False)

    offending_files = []
    for name in file_names:
        file_path = root / name
        if not file_path.exists() or not file_path.is_file():
            continue

        if file_path.suffix.lower() not in VALID_EXTENSIONS:
            continue

        errors = check_file(file_path)
        if errors:
            for line_num, _ in errors:
                offending_files.append(f"{name}:line {line_num}")

    assert not offending_files, "Found trailing whitespace in the following files:\n" + "\n".join(offending_files)
