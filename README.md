# gerrit-owners-cli

Print Gerrit Code Owners groups for a file.

## Installation

```bash
python -m pip install gerrit-owners-cli
```

## Requirements

Run the command inside a Git repository with:

- `gitreview.hostname` configured in Git config;
- `gitreview.username` configured in Git config, unless the credential helper provides it;
- a Git credential helper that can provide the HTTPS password;
- a `.gitreview` file with `[gerrit] project=...`.

The password is read through `git credential fill` and is never a command-line argument.

## Usage

```bash
gerrit-owners path/to/file
gerrit-owners path/to/file --branch release/1.0
gerrit-owners path/to/file --json
```

The default branch is `master`.

The command prints owner groups and resolves code owner account IDs to names and emails.
Inherited and global owner groups included by the API are printed too. Account lookup failures
fall back to the account ID.

Use `--json` to print the complete Gerrit response, including `code_owners` account IDs and
scoring data alongside `code_owner_configs`.

Example:

```text
Owner groups:
- project-a:team-a
- project-b:team-b

Code owners:
- Example User <user@example.com>
```

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
python -m build
```

## Releases

The version is derived from Git tags by `setuptools-scm`. Create a tag such as `v0.1.0` and
publish a GitHub release. The included workflow publishes the distribution to PyPI through
Trusted Publishing.
