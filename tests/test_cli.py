import pytest
from pathlib import Path
import subprocess

import pytest
from pathlib import Path
import subprocess
from lando_cli.cli import (
    Config,
    get_new_commits,
    get_commit_patches,
    get_commit_message,
    detect_new_tags,
    detect_merge_from_current_head,
    get_current_branch,
)


@pytest.fixture
def git_remote_repo(tmp_path: Path):
    """Create a temporary bare remote Git repo."""
    remote_repo = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", remote_repo.as_posix()], check=True)
    yield remote_repo


@pytest.fixture
def git_local_repo(tmp_path: Path, git_remote_repo: Path):
    """Create a temporary local Git repo with remote set up."""
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


@pytest.mark.parametrize(
    "config_content, expected, should_raise",
    [
        (
            """
            [auth]
            api_token = "fake_token"
            user_email = "test@example.com"
            lando_url = "https://lando.test"
            """,
            {
                "api_token": "fake_token",
                "user_email": "test@example.com",
                "lando_url": "https://lando.test",
            },
            False,
        ),
        (
            """
            [auth]
            api_token = "fake_token"
            user_email = "test@example.com"
            """,
            {
                "api_token": "fake_token",
                "user_email": "test@example.com",
                "lando_url": "https://lando.moz.tools",
            },
            False,
        ),
        (
            """
            [auth]
            user_email = "test@example.com"
            """,
            {},
            True,
        ),
        (
            """
            [auth]
            api_token = "fake_token"
            """,
            {},
            True,
        ),
    ],
)
def test_config_loading_parametrized(
    tmp_path: Path, monkeypatch, config_content, expected, should_raise
):
    config_file = tmp_path / "lando.toml"
    config_file.write_text(config_content)

    monkeypatch.setenv("LANDO_CONFIG_PATH", str(config_file))

    if should_raise:
        with pytest.raises(KeyError):
            Config.load_config()
    else:
        config = Config.load_config()
        assert (
            config.api_token == expected["api_token"]
        ), "API token does not match value in config."
        assert (
            config.user_email == expected["user_email"]
        ), "User email does not match value in config."
        assert (
            config.lando_url == expected["lando_url"]
        ), "Lando URL does not match value in config."


def test_get_current_branch(git_local_repo: Path):
    subprocess.run(["git", "switch", "-c", "testbranch"], cwd=git_local_repo)
    branch = get_current_branch(git_local_repo)
    assert branch == "testbranch"


def test_get_new_commits(git_local_repo: Path):
    # Create a new commit
    (git_local_repo / "file.txt").write_text("content")
    subprocess.run(["git", "add", "."], cwd=git_local_repo)
    subprocess.run(["git", "commit", "-m", "New commit"], cwd=git_local_repo)

    commits = get_new_commits("main", "main", git_local_repo)
    assert len(commits) == 1

    commit_message = get_commit_message(commits[0], git_local_repo)
    assert commit_message.strip() == "New commit"


def test_get_commit_patches(git_local_repo: Path):
    (git_local_repo / "file.txt").write_text("patch content")
    subprocess.run(["git", "add", "."], cwd=git_local_repo)
    subprocess.run(["git", "commit", "-m", "Patch commit"], cwd=git_local_repo)

    commits = get_new_commits("main", "main", git_local_repo)
    patches = get_commit_patches(commits, git_local_repo)

    assert len(patches) == 1
    assert "Patch commit" in patches[0]
    assert "patch content" in patches[0]


def test_detect_new_tags(git_local_repo: Path):
    subprocess.run(["git", "tag", "v1.0"], cwd=git_local_repo)

    new_tags = detect_new_tags(git_local_repo)
    assert "v1.0" in new_tags

    # Push tag to remote
    subprocess.run(["git", "push", "--tags"], cwd=git_local_repo)

    new_tags_after_push = detect_new_tags(git_local_repo)
    assert not new_tags_after_push


def test_detect_merge_from_current_head_true_merge(git_local_repo: Path):
    # Create a branch and commit
    subprocess.run(["git", "switch", "-c", "branch"], cwd=git_local_repo)
    (git_local_repo / "branch_file.txt").write_text("branch content")
    subprocess.run(["git", "add", "."], cwd=git_local_repo)
    subprocess.run(["git", "commit", "-m", "Branch commit"], cwd=git_local_repo)

    # Switch to main and merge with no-ff
    subprocess.run(["git", "switch", "main"], cwd=git_local_repo)
    subprocess.run(
        ["git", "merge", "--no-ff", "branch", "-m", "Merge branch"], cwd=git_local_repo
    )

    actions = detect_merge_from_current_head(git_local_repo)
    assert actions is not None
    assert len(actions) == 1
    assert actions[0]["commit_message"] == "Merge branch"
    assert actions[0]["action"] == "merge-onto"
    assert actions[0]["target"] is not None


def test_detect_merge_from_current_head_fast_forward(git_local_repo: Path):
    subprocess.run(["git", "switch", "-c", "ff-branch"], cwd=git_local_repo)
    (git_local_repo / "ff_file.txt").write_text("ff content")
    subprocess.run(["git", "add", "."], cwd=git_local_repo)
    subprocess.run(["git", "commit", "-m", "FF commit"], cwd=git_local_repo)

    # Switch to main and perform fast-forward merge
    subprocess.run(["git", "switch", "main"], cwd=git_local_repo)
    subprocess.run(["git", "merge", "ff-branch"], cwd=git_local_repo)

    actions = detect_merge_from_current_head(git_local_repo)
    assert actions is not None
    assert len(actions) == 1
    assert actions[0]["commit_message"] == "FF commit"
    assert actions[0]["target"] is not None
