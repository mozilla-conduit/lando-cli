# Lando Headless CLI

The **Lando Headless CLI** is a command-line tool for interacting with [Lando](https://lando.moz.tools/)
via the automation API.

## 🐛 Bug Reports

Please file bugs in Bugzilla under [`Conduit :: Lando`](https://bugzilla.mozilla.org/enter_bug.cgi?product=Conduit&component=Lando)

Report issues or request enhancements in #engineering-workflow on Slack or #conduit on Matrix.

## 🔧 Installation

Install the CLI tool from PyPI, using `pip` or `pipx`.

```sh
pipx install lando_cli
```

Confirm the tool is installed locally.

```sh
lando --version
```

## 🔐 Configuration

The CLI expects a config file at `~/.mozbuild/lando.toml` with the following options:

```toml
[auth]
api_token = "TOKEN"
user_email = "ldap_user@mozilla.com"
```

Alternatively, you can supply the values as environment variables:

- `LANDO_HEADLESS_API_TOKEN`
- `LANDO_USER_EMAIL`
- `LANDO_URL` (optional, defaults to `https://lando.moz.tools`)

## 🚀 Usage

Run `lando --help` for an overview of available commands.

Run `lando <COMMAND> --help` for help with each command, including examples.

### push-commits

Push new commits to a Lando repo.

Create new commits against the specified branch locally. The currently checked
out branch will be used for the push, and the upstream branch will be used as
the base.

```sh
lando push-commits --lando-repo firefox-autoland
```

With a release branch:

```sh
lando push-commits --lando-repo firefox-beta --relbranch FIREFOX_64b_RELBRANCH
```

### push-tag

Push new tags to the specified repository.

```sh
lando push-tag --lando-repo firefox-main --tag-name TAG_NAME --tag-sha sha12345
```

### push-merge

Push merge actions to the specified repository.

Running without any options will detect the merge target and commit message
using the current `HEAD`.

```sh
lando push-merge --lando-repo firefox-main
```

Use `--target-commit` and `--commit-message` to create the merge in Lando
without detecting the change in your local repo.

```sh
lando push-merge --lando-repo firefox-main --target-commit SHA --commit-message "Merge"
```

### check-job

Check the status of a previously submitted job.

```sh
lando check-job 123
```
