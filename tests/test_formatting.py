import subprocess
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def test_black():
    subprocess.check_call(["black", "--check", BASE_DIR])


def test_ruff():
    """Run ruff on the codebase.

    Use the project root as the directory to lint, and define appropriate lint
    paths in the `pyproject.toml` file.
    """
    subprocess.check_call(
        (
            "ruff",
            "check",
            "--target-version",
            "py310",
        )
    )
