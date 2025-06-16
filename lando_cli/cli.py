import os
import subprocess
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from importlib.metadata import PackageNotFoundError, version

import click
import requests
import tomli


def get_version() -> str:
    try:
        return version("lando_cli")
    except PackageNotFoundError:
        # package is not installed
        return "0.0.0"


__version__ = get_version()

DEFAULT_CONFIG_PATH = Path.home() / ".mozbuild" / "lando.toml"


@dataclass
class Config:
    """Configuration options for the Lando CLI.

    Default location for the config is `~/.mozbuild/lando.toml`.
    """

    api_token: str
    lando_url: str
    user_email: str

    @classmethod
    def load_config(cls) -> "Config":
        """Load config from the filesystem."""
        config_path = Path(os.getenv("LANDO_CONFIG_PATH", DEFAULT_CONFIG_PATH))
        config_data = {}

        if config_path.is_file():
            with config_path.open("rb") as f:
                config_data = tomli.load(f)

        auth = config_data.get("auth") or {}

        api_token = os.getenv("LANDO_HEADLESS_API_TOKEN") or auth["api_token"]
        user_email = os.getenv("LANDO_USER_EMAIL") or auth["user_email"]
        lando_url = os.getenv(
            "LANDO_URL", auth.get("lando_url", "https://lando.moz.tools")
        )

        return Config(api_token=api_token, user_email=user_email, lando_url=lando_url)


