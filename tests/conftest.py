from pathlib import Path
import subprocess
import pytest


@pytest.fixture
def git_remote_repo(tmp_path: Path):
    """Create a temporary bare remote Git repo."""
    remote_repo = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", remote_repo.as_posix(), "--initial-branch", "main"],
        check=True,
    )
    yield remote_repo


@pytest.fixture
def git_local_repo(tmp_path: Path, git_remote_repo: Path):
    """Create a temporary local G
    it repo with remote set up."""
    local_repo = tmp_path / "local"
    local_repo.mkdir()

    subprocess.run(
        ["git", "clone", git_remote_repo.as_posix(), local_repo.as_posix()],
        check=True,
        cwd=local_repo,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=local_repo)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=local_repo)

    # Create an initial commit
    (local_repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=local_repo)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=local_repo)

    subprocess.run(["git", "push", "-u", "origin", "main:main"], cwd=local_repo)

    yield local_repo


@pytest.fixture
def create_commit(git_local_repo: Path):
    def commit_creator(
        patch_content: bytes | str = b"content",
        commit_message: str = "New commit",
        path: Path = Path("file.txt"),
    ):
        if not isinstance(patch_content, bytes):
            patch_content = patch_content.encode("utf-8")

        (git_local_repo / path).write_bytes(patch_content)
        subprocess.run(["git", "add", "."], cwd=git_local_repo)
        subprocess.run(["git", "commit", "-m", commit_message], cwd=git_local_repo)

    return commit_creator
