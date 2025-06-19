import base64
from pathlib import Path
from typing import Callable
from click.testing import CliRunner
from lando_cli import cli
import pytest
from unittest import mock


@pytest.fixture
def mock_get_repo_info(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    mock_fixture = mock.MagicMock()
    mock_fixture.return_value = {"branch_name": "main", "repo_name": "mock-repo"}
    monkeypatch.setattr(cli, "get_repo_info", mock_fixture)
    return mock_fixture


@pytest.fixture
def mock_submit_to_lando(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    mock_fixture = mock.MagicMock()
    monkeypatch.setattr(cli, "submit_to_lando", mock_fixture)
    return mock_fixture


def test_push_commits(
    git_local_repo: Path,
    create_commit: Callable,
    mock_get_repo_info: mock.Mock,
    mock_submit_to_lando: mock.Mock,
):
    commit_message = "New commit to push"

    runner = CliRunner()
    with runner.isolated_filesystem(git_local_repo):
        create_commit(commit_message=commit_message)
        result = runner.invoke(cli.push_commits, ["--yes"])

    assert result.exit_code == 0
    assert "local branch main" in result.output
    assert "origin/main as the base commit" in result.output
    assert commit_message in result.output

    mock_get_repo_info.assert_called_once()
    mock_submit_to_lando.assert_called_once()

    action = mock_submit_to_lando.call_args.args[2][0]
    assert action.get("action") == "add-commit-base64"

    content = action.get("content")
    assert content, "Empty action content"

    decoded = base64.b64decode(content)
    assert commit_message.encode("utf-8") in decoded