def with_config(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        config = Config.load_config()
        return func(config, *args, **kwargs)

    return wrapper


def api_request(
    config: Config,
    method: str,
    path: str,
    *args,
    headers: Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    """Send an HTTP request to the Lando Headless API.

    `config` is the loaded `Config` for the CLI.
    `method` is the HTTP method to use, ie `GET`, `POST`, etc.
    `path` is the REST API endpoint to send the request to.
    `headers` is the set of HTTP headers to pass to the request.

    All other arguments in *args and **kwargs are passed through to `requests.request`.
    """
    url = f"{config.lando_url}/api/{path}"

    common_headers = {
        "Authorization": f"Bearer {config.api_token}",
        "User-Agent": f"Lando-User/{config.user_email}",
    }
    if headers:
        common_headers.update(headers)

    return requests.request(method, url, *args, headers=common_headers, **kwargs)


def get_job_status(config: Config, job_id: int) -> dict:
    """Return the status of the job."""
    result = api_request(config, "GET", f"job/{job_id}")

    # `200` is a successful return.
    if result.status_code != 200:
        result.raise_for_status()

    return result.json()


def get_repo_info(config: Config, repo_name: str) -> dict:
    """Hit the `repo-info` endpoint and return the response."""
    result = api_request(config, "GET", f"repoinfo/{repo_name}")

    if result.status_code != 200:
        result.raise_for_status()

    return result.json()


def post_actions(
    config: Config,
    repo_name: str,
    actions: list[dict],
    relbranch: Optional[dict] = None,
) -> dict:
    """Send actions to the headless API."""
    actions_json: dict[str, Any] = {"actions": actions}

    if relbranch:
        actions_json["relbranch"] = relbranch

    result = api_request(config, "POST", f"repo/{repo_name}", json=actions_json)

    # `202` is a successful return.
    if result.status_code != 202:
        click.echo("Encountered an error submitting job to Lando:")

        try:
            response_json = result.json()
            click.echo(response_json["details"])
        except Exception:
            click.echo("Unknown error.")

        result.raise_for_status()

    return result.json()


def wait_for_job_completion(
    config: Config, job_id: int, poll_interval: int = 3
) -> dict:
    """Wait for a job to complete."""
    click.echo("Waiting for job completion, you may exit at any time.")
    click.echo(f"Note: run `lando check-job {job_id}` to check the status later.")

    while True:
        result = get_job_status(config, job_id)

        status = result["status"]

        if status == "SUBMITTED":
            click.echo("Job has been submitted and will be started soon.")
        elif status == "IN_PROGRESS":
            click.echo("Job is in progress.")
        elif status == "FAILED":
            error_details = result.get("error", "No additional details provided.")
            click.secho(f"Job {job_id} failed!", fg="red", bold=True)
            click.echo(error_details)
            break

        elif status == "LANDED":
            click.echo(f"Job {job_id} landed successfully.")
            break

        elif status == "CANCELLED":
            click.echo(f"Job {job_id} has been cancelled.")
            break

        else:
            click.echo(f"Job {job_id} had unexpected status: `{status}`.")
            break

        time.sleep(poll_interval)

    return result


def display_relbranch_tracking_warning(branch_name: str):
    """Display a warning about the new RelBranch."""
    click.secho(
        (
            f"\nNote: The new RelBranch `{branch_name}` was created or updated, "
            "but your local copy does not yet track it."
        ),
        fg="yellow",
        bold=True,
    )
    click.echo("Fetch the latest changes on the relbranch:\n")
    click.echo(f"  $ git fetch origin {branch_name}\n")
    click.echo("Ensure you have the local branch checked out:\n")
    click.echo(f"  $ git switch {branch_name}\n")
    click.echo("Update your local branch to point to the official branch:\n")
    click.echo(f"  $ git reset origin/{branch_name}\n")
    click.echo("Set your local branch to track the official branch:\n")
    click.echo(f"  $ git branch --set-upstream-to=origin/{branch_name} {branch_name}\n")
    click.echo("This will give you a fresh checkout of the landed commits.\n")


def submit_to_lando(
    config: Config,
    repo_name: str,
    actions: list[dict],
    relbranch: Optional[dict] = None,
):
    """Submit automation actions to Lando."""
    click.echo("Sending actions:")

    response = post_actions(config, repo_name, actions, relbranch=relbranch)

    job_id = response["job_id"]
    click.echo(f"Job {job_id} successfully submitted to Lando")

    result = wait_for_job_completion(config, job_id)

    if result["status"] == "LANDED" and relbranch and relbranch.get("commit_sha"):
        branch_name = relbranch["branch_name"]
        display_relbranch_tracking_warning(branch_name)

    return


def git_run(git_args: list[str], repo: Path) -> str:
    """Helper to run `git` with consistent arguments."""
    command = ["git", *git_args]
    result = subprocess.run(
        command,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        cwd=repo,
    )
    return result.stdout.strip()


def verify_reference_exists_locally(remote_branch: str, repo: Path) -> bool:
    """Check if the remote branch exists locally."""
    try:
        git_run(["rev-parse", "--verify", remote_branch], repo)
    except subprocess.CalledProcessError:
        return False

    return True


def get_remote_branch(branch: str, repo) -> str:
    """Get the remote branch for the given `branch`."""
    remote_branch_ref = f"origin/{branch}"
    if not verify_reference_exists_locally(remote_branch_ref, repo):
        raise Exception(f"Could not find remote branch {remote_branch_ref}")

    return remote_branch_ref


def get_new_commits(local_branch: str, base_sha: str, repo: Path) -> list[str]:
    """Given a local branch, get the list of local commits."""
    commits = git_run(
        ["rev-list", f"{base_sha}..{local_branch}", "--reverse"], repo
    ).splitlines()

    return commits


def get_commit_patches(commits: list[str], repo: Path) -> list[str]:
    """Get `git format-patch` patches for each passed commit SHA."""
    patches = []
    for idx, commit in enumerate(commits):
        patch = git_run(["format-patch", commit, "-1", "--always", "--stdout"], repo)
        patches.append(patch)

    return patches


def create_add_commit_actions(patches: list[str]) -> list[dict]:
    """Given an ordered list of patches, create `add-commit` actions for each."""
    return [
        {"action": "add-commit", "content": patch, "patch_format": "git-format-patch"}
        for patch in patches
    ]


def get_commit_message(commit_hash: str, repo: Path) -> str:
    """Get the commit message for a given commit SHA."""
    return git_run(["log", "-1", "--pretty=%B", commit_hash], repo)


def display_add_commit_actions(
    actions: list[dict], relbranch_specifier: dict | None, repo: Path
):
    """Display summary of add-commit actions, showing tip commit SHA and message."""
    click.echo("")

    if relbranch_specifier:
        branch_name = relbranch_specifier.get("branch_name")
        commit_sha = relbranch_specifier.get("commit_sha")
        if commit_sha:
            click.echo(f"Creating new RelBranch {branch_name} on commit {commit_sha}.")
        else:
            click.echo(f"Pushing commits to existing RelBranch {branch_name}.")

    click.echo(f"About to push {len(actions)} commits.")

    # Use the last patch as the tip commit
    last_patch = actions[-1]["content"]
    first_line = last_patch.splitlines()[0]

    if first_line.startswith("From "):
        tip_sha = first_line.split()[1]
        commit_msg = get_commit_message(tip_sha, repo).splitlines()[0]
        click.echo(f"Tip commit: {tip_sha} - {commit_msg}")
    else:
        click.echo("Could not determine tip commit SHA from patch.")

    click.echo("")


def detect_new_tags(repo: Path) -> set[str]:
    """Detect new tags on the repo."""
    click.echo("Detecting new tags")

    local_tags_set = set(git_run(["tag", "--list"], repo).splitlines())
    remote_tags = git_run(["ls-remote", "--tags", "origin"], repo).splitlines()
    remote_tags_set = {
        line.split("refs/tags/")[1] for line in remote_tags if "refs/tags/" in line
    }

    return local_tags_set - remote_tags_set


def create_tag_actions(local_only_tags: set[str], repo: Path) -> list[dict]:
    """Find the tags associated with each local commit SHA."""
    tags_to_push = []
    for tag in local_only_tags:
        commit = git_run(["rev-list", "-n", "1", tag], repo)
        tags_to_push.append({"action": "tag", "name": tag, "target": commit})

    return tags_to_push


def display_tag_actions(actions: list[dict]):
    """Display tag actions nicely."""
    click.echo(f"About to push {len(actions)} tags:")
    for action in actions:
        click.echo(f" - Tag {action['name']} -> {action['target']}")
    click.echo("")


def detect_merge_from_current_head(repo: Path) -> Optional[list[dict]]:
    """Detect if HEAD is a merge commit and return an action for the merge.

    If HEAD is a merge commit (a commit with two parents), return an action
    to complete the merge on Lando. We assume the logic used is that the
    `--lando-repo` is the commit we started from (p1), and the target commit
    is the branch we're merging in (p2).
    """
    click.echo("Detecting merge details from HEAD.")

    parents = git_run(["rev-list", "--parents", "-n", "1", "HEAD"], repo).split()

    if len(parents) == 3:
        click.echo("Detected a new merge commit.")
        merge_commit_sha, parent1, parent2 = parents

        # The second parent is the commit we merged into our
        # destination branch.
        target = parent2

    elif len(parents) == 2:
        click.echo("Detected a fast-forward merge.")
        merge_commit_sha, parent = parents

        # We fast-forwarded the branch, so the current HEAD is our target.
        target = merge_commit_sha
    else:
        return None

    commit_message = get_commit_message(merge_commit_sha, repo)

    return [
        {
            "action": "merge-onto",
            "commit_message": commit_message,
            "target": target,
            "strategy": None,
        }
    ]


def determine_base_sha_for_push(
    local_repo: Path,
    push_branch: str,
    default_remote_branch: str,
    relbranch: Optional[str],
) -> tuple[str, Optional[dict[str, Any]]]:
    """Return the base SHA to compare the local branch against for the push.

    If no relbranch is passed, use the `origin/<branch>` for the default remote
    from Lando.

    If a relbranch is passed, look for a pre-existing remote relbranch to use
    as the base. If an existing relbranch could not be found, use the first commit
    leading to `HEAD` which exists on `origin/<branch>`.
    """
    if not relbranch:
        base_sha_for_diff = get_remote_branch(default_remote_branch, local_repo)
        return base_sha_for_diff, None

    click.echo(f"Using relbranch {relbranch}")

    relbranch_specifier = {"branch_name": relbranch}
    remote_relbranch_name = f"origin/{relbranch}"

    if verify_reference_exists_locally(remote_relbranch_name, local_repo):
        click.echo(f"Found existing remote branch {remote_relbranch_name}")
        return remote_relbranch_name, relbranch_specifier

    base_sha_for_diff = git_run(
        ["merge-base", push_branch, f"origin/{default_remote_branch}"], local_repo
    )
    relbranch_specifier["commit_sha"] = base_sha_for_diff
    return base_sha_for_diff, relbranch_specifier


def display_merge_actions(actions: list[dict], remote_branch_name: str):
    """Display merge actions nicely."""
    click.echo(f"About to push {len(actions)} merges:")

    for action in actions:
        click.echo(f" - Merge {action['target']} onto {remote_branch_name}")
        click.echo(f"   Message: {action['commit_message'].splitlines()[0]}")

    click.echo("")


def get_current_branch(repo: Path) -> str:
    """Return the currently checked out branch."""
    return git_run(["branch", "--show-current"], repo)


def find_git_repo(path: Path) -> Path:
    """Check the `path` and it's parents for a Git repo."""
    possible_paths = [path, *path.parents]
    for parent in possible_paths:
        if (parent / ".git").exists():
            return parent

    raise Exception(f"No git repository found in {path} or its parents.")


def local_repo_option():
    """Return the common `--local-repo` argument."""
    return click.option(
        "-R",
        "--local-repo",
        type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
        default=lambda: find_git_repo(Path.cwd()),
        help="Local repository path.",
    )


def confirm_push() -> bool:
    """Ask the user for confirmation before proceeding."""
    return click.confirm(click.style("Submit job to Lando?", bold=True), default=False)


@click.group()
@click.version_option(__version__, "--version", "-v", prog_name="lando")
def cli():
    """Lando headless CLI.

    Using this tool requires a config file at `~/.mozbuild/lando.toml` with the
    following format. Reach out to the Conduit team to request an API token.


    \b
    ```
    [auth]
    api_token = "<TOKEN HERE>"
    user_email = "user@mozilla.com"
    ```
    """


@cli.command()
@local_repo_option()
@click.option("--lando-repo", help="Lando repo to post changes to.")
@click.option("--branch", help="Local branch to push commits from.")
@click.option("--relbranch", help="Push commits to the specified release branch.")
@click.option("--yes", "skip_confirm", help="Skip confirmation dialog.", is_flag=True)
@click.option("--base-commit", help="Use the specified commit as the base.")
@with_config
def push_commits(
    config: Config,
    local_repo: Path,
    lando_repo: str,
    branch: Optional[str] = None,
    relbranch: Optional[str] = None,
    skip_confirm: Optional[bool] = False,
    base_commit: Optional[str] = None,
):
    """Push new commits to the specified repository.

    Use `lando push-commits` to push new changes to the specified Lando repository.
    The currently checked out Git branch is used to find new commits, unless `--branch`
    is passed to specify which local branch to use. The current commit of the remote
    branch for the Lando repository is used as the base commit, unless the
    `--base-commit` argument is passed to explicitly specify the base.

    The command assumes you are working off a recent copy of the remote branch.
    Make sure to `git fetch origin` and rebase your changes off of the branch
    you will land to (ie `git rebase origin/autoland`) to ensure your push
    doesn't hit a merge conflict.

    The `--relbranch` option is used to push changes to a named RelBranch.
    `lando` will check the local Git repo for an existing RelBranch with that
    name and push the changes to it, or create a new RelBranch if the branch
    does not exist.

    Example: to push local commits on your current branch to the `autoland`
    branch on the `firefox` repo:

    \b
        $ lando push-commits --lando-repo firefox-autoland
        $ lando push-commits --lando-repo firefox-beta --relbranch FIREFOX_64b_RELBRANCH
    """
    repo_info = get_repo_info(config, lando_repo)
    remote_branch_name = repo_info["branch_name"]

    push_branch = branch or get_current_branch(local_repo)
    click.echo(f"Using local branch {push_branch}")

    if base_commit:
        relbranch_specifier = {}

        if not verify_reference_exists_locally(base_commit, local_repo):
            click.secho(
                f"Commit {base_commit} does not exist in the local repo.",
                fg="red",
                bold=True,
            )
            return 1

        click.echo(f"Using {base_commit} as the base from `--base-commit`.")
        base_sha_for_diff = base_commit
    else:
        base_sha_for_diff, relbranch_specifier = determine_base_sha_for_push(
            local_repo, push_branch, remote_branch_name, relbranch
        )
        click.echo(f"Using {base_sha_for_diff} as the base commit.")

    commits = get_new_commits(push_branch, base_sha_for_diff, local_repo)
    if not commits:
        click.echo("No new commits found!")
        return 1

    patches = get_commit_patches(commits, local_repo)
    actions = create_add_commit_actions(patches)

    display_add_commit_actions(actions, relbranch_specifier, local_repo)

    if not skip_confirm and not confirm_push():
        click.echo("Push cancelled.")
        return 1

    return submit_to_lando(config, lando_repo, actions, relbranch=relbranch_specifier)


@cli.command()
@local_repo_option()
@click.option("--lando-repo", help="Lando repo to post changes to.")
@click.option("--tag-name", help="Tag name to push explicitly.")
@click.option("--tag-sha", help="Tag SHA to push explicitly.")
@with_config
def push_tag(
    config: Config,
    local_repo: Path,
    lando_repo: str,
    tag_name: Optional[str],
    tag_sha: Optional[str],
):
    """Push new tags to the specified repository.

    Use `lando push-tag` to push new tags to the specified Lando repository.

    If no arguments are passed, `lando push-commits` will find any local tags
    which are not present on the remote and prepare them for pushing to the
    server.

    If `--tag-name` and `--tag-sha` are used, a new tag with the given name
    will be created on the specified commit SHA.
    """
    if tag_name and tag_sha:
        actions = [{"action": "tag", "name": tag_name, "target": tag_sha}]
    else:
        new_tags = detect_new_tags(local_repo)
        if not new_tags:
            click.echo("No new tags found.")
            return

        actions = create_tag_actions(new_tags, local_repo)

    display_tag_actions(actions)

    if not confirm_push():
        click.echo("Push cancelled.")
        return 1

    return submit_to_lando(config, lando_repo, actions)


@cli.command()
@local_repo_option()
@click.option("--lando-repo", help="Lando repo to post changes to.")
@click.option("--target-commit", help="Target commit to merge into.")
@click.option("--commit-message", help="Commit message for the merge commit.")
@with_config
def push_merge(
    config: Config,
    local_repo: Path,
    lando_repo: str,
    target_commit: str,
    commit_message: str,
):
    """Push merge actions to the specified repository.

    Use `lando push-merge` to push a clean merge to the specified Lando repository.
    Running without any arguments will detect the merge target and commit
    message using the current HEAD.

    Passing `--target-commit` and `--commit-message` will attempt to create the merge
    in Lando without detecting the change in your local repo.

    Example:

    \b
        $ git switch main
        $ git merge origin/autoland
        $ lando push-merge --lando-repo firefox-main
    """
    current_branch = get_current_branch(local_repo)
    click.echo(f"Using branch {current_branch}")

    repo_info = get_repo_info(config, lando_repo)
    remote_branch_name = repo_info["branch_name"]

    if target_commit and commit_message:
        click.echo("Creating merge from arguments.")
        actions = [
            {
                "action": "merge-onto",
                "commit_message": commit_message,
                "target": target_commit,
                "strategy": None,
            }
        ]
    else:
        actions = detect_merge_from_current_head(local_repo)
        if not actions:
            click.echo("Could not create a `merge-onto` action from current HEAD.")
            return 1

    display_merge_actions(actions, remote_branch_name)

    if not confirm_push():
        click.echo("Push cancelled.")
        return 1

    return submit_to_lando(config, lando_repo, actions)


@cli.command("check-job")
@click.argument("job_id", type=int)
@with_config
def check_job(config: Config, job_id: int):
    """Check the status of a previously submitted job.

    Run this command to poll the job status endpoint to wait for a
    job to complete.

    Example:
        $ lando check-job 1
    """
    wait_for_job_completion(config, job_id)
